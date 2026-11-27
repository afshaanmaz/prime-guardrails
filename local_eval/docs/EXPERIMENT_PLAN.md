# PRIME local eval: experiment plan

> **Superseded** by `EXPERIMENTATION_PLAN.md` (live, timestamped). Kept for history.

Written 2026-11-26, before any GPU time. Based on `local_eval/` at commit d0f367d (branch `local-eval`).

## What is being measured
Can PRIME (a judge model scores risk 0–1, then policy thresholds pick ALLOW / REWRITE / REFUSE)
stop unsafe content that the protected model would otherwise produce, and how often does it
wrongly flag safe prompts? Three conditions per prompt:

| condition | what runs |
|---|---|
| `none` | generator answers directly (baseline) |
| `input` | judge scores the prompt, then refuse / rewrite / allow, then generate |
| `input_output` | as `input`, then the judge scores the response before it is shown |

Datasets (both downloaded by `data.py` from GitHub raw):
- HarmBench, 200 "standard" behaviors, all unsafe → `harmful_rate`, `catch_on_unsafe`
- XSTest, 250 safe + 200 unsafe → `false_flag_on_safe` (over-refusal), plus `harmful_rate` on the unsafe half

Full run = (200 + 450) prompts × 3 conditions = **1,950 traces**.

## Checked already (no GPU)
`python3 run.py --mock --limit 20` and `grade.py --mock` run cleanly in a sandbox: datasets load
(200 / 450, labels 250 safe / 200 unsafe), all three conditions run, the judge-error path is
recorded, and summary.md is written. The real models are the only part left untested.

## Decisions needed before the real run
1. **Grader (required; `grade.py` exits until it is set).** Nothing in `serve.sh` serves port 8003.
   Options:
   - **(recommended)** `cais/HarmBench-Mistral-7b-val-cls`: HarmBench's own classifier, ungated,
     about 14.5 GB in fp16, so it runs alone on the L4 after the generator and judge are stopped. It needs its own
     prompt format on the completions endpoint, which is a small change to `grade.py`.
   - A different-family instruct model with `grade.py`'s current prompt, e.g.
     `microsoft/Phi-3.5-mini-instruct` (ungated). No code change, but less citable.
2. **Generator.** Default Qwen2.5-7B-Instruct-AWQ probably refuses most of HarmBench on its own.
   Rule: if the smoke run's HarmBench `none` harmful_rate is **below about 0.2**, switch the generator to
   a weaker-refusal ungated model (candidate: `TheBloke/zephyr-7B-beta-AWQ`, which has a high
   direct-request success rate in the HarmBench paper) so there is unsafe content for PRIME to catch.
   This also puts the generator and judge in different families (decision 3 in the README).
3. **Judge.** Keep Qwen2.5-7B-Instruct-AWQ. Different from the generator if decision 2 swaps it.

## Run order on prime-lab (1× L4, 24 GB)
1. Environment: `python3 -m venv ~/venv && . ~/venv/bin/activate && pip install -r requirements.txt`
   (a venv keeps vLLM's torch pin from fighting the Deep Learning VM image). `nvidia-smi` must show the L4.
2. `./serve.sh`: generator on :8001, judge on :8002, each at 0.42 GPU memory.
   Known risk: the judge starts 5 s after the generator and can fail its free-memory check while
   the generator is still loading. If `logs/judge.log` shows that, start the judge only after :8001 is up.
3. **Smoke run:** `python3 run.py --limit 20`. Check: judge_errors near 0 (JSON parsing works on
   real Qwen output), latencies are plausible, and the outputs in traces.jsonl are actually generated.
4. Stop both servers. Serve the grader on :8003 (`--gpu-memory-utilization 0.85`), grade the smoke
   run, and apply the generator rule from decision 2. If the generator changes, smoke-test again.
5. **Run A (main result):** LOOSE policy (0.7 / 0.3), full 1,950 traces. Then grade it as in step 4.
6. **Run B (if time allows):** `policy.mode: STRICT` (0.5 / 0.15), same models, then grade.
   This shows how much over-refusal the stricter thresholds cost on XSTest.
7. Stop the VM: `gcloud compute instances stop prime-lab --zone us-central1-a`.

## Time and cost estimate
g2-standard-4 is about $0.71/hr. The model download and server start take about 10 min, smoke tests about 15 min,
each full run about 30–60 min at concurrency 8, and grading about 10 min per run. Runs A and B together come to **about 2.5–3 h,
about $2**, well inside the 8 h auto-stop. The 60 min idle auto-stop can fire between steps if the GPU
is left idle, so keep the servers running or move straight on to the next step.

## What gets saved in the repo
For each run, `local_eval/results/<run_id>/` holds `meta.json`, `traces.jsonl`, `graded.jsonl`, `summary.json` and
`summary.md`. `logs/` is gitignored, so copy `logs/*.log` (the vLLM server logs) and the stdout of
run.py and grade.py into `results/<run_id>/logs/` before committing. Commit to a working branch,
not `main`.

## Caveats to report with the results
- Every grader verdict comes from a model. Spot-check about 20 graded HarmBench outputs by hand.
- Topic rules (Competitors / Mental Health / Geopolitical) can fire on benchmark prompts and
  inflate `catch` and `false_flag`. traces.jsonl records `topic_rule`, so count them separately.
- Temperature 0 with one seed gives one sample per prompt, so there are no error bars.
