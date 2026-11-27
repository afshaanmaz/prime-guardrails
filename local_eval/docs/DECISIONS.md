# PRIME design decisions ledger

What's decided for the current build, and the open questions parked for later builds. Newest
decisions at the top of each section. `DESIGN.md` has the longer discussion; where they differ,
this file wins.

## Decided (V1, text)

| # | Decision | Why | Date |
|---|---|---|---|
| D16 | The risk sensor's prompt gives the middle band (REWRITE) a concrete definition: "a safe, useful version exists, but answering exactly as asked could cause some harm", with cases (dual-use information, risky phrasing of a legitimate goal, ambiguous intent, sensitive topics needing care). The model answers two questions (legitimate need? harmful if answered literally?) before scoring. A borderline dataset (OR-Bench-Hard-1K) is added to exercise REWRITE | After D14, REWRITE disappeared (M0: 0 of 40); scores went bimodal (0.0 or 0.8-0.9), and XSTest/HarmBench have almost no genuinely borderline prompts. Graduated response is a core claim | 2026-11-27 |
| D15 | Roles: **P** defines the policy; **R** only measures risk; **I** decides the action by the policy's rule (plain code, so every decision is reproducible) and carries it out; **M** records; **E** judges offline | Each step has one job, with no "P twice". Matches the original PRIME's "Intervention Router" | 2026-11-27 |
| D14 | The risk sensor reads the policy: the general policy in config.yaml defines the categories with one-line definitions, and R's prompt is built from them. R is calibrated to score intent and real-world consequence, not alarming words, with the low-risk cases named explicitly | The pilot over-flagged 11 of 17 harmless prompts on words like "kill" or "Jewish", and R ignored the policy (the paper's core claim). Caveat: the low-risk cases mirror over-refusal taxonomies like XSTest's, so XSTest results are somewhat favourable; check on OR-Bench later | 2026-11-27 |
| D13 | Intervention has two tools: **steer** (change what the protected model is asked) and **respond** (reply on the model's behalf). REWRITE steers; REFUSE responds. Steering refusals through the protected model stays an optional research setting (Q6) | It's the only split that works for every model, including image-only ones (which can't write a refusal or have their output edited). Explains the asymmetry instead of hiding it | 2026-11-26 |
| D12 | Refusal prompt revised: say what you won't help with in your own words, explain briefly, then give real help directly (no empty offers), care and a crisis resource for self-harm. No word limit (dropped so it doesn't over-constrain the reply) | V1 pilot: refusals were 19-46 words, 20 of 26 opened identically, 9 promised help without giving it, and they lost to the protected model's own refusals | 2026-11-26 |
| D11 | Monitoring (M): PRIME writes one interaction record per request (every stage, R-P-I-model-outcome, plus the model-alone baseline in evals); the evaluator writes evaluation records linked by `pair_id`. Batched JSONL files to `gs://<bucket>/monitoring/<table>/dt=.../`, BigQuery external tables + view `interactions_with_eval`, Looker Studio dashboard. Test records tagged `source = test`. Details: `MONITORING.md` | The original audit log was never filled in, and eval traces were written only at batch end and uploaded at job end (lost on preemption). Files in the bucket need only storage write on the VM; external tables need no load jobs | 2026-11-26 |
| D10 | Evaluator LLM: Llama 4 Maverick (Vertex AI managed API). Names follow PRIME's letters: risk sensor LLM (R), intervention LLM (I), evaluator LLM (E); 'judge' is no longer used | The evaluator must not refuse to evaluate. The managed Llama 4 endpoint has no Llama Guard filter. If it refuses or errors, switch evaluators (fallback: Phi-4 on the T4) | 2026-11-26 |
| D9 | Image exploration runs on a separate branch, `eval/image-exploration` | Keeps V1 (text) clean | 2026-11-26 |
| D8 | V1 eval: protected model alone vs model + PRIME, scored by a blind evaluator LLM from a different model family, plus per-response labels (harmful / safe-helpful / refusal with alternative / bare refusal / over-refusal / off-target) | Shows whether PRIME adds value over the model, and where it fails | 2026-11-26 |
| D7 | The risk sensor LLM's prompt spells out the score scale (no example prompts) | Scores were saturated at 0.8-1.0, so REWRITE never fired | 2026-11-26 |
| D6 | Refusals are contextual, written by PRIME. Per-category templates are only a fallback, and the fallback rate is reported every run | A flat "I can't help" is less useful than the model's own nuance | 2026-11-26 |
| D5 | Option B: Intervention is its own model call, made only for REWRITE or REFUSE (runs on the risk sensor's model with separate prompts) | Keeps R (sense risk) and I (intervene) separate; works for image-only models too | 2026-11-26 |
| D4 | At most 2 PRIME model calls per request (Risk, plus Intervention when not ALLOW) | Low latency was an original PRIME goal; the original used 2 LLM calls on every request | 2026-11-26 |
| D3 | REWRITE acts on the request: Intervention rewrites the request and the protected model answers the rewrite. The original request is always logged | Extends to image generation (the original PRIME guarded a text-to-image tool) | 2026-11-26 |
| D2 | P-R-I-M-E only: the risk sensor runs once, at the start. No second risk pass on the answer | Stay within the framework's components | 2026-11-26 |
| D1 | Three actions only: ALLOW / REWRITE / REFUSE | Clear, matches the original | 2026-11-26 |

## Open questions (backlog)

| # | Question | Notes |
|---|---|---|
| Q1 | **Is PRIME adding value, or should users just pick a safer model?** | V1 uses a weak-refusal model. Planned: PRIME on a weak model vs a strong model alone; PRIME on a strong model |
| Q2 | Latency and cost budget per request | V1 adds 1-2 calls. Option A (the risk sensor writes the rewrite or refusal in the same call) would make it 1 |
| Q3 | Answer-side checking | Dropped for V1 (D2). Would catch harmful answers to allowed or rewritten requests |
| Q4 | Refusal text isn't safety-checked | Leak risk is low (the refusal prompt forbids operational detail) but unmeasured; the evaluator LLM's labels will show it |
| Q5 | Rewriting the request vs editing the response, for text models | D3 picked the request for image extensibility. Revisit with V1 data |
| Q6 | The protected model writes its own refusal (option D) | Only works for text-capable models. Same latency as B |
| Q7 | Severity tiers (hard decline / helpful refusal / safe completion) | Needs a calibrated severity signal |
| Q8 | Risk sensor calibration beyond the score scale | Few-shot anchors (careful with benchmark overlap), separate intent and severity |
| Q9 | Topic rules override regardless of score | e.g. any "Competitors" request is refused, even at risk 0. Measure on XSTest first |
| Q10 | Image extensibility is still a hypothesis | First experiment being planned on `eval/image-exploration` |
| Q11 | Benchmark against other guardrails | Plan in `RELATED_WORK.md` (Llama Guard, ShieldGemma, WildGuard, Qwen3Guard, Model Armor, ...) |
| Q12 | Personal-data redaction and prompt-injection detection on input | Model Armor-style. Not measurable on HarmBench or XSTest |
| Q13 | Human ratings to validate the evaluator LLM | About 100 items. No standard benchmark scores refusal quality, so this could be a contribution |
| Q14 | Monitoring alert thresholds | e.g. harmful rate, fallback rate, risk sensor errors or latency above a limit. Needs a baseline from real traffic first |
| Q15 | Drift detection on risk scores and the action mix | Compare score distributions per week or per policy hash |
| Q16 | Retention and redaction of prompts and answers in monitoring records | Records are stored verbatim today, including harmful content; needs a retention period and PII redaction before production |
| Q17 | Production serving and the `prod` source | Monitoring is built for it (`Prime.run(..., monitor)`), but there is no serving path yet |
| Q18 | Dashboard as a reusable template | Once the Looker Studio report is built, use its id as `c.reportId` in the Linking API URL so new reports come with the charts |
| Q19 | **Latency for a live app: replace the 7B risk sensor with a small trained guard (e.g. Qwen3Guard-Gen-0.6B) and stream or cap refusals?** | T4, `LATENCY.md`: R takes 3.45 s, the refusal 5.6 s; Qwen3Guard-0.6B takes 0.13 s. A short R output alone saves 2 s. Needs a quality comparison (guard as R vs the prompted 7B R) before it is adopted |
| Q20 | Industry-specific policies (e.g. consumer finance, children's education) as separate policy files | The mechanism exists (D14); writing and testing a second policy is backlog |
| Q21 | **Pattern 2: R only measures (score + category); I works out intent itself; R can be the prompt or a trained guard (e.g. Qwen3Guard)** | Enables "R is swappable" and much lower latency (Q19). Open exploration: decide between Pattern 1 (current) and Pattern 2 from data |
| Q22 | Split R's score into severity and intent, combined by I's rule | Would make decisions easier to interpret; needs re-tuned thresholds |
