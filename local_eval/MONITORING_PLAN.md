# PRIME Monitoring (M): implementation plan

Branch: `feature/build-monitoring` (from `eval/prime-v1` at 2753886). Status: plan approved, build in progress.

## Goal
One place that records **every interaction end to end**, plus a **dashboard** to track how requests and
outcomes change over time: what users asked, how risky it was, what PRIME did, what the user got, and
(added later by the evaluator) whether that was right.

Today there is no real monitoring. The original PRIME's audit log is created empty and never filled in.
V1 traces are written by the eval harness, not by PRIME, only at the end of each batch, and uploaded only
at the end of a job, so a Spot preemption loses everything. They also have no timestamps and no policy
version.

## Design (first principles)

### 1. One interaction record per request, covering every stage
| Stage | Fields |
|---|---|
| Request | `request_id` (uuid), `ts` (UTC ISO), `source` (e.g. `pilot`, `v1`, `prod`), `run_id`, `dataset`, `dataset_label`, `dataset_category`, `original_request` |
| R: Risk | `risk_score`, `risk_category`, `risk_reason`, `risk_intent`, `risk_error`, `risk_model` |
| P: Policy | `action` (ALLOW/REWRITE/REFUSE/ERROR), `policy_mode`, `policy_hash` (sha256 of the policy dict, first 12 hex chars), `topic_rule` |
| I: Intervention | `rewritten_request`, `refusal_source` (intervention/template), `fallback_reason`, `intervention_model` |
| Protected model | `model_input` (original or rewritten), `model_output`, `protected_model` |
| Outcome | `final_response`, `risk_ms`, `intervention_ms`, `gen_ms`, `prime_ms`, `total_ms`, `errors` (list) |
| Eval only | `condition` (`none` = model alone / `prime`), so the baseline answer is also monitored. Empty or `prime` in production |

The model-alone condition is recorded too (with `condition: none` and empty R/P/I fields). The goal is to
monitor everything, not just PRIME's work.

### 2. How E fits
The evaluator LLM reads interaction records (by run) and writes **evaluation records** keyed by
`request_id`: `evaluator_model`, `ts`, `winner` (prime/model/tie), labels, safety and helpfulness for each
side, `failure_mode`, `reason`, `error`. It must link to both the `none` and `prime` records of the same
request. Add a shared `pair_id` (= dataset item id + run_id) on interaction records so E can join them.

### 3. Write path: batched
- New module `local_eval/monitor.py` with a `Monitor` class: `record(dict)` buffers in memory, and
  `flush()` writes the buffer as **one new JSONL file** (never rewriting old ones) to a sink. It auto-flushes
  every `flush_every` records (default 20) or `flush_seconds` (default 60), and on `close()`.
- Sinks: `local` (directory) and `gcs` (`gs://<bucket>/monitoring/<table>/dt=YYYY-MM-DD/<run_id>-<seq>.jsonl`,
  written via `google-cloud-storage` if installed, else `gcloud storage cp`). Configurable in `config.yaml`
  under `monitoring:`.
- Also print one compact console line per request: `[M] <run_id> <dataset>/<id> <condition> action=... risk=... cat=... ms=...`.
- PRIME emits the record itself: `Prime.run()` takes an optional `monitor` and records the interaction at the
  end of each request. Keep hooks minimal so this merges cleanly with ongoing eval changes on
  `eval/prime-v1` (`prime_local.py`, `run.py`, `evaluate.py` are also being edited there). Put logic in
  `monitor.py`, not inline.
- `run.py` keeps writing `traces.jsonl` (the eval's per-run file) for now. Monitoring is additive.

### 4. Storage: BigQuery over the bucket files
- BigQuery dataset `prime_monitoring` in `afshaan-trial-1` (location US).
- External tables `interactions` and `evaluations` over `gs://afshaan-trial-1-prime-results/monitoring/<table>/*`
  (newline-delimited JSON, explicit schema, Hive partitioning on `dt` if straightforward). No load jobs,
  and nothing extra is needed on the VM, which only has storage write access.
- View `interactions_with_eval`: interactions joined to evaluations on `request_id`/`pair_id`.
- Script `local_eval/infra/setup-monitoring.sh` (idempotent) creates the dataset, tables and view with `bq`.

### 5. Dashboard: Looker Studio
- Recommended charts (documented in the plan or README): requests over time by risk category; action mix
  over time; fallback rate; harmful and over-refusal rate, model alone vs PRIME; latency p50/p90; a
  drill-down table (request → rewrite/refusal → response → verdict).
- Generate a Looker Studio **Linking API** URL that opens a new report pre-connected to the BigQuery view
  (the user clicks once to create it in their account). Put it in `local_eval/MONITORING.md`.
- `report.py` stays as the per-run snapshot.

### 6. Backfill
A one-off script `local_eval/infra/backfill_monitoring.py` that converts existing runs (`results/*/traces.jsonl`
and `evaluator.jsonl`) into interaction and evaluation records and uploads them, so the dashboard isn't empty
(at least the V1 pilot `results/20261126-104223`).

## Out of scope (decisions ledger)
Alert thresholds; retention and redaction of user prompts in logs; drift detection on risk scores; production
serving.

## Done when
- Mock run (`python run.py --mock --sizes harmbench=4 xstest=8` with monitoring on) writes interaction files.
  The mock evaluator writes evaluation files. Both appear in BigQuery and the view returns joined rows.
- A real (small) write to GCS and a BigQuery query over the external tables succeed.
- Pilot data is backfilled and queryable.
- `MONITORING.md` explains what's recorded, where, how to query it, and the dashboard link.
- `DECISIONS.md`: add D11 (monitoring design) and backlog items.
- Committed and pushed to `feature/build-monitoring` only.
