#!/usr/bin/env bash
# Starts the generator and judge on one L4 (24 GB). AWQ 4-bit models leave room for both.
# Usage: ./serve.sh            (reads models from config.yaml)
set -euo pipefail
cd "$(dirname "$0")"
GEN=$(python3 -c "import yaml;print(yaml.safe_load(open('config.yaml'))['generator']['model'])")
JUDGE=$(python3 -c "import yaml;print(yaml.safe_load(open('config.yaml'))['judge']['model'])")
mkdir -p logs
nohup vllm serve "$GEN"   --port 8001 --gpu-memory-utilization 0.42 --max-model-len 4096 > logs/gen.log 2>&1 &
sleep 5
nohup vllm serve "$JUDGE" --port 8002 --gpu-memory-utilization 0.42 --max-model-len 4096 > logs/judge.log 2>&1 &
echo "Waiting for both servers..."
for port in 8001 8002; do
  until curl -sf "http://localhost:$port/v1/models" >/dev/null; do sleep 5; done
  echo "port $port up"
done
