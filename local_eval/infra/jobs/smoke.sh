# Job: small real batch on the GPU VM (runs as root via startup.sh's watcher).
# 20 HarmBench prompts spread across categories, all three conditions:
#   none          -> does the protected model refuse on its own?   (Step A)
#   input, input_output -> does PRIME block what it doesn't?       (Step B)
# Uploads results/<run_id>/ (traces, meta, server logs) to gs://$BUCKET/<run_id>/.
set -euo pipefail
export HOME=/root PATH=/root/.local/bin:/usr/local/bin:/usr/bin:/bin:/snap/bin
BRANCH=eval/prime-v1
nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader

mkdir -p /opt && cd /opt
[[ -d prime-guardrails ]] || git clone -q https://github.com/afshaanmaz/prime-guardrails.git
cd prime-guardrails && git fetch -q origin "$BRANCH" && git checkout -q -B "$BRANCH" FETCH_HEAD
echo "code at $(git rev-parse --short HEAD)"
cd local_eval

command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null
[[ -d .venv ]] || uv venv -q --python 3.11 .venv
. .venv/bin/activate
# vLLM 0.9.x still runs on T4 (Turing) via its fallback engine; newer releases target newer GPUs.
# transformers>=4.54 registers "aimv2", which vLLM 0.9.2 also registers -> import error; pin below it.
uv pip install -q "vllm==0.9.2" "transformers>=4.53,<4.54" "openai>=1.40" "pyyaml>=6"
echo "vllm $(python -c 'import vllm; print(vllm.__version__)')"

./serve.sh stop >/dev/null; ./serve.sh
python run.py --datasets harmbench --limit 20 | tee logs/run.out
RUN=$(ls -td results/2* | head -1)
mkdir -p "$RUN/logs" && cp logs/*.log logs/run.out "$RUN/logs/"
nvidia-smi > "$RUN/logs/nvidia-smi.txt"
./serve.sh stop
gcloud storage cp -r "$RUN" "gs://$BUCKET/" --quiet
echo "RESULTS gs://$BUCKET/$(basename "$RUN")"
