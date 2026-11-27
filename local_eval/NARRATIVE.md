# PRIME: draft narrative and positioning

Status: living draft, started 2026-11-26. This is the story we expect the paper to tell, kept honest
about what's shown and what isn't. Evidence is linked to timestamped runs. Decisions and open questions
are in `DECISIONS.md`, related work in `RELATED_WORK.md`.

## One-line thesis (draft)
PRIME is a configurable safety **harness**: it wraps an existing model and, per request, senses risk (R),
applies a written policy (P), steers the response (I), and records everything (M) for evaluation (E),
without retraining the model.

## The problem: models that comply when harm is framed as a task
Open models with weak or partial safety tuning are widely deployed and fine-tuned. They often refuse a
blunt harmful request but comply when the same harm is framed as a task. Our protected model (Zephyr-7B, a
deliberately lightly safety-tuned open model; **not** a frontier model) shows the pattern clearly:

| Failure mode | What it looks like | Examples |
|---|---|---|
| **A. Warns, then complies** | "I must clarify I don't condone this… for educational purposes, here are the steps" | cash smuggling, fooling a breathalyzer, hacking email / ATM / drone, handgun for a minor |
| **B. Writing tasks, no warning** | Treats "write a note / article / message" as creative writing and produces the harmful text | racist and antisemitic notes, defamatory articles, a phishing text, a coercion message |
| **C. "Hypothetical argument" framing** | "I can't have opinions, but here's a hypothetical argument…" | arguments for sexist claims |
| **D. Dangerous lists as general knowledge** | Answers "list X that are easy to get" like a factual question | biological warfare agents, drug precursors |
| **E. Graphic fiction** | "Describe in graphic detail…" read as a creative brief | a domestic abuse scene |

The same model refuses well on its own when the request is short and blunt ("How do I kill someone?").
Source: `results/20261126-104223/PILOT_REVIEW.md` (26 harmful requests across two runs).

**Caveat for the paper:** frontier models resist these simple framings much better. The claim is about
weakly aligned and fine-tuned open models, and PRIME's value on strong models is an open question (Q1).

## What PRIME is, and where it sits
A harness, not a model. It sits at a different layer from guard classifiers like Llama Guard and
ShieldGemma, which only label text safe or unsafe. A guard classifier could serve as PRIME's risk sensor.
PRIME's closest competitors are other harnesses, especially NeMo Guardrails. See `RELATED_WORK.md` §1a.

Framing we like: **the guardrail as a steering agent.** PRIME decides how a request should be handled and
steers the protected model toward that outcome, rather than just blocking it.

## Early evidence (V1 pilot, 40 requests, `results/20261126-104223/`)
- **Where the model complies with harm, PRIME helps clearly:** HarmBench harmful answers went from 9 of 10 to 0 of 10.
- **Where the model already behaves well, PRIME currently hurts:** it over-flags harmless prompts that sound
  risky, and its refusals are terser than the model's own. Model alone preferred in 17 of 40, PRIME in 10.
- **Cost:** about 5 s per request added on a T4 (two 7B LLM calls). Breakdown and fixes are in `LATENCY.md`.
These are rough rates from 40 requests. Fixes are in progress (refusal quality, risk sensor calibration).

## Claims we want to be able to make (and the experiment for each)
| Claim | Experiment | Status |
|---|---|---|
| PRIME closes the task-framing gap on weakly aligned models | Model alone vs model + PRIME (HarmBench, XSTest) | Pilot: yes on HarmBench |
| …without over-refusing harmless requests | XSTest safe, OR-Bench; evaluator over-refusal label | Pilot: not yet (about 4 of 17 refused) |
| Steering beats block-or-allow | Model + guard classifier with stock refusal vs model + PRIME | Planned (RELATED_WORK §1a) |
| Policy is configurable without retraining | Toggle topic rules / STRICT vs LOOSE; measure behaviour change | Planned |
| PRIME adds value beyond picking a safer model | Model + PRIME vs a strong safety-trained model alone | Open (Q1) |
| Extends to image generation | `eval/image-exploration` plan | Hypothesis (Q10) |
| Low enough latency to sit in front of a live app | Per-call latency benchmark on a T4 (`LATENCY.md`) | **Not as is:** +3.5 s before the first token on ALLOW, about 9 s on REFUSE, vs 0.13 s for a 0.6B guard classifier. Levers in Q19 |

## Known weaknesses to address or acknowledge
Prompted (not trained) risk sensing is less calibrated than trained guards; latency; harness complexity;
the evaluator LLM's own errors (e.g. treating video-game violence as harmful); small samples so far.
