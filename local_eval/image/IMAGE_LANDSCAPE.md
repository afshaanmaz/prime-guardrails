# PRIME for images: landscape review

Status: research notes, 2026-11-26, branch `eval/image-exploration`. Companion to `IMAGE_PLAN.md`.

**How this was researched, and its limits.** All of this comes from web search. Direct fetches of
`huggingface.co`, `docs.mistral.ai` and `bfl.ai` failed in this session (the hosts were blocked), and
`arxiv.org` papers were read only through search excerpts. So model cards, dataset cards and papers
were read through search-result excerpts, official docs (Google, OpenAI, Microsoft, Stability) and
GitHub README pages, which could be fetched (Q16, OVERT, T2I-RiskyPrompt, T2ISafety, LlavaGuard).
Anything marked **(unverified)** needs checking against the primary page before it is cited or relied
on. "Estimate" marks my own arithmetic, not a sourced number. Sources are numbered [n] and listed at
the end.

---

## 1. Summary

- **Prompt benchmarks.** **I2P** [1][2][3] (4,703 real user prompts, 7 categories, MIT) is still the
  standard unsafe-prompt set, and nearly every defence paper reports on it. **OVERT** [11] (NeurIPS
  2025) adds what PRIME needs most: 4,600 *benign but risky-sounding* prompts for over-refusal, plus
  1,785 unsafe ones, across 9 categories, under Apache-2.0 per its GitHub repo. Newer, broader sets:
  **T2I-RiskyPrompt** [9] (6,432 prompts, 14 subcategories, with risk reasons) and **T2ISafety** [4][5]
  (about 70K prompts, 44 categories covering fairness, toxicity and privacy). Adversarial sets
  (**MMA-Diffusion** [6], **Ring-A-Bell** [7], **SneakyPrompt** [8]) target filters on purpose and
  should come later.
- **Image judges.** The I2P convention is **Q16 OR NudeNet** [1][17][19]. Both are small, run on CPU or
  any GPU, and are MIT-licensed (package level). They are dated: UnsafeBench found existing classifiers
  "not comprehensive or effective enough" [18], and one paper reports Q16 worse than random on an NSFW
  set [17-excerpt]. VLM judges add categories: **LlavaGuard v1.2** (0.5B/7B, 9 editable categories)
  [20], **ShieldGemma 2** (4B, sexual/dangerous/violence) [21], **Shieldstral 1.0** (3B, Apache-2.0,
  text and image, written policies) [24]. Two warnings: **Gemma 3 overflows in fp16 on T4** [22], so
  ShieldGemma 2 needs an L4; and Meta says **Llama Guard 4 does not support evaluating AI-generated
  images** [23], so it is unsuitable as the output judge.
- **Faithfulness.** **CLIPScore** [28] is cheap and standard, but behaves like a bag of words.
  **VQAScore** [29] agrees better with humans on compositional prompts. TIFA/DSG [30] are finer but cost
  more model calls. For PRIME the hard part is conceptual. On an unsafe prompt, "faithful to the
  original" partly means "unsafe", so faithfulness must be measured mainly on benign prompts.
- **Generators on a T4.** **SD 1.5** is the obvious first generator. It is the model that I2P, SLD,
  ESD, SAFREE and the Q16/NudeNet labels were built around, it fits easily, and it runs at 3.5 to
  5.5 it/s on a T4 at 512 px [34]. The original `runwayml` repo was deleted, so a mirror is
  needed [33]. Modern open models (**FLUX.2 klein 4B**, Apache-2.0, about 13 GB [38]; **Z-Image-Turbo
  6B**, Apache-2.0, about 16 GB [39]) are better candidates for a second, L4-based run.
- **Prompt-side safety is crowded.** LLM prompt rewriting for T2I safety is established. Examples
  are **POSI** (NAACL 2024, an RL-trained rewriter) [47], **VALOR** (AAAI-26, zero-shot agentic rewriting
  with category-specific prompts, intent disambiguation and optional regeneration) [53], and
  commercially **DALL·E 3's prompt transformation** (an LLM rewrite for safety and quality, returned as
  `revised_prompt`) [45]. OVERT found that rewriting cuts over-refusal but **often changes the prompt's
  meaning** [11]. **PRIME's image REWRITE is not novel on its own**. Its case rests on the
  configurable policy, the explicit ALLOW/REWRITE/REFUSE split with a helpful text refusal, the
  2-call latency budget and logging. It must also show that its rewrites keep meaning.
- **Native image-output LLMs** (GPT-image, Gemini image, BAGEL, Janus-Pro) change the setting. The
  protected model can talk, refuse and rewrite by itself, and API models run their own input and output
  filters [43][44]. So "every block is PRIME's own" holds only for open, image-only generators.

---

## 2. Unsafe text-to-image prompt benchmarks

"Benign?" = whether the set contains safe prompts for over-refusal or quality checks.

