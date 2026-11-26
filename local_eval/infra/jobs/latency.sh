# Job: per-call latency benchmark on the GPU VM (runs as root via startup.sh's watcher).
# Serves one model at a time with vLLM and runs bench_latency.py against it:
#   PRIME's risk sensor + intervention calls (Qwen2.5-7B-AWQ, as deployed with --enforce-eager, and with CUDA graphs),
#   cheap variants (short risk output; Qwen2.5-1.5B / 0.5B as risk sensor), ungated guard classifiers
#   (Qwen3Guard-Gen 0.6B / 4B, Granite Guardian 3.1-2B / 3.2-5B) and the protected model (Zephyr-7B-AWQ).
# Also records HF gating/licence for each guard model. Uploads results/latency-<ts>/ to gs://$BUCKET/
# after every model, so a Spot preemption keeps what finished.
set -uo pipefail
export HOME=/root PATH=/root/.local/bin:/usr/local/bin:/usr/bin:/bin:/snap/bin
BRANCH=eval/latency-benchmark
nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader

mkdir -p /opt && cd /opt
[[ -d prime-guardrails ]] || git clone -q https://github.com/afshaanmaz/prime-guardrails.git
cd prime-guardrails && git fetch -q origin "$BRANCH" && git checkout -q -f -B "$BRANCH" FETCH_HEAD  # -f: earlier runs leave result files that are now tracked
echo "code at $(git rev-parse --short HEAD)"
cd local_eval

command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null
[[ -d .venv ]] || uv venv -q --python 3.11 .venv
. .venv/bin/activate
# vLLM 0.9.x still runs on T4 (Turing) via its fallback engine; newer releases target newer GPUs.
# transformers>=4.54 registers "aimv2", which vLLM 0.9.2 also registers -> import error; pin below it.
uv pip install -q "vllm==0.9.2" "transformers>=4.53,<4.54" "openai>=1.40" "pyyaml>=6"
echo "vllm $(python -c 'import vllm; print(vllm.__version__)')"

RUN=results/latency-$(date -u +%Y%m%d-%H%M%S)
mkdir -p "$RUN/logs"
OUT=$RUN/bench.jsonl
upload() { gcloud storage cp -r "$RUN" "gs://$BUCKET/" --quiet >/dev/null 2>&1 || echo "upload failed"; }

# Gating / licence straight from the Hub (unauthenticated, like the runs).
python - > "$RUN/gating.json" <<'EOF'
import json
from huggingface_hub import HfApi
api = HfApi()
repos = ["Qwen/Qwen3Guard-Gen-0.6B", "Qwen/Qwen3Guard-Gen-4B", "Qwen/Qwen3Guard-Gen-8B",
         "ibm-granite/granite-guardian-3.1-2b", "ibm-granite/granite-guardian-3.2-5b",
         "ibm-granite/granite-guardian-3.3-8b", "Qwen/Qwen2.5-1.5B-Instruct", "Qwen/Qwen2.5-0.5B-Instruct",
         "meta-llama/Llama-Guard-3-1B", "meta-llama/Llama-Guard-3-8B", "meta-llama/Llama-Guard-4-12B",
         "google/shieldgemma-2b", "google/shieldgemma-9b", "allenai/wildguard"]
out = {}
for r in repos:
    try:
        i = api.model_info(r)
        cd = i.card_data.to_dict() if i.card_data else {}
        out[r] = {"gated": i.gated, "license": cd.get("license"), "license_name": cd.get("license_name")}
    except Exception as e:
        out[r] = {"error": f"{type(e).__name__}: {e}"[:200]}
print(json.dumps(out, indent=1))
EOF
cat "$RUN/gating.json"

pkill -f "vllm serve" || true
# label | model | extra vllm args | bench args
PLAN=(
  "qwen7b-awq-eager|Qwen/Qwen2.5-7B-Instruct-AWQ|--enforce-eager|--tasks risk risk_short rewrite refusal --conc 1 8"
  "qwen7b-awq-graphs|Qwen/Qwen2.5-7B-Instruct-AWQ||--tasks risk risk_short rewrite refusal --conc 1 8 --n-sub 20"
  "qwen2.5-1.5b|Qwen/Qwen2.5-1.5B-Instruct||--tasks risk risk_short --conc 1 8"
  "qwen2.5-0.5b|Qwen/Qwen2.5-0.5B-Instruct||--tasks risk risk_short --conc 1 8"
  "qwen3guard-gen-0.6b|Qwen/Qwen3Guard-Gen-0.6B||--tasks guard_qwen3guard --conc 1 8"
  "qwen3guard-gen-4b|Qwen/Qwen3Guard-Gen-4B||--tasks guard_qwen3guard --conc 1 8"
  "granite-guardian-3.1-2b|ibm-granite/granite-guardian-3.1-2b||--tasks guard_granite --conc 1 8"
  "granite-guardian-3.2-5b|ibm-granite/granite-guardian-3.2-5b||--tasks guard_granite --conc 1 8"
  "zephyr7b-awq-eager|TheBloke/zephyr-7B-beta-AWQ|--enforce-eager --chat-template infra/zephyr-chat-template.jinja|--tasks gen --conc 1 --n-sub 30"
)
for row in "${PLAN[@]}"; do
  IFS='|' read -r label model extra bargs <<<"$row"
  echo "--- $label ($model) $(date -u +%T)"
  t0=$(date +%s)
  # shellcheck disable=SC2086
  nohup vllm serve "$model" --port 8010 --dtype half --gpu-memory-utilization 0.85 --max-model-len 2048 \
    --swap-space 0 $extra > "$RUN/logs/$label.log" 2>&1 &
  up=0
  for _ in $(seq 180); do
    curl -sf http://localhost:8010/v1/models >/dev/null && { up=1; break; }
    pgrep -f "vllm serve" >/dev/null || break
    sleep 5
  done
  if [[ $up == 1 ]]; then
    echo "server up in $(( $(date +%s) - t0 ))s; $(nvidia-smi --query-gpu=memory.used --format=csv,noheader)"
    # shellcheck disable=SC2086
    timeout 1500 python bench_latency.py --base-url http://localhost:8010/v1 --model "$model" --label "$label" \
      --out "$OUT" $bargs || echo "bench for $label failed or timed out"
  else
    echo "server for $label did not start; last log lines:"; tail -15 "$RUN/logs/$label.log"
  fi
  pkill -f "vllm serve" || true
  for _ in $(seq 30); do pgrep -f "vllm serve" >/dev/null || break; sleep 2; done
  pkill -9 -f "vllm serve" 2>/dev/null || true; sleep 3
  echo "$label done in $(( $(date +%s) - t0 ))s"
  upload
done
nvidia-smi > "$RUN/logs/nvidia-smi.txt"
upload
echo "RESULTS gs://$BUCKET/$(basename "$RUN")"
