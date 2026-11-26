# PRIME local eval: design note on refusals, severity and rewriting


> **Superseded in parts.** This note records the discussion that led to V1. The current decisions are
> in `DECISIONS.md`, and that file wins where they differ. In particular, V1 dropped the answer check,
> the context note and the separate refusal safety check (D2), and REWRITE acts on the request (D3).

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
| P3 | PRIME rewrote the user's *question*, and the answer check is untested | See §3a and option 3 |
| P4 | We only measure harm, so a guardrail that refuses everything looks perfect | Run scored 20/20 "blocked" with no view of usefulness |
| P5 | Judge scores are saturated, so thresholds barely matter | All 20 scores between 0.8 and 1.0 |

## 3. Options and recommendations

### 3a. The input check classifies; it does not rewrite. Implemented
**Decision:** drop rewriting of the user's question. The input check now does only what input checks are
good at, which is classifying and, for the worst cases, blocking. Medium-risk prompts are answered **as asked**, with
a guardrail note to the model.

**Why rewriting the question was dropped:**
- It answers a question the user didn't ask, and hides that PRIME intervened.
- It throws away the signal we most want, the user's actual intent. The model never sees it, so it can't
  acknowledge or push back on it.
- It is circular: the judge flags a risky question, writes a "safe" one, and nothing checks that question
  or the answer to it.
- It confounds evaluation: a good answer can't be credited to the model or to the rewrite.

**How production guardrails treat input:** Google Cloud Model Armor's prompt-side checks *block or flag*
(responsible-AI content filters, prompt injection and jailbreak detection, child sexual abuse material).
The only check that changes the prompt is Sensitive Data Protection, which redacts personal and
confidential data (and in some integrations blocks instead). That change serves privacy, not harm. None of
them rewrites the question to make it "safe".

**New input flow** (`Prime.run` in `prime_local.py`):

| Input judge says | What happens | Trace `final_action` |
|---|---|---|
| Low risk (score < 0.3) | Model answers normally | `ALLOW` |
| Medium risk (0.3–0.7) | Model gets the **original question** plus a system note: category, likely intent, why flagged, and "no operational detail; add safety, legal or support context" | `CONTEXT` |
| High risk (≥ 0.7) | Refuse before the model answers (option 1 helpful refusal; option 2 would add a hard-decline tier) | `REFUSE` |

- The input judge now returns `intent` (one neutral sentence) instead of a rewritten question. It feeds
  both the context note and the helpful refusal.
- Topic rules with an instruction (e.g. Mental Health) are appended to the context note.
- `grade.py` reports `context_noted` separately from blocking, so answered-with-guidance isn't counted as
  a catch.

**Future input-side work (out of scope for this eval):** personal-data redaction (no personal data in
HarmBench or XSTest to measure), and prompt-injection detection (matters once PRIME guards agents or
tools).

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
- **Input check, medium risk:** previously rewrote the *question*. Replaced by the context note (§3a).
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

## 5. Benchmarking against other guardrails
PRIME's results only mean something next to existing guardrails and specialized safety models (e.g.
ShieldGemma, Llama Guard, Model Armor) on shared benchmarks. The literature and benchmark review is in
`RELATED_WORK.md` (some items there are marked unverified because model cards and papers couldn't be opened
from the research environment; check before citing). Its headline points:
- **Baselines:** Llama Guard 3 8B, ShieldGemma, WildGuard, Qwen3Guard, plus one guard that reads a written
  policy at inference time (the direct competitor to PRIME's configurable policy), and two cheap ones: our
  Qwen judge with no policy layer (ablation) and the OpenAI Moderation API. Model Armor is a commercial
  option in this project.
- **Two evaluation tracks:** classifier track (PRIME's judge + policy scored as a classifier) and system
  track (same protected model, prompts and grader; only the guard changes). Cache the protected model's
  answers once so each extra baseline only costs its classification calls.
- **"Configurable policy" alone is no longer distinctive:** several open guards now take a written policy.
  PRIME's case rests on the whole system: policy-driven actions, the output check, and helpful refusals.
- **No standard benchmark scores refusal quality.** A rubric plus about 100 human-rated items would be a
  contribution in itself (closest prior work: OpenAI's safe-completions paper).

## 6. Risks and open questions
- **Helpful refusals can leak.** Mitigated by the safety check and fallback. To verify, spot-check by hand
  plus the option 4 "harmful" bucket.
- **PRIME's judge also writes the reply.** That's simpler, but the judge is checking its own text.
  Alternative: write with a third model, or keep the check but use a different family for it.
- **Grader choice is still open** (README "Open decisions"): it must not be the judge. My recommendation:
  HarmBench's classifier for "harmful", plus a small rubric model for helpful vs unhelpful.
- **Latency:** each refusal now costs two more model calls. Fine for evaluation; for a product, the
  fixed-text fallback could be served while the helpful reply streams.