| Benchmark | Size | Categories | Labels | License / access | Benign? | Notes for PRIME |
|---|---|---|---|---|---|---|
| **I2P** (Schramowski et al., CVPR 2023) [1][2][3] | 4,703 prompts from real user prompts (scraped from the early Stable Diffusion Discord, per one description) [2] | 7: hate, harassment, violence, self-harm, sexual, shocking, illegal activity [1][2] | Per prompt: inappropriate %, nudity %, `hard` flag (≥ half of 10 SD-1.4 images flagged by Q16/NudeNet) [1][3] | **MIT** on HF (changed Nov 2022) [3]. Also an adversarial split, MIT [3] | No | The common reference point. Labels are estimates from SD 1.4 plus the Q16/NudeNet pair, so the same pair is the comparable judge. Multi-label `categories` field (unverified). |
| **OVERT** (Cheng et al., NeurIPS 2025 D&B) [11] | 4,600 benign prompts, plus OVERT-unsafe with 1,785 harmful prompts; `mini`, `full`, `unsafe` splits (mini size unverified) [11] | 9: privacy (individual), privacy (public figure), copyright, discrimination, self-harm, sexual, illegal activities, unethical/unsafe actions, violence [11] | Synthetic (LLM-generated from WildGuardMix or templates, filtered and audited) [11]. Refusal recorded per output | **Apache-2.0** per GitHub repo [11]. HF card history shows a license line being edited (current card license unverified) [11] | **Yes**, its main purpose | Over-refusal and safety-utility trade-off. OVERT-unsafe was built from OVERT-mini benign prompts (per a summary), so it gives **paired** benign and unsafe prompts [11]. Reports that **prompt rewriting reduces over-refusal but alters meaning** [11]. |
| **T2I-RiskyPrompt** (AAAI 2026) [9] | 6,432 prompts (one version says 6,431); 20,373 images from SD3 and FLUX [9] | 6 primary, 14 fine-grained (adds political sensitivity and copyright, beyond NSFW) [9] | Category labels plus a human-written risk reason per prompt [9] | Public JSON on GitHub. **No license stated** [9] | No | Risk reasons could check PRIME's judge `reason` field. Ships an MLLM risky-image detector (91.8% accuracy on its own set) [9]. |
| **T2ISafety** (CVPR 2025) [4][5] | About 70K prompts; about 68K annotated images [4] | 3 domains (fairness, toxicity, privacy), 12 tasks, 44 categories [4] | Human image annotations; **ImageGuard** MLLM evaluator [4][25] | README shows an Apache-2.0 badge but no LICENSE file [5]. HF hosting; gating unverified | Partly (fairness prompts are mostly benign) (unverified) | Broadest taxonomy. Fairness and bias are outside PRIME V1's risk categories. |
| **MMA-Diffusion** (CVPR 2024) [6] | 1,000 adversarial plus 1,000 clean prompts [6] | Sexual (from LAION-COCO, per one paper) [6] | Adversarial text (and image) attacks | **Gated** HF access request, research use [6]. Dataset license not found | Clean prompts (unverified use) | Built to evade text filters, which is PRIME's weakest point (§6). Later run. |
| **Ring-A-Bell** (ICLR 2024) [7] | Size not found | Nudity, violence [7] | Model-agnostic red-teaming prompts built with the CLIP text encoder [7] | Code on GitHub [7]. Prompt-set license unverified | No | Against concept-removal methods it gets ASR more than 30% higher than the original prompts [7]. Later run. |
| **SneakyPrompt** (IEEE S&P 2024) [8] | 200 GPT-4-generated risky prompts ("NSFW-200" name unverified) [9] | Pornographic, violent [9] | Attack framework (RL token perturbation) [8] | Code open-source [8] | No | Small and unbalanced, per a follow-up [8]. |
| **Unsafe Diffusion** (CCS 2023) [10] | 4 prompt sets: 4chan, Lexica, template-based (sizes not verified) [10] | 5: sexual, violent, disturbing, hateful, political [10] | 14.56% of images unsafe across 4 models; SD worst at 18.92% [10] | Unverified | No | Classic reference; the "political" category is useful. |
| **CoPro / CoProV2** (Latent Guard, ECCV 2024; SafetyDPO / AlignGuard) [16][12] | CoProV2-SDXL card: 31,380 training examples; SD1.5 card cites 1.04M images (the two conflict) [12] | LLM-generated harmful and **safe counterpart** pairs [12] | Image–text pairs | HF datasets (license unverified) [12] | **Yes**, paired | Pairs could serve as reference rewrites for faithfulness checks. |
| **FVH-Bench** (2026 preprint) [13] | 669 prompts, 5 "harmful visual functions", 10 risk domains [13] | Functional harm (what an image *enables*) [13] | 11 generators "rarely refuse"; existing detectors cover it poorly [13] | Unverified | No | Shows that NSFW classifiers miss whole harm types (e.g. fake documents). |
| **PartiPrompts (P2)** (Google, 2022) [15] | Over 1,600 prompts [15] | 12 categories, 11 challenge aspects [15] | None (capability set) | HF mirror lists Apache-2.0; upstream license unverified [15] | **Yes**, fully benign | Standard quality and faithfulness control set. |

A systematic review of open T2I safety datasets exists [14] and is worth reading before the paper.

---

## 3. Image safety classifiers and judges

T4 = 16 GB, Turing, fp16 only (no native bf16). L4 = 24 GB. "Fit" is weights plus activations,
estimated from parameter count unless a source is cited.

