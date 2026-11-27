# PRIME research benchmark study plan (draft)

Status: draft, 2026-11-26. Goal: enough data points to find the limits of the harness approach, not to run
everything. Each phase only starts if the previous one says it's worth it. Decisions: `DECISIONS.md`.
Story: `NARRATIVE.md`. Baselines and benchmarks: `RELATED_WORK.md`.

## Research questions
| # | Question | Main evidence |
|---|---|---|
| RQ1 | Does PRIME reduce harmful output, and does that hold beyond weak models? | Harmful rate, model alone vs model + PRIME, across protected models of different safety strength |
| RQ2 | At what cost to helpfulness (over-refusal, worse answers)? | Over-refusal rate on safe prompts, evaluator helpfulness and win rate |
| RQ3 | Is steering better than block-or-allow? | Model + PRIME vs model + guard classifier with a stock refusal |
| RQ4 | Does PRIME add value beyond just using a safer model? (DECISIONS Q1) | Weak model + PRIME vs strong model alone; strong model + PRIME |
| RQ5 | Which components matter? | Ablations (below) |
| RQ6 | Is the latency and cost acceptable? | `LATENCY.md` |
| RQ7 | Does the policy really configure behaviour? | Topic rules on/off, STRICT vs LOOSE |
| (RQ8) | Does it extend to image generation? | Separate branch `eval/image-exploration` |

## Protected models: a spread of safety strength
Constraints: not Qwen (the risk sensor family), not Llama (the evaluator's family), and ungated on Hugging
Face (we have no access token) or available through an API we can use.

| Tier | Model | Why | Where it runs | Status |
|---|---|---|---|---|
| Weak | **Zephyr-7B-beta** (Mistral-based) | Light safety tuning; complies when harm is framed as a task | T4 | In use |
| Mid / strong open | **Phi-4** (Microsoft, 14B, MIT) | Open weights with substantial safety post-training | T4 in 4-bit, one model at a time (see "Engineering"), or L4 | Proposed. Verify licence and fit on the VM |
| Frontier (API) | **Gemini 3 Flash** (Vertex AI) | A strong safety-trained model with Google's default filters, i.e. what a real deployment gets. Answers RQ4 | Vertex AI, no GPU | Proposed |
| Optional | gpt-oss-20b (OpenAI open weights) | Frontier-style safety training, open weights | L4 (likely too big for a T4) | Only if an L4 is available |

Alternative mid-tier if Phi-4 doesn't fit or is too slow: IBM Granite 3.3 8B Instruct (Apache 2.0).
Expectation to test, not assume: PRIME's harm reduction shrinks as the protected model gets safer, while its
over-refusal cost stays. Where those lines cross is the key finding.

## Conditions
| Condition | What the user gets |
|---|---|
| `none` | Protected model alone |
| `guard` | Guard classifier on the request; if unsafe, a stock refusal; else the model answers (industry baseline, RQ3) |
| `prime` | Full PRIME (V1) |
| Ablations | One change from `prime` each (below) |

## Ablations (on a 100-request subset, one protected model)
| Ablation | Tests |
|---|---|
| Risk sensor: Qwen-7B vs a small model vs a trained guard (Qwen3Guard / Granite Guardian) as R | Is a prompted LLM worth it as R? Latency vs accuracy |
| Refusal: `prime` writes vs `steer` (protected model writes) (DECISIONS Q6) | Refusal quality, how often refusals actually refuse, latency |
| No REWRITE (ALLOW / REFUSE only) | Does the middle tier add value? |
| Refusal prompt v1 vs v2 | The pilot's fix, isolated |
| STRICT vs LOOSE thresholds; topic rules on vs off | Configurability (RQ7) and the over-refusal trade-off |

## Datasets
| Set | Purpose | Size per protected model |
|---|---|---|
| HarmBench standard (+ contextual) | Harmful requests the model may comply with | 50 |
| XSTest safe | Over-refusal | 80 |
| XSTest unsafe | Blunt harmful requests | 70 |
| A jailbreak set (JailbreakBench or StrongREJECT prompts) | Task-framing and adversarial wrappers, exactly Zephyr's failure modes A-E | 50 (phase 4) |
| OR-Bench-Hard subset | Harder over-refusal | 50 (phase 4) |

## Controls and validity
- Same prompts, same decoding (temperature 0), same evaluator across conditions. Protected-model answers are
  cached once per (model, request) and reused by every guard condition.
- The evaluator is blind (random A/B order) and from a different family than the models it judges. Validate it:
  a position-bias check, a second evaluator on a 40-request subset, and about 100 human-rated items (Q13).
- Report rates with 95% bootstrap confidence intervals. With 200 requests that's about ±7 points overall.
- Watch for benchmark contamination of guard models (RELATED_WORK pitfalls).

## Phases
| Phase | What | Size | Rough cost |
|---|---|---|---|
| 0 | V1 pilot (done) | 40, Zephyr | done |
| 1 | Fix refusals and calibrate the risk sensor; before/after on the same 40 | 40, Zephyr | ~$0.10 |
| 2 | Main run: `none` vs `prime` on three protected models | 200 × 3 | T4 ~6-8 h (~$2) + Gemini API (cents to a few $) |
| 3 | Baselines: `guard` condition; strong model alone vs weak + PRIME | reuse phase 2 answers | ~1-2 h GPU |
| 4 | Ablations; jailbreak and OR-Bench sets | 100-subset; +100 | ~3-4 h GPU |
| 5 | Evaluator validation (second evaluator, human ratings) | 40 + 100 | human time |

## Engineering needed
- **Staged runs**, so any protected model fits on one GPU: run the risk sensor and intervention for all
  requests first, unload, then run the protected model on the original or rewritten requests. This replaces
  serving both models at once. It also caches protected-model answers for reuse.
- Protected model via API (for Gemini): an OpenAI-compatible client option, like the evaluator's.
- A `guard` condition with a pluggable classifier.
- A `refuse_via: prime | steer` flag (Q6).
- Merge monitoring (`feature/build-monitoring`) so every run is recorded.
