# PRIME Monitoring (M)

Every request PRIME handles is recorded end to end, in one place, and can be charted over time.
Design and reasons: `MONITORING_PLAN.md` and D11 in `DECISIONS.md`.

> **Content warning:** records hold prompts and answers verbatim, including raw answers to harmful
> benchmark requests. Redaction and retention are not handled yet (backlog Q16).

## What is recorded

**Interaction records** (table `interactions`): one per request, written by PRIME itself at the end of
`Prime.run()`. Eval runs also record the model-alone baseline (`condition = none`, with empty risk,
policy and intervention fields), so the baseline is monitored too.

| Stage | Fields |
|---|---|
| Request | `request_id`, `pair_id` (= `<run_id>:<dataset item id>`; links the `none` and `prime` records of one item), `ts` (UTC, when the request arrived), `source`, `run_id`, `condition`, `dataset`, `dataset_id`, `dataset_label`, `dataset_category`, `original_request` |
| R: Risk | `risk_score`, `risk_category`, `risk_reason`, `risk_intent`, `risk_error`, `risk_model` |
| P: Policy | `action` (ALLOW / REWRITE / REFUSE / ERROR; empty for model alone unless it errored), `policy_mode`, `policy_hash` (first 12 hex of the sha256 of the policy), `topic_rule` |
| I: Intervention | `rewritten_request`, `refusal_source` (intervention / template), `fallback_reason`, `intervention_model` |
| Protected model | `model_input` (original or rewritten request; empty if REFUSE), `model_output`, `protected_model` |
| Outcome | `final_response`, `risk_ms`, `intervention_ms`, `gen_ms`, `prime_ms`, `total_ms`, `errors` |

**Evaluation records** (table `evaluations`): one per evaluated pair, written by `evaluate.py`:
`eval_id`, `pair_id`, `prime_request_id`, `model_request_id`, `ts`, `source`, `run_id`, `dataset`,
`dataset_id`, `evaluator_model`, `winner` (prime / model / tie), `prime_was` (A / B), `identical`,
`prime_safety`, `prime_helpfulness`, `prime_label`, `model_safety`, `model_helpfulness`, `model_label`,
`failure_mode`, `reason`, `evaluator_ms`, `error`.

The record shapes and the BigQuery schemas come from one place: `INTERACTION_SCHEMA` and
`EVALUATION_SCHEMA` in `monitor.py`.

### `source` values
| source | What |
|---|---|
| `pilot` | V1 pilot, backfilled from `../results/20261126-104223` (80 interactions, 40 evaluations) |
| `v1` | real eval runs (default in `config.yaml`) |
| `test` | every `--mock` run (always, whatever the config says). Filter these out on the dashboard |
| `prod` | reserved for production serving |

Test records live in the same tables as real ones, tagged `source = test`, so the whole pipeline
(files, tables, view, dashboard) is tested exactly as it runs. To remove them from the bucket:
`gcloud storage rm "gs://afshaan-trial-1-prime-../results/monitoring/*/dt=*/*-mock-*.jsonl"`.

## Where it goes

```
gs://afshaan-trial-1-prime-../results/monitoring/
  interactions/dt=YYYY-MM-DD/<run_id>-<tag>-<seq>.jsonl
  evaluations/dt=YYYY-MM-DD/<run_id>-<tag>-<seq>.jsonl
```
- Records are buffered and written as a **new file** every 20 records or 60 seconds (whichever comes
  first) and when the run ends. Old files are never rewritten, and a Spot preemption loses at most
  the last minute.
- `dt` is the UTC date the file was written; use `ts` for time. `<tag>` is random per writer, so files
  never collide; backfills use the fixed tag `backfill` so re-running overwrites instead of duplicating.
- Writes use `google-cloud-storage` if it is installed and has credentials, else `gcloud storage cp`
  (what the VM has). If a GCS write fails, the batch is kept under `../results/monitoring/` and a warning
  is printed; the run carries on.
- A console line per request: `[M] <run_id> <dataset>/<id> <condition> action=... risk=... cat=... ms=...`.
- `traces.jsonl` is still written per run (now with `request_id` and `pair_id`); monitoring is additive.

Settings: `monitoring:` in `config.yaml` (`sink: gcs | local`, `gcs_prefix`, `source`, `flush_every`,
`flush_seconds`, `console`). Environment overrides: `PRIME_MONITOR_SINK=gcs|local|off`,
`PRIME_MONITOR_SOURCE=<tag>`. Mock runs write to `../results/monitoring/` unless `PRIME_MONITOR_SINK=gcs`.

```bash
python run.py --mock --sizes harmbench=4 xstest=8                   # local files, source=test
PRIME_MONITOR_SINK=gcs python run.py --mock --sizes harmbench=4 xstest=8   # to the bucket, source=test
python evaluate.py ../results/<run_id>-mock --mock                     # evaluation records, same rules
```

On the VM: the job scripts check out `eval/prime-v1`, so monitoring starts there once this branch is
merged. Nothing else is needed on the VM (it has `gcloud` and storage write access). To tag a run:
`infra/run-job.sh infra/jobs/v1.sh SIZES="..." PRIME_MONITOR_SOURCE=pilot`.

## BigQuery

Dataset `afshaan-trial-1.prime_monitoring` (US), created by `infra/setup-monitoring.sh` (idempotent;
re-run it after changing a schema in `monitor.py`):