| Model | Detects | Size / base | License / gating | Output | T4 | L4 | Notes |
|---|---|---|---|---|---|---|---|
| **Q16** [17] | "Inappropriate" (offensive, insulting, threatening, etc.), binary | Learned soft prompts on CLIP (default ViT-L/14; ViT-B/16 reproduces the paper) [17] | **MIT** (repo badge) [17] | P(inappropriate) | Yes (CPU OK) | Yes | Half of the I2P labelling pair [1]. One paper finds Q16 "worse than random" on an NSFW set [17-excerpt], so use it with NudeNet. |
| **NudeNet v3** [19] | Exposed or covered body parts (object detector) | ONNX: `320n` (YOLOv8n, 320 px, default, bundled) and `640m` (YOLOv8m, 640 px, more accurate) [19] | Package **MIT** (per PyPI mirror) [19]. Weight-file license unverified | Boxes + class + score | Yes (CPU OK) | Yes | Other half of the I2P pair. Full class list and the "unsafe" class subset not verified here. Fix them before the run. |
| **SD safety checker** (built into SD 1.x pipelines) [26] | CLIP similarity to **17 obfuscated concept embeddings, all nudity-related** [26] | CLIP ViT-L/14 (unverified) | Same as SD | Black image when triggered | Yes | Yes | **Ignores violence and gore** [26]. Weak but free baseline: it can be run after the fact on baseline images. |
| **LlavaGuard v1.2** (CVPRW 2024; v1.2 later) [20] | 9 default categories: hate/harassment; violence/harm/cruelty; sexual; nudity; criminal planning; weapons or substance abuse; self-harm; animal cruelty; disasters/emergencies [20]. **Taxonomy editable in the prompt** [20] | 0.5B and 7B on LLaVA-OneVision **Qwen2** [20]; older 7B/13B | Repo **Apache-2.0** [20]. HF gate with a research-use acknowledgement [20]. Weight license unverified | JSON: rating, category, rationale | 0.5B yes. 7B tight in fp16 (estimate) | 7B yes | SGLang recommended; vLLM supported [20]. Policy-configurable, like PRIME. **Same base family (Qwen) as PRIME's judge**. |
| **ShieldGemma 2** [21] | Sexually explicit, dangerous content, violence/gore [21] | 4B on Gemma 3 [21] | Gemma terms; **gated** (accept license) [21] | P(Yes) per policy, via `ShieldGemma2ForImageClassification` [21] | **Risky**: Gemma 3 activations overflow fp16 on T4 and give empty or NaN output [22] | Yes (bf16) | Google suggests it as an *output filter of image generation* [21]. Sensitive to policy wording [21]. Internal F1 (probably) 88.6 / 93.7 / 85.0 (unverified reading) [21]. |
| **Shieldstral 1.0** (Mistral, Aug 2026) [24] | Text, images, text + image against **plain-language yes/no policies** [24] | 3B (Mistral docs list 3.8B) [24] | **Apache-2.0**, open weights [24] | Continuous safety score [24] | Yes, per Mistral (one 16 GB GPU) [24] | Yes | Vendor reports 83.8% average on its multimodal image-safety benchmark (unverified) [24]. Policy-following: the closest image peer to PRIME's configurable policy. |
| **Llama Guard 4** [23] | Prompt text + images, MLCommons categories | 12B [23] | Llama 4 license, gated [23] | Safe/unsafe + category | No (fp16 weights about 24 GB, estimate) | Quantised only | **Meta: "does not support the evaluation of images that were themselves created using generative AI"** [23]. Do not use it as the output judge. |
| **ImageGuard** (T2ISafety) [4][25] | T2ISafety taxonomy (fairness, toxicity, privacy) | InternLM-XComposer2-based [25] | Code Apache-2.0; weights academic, free commercial use per card [25] (unverified) | Category judgements | Unverified | Unverified | Matches T2ISafety. |
| **PerspectiveVision** (UnsafeBench) [18] | 11 unsafe categories (DALL·E content policy) [18] | LoRA-tuned LLaVA [18] | Unverified | Labels | Unverified | Unverified | Reported F1 0.810 across 6 datasets, comparable to GPT-4V [18]. |
| **T2I-RiskyPrompt detector** [9] | Its 14 subcategories | MLLM-based (`image_moderation.py`) [9] | No license stated [9] | Reason + label | Unverified | Unverified | 91.8% accuracy on its own image set [9]. |

Also seen, not checked: SafeVision [27], HoliSafe guard (CVPR 2026 Findings) [27], SigLIP-2 based
"Image-Guard" community models [27]. **UnsafeBench** [18] (10K images, 11 categories, real and
AI-generated) is the benchmark for judging the *judges*. GPT-4V was best there but closed [18].

---

## 4. Faithfulness and quality metrics

PRIME's REWRITE changes the prompt, so we must check that the image is still relevant to what the
user asked.

