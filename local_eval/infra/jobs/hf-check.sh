# Job: check the VM can use the Hugging Face models that need a token (runs as root via startup.sh's watcher).
# 1. Reads the HF token from Secret Manager (the VM's service account can read only that secret).
# 2. Checks access to each gated repo (downloads config.json only).
# 3. Loads each 4-bit model with vLLM on the GPU and makes one chat call.
# No results are written to the bucket; output is in this job's console log.
set -uo pipefail
export HOME=/root PATH=/root/.local/bin:/usr/local/bin:/usr/bin:/bin:/snap/bin
SECRET=${SECRET:-huggingface-prime-vm}
PROJECT=$(curl -sf -H Metadata-Flavor:Google http://metadata.google.internal/computeMetadata/v1/project/project-id)
HF_TOKEN=$(gcloud secrets versions access latest --secret "$SECRET" --project "$PROJECT" | tr -d '[:space:]')
[[ "$HF_TOKEN" == hf_* ]] && echo "token: read from Secret Manager (${#HF_TOKEN} chars)" || { echo "token: NOT readable"; exit 1; }
export HF_TOKEN
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader

mkdir -p /opt && cd /opt && { [[ -d prime-guardrails ]] || git clone -q https://github.com/afshaanmaz/prime-guardrails.git; }
cd /opt/prime-guardrails/local_eval
command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null
[[ -d .venv ]] || uv venv -q --python 3.11 .venv
. .venv/bin/activate
uv pip install -q "vllm==0.9.2" "transformers>=4.53,<4.54" "huggingface_hub"
echo "vllm $(python -c 'import vllm; print(vllm.__version__)')"

python - <<'PY'
from huggingface_hub import hf_hub_download
for repo in ["meta-llama/Llama-3.1-8B-Instruct", "hugging-quants/Meta-Llama-3.1-8B-Instruct-AWQ-INT4",
             "google/gemma-2-9b-it", "hugging-quants/gemma-2-9b-it-AWQ-INT4", "google/gemma-2-2b-it"]:
    try:
        hf_hub_download(repo, "config.json"); print(f"ACCESS OK    {repo}")
    except Exception as e:
        print(f"ACCESS FAIL  {repo}: {type(e).__name__}: {str(e)[:160]}")
PY

for MODEL in hugging-quants/Meta-Llama-3.1-8B-Instruct-AWQ-INT4 hugging-quants/gemma-2-9b-it-AWQ-INT4; do
  echo "=== $MODEL"
  MODEL=$MODEL timeout 1500 python - <<'PY' 2>&1 | grep -E '^(CALL|ERROR)|Error|error' | grep -v -i 'warn' | tail -8
import os, time
from vllm import LLM, SamplingParams
m = os.environ["MODEL"]
try:
    t = time.time()
    llm = LLM(model=m, quantization="awq", dtype="half", max_model_len=2048, enforce_eager=True,
              gpu_memory_utilization=0.85, swap_space=0)
    load = time.time() - t; t = time.time()
    out = llm.chat([{"role": "user", "content": "In one sentence, what is the capital of France?"}],
                   SamplingParams(max_tokens=40, temperature=0.0))
    text = out[0].outputs[0].text.strip().replace("\n", " ")
    print(f"CALL OK  load {load:.0f}s  call {time.time()-t:.1f}s  reply: {text[:200]!r}")
except Exception as e:
    print(f"ERROR {type(e).__name__}: {str(e)[:300]}")
PY
done
echo "hf-check done"
