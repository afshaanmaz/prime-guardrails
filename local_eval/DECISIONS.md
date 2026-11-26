# PRIME design decisions ledger

What's decided for the current build, and the open questions parked for later builds. Newest
decisions at the top of each section. `DESIGN.md` has the longer discussion; where they differ,
this file wins.

## Decided (V1, text)

| # | Decision | Why | Date |
|---|---|---|---|
| D13 | Intervention has two tools: **steer** (change what the protected model is asked) and **respond** (reply on the model's behalf). REWRITE steers; REFUSE responds. Steering refusals through the protected model stays an optional research setting (Q6) | It's the only split that works for every model, including image-only ones (which can't write a refusal or have their output edited). Explains the asymmetry instead of hiding it | 2026-11-26 |
| D12 | Refusal prompt revised: say what you won't help with in your own words, explain briefly, then give real help directly (no empty offers), care and a crisis resource for self-harm, about 60-150 words | V1 pilot: refusals were 19-46 words, 20 of 26 opened identically, 9 promised help without giving it, and they lost to the protected model's own refusals | 2026-11-26 |
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
| Q8 | Judge calibration beyond the score scale | Few-shot anchors (careful with benchmark overlap), separate intent and severity |
| Q9 | Topic rules override regardless of score | e.g. any "Competitors" request is refused, even at risk 0. Measure on XSTest first |
| Q10 | Image extensibility is still a hypothesis | First experiment being planned on `eval/image-exploration` |
| Q11 | Benchmark against other guardrails | Plan in `RELATED_WORK.md` (Llama Guard, ShieldGemma, WildGuard, Qwen3Guard, Model Armor, ...) |
| Q12 | Personal-data redaction and prompt-injection detection on input | Model Armor-style. Not measurable on HarmBench or XSTest |
| Q13 | Human ratings to validate the evaluator LLM | About 100 items. No standard benchmark scores refusal quality, so this could be a contribution |