| Metric | What it measures | Cost | Notes |
|---|---|---|---|
| **CLIPScore** [28] | Image–text cosine similarity in CLIP space. Paper: `w · max(cos, 0)`, w = 2.5. torchmetrics scales to 0–100, default `openai/clip-vit-large-patch14` [28] | One CLIP forward pass per image | Cheap and reference-free. **Bag-of-words behaviour**: it cannot tell "horse eats grass" from "grass eats horse" [29]. |
| **VQAScore** [29] | P("Yes") from a VQA model asked "Does this figure show '{prompt}'?" | One VLM forward pass; CLIP-FlanT5 is strongest [29]. Size of the XXL checkpoint is large (exact size unverified) | Beats CLIPScore on human agreement for compositional prompts [29]. `t2v_metrics` package [29]. Also introduces GenAI-Bench (1,600 prompts) [29]. |
| **TIFA / DSG** [30] | An LLM writes questions from the prompt; a VQA model answers them on the image; DSG adds dependency structure [30] | Many calls per image | Fine-grained, interpretable. Depends on the LLM and VQA quality [30]. DSG-1k: 1,060 prompts [30]. |
| **HPSv2 / PickScore / ImageReward** [31] | Predicted human preference (aesthetics plus alignment) | One CLIP-sized forward pass | Quality proxy, not faithfulness. Each paper favours its own model [31]. |

A 2024 meta-evaluation of T2I consistency metrics [32] is worth citing for metric choice.

**The PRIME-specific problem.** For an unsafe prompt, the image from a *good* rewrite should **not**
match the original prompt's unsafe parts. So CLIPScore against the original prompt is confounded on
unsafe sets. Options (see `IMAGE_PLAN.md` §5): measure faithfulness on **benign** prompts (PartiPrompts,
OVERT benign), where any rewrite is pure loss; on unsafe prompts report CLIPScore against the original
only as "retained relevance", together with the unsafe rate; and use paired safe counterparts
(CoProV2 [12]) or VQA questions about the non-harmful subject later.

---

## 5. Image generators for a T4 / L4 eval

Seconds per image are for one 512 px (SD 1.x) or 1024 px (others) image, batch 1, unless noted.

| Model | Params | License / gating | VRAM | Speed | T4? | Notes |
|---|---|---|---|---|---|---|
| **SD 1.5** [33][34] | UNet about 0.86B (unverified) | CreativeML OpenRAIL-M [33]. **`runwayml/stable-diffusion-v1-5` deleted (2024)**; mirrors such as `Comfy-Org/stable-diffusion-v1-5-archive` (hash-identical) or `stable-diffusion-v1-5/stable-diffusion-v1-5` [33] | A few GB in fp16 (estimate) | T4 fp16 at 512 px: **3.5 it/s** (base attention) to **5.5 it/s** (memory-efficient attention) [34]; fal reports 13.7–16.2 s on T4 (settings unverified) [34]. About 5–9 s at 25–50 steps (estimate) | **Yes** | The model I2P, SLD, ESD, SAFREE and most baselines use (SD 1.4/1.5) [1][50][51]. Built-in safety checker must be **disabled** for the baseline. Weak at refusing: it has no refusal ability at all. CLIP text encoder truncates at 77 tokens (well known; unverified here). |
| **SD 2.1** | Not researched | Unverified | | | Probably | Trained on a filtered LAION subset (unverified), so it produces less unsafe content and is a weaker test. |
| **SDXL 1.0** [35] | About 3.5B total (unverified) | CreativeML OpenRAIL++-M (unverified) | fp32 default attention 28 GB; fp16 + SDPA much less [35] | 11.4 s in fp16 + SDPA on an unnamed GPU [35]; 8–10 s on A100 (Baseten) [35]. T4 likely 30–60 s (estimate) | Slow | Optional second generator. |
| **SD 3.5 Medium** [36] | 2.5B [36] | Stability AI Community License; **gated** [36] | Claims range from 5.4 to 9.9 GB; about 8 GB per guides [36] | Unverified | Probably (fp16 behaviour unverified) | Modern MMDiT at T4 scale. |
| **FLUX.1 [schnell]** [37] | 12B [37] | **Apache-2.0**; official HF repo gated (accept conditions); an ungated Unsloth mirror exists [37] | Official example uses bf16 + CPU offload [37]. 12B in fp16 is about 24 GB (estimate) | 1–4 steps [37] | Only with offload or quantisation; slow (estimate) | No negative prompt (guidance 0 in the example) [37]. |
| **FLUX.2 [klein] 4B** [38] | 4B (9B variant exists) [38] | **4B: Apache-2.0**; 9B: non-commercial [38] | About **13 GB** (BFL); one mirror says about 8 GB [38] | Unverified | Tight | **L4 candidate** for a modern second run. Released 15 Jan 2026 [38]. |
| **Z-Image-Turbo** [39] | 6B [39] | **Apache-2.0** [39] (secondary sources) | About 16 GB in practice; FP8 6–8 GB [39] | About 8 NFEs; sub-second on H800 [39] | No (bf16) | L4 candidate. Released Nov 2025 [39]. |
| **SANA-Sprint 1.6B** [40] | 1.6B [40] | **NVIDIA non-commercial** (sources conflict) [40] | Unverified | 0.1 s on H100 at 1 step; 1–4 steps [40] | Probably | License limits use. |

**Serving.** vLLM-Omni now serves diffusion models (Flux, SD3, Qwen-Image and others) with a
DALL·E-compatible `/v1/images/generations` endpoint [46]. It is built on vLLM 0.11+ [46], and our T4
pins vLLM 0.9.2, so its T4 support is unverified. A small diffusers server exposing the same endpoint
keeps the client code identical either way (see `IMAGE_PLAN.md` §4).

### 5a. Native image-output multimodal LLMs

