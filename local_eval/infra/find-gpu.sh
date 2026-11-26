#!/usr/bin/env bash
# One-shot check: which zones can start a GPU VM right now?
#
# Google has no API that reports spare GPU capacity, so this tries what you would
# actually do: create a minimal VM with the GPU attached, one zone at a time, and
# delete it as soon as it starts. Each successful probe costs about a cent.
#
# Usage:
#   ./find-gpu.sh                 # print the first zone that works, then stop
#   ./find-gpu.sh --all           # try every candidate zone and report each
#   REGIONS="us-central1 us-east4" ./find-gpu.sh   # only these regions, in this order
#
# Prints the working zone(s) on stdout (progress goes to stderr), so it can be used
# as:  ZONE=$(./find-gpu.sh)  ...  or via ZONE=auto in setup-prime-lab.sh.
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-$(gcloud config get project 2>/dev/null)}"
GPU="${GPU:-nvidia-l4}"
MACHINE="${MACHINE:-g2-standard-4}"     # g2 machine types come with the L4 attached
# Nearest first. Regions not in this list are tried after, alphabetically.
PREFERRED="${REGIONS:-us-central1 us-east4 us-east1 us-east5 us-south1 us-west1 us-west4 us-west2 us-west3 northamerica-northeast1}"
ALL=false; [[ "${1:-}" == "--all" ]] && ALL=true

log() { echo "$@" >&2; }

# Zones that offer this GPU type, grouped by region.
mapfile -t ZONES < <(gcloud compute accelerator-types list --project "$PROJECT_ID" \
  --filter="name:$GPU" --format='value(zone)' | sort -u)
[[ ${#ZONES[@]} -gt 0 ]] || { log "No zones offer $GPU."; exit 1; }

# Regions where quota for this GPU still has room (usage < limit).
QUOTA_METRIC="NVIDIA_$(echo "${GPU#nvidia-}" | tr '[:lower:]-' '[:upper:]_')_GPUS"
mapfile -t OK_REGIONS < <(gcloud compute regions list --project "$PROJECT_ID" --format=json |
  python3 -c "
import json, sys
for r in json.load(sys.stdin):
    for q in r['quotas']:
        if q['metric'] == '$QUOTA_METRIC' and q['usage'] < q['limit']:
            print(r['name'])")
GLOBAL_FREE=$(gcloud compute project-info describe --project "$PROJECT_ID" --format=json |
  python3 -c "
import json, sys
q = [q for q in json.load(sys.stdin)['quotas'] if q['metric'] == 'GPUS_ALL_REGIONS']
print(int(q[0]['limit'] - q[0]['usage']) if q else 1)")
if [[ "$GLOBAL_FREE" -lt 1 ]]; then
  log "GPUS_ALL_REGIONS quota is used up: a running GPU VM is holding it. Stop it first."; exit 1
fi

# Order candidate zones: preferred regions first, then the rest.
ordered=()
for r in $PREFERRED; do for z in "${ZONES[@]}"; do [[ "${z%-*}" == "$r" ]] && ordered+=("$z"); done; done
if [[ -z "${REGIONS:-}" ]]; then
  for z in "${ZONES[@]}"; do [[ " ${ordered[*]} " == *" $z "* ]] || ordered+=("$z"); done
fi
candidates=()
for z in "${ordered[@]}"; do [[ " ${OK_REGIONS[*]} " == *" ${z%-*} "* ]] && candidates+=("$z"); done
[[ ${#candidates[@]} -gt 0 ]] || { log "No zone with free $GPU quota."; exit 1; }
log "Probing ${#candidates[@]} zone(s) for $GPU ($MACHINE) in $PROJECT_ID..."

found=0
for z in "${candidates[@]}"; do
  name="gpu-probe-$(date +%s)"
  # --max-run-duration deletes the probe even if this script dies before cleaning up.
  if out=$(gcloud compute instances create "$name" --project "$PROJECT_ID" --zone "$z" \
        --machine-type "$MACHINE" --maintenance-policy TERMINATE \
        --image-family debian-12 --image-project debian-cloud --boot-disk-size 10GB \
        --max-run-duration 10m --instance-termination-action DELETE \
        --no-address --quiet 2>&1); then
    log "  $z: AVAILABLE"
    # Delete before the next probe: the global GPU quota may only allow one at a time.
    gcloud compute instances delete "$name" --project "$PROJECT_ID" --zone "$z" --quiet >/dev/null 2>&1 ||
      log "  (couldn't delete $name in $z; it deletes itself within 10 min)"
    echo "$z"; found=$((found + 1))
    $ALL || break
  else
    reason=$(grep -oE 'ZONE_RESOURCE_POOL_EXHAUSTED[A-Z_]*|QUOTA_EXCEEDED|does not exist|not supported|[A-Z_]{12,}' <<<"$out" | head -1)
    log "  $z: no (${reason:-$(tail -1 <<<"$out")})"
  fi
done
[[ $found -gt 0 ]] || { log "No capacity for $GPU in any candidate zone right now."; exit 1; }
