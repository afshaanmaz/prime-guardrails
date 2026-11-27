#!/usr/bin/env bash
# Create (or update) PRIME's monitoring tables in BigQuery. Idempotent: safe to re-run after a
# schema change in monitor.py.
#   dataset  <project>.prime_monitoring (location US)
#   tables   interactions, evaluations: external tables over gs://<bucket>/monitoring/<table>/dt=*/
#            (newline-delimited JSON, Hive-partitioned on dt; nothing is loaded or copied)
#   view     interactions_with_eval: each interaction with the evaluator's verdict for its side
# The DDL is generated from the schemas in monitor.py (`python3 monitor.py ddl`).
# Usage: infra/setup-monitoring.sh          (from local_eval/; needs bq and BigQuery admin on the project)
set -euo pipefail
cd "$(dirname "$0")/.."

PROJECT=$(python3 -c "import yaml; c=yaml.safe_load(open('config.yaml')); print((c.get('monitoring') or {}).get('bq_project') or c['infra']['project'])")
sql=$(python3 monitor.py ddl)
echo "$sql"
bq --project_id="$PROJECT" query --quiet --use_legacy_sql=false --location=US "$sql" >/dev/null
echo "BigQuery monitoring tables ready in $PROJECT:"
bq --project_id="$PROJECT" ls --format=pretty prime_monitoring