| Model | Type | License | Fit | Safety behaviour |
|---|---|---|---|---|
| **Janus-Pro-7B** [41] | Unified understanding + generation (autoregressive) | Code MIT; **weights under DeepSeek Model License** [41] | Probably fits on a T4 in fp16 (estimate) | Unverified |
| **BAGEL** (ByteDance) [42] | Unified MoT, 7B active / 14B total [42] | **Apache-2.0** [42] | NF4 recommended for 12–32 GB GPUs [42] | GenEval 0.82 (0.88 with rewriter/CoT) [42]. Safety behaviour unverified |
| **gpt-image-1** (OpenAI API) [43] | Native image generation | Commercial API | n/a | `moderation`: `auto` (default) or `low`; C2PA metadata [43]. Same safeguards as 4o image generation in ChatGPT [43] |
| **Gemini image models ("Nano Banana")** [44] | Native image generation | Commercial API | n/a | Prompt blocks via `PromptFeedback.BlockedReason`; output blocks via finish reasons `IMAGE_SAFETY` / `IMAGE_PROHIBITED_CONTENT` [44]. A forum report says `BLOCK_NONE` still gets output-filtered [44] |
| **DALL·E 3** (historical) [45] | Diffusion behind an **LLM prompt rewriter** | Commercial | n/a | GPT-4 rewrites every prompt for quality and safety; returned as `revised_prompt`; cannot be disabled in Azure; Azure retired it on 4 Mar 2026 [45] |

**What these change for PRIME:**
1. **The protected model can talk.** A text-capable image model can refuse, ask a clarifying question,
   or explain. PRIME's REWRITE could then pass a *guardrail instruction* (as in the text V1) instead of
   a rewritten prompt. With an image-only model, rewriting the prompt is the only lever short of
   refusing.
2. **Upstream filters.** API models have their own input and output filters [43][44], and DALL·E 3
   already did safety rewriting [45]. Blocks are then no longer PRIME's own, which is the reason
   `local_eval` uses open models.
3. **Image inputs.** Editing (image + text in) means R must judge images too, which needs a VLM judge.
   That is out of scope for V1.

---

## 6. Prior prompt-side (and model-side) safety for T2I: baselines

| Approach | Where it acts | Training? | What it does | Relation to PRIME |
|---|---|---|---|---|
| **SD safety checker** [26] | Output image (post hoc) | No | Blacks out images near 17 nudity concepts | Free baseline. Nudity only [26]. |
| **Negative prompt** (generic unsafe terms) | Sampling (classifier-free guidance) | No | Steers away from listed concepts | Cheap baseline (no source; standard SD practice). Not available on guidance-distilled models such as FLUX schnell [37]. |
| **Safe Latent Diffusion (SLD)** [2][52] | Sampling guidance | No | Pushes away from a "safety concept" during denoising; presets WEAK, MEDIUM, STRONG, MAX [52] | In diffusers as `StableDiffusionPipelineSafe` (marked deprecated but usable) [52]. Natural baseline with SD 1.5 and I2P (same authors as I2P). |
| **ESD / UCE** [51] | Model weights | ESD: fine-tune; UCE: closed form | Erase concepts (e.g. nudity) from the model [51] | Model-side baseline. Public checkpoints for SD 1.4 (unverified). Over-erasure risk [51]. |
| **SAFREE** (ICLR 2025) [50] | Text embeddings + latent re-attention | No | Projects trigger tokens away from a toxic subspace [50] | Strong training-free baseline. Follow-up PurifyGen [50]. |
| **Latent Guard** (ECCV 2024) [16] | Text-encoder embedding (detector) | Yes (contrastive) | Blacklist check in a learned latent space; blacklist editable at test time [16] | Detector baseline. "Editable blacklist" is a form of configurable policy. |
| **GuardT2I** (NeurIPS 2024) [48] | Text embedding → decoded prompt (detector) | Yes (conditional LLM) | Decodes the guidance embedding back to text and compares it with the input; can halt early [48] | Detector aimed at adversarial prompts, where PRIME's text judge is weak. |
| **POSI** (NAACL 2024) [47] | Prompt rewrite | Yes (PPO) | LLM rewriter trained on toxic→clean pairs with a reward for toxicity and alignment [47] | **Closest learned analogue to PRIME REWRITE.** |
| **VALOR** (AAAI-26) [53] | Prompt rewrite (zero-shot, agentic) | No | Multi-level risk detection → intent disambiguation → category-specific rewrite prompts → optional style-guided regeneration after a post-hoc check [53] | **Closest zero-shot analogue to PRIME image.** Its category-specific rewrite prompts are what PRIME's topic `instruction` would provide. |
| **PromptSafe** [54] | Soft prompt (gated by toxicity) | Yes | LLM rewrites used offline; CLIP similarity ≥ 0.7 to keep rewrites faithful [54] | Supports a similarity floor for PRIME rewrites. |
| **SPOT** (2026 preprint) [55] | Prompt projection | No | LLM generates and ranks candidate rewrites; a safeguard VLM checks the image [55] | Notes meaning drift on borderline prompts [55]. |
| **DALL·E 3 prompt transformation** [45] | Prompt rewrite (commercial) | n/a | Rewrites every prompt for safety and quality [45] | Commercial precedent for REWRITE. |

---

## 7. What this means for PRIME (pointers into IMAGE_PLAN.md)

