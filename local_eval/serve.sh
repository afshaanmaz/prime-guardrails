#!/usr/bin/env bash
# Starts the protected model (generator) and PRIME's risk sensor LLM with vLLM on one GPU.
# Each model's GPU memory share, context length and optional chat template come from
# its `serve:` block in config.yaml. The risk sensor starts only once the generator is up, so
# the two don't race for memory while loading.
# Usage: ./serve.sh            both (reads config.yaml)        ./serve.sh stop
#        ./serve.sh risk_sensor                               only PRIME's model (for run.py --decide-only)
#        GENERATOR=llama ./serve.sh generator                 only a protected model from `generators:`
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p logs

if [[ "${1:-}" == "stop" ]]; then
  pkill -f "vllm serve" || true; echo "stopped"; exit 0
fi

start() {  # role port
  local args
  args=$(python3 - "$1" <<'EOF'
import sys, yaml, shlex
import os
cfg = yaml.safe_load(open("config.yaml"))
c = cfg[sys.argv[1]]
if sys.argv[1] == "generator" and os.environ.get("GENERATOR"):
    c = {**c, **cfg["generators"][os.environ["GENERATOR"]]}
s = c.get("serve", {})
a = [c["model"], "--gpu-memory-utilization", str(s.get("gpu_memory", 0.42)),
     "--max-model-len", str(s.get("max_model_len", 4096)),
     "--dtype", s.get("dtype", "half"), "--enforce-eager",   # fp16 works on every GPU incl. T4 (Gemma 2 needs float32 there); eager saves GPU memory
     # vLLM reserves 4 GB of CPU RAM per server for KV overflow by default; two servers on a
     # 15 GB host got OOM-killed. Not needed at low concurrency.
     "--swap-space", str(s.get("swap_space_gb", 0))]
if s.get("chat_template"):
    a += ["--chat-template", s["chat_template"]]
print(shlex.join(a))
EOF
)
  echo "starting $1 on :$2  ($args)"
  eval "nohup vllm serve $args --port $2" > "logs/$1.log" 2>&1 &
  until curl -sf "http://localhost:$2/v1/models" >/dev/null; do
    sleep 5
    if ! pgrep -f "vllm serve.*--port $2" >/dev/null; then
      echo "$1 server exited; last lines of logs/$1.log:"; tail -30 "logs/$1.log"; exit 1
    fi
  done
  echo "$1 up on :$2"
}

case "${1:-all}" in
  generator)   start generator 8001 ;;
  risk_sensor) start risk_sensor 8002 ;;
  all)         start generator 8001; start risk_sensor 8002 ;;
  *) echo "usage: ./serve.sh [all|generator|risk_sensor|stop]"; exit 2 ;;
esac
nvidia-smi --query-gpu=name,memory.used,memory.total --format=csv,noheader
