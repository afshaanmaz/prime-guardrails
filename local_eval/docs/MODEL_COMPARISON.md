# Protected models: comparison and choice

Status: 28 Nov 2026. Which models PRIME protects in the experiments, and why.
Related decisions: D17 (open-weight protected models, several providers) and D18 (roles) in `DECISIONS.md`.

## What we want to cover

PRIME is a framework, so it should help across different kinds of protected model, not just one.
Three axes:

1. **Model family / provider.** Results shouldn't hinge on one vendor's training recipe.
2. **Safety level (the most important axis).**
   - On a **weakly aligned** model, PRIME's job is to *prevent harm*. The model complies with harmful
     requests on its own, so PRIME should clearly win.
   - On a **strongly aligned** model, the model already refuses. PRIME can only add value by handling
     borderline requests well (rewrites), and its cost (over-refusal) shows most clearly.
3. **Size.** Small models (≤ 3B) are the realistic choice for on-device and low-latency use, where a cheap
   model plus a guardrail framework is the natural pitch. Mid-size (7–9B) is the usual open-model baseline.

**No serving-side filters.** Open-weight models run on our own GPU with vLLM, so the only safety is what
each model learned in training. The hosted DeepSeek model runs on Vertex AI, where no content filter is
documented (see below). Closed models (GPT, Claude, Gemini) are excluded: their providers' filters would
mix with what we measure.

**Also considered, not pursued:** Phi-3.5-mini and Phi-4-mini (Microsoft), Granite 3.x (IBM), Qwen2.5
(Alibaba; also our risk sensor's family), OLMo-2 (Ai2), SmolLM2 (Hugging Face) and TinyLlama. They are either
less widely used, a second example of a cell we already cover, or too weak to judge answers meaningfully.

"Safety training" below is from each model card or the developer's own statements. "Expected behaviour" is
our expectation; the model-alone side of our runs measures the real behaviour on our benchmarks.

## Weak safety: known to have little or no safety training

| Model | Provider | Size | Released | Safety training | Expected on harmful requests | How we'd run it | Status |
|---|---|---|---|---|---|---|---|
| **Zephyr-7B-beta** | Hugging Face (on Mistral-7B) | 7B | Oct 2023 | **None.** The model card says it was not aligned for safety and "can produce problematic outputs" | Mostly complies (our smoke run: 16 of 20 HarmBench requests) | T4, 4-bit | **In the quick benchmark** |
| **Mistral-7B-Instruct** (v0.1 / v0.2 / v0.3) | Mistral AI | 7B | Sep 2023 / Dec 2023 / May 2024 | **None.** The model card says it "does not have any moderation mechanisms" | Mostly complies | T4, 4-bit (v0.3 needs a click-through on Hugging Face) | Candidate |
| **DeepSeek V4.1-Flash** | DeepSeek | Not published | 2026 (exact date unverified; a `-1017` version exists) | Not documented. DeepSeek models have a weak-safety reputation (see R1), but this newer model is unmeasured | Unknown; to be measured | Hosted on Vertex AI (no GPU, pay per token). Thinking text, if any, comes back separately from the answer | Access tested; **awaiting approval to run** |
| DeepSeek-R1 (full) | DeepSeek | 671B (mixture of experts) | Jan 2025 (R1-0528: May 2025) | Weak. A widely cited 2025 security study reported harmful content on every HarmBench prompt it tried (with jailbreak attacks) | Mostly complies | Too big for our GPU. Its Vertex AI endpoint was **retired on 21 Oct 2026** | Not available |
| DeepSeek-R1-Distill-Qwen-1.5B | DeepSeek (on Qwen2.5) | 1.5B | Jan 2025 | Weak; distilled for reasoning, not safety | Mostly complies (expected) | T4, fp16. Writes a long "thinking" section first, so it needs a longer answer limit and the thinking stripped before scoring | Candidate (small, weak) |
| Hermes 3 | Nous Research (on Llama 3.1) | 8B | Aug 2024 | Deliberately "neutrally aligned", with few refusals | Mostly complies | T4, 4-bit | Not pursued (community model) |
| Dolphin 2.9 | Cognitive Computations (on Llama 3 / Mistral) | 7–8B | Apr 2024 | Explicitly "uncensored": refusals removed from the training data | Complies | T4, 4-bit | Not pursued (community model) |

## Strong safety: dedicated safety training

| Model | Provider | Size | Released | Safety training | Expected on harmful requests | How we'd run it | Status |
|---|---|---|---|---|---|---|---|
| **Llama 3.1 8B Instruct** | Meta | 8B | Jul 2024 | Strong: dedicated safety fine-tuning and red-teaming. Meta reports fewer unnecessary refusals than Llama 2 | Mostly refuses direct requests | T4, 4-bit (gated: licence accepted) | **In the quick benchmark** |
| **Gemma 2 2B it** | Google | 2B | Jul 2024 | Strong: filtered training data plus safety-focused tuning | Mostly refuses; small models are often easier to talk around | T4, float32 (vLLM won't run Gemma 2 in fp16, and the T4 has no bf16) | **In the quick benchmark** |
| Gemma 2 9B it | Google | 9B | Jun 2024 | Same recipe as Gemma 2 2B | Mostly refuses | Needs bf16 (an L4 or newer); does **not** run on our T4 | Blocked on hardware |
| Llama 3.2 1B / 3B Instruct | Meta | 1B, 3B | Sep 2024 | Same approach as Llama 3.1 | Mostly refuses | T4, fp16 | Candidate (second small, strong model) |

## The grid: size × safety (popular models only)

| | **Small (≤ 3B)** | **Mid-size (7–9B)** | **Hosted API (size not published)** |
|---|---|---|---|
| **Weak safety** | DeepSeek-R1-Distill-Qwen-1.5B (candidate) | **Zephyr-7B-beta** (running) · Mistral-7B-Instruct (candidate) | **DeepSeek V4.1-Flash** (access tested) |
| **Strong safety** | **Gemma 2 2B** (running) · Llama 3.2 1B/3B (candidate) | **Llama 3.1 8B** (running) · Gemma 2 9B (needs an L4) | — |

**Current choice:** Zephyr, Llama 3.1 8B and Gemma 2 2B in the quick benchmark (90 requests), with DeepSeek
V4.1-Flash as a second weak-safety model if approved. That covers three providers plus DeepSeek, both safety levels,
and two sizes. The third model for the full run is to be decided after the quick benchmark.

## Notes on hosted DeepSeek (Vertex AI)

- Model `deepseek-ai/deepseek-v4.1-flash-maas`, Vertex AI `global` region, OpenAI-compatible endpoint (the same
  kind we use for the evaluator). A test call on 28 Nov 2026 worked from our project with no setup.
- By default it answers directly: on a test prompt there was no thinking text, and the answer fit well inside
  our 512-token limit, so it is comparable with the other models.
- **Content filter:** none documented by Google for DeepSeek on Vertex AI (desk research, 28 Nov 2026; Google's
  pages could only be read through search excerpts). If responses are blocked, they will show up in our runs
  as errors or empty answers.
- The code reads a fresh Google access token every 45 minutes (`run.py`, `RefreshingKeyClient`), since tokens
  expire after an hour.
