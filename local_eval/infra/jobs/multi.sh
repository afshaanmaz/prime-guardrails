# Job: PRIME on several protected models (runs as root via startup.sh's watcher).
#   Phase A: PRIME's decisions (risk sensor + policy + intervention) once per request; only PRIME's model on the GPU.
#   Phase B: for each protected model, its answers alone and under PRIME (reusing phase A's decisions);
#            only that model on the GPU.
# Every phase uploads results/<run_id>/ to gs://$BUCKET/ when it ends.
# Variables (run-job.sh KEY=VALUE):
#   BRANCH      code to run (default feat/multi-model-run)
#   GENERATORS  protected models from config `generators:` (default "zephyr llama")
#   SIZES       per-dataset sample, e.g. "harmbench=50 xstest=100"; default: full run.datasets
#   DECISIONS   gs://.../<decide_run_id> to reuse instead of running phase A
#   TITLE       short title for the results site
set -uo pipefail
export HOME=/root PATH=/root/.local/bin:/usr/local/bin:/usr/bin:/bin:/snap/bin
BRANCH=${BRANCH:-feat/multi-model-run}
GENERATORS=${GENERATORS:-zephyr llama}
SECRET=${SECRET:-huggingface-prime-vm}
PROJECT=$(curl -sf -H Metadata-Flavor:Google http://metadata.google.internal/computeMetadata/v1/project/project-id)
nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader

HF_TOKEN=$(gcloud secrets versions access latest --secret "$SECRET" --project "$PROJECT" 2>/dev/null | tr -d '[:space:]')
if [[ "$HF_TOKEN" == hf_* ]]; then export HF_TOKEN; echo "HF token: read from Secret Manager"; else echo "HF token: not available (gated models will fail)"; fi

mkdir -p /opt && cd /opt
[[ -d prime-guardrails ]] || git clone -q https://github.com/afshaanmaz/prime-guardrails.git
cd prime-guardrails && git fetch -q origin "$BRANCH" && git checkout -q -f -B "$BRANCH" FETCH_HEAD
echo "code at $(git rev-parse --short HEAD) ($BRANCH)"
cd local_eval
command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null
[[ -d .venv ]] || uv venv -q --python 3.11 .venv
. .venv/bin/activate
uv pip install -q "vllm==0.9.2" "transformers>=4.53,<4.54" "openai>=1.40" "pyyaml>=6"
echo "vllm $(python -c 'import vllm; print(vllm.__version__)')"
SIZE_ARGS=(); [[ -n "${SIZES:-}" ]] && SIZE_ARGS=(--sizes $SIZES)

upload() {  # run_dir
  mkdir -p "$1/logs" && cp logs/*.log "$1/logs/" 2>/dev/null; nvidia-smi > "$1/logs/nvidia-smi.txt"
  gcloud storage cp -r "$1" "gs://$BUCKET/" --quiet && echo "RESULTS gs://$BUCKET/$(basename "$1")"
}

# ---- Phase A: decisions
if [[ -n "${DECISIONS:-}" ]]; then
  gcloud storage cp -r "$DECISIONS" results/ --quiet
  DEC="results/$(basename "$DECISIONS")/decisions.jsonl"
  echo "phase A: reusing $DECISIONS"
else
  ./serve.sh stop >/dev/null; ./serve.sh risk_sensor || { echo "phase A: risk sensor failed to start"; exit 1; }
  python run.py --decide-only "${SIZE_ARGS[@]}" | tee logs/decide.out
  ./serve.sh stop >/dev/null
  RUN=$(ls -td results/*-decide | head -1); cp logs/decide.out "$RUN/logs/" 2>/dev/null
  upload "$RUN"
  DEC="$RUN/decisions.jsonl"
fi
[[ -s "$DEC" ]] || { echo "no decisions at $DEC"; exit 1; }

# ---- Phase B: each protected model, served alone
for G in $GENERATORS; do
  echo "=== phase B: $G"
  ./serve.sh stop >/dev/null
  if ! GENERATOR=$G ./serve.sh generator; then echo "phase B $G: model failed to start; skipping"; continue; fi
  python run.py --decisions "$DEC" --generator "$G" ${TITLE:+--title "$TITLE"} | tee logs/run-$G.out
  ./serve.sh stop >/dev/null
  RUN=$(ls -td results/*-"$G" | head -1); cp logs/run-$G.out "$RUN/logs/" 2>/dev/null
  upload "$RUN"
done
echo "multi done"
