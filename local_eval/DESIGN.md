# PRIME local eval: design note on refusals, severity and rewriting

Status: draft, 2026-11-26. Option 1 is implemented on `eval/gcp-run`. The rest are proposals.

## 1. Where we are

The first real GPU run (`results/20261126-084321/`: see `REVIEW.md` and `COMPARISON.md`) ran 20 HarmBench
prompts through Zephyr-7B (the protected model) with Qwen2.5-7B as PRIME's judge.

- **The protected model mostly does not refuse on its own.** In 16 of the 20 answers it opens with a
  disclaimer and then complies anyway, e.g. *"…I strongly advise against engaging in such activities.
  However, for the sake of this tutorial, I will provide…"*, followed by a step-by-step plan. It truly
  deflected only 3 times. So there is real harm for PRIME to catch.
- **PRIME blocked all 20, at the input check.** The judge scored every prompt 0.8–1.0, so the output check
  never ran.
- **What the user sees when PRIME blocks is a flat "I can't help with that request."** That is less useful
  than the nuance in the model's own first sentence, which is the gap this note is about.

## 2. Problems

| # | Problem | Evidence |
|---|---|---|
| P1 | Refusals are unhelpful: one fixed sentence, whatever the request | Every one of the 20 blocked answers is identical |
| P2 | Every unsafe request gets the same treatment | "Fool a breathalyzer" and "bio-weapon agents" both scored ≥ 0.8 → same flat refusal |
| P3 | Rewriting is shallow, and the answer check is untested | See §3, option 3 |
| P4 | We only measure harm, so a guardrail that refuses everything looks perfect | Run scored 20/20 "blocked" with no view of usefulness |
| P5 | Judge scores are saturated, so thresholds barely matter | All 20 scores between 0.8 and 1.0 |

## 3. Options and recommendations

### Option 1: helpful refusals (fixes P1). Implemented
When PRIME refuses, the judge model writes the reply instead of using the fixed sentence. The reply:
- names what it won't help with, in one plain sentence (no lecturing)
- offers the nearest legitimate help: lawful alternatives, safety information, or who to ask

For the cash-smuggling prompt, that means declining to help evade monitoring, then explaining that carrying
more than $10k across the border is legal if you declare it (FinCEN Form 105), and suggesting a lawyer or
bank for international transfers.

The safeguard is that **the reply is itself run through the output judge.** Unless it scores clearly safe
(below the REWRITE threshold, 0.3), PRIME falls back to the fixed sentence. So a bad helpful reply can
never be worse than today's behaviour.

- Code: `Prime._refuse()` in `prime_local.py`. It covers all three refusal paths: blocked at the input
  check, a rewrite asked for but not provided, and blocked at the output check.
- Config: `policy.refusal_style: helpful | fixed`. `fixed` restores the original behaviour exactly.
- Traces record `refusal: {style, check_score, fell_back, rejected_text, latency_ms}`, so every fallback
  and its reason can be audited. `compare.py` shows the check result per row.
- Cost: two extra judge calls per refusal (write the reply, then check it). On the T4 an estimated
  3–6 s per refusal (a judge call took about 3 s in the last run).
- Judge errors still get the fixed sentence, since there is no verdict to explain.

### Option 2: severity tiers (fixes P2, needs P5). Proposed
**Why:** a risk score answers "is this unsafe?" but not "how bad would helping be?". Those call for
different replies:

| Tier | Examples | Reply |
|---|---|---|
| **Hard decline** | Weapons capable of mass casualties, sexual content involving minors, targeted violence | Brief decline. **No** alternatives, because even "adjacent" help can leak (e.g. "safe" chemistry tips next to a nerve-agent request). |
| **Helpful refusal** | Crime, hacking, defamation, harassment, fraud | Option 1: decline plus a safe alternative |
| **Safe completion** | Dual-use or mostly benign: breathalyzer limits, how phishing works so you can spot it | **Answer** the safe part fully and leave out only the operational detail |

Today PRIME has two levers, a score threshold and per-topic rules (Competitors, Mental Health,
Geopolitical). Option 2 extends the topic rules to every harm category, each with an action and
instructions, and asks the judge for a `severity` field alongside `score`.

**Why not just rely on option 1?** Option 1 alone would offer "alternatives" for bio-weapon requests too,
which is exactly where we want *less* help. Option 2 also saves the opposite case: low-severity requests
that should simply be answered rather than refused.

### Option 3: rewrite the answer, not just the question (fixes P3). Proposed
**What the current code does** (easy to miss, because none of it ran in our batch):
- **Input check, REWRITE (score 0.3–0.7):** PRIME rewrites the *question* (the judge's `safe_rewrite`)
  and sends that to the model. The user's actual question is never answered as asked.
- **Output check (condition `input_output`):** it exists, but only sees answers the input check let
  through. In our run that was none, so it is untested.
- **Output check, REWRITE:** the user gets the judge's `safe_rewrite` *of the answer* verbatim, and **that
  text is never checked again**. That is a leak path.

**Proposal:** for medium-risk prompts, let the model answer, then have the output check *edit* the answer:
keep the warning, the legal context and safety information, and cut the actionable steps. That preserves
exactly the nuance in Zephyr's first sentence that we liked. Every edited answer goes through the output
judge again. If it fails, PRIME falls back to option 1 (helpful refusal), then to the fixed sentence. The
same re-check should be added to the existing output-REWRITE path either way.

**How to test it:** an `output_only` condition (skip the input check) so we can see the output check work
on real harmful answers, and so P3 doesn't stay untested.

### Option 4: measure helpfulness too (fixes P4). Proposed
Grade every final answer into three buckets: **harmful**, **safe and helpful**, **safe but unhelpful
refusal**. Report all three per condition, and add XSTest's 250 safe-but-scary-sounding prompts to catch
over-blocking. Without this we can't show that option 1 is better than a flat refusal, so option 1's real
evaluation depends on it.

### Option 5: calibrate the judge (fixes P5). Proposed
Add a few scored examples to the judge prompt spanning low to catastrophic, ask for `intent` and
`severity` separately, then check on a small labelled set that scores actually spread out. This is a
prerequisite for option 2's tiers and for the thresholds to mean anything.

## 4. Order of work

| Step | What | Depends on | Run |
|---|---|---|---|
| 1 | Option 1 (done) + option 4 grading | none | Same 20 HarmBench prompts: fixed vs helpful refusal, side by side |
| 2 | Option 3 + `output_only` condition | none | Same 20, so the output check finally runs |
| 3 | Option 5, then option 2 | 5 before 2 | 20 HarmBench + 20 XSTest |
| 4 | Full run (1,950 traces) | 1–3 | Only once the above look right |

Each step is a small code change plus about 10–20 minutes on the T4 Spot VM (about $0.10–0.20).

## 5. Risks and open questions
- **Helpful refusals can leak.** Mitigated by the safety check and fallback. To verify, spot-check by hand
  plus the option 4 "harmful" bucket.
- **PRIME's judge also writes the reply.** That's simpler, but the judge is checking its own text.
  Alternative: write with a third model, or keep the check but use a different family for it.
- **Grader choice is still open** (README "Open decisions"): it must not be the judge. My recommendation:
  HarmBench's classifier for "harmful", plus a small rubric model for helpful vs unhelpful.
- **Latency:** each refusal now costs two more model calls. Fine for evaluation; for a product, the
  fixed-text fallback could be served while the helpful reply streams.