1. **Benchmarks for the first run:** I2P (unsafe) + OVERT benign (over-refusal) + PartiPrompts
   (benign quality control). OVERT-unsafe, T2I-RiskyPrompt and the adversarial sets come later.
2. **Judge for the first run:** Q16 OR NudeNet (comparable to the literature, CPU-cheap, unrelated to
   PRIME's judge), plus a hand spot-check. Add a VLM judge (ShieldGemma 2 or LlavaGuard 7B on an L4,
   or Shieldstral after verifying it) for categories other than nudity.
3. **Generator:** SD 1.5 on the T4, safety checker off for the baseline.
4. **Baselines:** SD safety checker (post hoc, free), SLD (same weights), generic negative prompt.
   Later: SAFREE, ESD/UCE, POSI, VALOR.
5. **Novelty:** position PRIME as a configurable, auditable *system* with measured faithfulness, not
   as "the first LLM rewriter for T2I".

---

## Sources

1. I2P dataset card (AIML-TUDA): https://huggingface.co/datasets/AIML-TUDA/i2p/raw/main/README.md
2. Safe Latent Diffusion (CVPR 2023): [arXiv 2211.05105](https://arxiv.org/abs/2211.05105), [CVPR paper](https://openaccess.thecvf.com/content/CVPR2023/papers/Schramowski_Safe_Latent_Diffusion_Mitigating_Inappropriate_Degeneration_in_Diffusion_Models_CVPR_2023_paper.pdf), [DFKI PDF](https://www-live.dfki.de/fileadmin/user_upload/import/13359_main.pdf)
3. I2P license commit (MIT) and adversarial split: [commit](https://huggingface.co/datasets/AIML-TUDA/i2p/commits/6594f223b0544fcbf63a6889417a6b9d2e40a77c), [i2p-adversarial-split](https://huggingface.co/datasets/AIML-TUDA/i2p-adversarial-split/blob/main/README.md)
4. T2ISafety (CVPR 2025): [arXiv 2501.12612](https://arxiv.org/abs/2501.12612v2), [CVPR paper](https://openaccess.thecvf.com/content/CVPR2025/papers/Li_T2ISafety_Benchmark_for_Assessing_Fairness_Toxicity_and_Privacy_in_Image_CVPR_2025_paper.pdf)
5. T2ISafety GitHub: https://github.com/adwardlee/t2i_safety
6. MMA-Diffusion: [GitHub](https://github.com/yangyijune/mma-diffusion), [arXiv 2311.17516](https://arxiv.org/html/2311.17516v2/), [follow-up describing its prompts](https://arxiv.org/html/2504.11707v1)
7. Ring-A-Bell (ICLR 2024): [proceedings](https://proceedings.iclr.cc/paper_files/paper/2024/hash/b5b4d92374323c53c24bbbc8ee0e715c-Abstract-Conference.html), [arXiv 2310.10012](https://arxiv.org/abs/2310.10012v3)
8. SneakyPrompt (IEEE S&P 2024): [arXiv 2305.12082](https://arxiv.org/abs/2305.12082v3)
9. T2I-RiskyPrompt (AAAI 2026): [arXiv 2510.22300](https://arxiv.org/html/2510.22300v1), [AAAI](https://ojs.aaai.org/index.php/AAAI/article/view/40920), [GitHub](https://github.com/datar001/T2I-RiskyPrompt)
10. Unsafe Diffusion (CCS 2023): [arXiv 2305.13873](https://arxiv.org/abs/2305.13873v2)
11. OVERT (NeurIPS 2025): [arXiv 2505.21347](https://arxiv.org/abs/2505.21347), [NeurIPS poster](https://neurips.cc/virtual/2025/poster/121840), [GitHub](https://github.com/yixiao-huang/OVERT), [HF README commit](https://huggingface.co/datasets/yixiaoh/OVERT/commit/b3cc337edd8a537519e0965c38bc9b5892103044), [paper notes](https://en.papernotes.org/NeurIPS2025/image_generation/overt_a_benchmark_for_over-refusal_evaluation_on_text-to-image_models/), [Berkeley summary](https://ieor.berkeley.edu/when-ai-image-generators-refuse)
12. CoProV2 / SafetyDPO (AlignGuard): [arXiv 2412.10493](https://arxiv.org/abs/2412.10493v1), [CoProv2-SDXL card](https://huggingface.co/datasets/Visualignment/CoProv2-SDXL/blob/refs%2Fpr%2F2/README.md), [CoProv2-SD15 card](https://huggingface.co/datasets/Visualignment/CoProv2-SD15/blob/refs%2Fpr%2F1/README.md)
13. FVH-Bench (2026 preprint): [arXiv 2610.37722](https://arxiv.org/pdf/2610.37722)
14. Systematic review of open T2I safety datasets: [arXiv 2503.00020](https://arxiv.org/pdf/2503.00020)
15. PartiPrompts: [Parti paper arXiv 2206.10789](https://arxiv.org/pdf/2206.10789), [HF mirror](https://huggingface.co/datasets/nateraw/parti-prompts/blob/main/README.md)
16. Latent Guard (ECCV 2024): [arXiv 2404.08031](https://arxiv.org/abs/2404.08031), [ECCV paper](https://www.ecva.net/papers/eccv_2024/papers_ECCV/papers/03726.pdf)
17. Q16: [paper arXiv 2202.06675](https://arxiv.org/pdf/2202.06675), [GitHub](https://github.com/ml-research/Q16); "worse than random on NSFW" excerpt from [arXiv 2412.03876](https://arxiv.org/pdf/2412.03876) (attribution to that exact paper unverified)
18. UnsafeBench / PerspectiveVision: [arXiv 2405.03486 v2](https://arxiv.org/html/2405.03486v2), [v3](https://arxiv.org/html/2405.03486v3)
19. NudeNet: [PyPI](https://pypi.org/project/nudenet), [CERN PyPI mirror (MIT)](https://simple-repository.app.cern.ch/project/NudeNet), [README fork with model details](https://github.com/PranavN45/nudeNet), [DeepWiki](https://deepwiki.com/notAI-tech/NudeNet)
20. LlavaGuard: [arXiv 2406.05113](https://arxiv.org/abs/2406.05113v2), [GitHub](https://github.com/ml-research/LlavaGuard), [v1.2 0.5B card](https://huggingface.co/AIML-TUDA/LlavaGuard-v1.2-0.5B-OV-hf), [CVPRW paper](https://openaccess.thecvf.com/content/CVPR2024W/ReGenAI/papers/Helff_LLAVAGUARD_VLM-based_Safeguard_for_Vision_Dataset_Curation_and_Safety_Assessment_CVPRW_2024_paper.pdf)
21. ShieldGemma 2: [model card](https://ai.google.dev/gemma/docs/shieldgemma/model_card_2?hl=en), [tech report arXiv 2504.01081](https://arxiv.org/pdf/2504.01081), [Transformers docs](https://huggingface.co/docs/transformers/model_doc/shieldgemma2), [HF gate](https://huggingface.co/google/shieldgemma-2-4b-it)
22. Gemma 3 fp16 overflow on T4: [Unsloth guide](https://unsloth.ai/docs/models/tutorials/gemma-3-how-to-run-and-fine-tune), [Transformers issue 36822](https://github.com/huggingface/transformers/issues/36822), [vLLM forum](https://discuss.vllm.ai/t/gemma3-on-a-t4-gpu/643)
23. Llama Guard 4: [HF model page](https://huggingface.co/meta-llama/Llama-Guard-4-12B), [Meta docs](https://developer.meta.com/ai/docs/model-cards-and-prompt-formats/llama-guard-4/)
24. Shieldstral 1.0: [HF](https://huggingface.co/mistralai/Shieldstral-1.0), [Mistral news](https://mistral.ai/news/shieldstral/), [Mistral docs](https://docs.mistral.ai/models/shieldstral-1-0.md), [SiliconANGLE](https://siliconangle.com/2026/08/05/mistral-introduces-shieldstral-provide-lightweight-policy-aware-moderation-ai-models/), [NYU RITS](https://rits.shanghai.nyu.edu/ai/mistral-releases-shieldstral-a-3b-policy-adaptive-safety-classifier)
25. ImageGuard: https://huggingface.co/OpenSafetyLab/ImageGuard
26. SD safety filter red-teaming (Rando et al. 2022): [arXiv 2210.04610](https://arxiv.org/abs/2210.04610); DiffGuard summary: [arXiv 2412.00064](https://arxiv.org/pdf/2412.00064)
27. Other image guards: [SafeVision arXiv 2510.23960](https://arxiv.org/pdf/2510.23960), [HoliSafe CVPR 2026 Findings](https://openaccess.thecvf.com/content/CVPR2026F/html/Lee_HoliSafe_Holistic_Safety_Benchmarking_and_Modeling_for_Vision-Language_Model_CVPRF_2026_paper.html), [Image-Guard-2.0 blog](https://huggingface.co/blog/prithivMLmods/image-guard-models)
28. CLIPScore: [arXiv 2104.08718](https://arxiv.org/abs/2104.08718v2), [ACL Anthology](https://aclanthology.org/2021.emnlp-main.595), [torchmetrics CLIPScore](https://lightning.ai/docs/torchmetrics/stable/multimodal/clip_score.html), [w = 2.5 formula excerpt](https://arxiv.org/pdf/2502.06600)
29. VQAScore / GenAI-Bench: [arXiv 2404.01291](https://arxiv.org/abs/2404.01291), [t2v_metrics](https://github.com/linzhiqiu/t2v_metrics)
30. TIFA / DSG: [DSG arXiv 2310.18235](https://arxiv.org/pdf/2310.18235), [DSG project](https://google.github.io/dsg)
31. Preference metrics: [HPSv2 arXiv 2306.09341](https://arxiv.org/pdf/2306.09341), [Pick-a-Pic arXiv 2305.01569](https://arxiv.org/pdf/2305.01569)
32. Meta-evaluation of T2I consistency metrics: [arXiv 2412.13989](https://arxiv.org/pdf/2412.13989)
33. SD 1.5 removal and mirrors: [Comfy-Org archive](https://huggingface.co/Comfy-Org/stable-diffusion-v1-5-archive), [HF forum: runwayml repo 404](https://discuss.huggingface.co/t/license-agreement-error-runwayml-stable-diffusion-v1-5-returns-404/161673), [takedown discussion](https://huggingface.co/lllyasviel/control_v11p_sd15_inpaint/discussions/16)
34. SD 1.x speed on T4: [diffusers fp16 docs (T4 it/s)](https://huggingface.co/docs/diffusers/v0.9.0/optimization/fp16), [fal-ai benchmarks](https://github.com/fal-ai/stable-diffusion-benchmarks)
35. SDXL speed and memory: [HF blog: simple SDXL optimizations](https://huggingface.co/blog/simple_sdxl_optimizations), [Baseten SDXL guide](https://www.baseten.co/blog/sdxl-inference-in-under-2-seconds-the-ultimate-guide-to-stable-diffusion-optimiza)
36. SD 3.5: [Stability announcement](https://stability.ai/news/introducing-stable-diffusion-3-5), [HF gated repo](https://huggingface.co/stabilityai/stable-diffusion-3.5-medium), [The Decoder](https://the-decoder.com/stability-ai-releases-stable-diffusion-3-5-medium-with-lower-vram-requirements/), [ApX](https://apxml.com/models/stable-diffusion-3-5-medium)
37. FLUX.1 [schnell]: [HF model card](https://huggingface.co/black-forest-labs/FLUX.1-schnell), [Unsloth ungated mirror](https://huggingface.co/unsloth/FLUX.1-schnell)
38. FLUX.2 [klein]: [HF 4B card](https://huggingface.co/black-forest-labs/FLUX.2-klein-4B), [BFL blog](https://bfl.ai/blog/flux2-klein-towards-interactive-visual-intelligence), [VentureBeat](https://venturebeat.com/technology/black-forest-labs-launches-open-source-flux-2-klein-to-generate-ai-images-in), [GitHub mirror](https://github.com/brookman/flux2)
39. Z-Image: [arXiv 2511.22699](https://arxiv.org/html/2511.22699v1), [HF Z-Image-Turbo](https://huggingface.co/TONGYI-MAI/Z-Image-Turbo), [codesota](https://codesota.com/news/z-image-turbo-consumer-gpu)
40. SANA-Sprint: [MIT HAN lab project](https://hanlab.mit.edu/projects/sana-sprint), [Replicate model card](https://replicate.com/nvidia/sana-sprint-1.6b/readme)
41. Janus-Pro-7B: https://huggingface.co/deepseek-ai/Janus-Pro-7B
42. BAGEL: [GitHub](https://github.com/bytedance-seed/BAGEL), [arXiv 2505.14683](https://arxiv.org/html/2505.14683v3)
43. OpenAI image API: [announcement](https://openai.com/index/image-generation-api/), [API reference](https://developers.openai.com/api/reference/resources/images.md)
44. Gemini image safety: [Vertex AI responsible AI for Gemini image](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/multimodal/gemini-image-responsible-ai), [GenerateContentResponse reference](https://cloud.google.com/vertex-ai/generative-ai/docs/reference/rest/v1/GenerateContentResponse), [forum: IMAGE_SAFETY with BLOCK_NONE](https://discuss.ai.google.dev/t/nano-banana-pro-suddenly-blocking-non-nsfw-ecommerce-underwear-images-with-image-safety-error/113109)
45. DALL·E 3 prompt rewriting: [OpenAI cookbook](https://developers.openai.com/cookbook/articles/what_is_new_with_dalle_3), [Azure prompt transformation](https://learn.microsoft.com/en-us/azure/ai-services/openai/concepts/prompt-transformation)
46. vLLM-Omni: [launch post](https://vllm.ai/blog/vllm-omni), [Red Hat intro](https://next.redhat.com/2026/06/30/expanding-ai-beyond-text-vllm-omni-extension-for-multimodal-models/), [arXiv 2602.02204](https://arxiv.org/html/2602.02204v1)
47. POSI (NAACL 2024): [ACL Anthology](https://aclanthology.org/2024.naacl-long.351), [arXiv 2402.10882](https://arxiv.org/abs/2402.10882v3)
48. GuardT2I (NeurIPS 2024): [NeurIPS poster](https://neurips.cc/virtual/2024/poster/95982), [arXiv 2403.01446](https://arxiv.org/abs/2403.01446v1)
49. (reserved)
50. SAFREE (ICLR 2025): [arXiv 2410.12761](https://arxiv.org/abs/2410.12761v2), [ICLR poster](https://iclr.cc/virtual/2025/poster/28752); PurifyGen: [arXiv 2512.23546](https://arxiv.org/pdf/2512.23546v1)
51. ESD / UCE: [ESD ICCV 2023](https://openaccess.thecvf.com/content/ICCV2023/html/Gandikota_Erasing_Concepts_from_Diffusion_Models_ICCV_2023_paper.html), [UCE arXiv 2308.14761](https://arxiv.org/abs/2308.14761v2), [UCE GitHub](https://github.com/rohitgandikota/unified-concept-editing), [ACE (over-erasure note)](https://arxiv.org/pdf/2504.11850)
52. Diffusers Safe Stable Diffusion (SLD) pipeline: https://huggingface.co/docs/diffusers/api/pipelines/stable_diffusion/stable_diffusion_safe
53. VALOR (AAAI-26): [AAAI](https://ojs.aaai.org/index.php/AAAI/article/view/41152), [arXiv 2511.11693](https://arxiv.org/abs/2511.11693v1)
54. PromptSafe: [arXiv 2508.01272](https://arxiv.org/pdf/2508.01272)
55. SPOT: [arXiv 2602.00616](https://arxiv.org/pdf/2602.00616)
