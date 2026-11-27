#!/usr/bin/env bash
# Build the experiments site and upload it to the private results bucket.
# View (Google login required): https://storage.cloud.google.com/afshaan-trial-1-prime-results/site/index.html
# Usage: bash tools/publish_site.sh RESULTS_DIR [RESULTS_DIR ...]   (runs are listed in tools/experiments.json)
set -euo pipefail
BUCKET=gs://afshaan-trial-1-prime-results/site
URL=https://storage.cloud.google.com/afshaan-trial-1-prime-results/site
OUT=$(mktemp -d)
python3 "$(dirname "$0")/build_site.py" "$OUT" "$@"
# Absolute links: storage.cloud.google.com redirects after login, so relative links are not reliable.
sed -i -E "s#href=\"(20[0-9]{6}-[0-9]{6}\.html)\"#href=\"$URL/\1\"#g" "$OUT/index.html"
sed -i "s#href=\"index.html\"#href=\"$URL/index.html\"#" "$OUT"/20*.html
gcloud storage cp -q "$OUT"/index.html "$OUT"/20*.html "$BUCKET/"
echo "Published: $URL/index.html"
