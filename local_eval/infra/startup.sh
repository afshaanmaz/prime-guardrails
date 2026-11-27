#!/bin/bash
# Boot script for the experiment VM (runs as root on every start). Installs:
#  1. idle auto-stop: shuts down after IDLE_MINUTES with GPU util < 5% and load < 0.5
#  2. job watcher: every minute, checks the VM metadata key `prime-job-id`; when it changes,
#     runs the script in metadata key `prime-job` once. Output goes to the serial console
#     (lines prefixed PRIMEJOB) and /var/log/prime-job.log. This lets a machine that can't
#     SSH run work on the VM with only Compute Engine API access (see run-job.sh).
MD=http://metadata.google.internal/computeMetadata/v1/instance/attributes
IDLE_MINUTES=$(curl -sf -H Metadata-Flavor:Google "$MD/idle-minutes" || echo 60)

apt-get update -y && apt-get install -y tmux git jq

cat > /usr/local/bin/idle-shutdown.sh <<IDLE
#!/bin/bash
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

cat > /usr/local/bin/prime-job-watch.sh <<'WATCH'
#!/bin/bash
MD=http://metadata.google.internal/computeMetadata/v1/instance/attributes
ID=$(curl -sf -H Metadata-Flavor:Google "$MD/prime-job-id") || exit 0
[[ -n "$ID" && "$ID" != "$(cat /var/lib/prime-job-id 2>/dev/null)" ]] || exit 0
pgrep -f /var/lib/prime-job.sh >/dev/null && exit 0
curl -sf -H Metadata-Flavor:Google "$MD/prime-job" > /var/lib/prime-job.sh || exit 0
echo "$ID" > /var/lib/prime-job-id
( echo "=== job $ID start $(date -u +%FT%TZ)"
  bash /var/lib/prime-job.sh; rc=$?
  echo "=== job $ID end rc=$rc $(date -u +%FT%TZ)"
) 2>&1 | tee -a /var/log/prime-job.log | sed -u 's/^/PRIMEJOB /' > /dev/ttyS0
WATCH
chmod +x /usr/local/bin/prime-job-watch.sh

cat > /etc/cron.d/prime <<'CRON'
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/snap/bin
*/5 * * * * root /usr/local/bin/idle-shutdown.sh
* * * * * root /usr/local/bin/prime-job-watch.sh
CRON