| Object | What |
|---|---|
| `interactions` | external table over `monitoring/interactions/*` (JSON, Hive-partitioned on `dt`) |
| `evaluations` | external table over `monitoring/evaluations/*` |
| `interactions_with_eval` | view: every interaction plus the latest error-free verdict for its pair, with the verdict for its own side: `safety`, `helpfulness`, `eval_label`, `is_harmful`, `is_over_refusal`, `won`, plus `condition_name` ("model alone" / "model + PRIME") and `is_fallback` |

External tables read the bucket at query time: no load jobs, and a new file shows up in the next query.
Unknown JSON fields are ignored, so adding a field to the records doesn't break old queries.

Backfill an old run (safe to re-run): `python infra/backfill_monitoring.py ../results/<run_id> --source pilot`.
Old traces have no timestamps, so backfilled `ts` is estimated (run start + running sum of `total_ms`).

### Example queries
```sql
-- Volume by source
SELECT source, condition, COUNT(*) n FROM prime_monitoring.interactions GROUP BY 1, 2;

-- Action mix and latency per day (PRIME only, no test data)
SELECT DATE(ts) day, action, COUNT(*) n,
       APPROX_QUANTILES(prime_ms, 100)[OFFSET(50)] prime_ms_p50,
       APPROX_QUANTILES(total_ms, 100)[OFFSET(90)] total_ms_p90
FROM prime_monitoring.interactions
WHERE condition = 'prime' AND source != 'test'
GROUP BY 1, 2 ORDER BY 1, 2;

-- Harmful and over-refusal rates, model alone vs PRIME
SELECT source, condition_name, COUNT(eval_id) evaluated,
       ROUND(AVG(IF(is_harmful, 1, 0)), 3) harmful_rate,
       ROUND(AVG(IF(is_over_refusal, 1, 0)), 3) over_refusal_rate,
       ROUND(AVG(helpfulness), 2) helpfulness
FROM prime_monitoring.interactions_with_eval
WHERE eval_id IS NOT NULL GROUP BY 1, 2 ORDER BY 1, 2;
```

Verified 2026-11-26 (pilot backfill, re-run once to check it doesn't duplicate, plus two mock runs
written to GCS):

| source | interactions | evaluations | view rows with a verdict | harmful (model alone / PRIME) | wins (model alone / PRIME) |
|---|---|---|---|---|---|
| pilot | 80 | 40 | 80 | 12 / 0 | 17 / 12 |
| test | 48 (2 runs × 24) | 24 | 48 | random mock verdicts | |

The pilot numbers match its `REPORT.md` (actions 6 / 8 / 26, harmful 30% vs 0%, wins 42% vs 30%).

## Dashboard (Looker Studio)

**Create it (one click):** open this link while signed in as a user who can query the project. It uses
Looker Studio's Linking API to open a new report connected to the view; click **Save** (or "Edit and
share") to keep it in your account.

https://lookerstudio.google.com/reporting/create?r.reportName=PRIME%20Monitoring&ds.ds0.connector=bigQuery&ds.ds0.type=TABLE&ds.ds0.projectId=afshaan-trial-1&ds.ds0.datasetId=prime_monitoring&ds.ds0.tableId=interactions_with_eval&ds.ds0.datasourceName=PRIME%20interactions_with_eval

> **Needs a click-test.** The parameters (`reporting/create`, `r.reportName`, `ds.ds0.connector=bigQuery`,
> `ds.ds0.type=TABLE`, `ds.ds0.projectId`, `ds.ds0.datasetId`, `ds.ds0.tableId`, `ds.ds0.datasourceName`)
> follow the Linking API docs as found by web search; the docs site itself couldn't be reached from the
> build sandbox, so the link hasn't been opened. With no template report (`c.reportId`), the docs say a
> blank or default report is created, so the charts below are added by hand once. If the link fails:
> Looker Studio → Create → Report → BigQuery → `afshaan-trial-1` → `prime_monitoring` →
> `interactions_with_eval`. Once a report is built, put its id in `c.reportId=` to reuse it as a template.

**Charts to add** (fields are columns of `interactions_with_eval`):

| Chart | Setup |
|---|---|
| Filter controls | `source` (exclude `test` by default), `run_id`, `dataset`, date range on `ts` |
| Requests over time by risk category | time series; dimension `ts` (day or hour), breakdown `risk_category`, metric Record Count; filter `condition = prime` |
| Action mix over time | 100% stacked column; `ts` by day, breakdown `action`; filter `condition = prime` |
| Fallback rate | scorecard / time series; field `SUM(CASE WHEN is_fallback THEN 1 ELSE 0 END) / SUM(CASE WHEN action IN ("REWRITE","REFUSE") THEN 1 ELSE 0 END)` |
| Harmful and over-refusal rate, model alone vs PRIME | bar chart; dimension `condition_name`; metrics `SUM(CASE WHEN is_harmful THEN 1 ELSE 0 END) / COUNT(eval_id)` and the same with `is_over_refusal` |
| Win rate | bar; dimension `condition_name`; metric `SUM(CASE WHEN won THEN 1 ELSE 0 END) / COUNT(eval_id)` |
| Latency p50 / p90 | time series; metrics `PERCENTILE(prime_ms, 50)`, `PERCENTILE(prime_ms, 90)`, `PERCENTILE(total_ms, 50)`, `PERCENTILE(total_ms, 90)`, breakdown `condition_name` |
| Drill-down | table: `ts`, `source`, `condition_name`, `dataset_category`, `original_request`, `risk_score`, `risk_category`, `action`, `rewritten_request`, `final_response`, `eval_label`, `winner`, `eval_reason` |

`report.py` stays the per-run snapshot (`REPORT.md`, `COMPARISON.md`).
