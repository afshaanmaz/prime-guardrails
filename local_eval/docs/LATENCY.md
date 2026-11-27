# PRIME latency: can it sit in front of a live app?

Status: quick benchmark, 2026-11-26. One T4 (16 GB), vLLM 0.9.2 (V0 engine, the only one that runs on a T4),
one model on the GPU at a time, temperature 0, streaming. Run: `results/latency-20261126-114207/`
(`bench.jsonl`, `gating.json`, server logs). Script: `bench_latency.py`; job: `infra/jobs/latency.sh`.
Summary table: `python bench_latency.py --summarize results/latency-20261126-114207/bench.jsonl`.
The run used the full job plan at commit `1148c85` and was stopped by hand after five models to stay within
about 45 min of GPU time. The committed `latency.sh` is a cut-down version (40 prompts, concurrency 1) for
quick re-runs.

**Short answer:** not as it stands. On a T4, PRIME adds **3.5 s before the first token on an allowed
request**, about 5.3 s on a rewritten one, and about 9 s for a refusal. A trained 0.6B guard classifier
on the same GPU takes **0.13 s**. The original "low latency" figure was throughput at 50 parallel threads,
not per-request latency. Most of the gap comes from design choices that can be changed. See "Levers".

## 1. What the V1 pilot already showed (free: `results/20261126-104223/traces.jsonl`)
40 requests, concurrency 1. Protected model and risk sensor shared the T4. Prompts were the pilot's,
so the refusal prompt still had its word limit.

