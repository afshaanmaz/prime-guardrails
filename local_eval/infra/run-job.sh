#!/usr/bin/env bash
# Run a job script on the experiment VM using only the Compute Engine API (no SSH).
# Starts the VM if needed (recreating it elsewhere if its zone has no GPU), hands it the script via metadata (startup.sh's watcher runs it
# within a minute), and prints its console progress until the job ends.
# Usage: infra/run-job.sh infra/jobs/smoke.sh        (from local_eval/; needs infra/vm.env)
#        infra/run-job.sh --follow                   (just follow the current job's output)
set -euo pipefail
cd "$(dirname "$0")/.."
source infra/vm.env
G=(--project "$PROJECT" --zone "$ZONE")

# Start the VM. A stopped VM gives its GPU back, so a restart can fail for lack of capacity
# in its zone. Then fall back: delete it and run create-gpu-vm.sh, which tries every GPU type,
# provisioning option and region in config.yaml and records the new VM in infra/vm.env.
ensure_running() {
  [[ "$(gcloud compute instances describe "$NAME" "${G[@]}" --format='value(status)')" == RUNNING ]] && return
  local out
  if out=$(gcloud compute instances start "$NAME" "${G[@]}" 2>&1); then return; fi
  if ! grep -qiE 'RESOURCE_POOL_EXHAUSTED|resource_availability|STOCKOUT|does not have enough resources' <<<"$out"; then
    echo "$out" >&2; exit 1
  fi
  echo "No GPU capacity in $ZONE to restart $NAME; recreating it wherever config.yaml allows." >&2
  gcloud compute instances delete "$NAME" "${G[@]}" --quiet >&2
  infra/create-gpu-vm.sh >&2
  source infra/vm.env; G=(--project "$PROJECT" --zone "$ZONE")
}

if [[ "${1:-}" != "--follow" ]]; then
  job=${1:?usage: run-job.sh JOB_SCRIPT}
  ensure_running
  id="$(basename "$job" .sh)-$(date -u +%Y%m%d-%H%M%S)"
  tmp=$(mktemp); { echo "export BUCKET=$BUCKET JOB_ID=$id"; cat "$job"; } > "$tmp"
  gcloud compute instances add-metadata "$NAME" "${G[@]}" \
    --metadata-from-file prime-job="$tmp" --metadata prime-job-id="$id" >/dev/null
  rm -f "$tmp"
  echo "job $id sent to $NAME ($ZONE)"
fi

id=$(gcloud compute instances describe "$NAME" "${G[@]}" --format=json |
  python3 -c "import json,sys; print(next((m['value'] for m in json.load(sys.stdin)['metadata'].get('items',[]) if m['key']=='prime-job-id'),''))")
seen=0
while :; do
  log=$(gcloud compute instances get-serial-port-output "$NAME" "${G[@]}" 2>/dev/null |
        grep -o 'PRIMEJOB .*' | sed 's/^PRIMEJOB //' | sed -n "/^=== job $id start/,\$p") || true
  n=$(grep -c '' <<<"$log" || true)
  [[ -n "$log" && $n -gt $seen ]] && { tail -n +$((seen + 1)) <<<"$log"; seen=$n; }
  grep -q "^=== job $id end rc=" <<<"$log" && break
  sleep 30
done
