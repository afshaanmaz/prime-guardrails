#!/usr/bin/env bash
# Create the persistent experiment VM wherever a GPU is available right now. One pass, no polling.
#
# Google has no API that reports spare GPU capacity; its documented approach is to request
# the VM and handle "out of capacity". Following its guidance, this asks per REGION
# (`instances bulk create --region`, so Compute Engine picks a zone that has capacity)
# and creates the real VM directly, rather than probing and deleting (deleting releases
# the GPU, which someone else can then take).
#   https://cloud.google.com/compute/docs/troubleshooting/troubleshooting-resource-availability
#   https://cloud.google.com/compute/docs/gpus/create-gpu-vm-bulk
#
# Reads the `infra:` block of ../config.yaml: gpu_types (tried in order), regions (in
# order), machine type per GPU, disk, auto-stop limits. Writes what it got to infra/vm.env.
# Usage: infra/create-gpu-vm.sh            (from local_eval/)
set -euo pipefail
cd "$(dirname "$0")/.."

eval "$(python3 - <<'EOF'
import yaml, shlex
i = yaml.safe_load(open("config.yaml"))["infra"]
print(f"PROJECT={shlex.quote(i['project'])} NAME={shlex.quote(i['vm_name'])}")
print(f"GPUS=({' '.join(i['gpu_types'])}) REGIONS=({' '.join(i['regions'])})")
print(f"PROVISIONING=({' '.join(i.get('provisioning', ['standard']))})")
print(f"DISK_GB={i['disk_gb']} MAX_HOURS={i['max_hours']} IDLE_MINUTES={i['idle_minutes']}")
print(f"BUCKET={shlex.quote(i['results_bucket'])}")
print("declare -A MACHINE=(" + " ".join(f"[{k}]={v}" for k, v in i["machine_types"].items()) + ")")
EOF
)"

existing=$(gcloud compute instances list --project "$PROJECT" --filter="name=$NAME" --format='value(zone.basename())')
if [[ -n "$existing" ]]; then
  echo "$NAME already exists in $existing; not creating another." >&2
else
  IMAGE_FAMILY=$(gcloud compute images list --project=deeplearning-platform-release \
    --filter="family~^common-cu12 AND family~ubuntu-2204" \
    --sort-by=~creationTimestamp --limit=1 --format='value(family)')
  [[ -n "$IMAGE_FAMILY" ]] || { echo "No Deep Learning VM image family found." >&2; exit 1; }
  created=""
  for prov in "${PROVISIONING[@]}"; do
  pm=(); [[ "$prov" == spot ]] && pm=(--provisioning-model SPOT)
  for gpu in "${GPUS[@]}"; do
    machine=${MACHINE[$gpu]:?no machine type for $gpu in infra.machine_types}
    accel=(); [[ "$machine" == g2-* ]] || accel=(--accelerator "type=$gpu,count=1")
    for region in "${REGIONS[@]}"; do
      echo -n "  $gpu ($prov) in $region: " >&2
      if out=$(gcloud compute instances bulk create --project "$PROJECT" --region "$region" \
            --count 1 --predefined-names "$NAME" --machine-type "$machine" "${accel[@]}" "${pm[@]}" \
            --on-host-maintenance TERMINATE \
            --image-family "$IMAGE_FAMILY" --image-project deeplearning-platform-release \
            --boot-disk-size "${DISK_GB}GB" --boot-disk-type pd-balanced \
            --max-run-duration "${MAX_HOURS}h" --instance-termination-action STOP \
            --service-account "prime-vm@$PROJECT.iam.gserviceaccount.com" --scopes cloud-platform \
            --metadata "install-nvidia-driver=True,idle-minutes=$IDLE_MINUTES" \
            --metadata-from-file startup-script=infra/startup.sh --quiet 2>&1); then
        echo "created" >&2; created="$gpu"; break 3
      else
        echo "no ($(grep -oE '[A-Z_]{12,}' <<<"$out" | head -1 || tail -1 <<<"$out"))" >&2
      fi
    done
  done
  done
  [[ -n "$created" ]] || { echo "No capacity for ${GPUS[*]} (${PROVISIONING[*]}) in ${REGIONS[*]} right now." >&2; exit 1; }
fi

ZONE=$(gcloud compute instances list --project "$PROJECT" --filter="name=$NAME" --format='value(zone.basename())')
GPU=$(gcloud compute instances describe "$NAME" --project "$PROJECT" --zone "$ZONE" \
  --format='value(guestAccelerators[0].acceleratorType.basename())')
gcloud storage buckets describe "gs://$BUCKET" --project "$PROJECT" >/dev/null 2>&1 ||
  gcloud storage buckets create "gs://$BUCKET" --project "$PROJECT" --location "${ZONE%-*}" \
    --uniform-bucket-level-access >/dev/null
printf 'PROJECT=%s\nNAME=%s\nZONE=%s\nGPU=%s\nBUCKET=%s\n' "$PROJECT" "$NAME" "$ZONE" "$GPU" "$BUCKET" > infra/vm.env
cat infra/vm.env