| PRIME action | n | risk (R) p50 / p90 | intervention (I) p50 / p90 | PRIME total p50 / p90 | PRIME share of end-to-end (mean) | vs model alone, same prompt (p50) |
|---|---|---|---|---|---|---|
| ALLOW | 6 | 2.96 / 3.15 s | none | 2.96 / 3.15 s | 32% | +3.0 s |
| REWRITE | 8 | 3.05 / 3.18 s | 1.36 / 1.54 s | 4.47 / 4.66 s | 36% | +5.1 s |
| REFUSE | 26 | 3.37 / 3.86 s | 2.05 / 2.64 s | 5.46 / 6.52 s | 100% (model not called) | −3.3 s (faster than Zephyr's full answer) |
| all | 40 | 3.15 / 3.78 s | | **5.01 / 6.48 s** | 58% of summed time | +0.7 s |

- On its own, the protected model (Zephyr-7B-AWQ) took **9.4 s p50 and 20.8 s p90** for a full answer
  (about 175 words, about 18 words/s).
- Measured end to end, PRIME looks almost free, because refusals replace long answers. That hides the real
  cost: **every byte the user sees now waits for R (and I) to finish**, while the model alone starts
  streaming in about 0.5 s.

## 2. Measured per-call latency (T4, concurrency 1 unless noted)
100 prompts (50 HarmBench + 50 XSTest, spread across categories via `data.py`). Rewrite and refusal used
40 of them, each with the risk verdict from the same run. All prompts are the ones currently in
`prime_local.py`.

| Call | Model | Output | p50 | p90 | TTFT p50 | Tokens in / out (p50) |
|---|---|---|---|---|---|---|
| **R: risk sensor (as deployed)** | Qwen2.5-7B-Instruct-AWQ | JSON: category, score, reason, intent | **3.45 s** | 4.14 s | 0.56 s | 336 / 61 |
| R, short output | Qwen2.5-7B-AWQ | `{"score","category"}`, max 24 tokens | 1.45 s | 1.50 s | 0.76 s | 214 / 15 |
| I: rewrite | Qwen2.5-7B-AWQ | rewritten request | 1.83 s | 3.08 s | 0.82 s | 232 / 22 (p90 47) |
| **I: refusal (current prompt, no word limit, D12)** | Qwen2.5-7B-AWQ | contextual refusal | **5.63 s** | 8.11 s | 0.57 s | 342 / 105 (p90 156) |
| R, small model | Qwen2.5-1.5B-Instruct (fp16) | full JSON | 1.06 s | 1.22 s | 0.09 s | 336 / 53 |
| R, small model, short output | Qwen2.5-1.5B | score + category | 0.34 s | 0.37 s | 0.07 s | 214 / 15 |
| R, tiny model | Qwen2.5-0.5B-Instruct | full JSON | 0.56 s | 0.94 s | 0.04 s | 336 / 72 |
| R, tiny model, short output | Qwen2.5-0.5B | score + category | 0.20 s | 0.20 s | 0.04 s | 214 / 24 |
| **Guard classifier** | **Qwen3Guard-Gen-0.6B** (fp16) | `Safety: … Categories: …` | **0.13 s** | 0.15 s | 0.06 s | 309 / 10 |
| Protected model (context, from the pilot) | Zephyr-7B-beta-AWQ | full answer, max 512 tokens | 9.4 s | 20.8 s | not recorded | about 230 out |

**At concurrency 8** (100 requests in flight 8 at a time):

| Call | p50 | p90 | Throughput |
|---|---|---|---|
| R, 7B, as deployed | 7.83 s | 9.65 s | 1.0 req/s (0.28 at concurrency 1) |
| R, 7B, short output | 3.51 s | 3.94 s | 2.2 req/s |
| R, 1.5B, short output | 0.61 s | 0.68 s | 12.7 req/s |
| Qwen3Guard-Gen-0.6B | 0.39 s | 0.51 s | 20.3 req/s |

What these numbers show:
- **Output length drives the cost.** Decode on the 7B AWQ model runs at about 20.5 tokens/s on a T4, or
  about 49 ms per token. The risk sensor's `reason` and `intent` sentences (about 45 of its 61 tokens) cost
  about 2 s on every request.
- **Refusal latency has nearly tripled since the pilot:** 2.0 s → 5.6 s p50, because the D12 refusal prompt
  (no word limit) produces about 105 tokens instead of 20-46 words.
- **CUDA graphs made no difference** for the 7B AWQ model (risk p50 3.54 s with graphs vs 3.45 s eager;
  rows labelled `qwen7b-awq-graphs`). vLLM warns that AWQ "is not fully optimized"; on Turing the AWQ kernel
  is the bottleneck, not Python overhead.
- **Current PRIME, end to end, per request** (sum of the calls above):

  | Action | Wait before the user sees anything |
  |---|---|
  | ALLOW | about 3.5 s |
  | REWRITE | about 5.3 s |
  | REFUSE | about 9.1 s; about 4.0 s if the refusal were streamed (it isn't today) |

  The protected model alone starts streaming in about 0.5 s (estimate: prefill on a T4 is about 0.55 s per
  300 tokens here).

**Quality was not evaluated.** Outputs were kept only to check that each call worked. A rough look against
the dataset labels (n = 100, not an eval):

| Risk sensor | Unsafe prompts flagged | Safe prompts flagged |
|---|---|---|
| Qwen3Guard-0.6B | 66 of 72 Unsafe (plus 4 Controversial) | 2 of 28 Unsafe (plus 3 Controversial) |
| 7B, short output (score ≥ 0.7) | 64 of 72 | 6 of 28 |
| 1.5B, short output | 66 of 72 | **18 of 28**, so it over-flags |
| 0.5B | scores flat around 0.4 to 0.5 | unusable |

Not run (cut for time): Qwen3Guard-Gen-4B, Granite Guardian 3.1-2B / 3.2-5B, a fresh Zephyr timing.

## 3. Gating and licences (checked from the VM against the Hugging Face API, `gating.json`)

| Model | Gated? | Licence |
|---|---|---|
| Qwen3Guard-Gen 0.6B / 4B / 8B | No | Apache-2.0 |
| Granite Guardian 3.1-2B / 3.2-5B / 3.3-8B | No | Apache-2.0 |
| Qwen2.5-1.5B / 0.5B-Instruct | No | Apache-2.0 |
| Llama Guard 3-1B / 3-8B / 4-12B | **Manual approval** | Llama 3.2 / 3.1 / 4 |
| ShieldGemma 2B / 9B | **Manual approval** (the HF API says "manual"; earlier notes said instant) | Gemma |
| WildGuard | Auto-approval after a form | Apache-2.0 |

## 4. Published figures (not measured by us)
The sandbox could not open most of these pages (no network access to arxiv.org, docs.nvidia.com and
similar), so every number below comes from search-result summaries. **All are (unverified)**, and they come
from different hardware, so they are not comparable with each other or with our T4 numbers.

| System | Reported latency | Conditions | Source |
|---|---|---|---|
| Llama Guard 3 (8B) / ShieldGemma | > 57 ms per input | H100; cited from Deng et al. 2025 | LEG paper, arXiv 2602.15853 (unverified) |
| Llama Prompt Guard 2 (22M / 86M) | about 9 to 10 ms | H100 | same (unverified) |
| Llama Guard 2 8B | about 141 ms per sample | V100 | arXiv 2502.15427 (unverified) |
| Llama Guard 3-1B-INT4 | TTFT ≤ 2.5 s, ≥ 30 tok/s | Android phone CPU | Meta, arXiv 2411.17713 (unverified) |
| Llama Guard 4 12B, hosted | p50 0.13 to 0.29 s round trip | OpenRouter dashboard snapshots (Groq) | openrouter.ai (unverified) |
| Llama 3.1 Nemotron Safety Guard 8B (NIM) | TTFT about 48 ms, mean about 136 ms | concurrency 1; GPU not stated in the snippet | NVIDIA NIM performance docs (unverified) |
| WildGuard 7B | about 70 to 130 ms | fp16, A100; third-party site, no method given | aipromptshub.co (unverified) |
| ShieldGemma 2B, Granite Guardian | no ms figures found | IBM: pruning 8B → 5B gave 1.4x faster inference | research.ibm.com (unverified) |
| Qwen3Guard-Stream | 1 to 1.5 s overhead | one third-party test on Modal | amaarora.github.io (unverified) |
| NeMo Guardrails, NIM rails | about 0.5 s added for up to 5 parallel guardrails, 1.4x detection | vendor marketing (the page is inconsistent across versions) | developer.nvidia.com (unverified) |
| NeMo Guardrails, LLM self-check rails | about 3x a normal bot call (2023 paper); median 14.1 s vs 0.31 s for the raw LLM with three sequential LLM rails (2026 study) | the authors' own setups | arXiv 2310.10501; arXiv 2610.09906 (unverified) |
| OpenAI Moderation | about 192 ms server-side | TrueFoundry benchmark | truefoundry.com (unverified) |
| Azure AI Content Safety | about 52 ms server-side | same benchmark | truefoundry.com (unverified) |
| AWS Bedrock Guardrails | p50 about 445 ms, p90 about 892 ms | Guardion leaderboard | guardion.ai (unverified) |
| Google Model Armor | mean about 564 ms, p95 684 ms, p99 720 ms | Berlin → europe-west4, community test; a CLI guide says 100 to 500 ms | medium.com/google-cloud (unverified) |
| Lakera Guard | p95 about 50 ms (1k chars, 1 detector), 300 ms (5k chars, 16 detectors) | vendor | lakera (unverified) |
| Industry budget guidance | input rail < 100 ms p50; "a 400 ms p50 guardrail becomes the product's latency problem" | vendor blog | futureagi.com (unverified) |

**Comparison:** guard classifiers and moderation APIs typically add 50 to 600 ms. Harnesses that chain
LLM self-checks (NeMo self-check rails, current PRIME) add seconds. Our own T4 measurement fits that
pattern: Qwen3Guard-0.6B takes 0.13 s against PRIME's 3.5 to 9 s.

## 5. Verdict
- **As is, PRIME is not viable in front of a live interactive app on a T4.** It adds 3.5 s to time to first
  token on every allowed request (about 7x what a user waits for the model alone) and about 9 s on a refusal.
  Under load, one T4 sustains about 1 risk check per second at about 8 s each.
- **It is fine for offline or batch use**, and for async or agentic steps where a few seconds don't matter.
  Measured end to end, it is no slower than a chatty 7B model, because refusals replace long answers.
- **A realistic budget for a live app is about 100 to 300 ms added before the first token** on the common
  (ALLOW) path. On a T4 that rules out a 7B generative risk sensor. A 0.6B to 1.5B risk sensor with a short
  output meets it (0.13 to 0.34 s measured). REWRITE and REFUSE can afford about 1 to 2 s more, because they
  are a minority of traffic.

## 6. Levers, ranked by measured gain

| # | Lever | Gain (from the measurements above) | Cost / risk |
|---|---|---|---|
| 1 | **A small trained guard as R** (Qwen3Guard-Gen-0.6B; P and I unchanged) | R 3.45 s → **0.13 s** (−3.3 s, 26x) on every request. 20 req/s at concurrency 8 vs 1. Fits next to the protected model on the T4 | Fixed taxonomy and a 3-level verdict (Safe / Controversial / Unsafe), not a 0-1 score. P's thresholds have to map onto it. Calibration needs an eval (RELATED_WORK §1a, experiment 1) |
| 2 | **Short structured R output** (score + category only) | 7B: 3.45 → **1.45 s** (−2.0 s, −58%). 1.5B: 1.06 → 0.34 s | I loses R's `reason` and `intent`. I can infer them itself, since it sees the request |
| 3 | **Refusal path: stream it, cap it, or use templates** | Streaming: the user sees text about 0.6 s after R, instead of 5.6 s. Capping at about 60 tokens: about 3 s. Template: −5.6 s | Templates undo D12's quality gains. Streaming and capping keep them |
| 4 | **Run R in parallel with generation and hold the output until R's verdict** (as NeMo's speculative IORails do) | ALLOW total becomes max(R, gen) instead of R + gen. TTFT becomes max(R, model TTFT): close to zero added with lever 1 | Generation work is wasted on REFUSE. R and the model share the GPU (slowdown not measured). Never stream output before the verdict |
| 5 | **A faster GPU or kernel** | CUDA graphs: 0% (measured). L4 / A10G / A100 with Marlin AWQ or fp16 kernels: probably 2-4x faster decode (estimate, unverified) | About 2-4x the hourly cost of a T4 |
| 6 | **Batching** | 7B R: 3.6x throughput at concurrency 8, but 2.3x the latency per request | Helps cost, hurts latency |
| 7 | **Merge R and I into one call** (DECISIONS Q2, option A) | Saves one prefill: about 0.6 to 0.8 s, and only on REWRITE / REFUSE | Small gain. Tangles R and I (against D5). Worth it only if R stays a 7B LLM |

**Combined, on the same T4** (estimate from the rows above): Qwen3Guard-0.6B as R, I only for REWRITE, a
streamed refusal.

| Action | Today | Combined |
|---|---|---|
| ALLOW | +3.5 s | **+0.13 s** |
| REWRITE | +5.3 s | about +2 s |
| REFUSE | 9 s | about 0.7 s to the first token |

That is in the range of the guard classifiers and moderation APIs above, and it keeps what PRIME adds
beyond them (policy, rewrite, contextual refusal, logging). Before claiming it, run the quality comparison:
the guard as R vs the prompted 7B R on the same prompts.
