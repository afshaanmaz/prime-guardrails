# PRIME on local models

Tests whether PRIME catches unsafe content when the protected model lets it through.
Everything runs on open models served locally with vLLM, so no provider safety filter
blocks anything upstream and every block in the results is PRIME's own.

> **Branch `feat/redesign-risk-sensor`:** the risk sensor returns a level (low / medium / high) and a
> category instead of a 0-1 score, and the policy maps them to actions with a table. Refusals are canned per
> category (no model call); REWRITE rewrites the request. Errors are recorded as errors, never as risk.
> Design: `docs/RISK_SENSOR_REDESIGN.md`. Code: `risk.py`, `prime_local.py`, `config.yaml` (`policy`).
> Tests: `python3 -m pytest tests`. Points 2 and 3 below describe the V1 branch.

Lives alongside the original ADK agent in `../prime-guardrails/`, which is unchanged. Same
P-R-I-M-E structure and policy (LOOSE thresholds 0.7 / 0.3 on V1), with these changes:
1. **Intervention is code plus one LLM call, not a router LLM.** Policy is applied deterministically. Only
   REWRITE (rewrite the request) and REFUSE (contextual refusal) call the intervention LLM. At most two PRIME
   calls per request, the same as the original's risk sensor plus router.
2. **Contextual refusals** instead of a fixed sentence; per-category templates only as a logged fallback.
3. **Policy fully enforced:** the original's per-topic rules (`sensitive_topics`) were never read by any code.
   Here they apply after the score and can only make the action stricter. `mode: STRICT` uses 0.5 / 0.15.
4. **Errors counted separately**, and **per-request latency** for every model call (the original's
   sub-second figure was throughput at 50 parallel threads).

Decisions and open questions: `docs/DECISIONS.md`. All design notes, plans and reviews are in `docs/`.

## Conditions (V1)
- `none`: the protected model answers directly (baseline).
- `prime`: PRIME's risk sensor rates the request (level + category); the policy picks ALLOW (original request
  goes to the model), REWRITE (the request is rewritten, and the model answers the rewrite) or REFUSE (the
  category's canned refusal; the model isn't called). See `prime_local.py` and `docs/DECISIONS.md`.

## Datasets
- **HarmBench** (200 standard behaviors, all unsafe): does harmful content reach the user?
- **XSTest** (250 safe prompts that look risky, 200 unsafe): does PRIME over-flag?
SafetyBench (the original eval) is multiple-choice safety knowledge with no answer key
in the test file, so it can't measure this.

## Run on the VM
VM setup is in `infra/` (`setup-prime-lab.sh`, then `docs/vm-steps.md`).
```bash
cd local_eval
python3 -m pip install -r requirements.txt
./serve.sh                      # protected model on :8001, risk sensor LLM on :8002
python3 run.py --sizes harmbench=10 xstest=30    # pilot
python3 run.py --sizes harmbench=50 xstest=150   # V1 run
python3 evaluate.py results/<run_id>             # evaluator LLM, blind A/B (evaluator in config.yaml)
python3 report.py results/<run_id>               # REPORT.md + COMPARISON.md
```
`python3 run.py --mock --limit 20`, `python3 evaluate.py results/<id>-mock --mock`, `python3 report.py results/<id>-mock`
tests the plumbing without a GPU.

Each run writes `results/<run_id>/`: `meta.json` (models, policy, commit), `traces.jsonl` (every request, with `request_id` and `pair_id`:
risk verdict, action, rewritten request or refusal, output, per-step timing), `evaluator.jsonl`,
`REPORT.md`, `COMPARISON.md` and `summary.json`.

## Monitoring
Every request (and the model-alone baseline) is recorded end to end and batched to
`gs://afshaan-trial-1-prime-results/monitoring/`; BigQuery (`prime_monitoring`) reads it, and a Looker Studio
dashboard charts it over time. What's recorded, how to query it and the dashboard link: `docs/MONITORING.md`.

## Metrics (REPORT.md)
- PRIME's action mix (ALLOW / REWRITE / REFUSE) per slice, template fallback rate, risk sensor errors.
- Evaluator LLM, blind A/B: PRIME wins / ties / model wins; harmful and over-refusal rates for model alone vs
  PRIME; mean helpfulness (1-5); outcome by PRIME action; harm prevented vs introduced; failure modes; every loss.
- `prime_ms_*`, `total_ms_*`: what PRIME adds per request, and end-to-end latency.

## Models and open decisions
- **Protected model:** Zephyr-7B-beta (AWQ). Chosen because it complies with most harmful requests on
  its own (16 of 20 in the first T4 run), so there's something for PRIME to catch.
- **Risk sensor LLM (R) and intervention LLM (I):** Qwen2.5-7B-Instruct (AWQ), a different family from the protected model.
- **Evaluator LLM (E):** Llama 4 Maverick on Vertex AI's managed API (`evaluator` in config.yaml). A different family from both, and no Llama Guard filter in front of it.
- Everything else that's open is tracked in `docs/DECISIONS.md`.
