#!/usr/bin/env bash
# One-time setup for a GPU VM that Claude Code runs on, steered from your phone.
# Run in Google Cloud Shell. Fill in the two values below first.
set -euo pipefail

PROJECT_ID="afshaan-trial-1"   # the GCP project for this work
BUDGET_USD="50"                # weekend budget; alerts at 50%, 90%, 100%

ZONE="us-central1-a"
VM_NAME="prime-lab"
MACHINE="g2-standard-4"        # 1x NVIDIA L4, 4 vCPU, 16 GB RAM (~$0.71/hr on-demand)
DISK_GB="200"
MAX_HOURS="8"                  # VM stops itself this many hours after each start
IDLE_MINUTES="60"              # VM stops itself after this long with GPU and CPU idle

if [[ "$PROJECT_ID" == "YOUR_PROJECT_ID" ]]; then
  echo "Set PROJECT_ID at the top of the script first." >&2; exit 1
fi

gcloud config set project "$PROJECT_ID"
gcloud services enable compute.googleapis.com billingbudgets.googleapis.com cloudbilling.googleapis.com

# --- Budget alert (emails billing admins; it does not stop spending by itself) ---
BILLING=$(gcloud billing projects describe "$PROJECT_ID" --format='value(billingAccountName)' | sed 's#billingAccounts/##')
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
if [[ -n "$BILLING" ]]; then
  gcloud billing budgets create \
    --billing-account="$BILLING" \
    --display-name="${VM_NAME}-budget" \
    --budget-amount="${BUDGET_USD}USD" \
    --filter-projects="projects/${PROJECT_NUMBER}" \
    --threshold-rule=percent=0.5 \
    --threshold-rule=percent=0.9 \
    --threshold-rule=percent=1.0 \
  || echo "WARNING: couldn't create the budget (you may lack billing admin on this account). The VM time limits below still apply."
else
  echo "WARNING: no billing account linked to $PROJECT_ID; link one before creating the VM." >&2; exit 1
fi

# --- Startup script: tools + idle auto-shutdown (runs on every boot) ---
STARTUP=$(cat <<EOF
#!/bin/bash
apt-get update -y && apt-get install -y tmux git gh jq
cat > /usr/local/bin/idle-shutdown.sh <<'IDLE'
#!/bin/bash
# Stops the VM after ${IDLE_MINUTES} min with GPU util < 5% and 1-min load < 0.5.
STATE=/var/tmp/idle-count
GPU=\$(nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits 2>/dev/null | head -1)
LOAD=\$(cut -d' ' -f1 /proc/loadavg)
if [[ "\${GPU:-0}" -lt 5 ]] && awk "BEGIN{exit !(\$LOAD < 0.5)}"; then
  N=\$(( \$(cat \$STATE 2>/dev/null || echo 0) + 1 ))
else
  N=0
fi
echo \$N > \$STATE
if [[ \$N -ge $(( IDLE_MINUTES / 5 )) ]]; then echo 0 > \$STATE; shutdown -h now; fi
IDLE
chmod +x /usr/local/bin/idle-shutdown.sh
echo 0 > /var/tmp/idle-count
echo '*/5 * * * * root /usr/local/bin/idle-shutdown.sh' > /etc/cron.d/idle-shutdown
EOF
)

STARTUP_FILE=$(mktemp)
printf '%s\n' "$STARTUP" > "$STARTUP_FILE"

# Newest Deep Learning VM image (CUDA + Python preinstalled)
IMAGE_FAMILY=$(gcloud compute images list --project=deeplearning-platform-release \
  --filter="family~^common-cu12 AND family~ubuntu" \
  --sort-by=~creationTimestamp --limit=1 --format='value(family)')
if [[ -z "$IMAGE_FAMILY" ]]; then
  echo "Couldn't find a Deep Learning VM image family; tell Claude and it will adjust the filter." >&2; exit 1
fi
echo "Using image family: $IMAGE_FAMILY"

gcloud compute instances create "$VM_NAME" \
  --zone="$ZONE" \
  --machine-type="$MACHINE" \
  --maintenance-policy=TERMINATE \
  --image-family="$IMAGE_FAMILY" \
  --image-project=deeplearning-platform-release \
  --boot-disk-size="${DISK_GB}GB" \
  --boot-disk-type=pd-balanced \
  --max-run-duration="${MAX_HOURS}h" \
  --instance-termination-action=STOP \
  --metadata=install-nvidia-driver=True \
  --metadata-from-file=startup-script="$STARTUP_FILE"

cat <<EOF

VM created. Next, on the VM (takes a few minutes for drivers on first boot):

  gcloud compute ssh $VM_NAME --zone $ZONE

Then run the steps in the message I sent with this script.
EOF
