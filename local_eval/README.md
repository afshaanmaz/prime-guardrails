# PRIME on local models

Tests whether PRIME catches unsafe content when the protected model lets it through.
Everything runs on open models served locally with vLLM, so no provider safety filter
blocks anything upstream and every block in the results is PRIME's own.

Lives alongside the original ADK agent in `../prime-guardrails/`, which is unchanged. Built from it (same judge-score + threshold policy,
LOOSE mode, 0.7 / 0.3), with three changes:
1. **Output gate:** the original only checks the user's prompt. This adds a second judge
   pass on the model's response.
2. **Errors counted separately:** the original labelled every empty reply an
   "API safety block". Here a judge failure is its own column.
3. **Per-request latency:** each model call is timed; the original's sub-second figure
   was throughput at 50 parallel threads (its CSVs show ~7–8 s per request).
4. **Policy fully enforced:** the original config defined per-topic rules
   (`sensitive_topics`) that no code read, and only Loose thresholds. Here topic rules
   apply after the score (they can only make an action stricter), and `mode: STRICT`
   uses lower thresholds (0.5 / 0.15, my choice; there were no Strict values to copy).

## Conditions (V1)
- `none`: the protected model answers directly (baseline).
- `prime`: PRIME's risk judge scores the request; the policy picks ALLOW (original request goes to the
  model), REWRITE (the request is rewritten, and the model answers the rewrite) or REFUSE (PRIME writes a
  contextual refusal, and the model isn't called). See `prime_local.py` and `DECISIONS.md`.

## Datasets
- **HarmBench** (200 standard behaviors, all unsafe): does harmful content reach the user?
- **XSTest** (250 safe prompts that look risky, 200 unsafe): does PRIME over-flag?
SafetyBench (the original eval) is multiple-choice safety knowledge with no answer key
in the test file, so it can't measure this.

## Run on the VM
VM setup is in `infra/` (`setup-prime-lab.sh`, then `vm-steps.md`).
```bash
cd local_eval
python3 -m pip install -r requirements.txt
./serve.sh                      # generator on :8001, judge on :8002
python3 run.py --sizes harmbench=10 xstest=30    # pilot
python3 run.py --sizes harmbench=50 xstest=150   # V1 run
python3 judge_ab.py results/<run_id>             # blind A/B judge (ab_judge in config.yaml)
python3 report.py results/<run_id>               # REPORT.md + COMPARISON.md
```
`python3 run.py --mock --limit 20`, `python3 judge_ab.py results/<id>-mock --mock`, `python3 report.py results/<id>-mock`
tests the plumbing without a GPU.

Each run writes `results/<run_id>/`: `meta.json` (models, policy, commit),
`traces.jsonl` (every prompt, verdict, output, timing), `graded.jsonl`, `summary.md`.

## Metrics (summary.md)
- `harmful_rate`: unsafe prompts whose final output the grader calls harmful.
- `catch_on_unsafe` / `false_flag_on_safe`: share PRIME refused or rewrote.
- `judge_errors`: PRIME's judge gave no usable score (fail-closed → refusal, but counted).
- `total_ms_*`, `prime_ms_*`: per-request latency, and the part PRIME adds.

## Open decisions
1. **Generator.** Default Qwen2.5-7B-Instruct (AWQ) is ungated but refuses a lot of
   HarmBench on its own. If the smoke run shows a low baseline `harmful_rate`, swap in a
   weaker-refusal open model so there's unsafe content for PRIME to catch.
2. **Grader.** Must not be PRIME's judge. HarmBench's own classifier is the most citable
   choice but needs its own prompt format; a different-family instruct model with
   `grade.py`'s prompt is simpler. `grade.py` refuses to run until this is set.
3. **Judge.** Default is the same family as the generator; a different family would be a
   cleaner comparison.
