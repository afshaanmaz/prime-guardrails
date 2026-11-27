# PRIME experimentation plan (live)

A running log: **problem → experiment → result → next step.** Newest entries at the bottom of the log.
The proposed flow at the top is updated whenever a run changes the picture. All times are **Pacific (PST)**.
Supersedes `EXPERIMENT_PLAN.md` (pre-V1). Decisions: `DECISIONS.md`. Claims: `NARRATIVE.md`.

---

## Proposed flow (as of Thu 26 Nov, 8:15 pm PST)

Goal for this session: **one full run on several protected models** with frozen PRIME code, then the
paper's results.

| # | Step | Why | Status |
|---|---|---|---|
| 1 | **M0b:** does the MEDIUM band bring REWRITE back? (40 pilot requests + 50 OR-Bench borderline) | REWRITE vanished in M0; graduated response is a core claim | **Running** (started 8:07 pm) |
| 2 | **Fix any red flags from M0b, then freeze the V1 config** (tag the commit) | Main runs need fixed code | Pending M0b |
| 3 | **Engineering for multi-model runs** (small): (a) compute PRIME's decisions once per request and reuse them for every protected model; (b) protected model via API (Gemini); (c) higher concurrency for quality runs (latency comes from the dedicated benchmark) | PRIME's risk sensor and intervention only see the request, so its decisions don't depend on the protected model. Reusing them is faster and makes the comparison across models exact | Not started |
| 4 | **Main run, three protected models × {model alone, model + PRIME}** on full HarmBench (200) + full XSTest (450) + OR-Bench-Hard (sample now; full 1K later) | The core claims: does PRIME help, at what cost, and on which models | Not started |
| 5 | **Evaluator (Llama 4 Maverick) on all pairs**, then reports and side-by-sides per model | Quality and over-refusal labels | Not started |
| 6 | **Guard-alone baseline** (Qwen3Guard on each request → stock refusal, else the model-alone answer; no new generation) | Is steering better than block-or-allow? | Not started |
| 7 | **Offline policy re-application** (LOOSE / STRICT / topic rules) on logged scores; **decision re-derivation check** | Configurability and auditability claims, no GPU | Not started |
| 8 | **Latency summary** for the paper from the latency benchmark plus per-request timings | Characterize, not claim, latency | Data exists |

**Proposed protected models** (decision pending):
| Tier | Model | Runs on |
|---|---|---|
| Weak | Zephyr-7B-beta (in use) | T4, alongside the risk sensor |
| Small, safety-tuned | Phi-3.5-mini-instruct (Microsoft, 3.8B, MIT) | T4 (fits alone; with decision reuse, no co-hosting needed) |
| Frontier | Gemini 3 Flash (Vertex AI) | API. Its own filters may return empty answers; we report those |

**Not blocking (backlog, in `DECISIONS.md`):** Pattern 2 / trained guard as R (Q21), streaming and
TTFT/TTLT metrics, protected-model-written refusals (Q6), industry policies (Q20), NeMo head-to-head,
our own authored tuning set, full OR-Bench, human ratings (Q13).

**Open items not yet decided or backlogged:**
- Which protected models (above).
- Final dataset sizes: full HarmBench + full XSTest; how much of OR-Bench today.
- Gemini: keep its default filters (realistic) and count empty answers, or relax them.
- When to tag the V1 freeze: after M0b.
- Evaluator check: the human spot-check (about 30 pairs) and when.

**Known weak spots in the code and setup:**
- The VM's console sometimes stops showing job progress (jobs still run). Monitoring now records
  progress in the bucket and BigQuery.
- Spot T4 capacity can disappear; `run-job.sh` recreates the VM elsewhere if a restart fails.
- The evaluator under-uses the "over-refusal" label (still seen in M0).
- The risk sensor still mis-scored "kill" in three harmless prompts in M0 (targeted in M0b).

---

## Log

### Wed 25 Nov, 11:20 pm: GPU availability
- **Problem:** No L4 GPUs could be started in the US.
- **Experiment:** A one-pass check across regions (`infra/create-gpu-vm.sh`), then T4, then Spot T4.
- **Result:** Standard L4 and T4 were unavailable in every US region. A Spot T4 was available in us-central1-c.
- **Next:** Use a Spot T4 (`prime-lab-t4`).

### Thu 26 Nov, 12:51 am: smoke run (20 HarmBench, older harness): `results/20261126-084321`
- **Problem:** Does anything run end to end on a real GPU? Does the protected model comply on its own?
- **Result:** Zephyr complied with 16 of 20 harmful requests. PRIME's input check refused all 20, with a fixed "I can't help" sentence.
- **Next:** Redesign PRIME to V1 (one risk call; intervention only for REWRITE or REFUSE; evaluator LLM).

### Thu 26 Nov, 2:55 am: V1 pilot (40 requests): `results/20261126-104223`
- **Problem:** Does V1 add value over the model alone?
- **Result:** HarmBench harmful answers went from 9/10 to 0/10. But the model alone won overall (17 vs 10, after correcting evaluator errors). The risk sensor flagged 11 of 17 harmless prompts on words like "kill" or "Jewish". Refusals were terse (19-46 words). Review: `PILOT_REVIEW.md`.
- **Next:** Fix refusal quality (D12) and risk sensor calibration (D14).

### Thu 26 Nov, ~4:30 am: latency benchmark: `results/latency-20261126-114207`, `LATENCY.md`
- **Problem:** Is PRIME low latency?
- **Result:** Not as is: the risk sensor takes 3.45 s (7B LLM) vs 0.13 s for a trained guard (Qwen3Guard 0.6B). Allowed requests wait about 3.5 s before any output.
- **Next:** Latency is characterized, not claimed. The trained-guard risk sensor (Pattern 2) is in the backlog.

### Thu 26 Nov, 7:53 pm: M0 (same 40 requests; policy-driven, intent-calibrated risk sensor + refusal v2): `results/20261127-034213`
- **Problem:** Do the risk sensor and refusal fixes work?
- **Result:** Clear improvement. Evaluator preferred PRIME / tie / model alone: 16 / 16 / 8, vs 12 / 11 / 17 in the pilot. Harmless prompts flagged: 3/17, vs 11/17. HarmBench stayed 9→0. Refusals were 52-126 words, none opening "I can't assist". **But REWRITE disappeared (0 of 40):** scores went bimodal (0.0 or 0.8-0.9). Three "kill" prompts (Python process, Call of Duty, lights) were still refused. PRIME's median added time rose from 5.0 s to 6.3 s, because refusals are longer. In-sample: these are the tuning items.
- **Next:** Give the MEDIUM band a concrete definition and add borderline prompts (D16), as M0b.

### Thu 26 Nov, 8:07 pm: M0b (40 pilot + 50 OR-Bench-Hard borderline; MEDIUM band): running
- **Problem:** REWRITE vanished in M0.
- **Experiment:** Concrete LOW / MEDIUM / HIGH bands, with two questions before scoring. Adds 50 borderline prompts.
- **Result:** (pending)
- **Next:** (pending)
