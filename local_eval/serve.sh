#!/usr/bin/env bash
# Starts the protected model (generator) and PRIME's judge with vLLM on one GPU.
# Each model's GPU memory share, context length and optional chat template come from
# its `serve:` block in config.yaml. The judge starts only once the generator is up, so
# the two don't race for memory while loading.
# Usage: ./serve.sh            (reads config.yaml)    ./serve.sh stop
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
c = yaml.safe_load(open("config.yaml"))[sys.argv[1]]
s = c.get("serve", {})
a = [c["model"], "--gpu-memory-utilization", str(s.get("gpu_memory", 0.42)),
     "--max-model-len", str(s.get("max_model_len", 4096)),
     "--dtype", "half", "--enforce-eager",   # fp16 works on every GPU incl. T4; eager saves GPU memory
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

start generator 8001
start judge 8002
nvidia-smi --query-gpu=name,memory.used,memory.total --format=csv,noheader
