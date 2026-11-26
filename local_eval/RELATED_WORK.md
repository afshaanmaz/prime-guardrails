# PRIME: related work and benchmark plan

Status: landscape review, 2026-11-26. Written for the paper's related-work and evaluation sections.

**How this was researched, and its limits.** Everything below comes from web search. Direct page fetches
from `huggingface.co` and `arxiv.org` were blocked in this session, so model cards and papers were read
through search-result excerpts, official docs (Google, Microsoft, NVIDIA, OpenAI, Mistral, IBM) and
mirrors, not opened in full. Anything marked **(unverified)** needs checking against the primary page
before it goes in the paper. Numbers quoted from papers are the authors' own results unless stated
otherwise. Sources are numbered as [n] and listed at the end.

---

## 1. Summary

- **Baselines.** The open guard models that are cited most often and that run on one T4/L4 are
  **Llama Guard 3** (1B/8B) [1][2], **ShieldGemma** (2B/9B) [3][4], **WildGuard** (7B) [6][7] and
  **Qwen3Guard-Gen** (0.6B/4B/8B) [9][10]. The newer **policy-following** guards read a policy written
  in plain language at inference time, which is PRIME's headline feature:
  **gpt-oss-safeguard** (20B/120B) [11][12], **Nemotron-Content-Safety-Reasoning-4B** [17],
  **Granite Guardian** with "bring your own criteria" [13][14] and Mistral's **Shieldstral** 3B
  (released Aug 2026) [19][20]. **"Configurable policy" alone is no longer new.** Since late 2025 at
  least five open models do it, and DynaGuard (ICLR 2026) made it a research topic in its own
  right [41].
- **What PRIME is.** PRIME is a **system**: a judge, a policy layer that maps a score to an action
  (allow / rewrite / refuse / topic rules), an output gate and helpful refusals, wrapped around a
  protected model. Most baselines are **classifiers**. A fair comparison needs two tracks: a
  *classifier track* (PRIME's judge plus policy, used as a classifier) and a *system track* (the same
  protected model and harness, with each guard swapped in as the gate). Recent harness papers report
  attack success, false refusal and latency together. They find that no configuration wins on all
  three at once [44].
- **Benchmarks.** These are standard enough for reviewers to accept:
  - **classification:** WildGuardTest [6], Aegis 2.0 [16], OpenAI Moderation [28], ToxicChat [29]
  - **system harm:** HarmBench [23], StrongREJECT [27] or JailbreakBench [25]
  - **over-refusal:** XSTest [31], OR-Bench [32]
  - **aggregate suite:** GuardBench (40 datasets, with a pip library) [34][35]
- **Gaps.** There is **no standard benchmark for helpful-refusal quality**. The closest are OpenAI's
  safe-completions paper (internal evaluations) [37], the partial-refusal label in XSTest, FalseReject
  [38] and CoSA-Score [40]. PRIME will need its own small rubric with human spot-checks, and that can
  be one of the paper's contributions.
- **Main risks.**
  - **Taxonomy and label mismatch** across benchmarks [46][47].
  - **Contamination:** one NeurIPS 2026 paper reports that guard training pools already contained 88%
    of JailbreakBench-benign and 82% of OR-Bench-hard [45].
  - **Same family:** PRIME's judge is Qwen2.5 and one baseline is Qwen3Guard.
  - **Unfair framing:** comparing a full system against bare classifiers.

---

## 2. Baselines

Hardware fit assumes vLLM. Weight memory is roughly 2 bytes per parameter in fp16/bf16 (my estimate, not
from the sources). The T4 has 16 GB and no bf16 support, so vLLM runs in fp16. The L4 has 24 GB. "Policy
at inference" means you can supply new rules or categories in the prompt without retraining.

### 2a. Open-weight guard models

| Model | What it checks | Taxonomy | Sizes | License / gating | Policy at inference? | T4 16 GB | L4 24 GB |
|---|---|---|---|---|---|---|---|
| **Llama Guard 3** (Meta) | Prompt + response | 14 categories, MLCommons hazards S1–S13 plus S14 Code Interpreter Abuse [2] | 1B, 8B (also 11B-Vision) | Llama 3.1 / 3.2 Community License. **Gated on HF: needs a Meta access request** [1][2] | Partly. The category list is part of the prompt, so you can remove or add categories, but generalisation to very different taxonomies is limited [22] | 1B yes. 8B only quantised | 8B yes |
| **Llama Guard 4** (Meta) | Prompt + response, text + image | MLCommons-based, plus Code Interpreter Abuse [5] | 12B dense (pruned from Llama 4 Scout) [5] | Llama 4 Community License. **Gated**, with an anecdotal report of a denied request [21] | Same as LG3 | No | Tight: about 24 GB of weights in bf16, so quantisation is needed (estimate). any-guardrail deliberately does not support LG4 [1] |
| **ShieldGemma 1** (Google) | Prompt + response | 4 harm types: sexually explicit, dangerous content, hate, harassment [3] | 2B, 9B, 27B (Gemma 2) | Gemma Terms. **HF gate is "acknowledge license", approved instantly** [4] | The policy definition is written into the prompt. It was trained on the 4 types; how well custom policies work is (unverified) | 2B yes. 9B only quantised. Gemma 2 is meant to run in bf16, so check fp16 on the T4 (unverified risk) | 2B, 9B yes |
| **ShieldGemma 2** (Google) | **Images only** | Sexual, dangerous, violent [8] | 4B (Gemma 3) | Gemma Terms, instant gate [4] | Policy text in the prompt. Google warns it is sensitive to policy wording [8] | n/a for PRIME (text) | n/a |
| **WildGuard** (Ai2) | Prompt harm, response harm, **refusal detection** | 13 risk categories (WildGuardMix) [7] | 7B (Mistral-7B-v0.3) [6] | Apache-2.0, but **HF gate**: automatic after accepting Ai2 Responsible Use Guidelines and filling in a form [43] | No (fixed) | Tight in fp16 (about 14.5 GB). Use AWQ/INT8 | Yes |
| **Qwen3Guard-Gen / -Stream** (Alibaba) | Prompt + response, refusal detection; Stream adds token-level moderation during generation [9][10] | Safe / **Controversial** / Unsafe severity, plus categories (PII, violence, self-harm, jailbreak on input, etc.; full list unverified) [9][18] | 0.6B, 4B, 8B [9] | Reported Apache-2.0 [9] (confirm on the HF card). **Ungated** (unverified) | Only **strict/loose** (whether Controversial counts as unsafe) [18] | 0.6B, 4B yes. 8B only quantised | All |
| **gpt-oss-safeguard** (OpenAI) | Any content against **your written policy**. Reasons, then labels | None built in; bring your own [11] | 20B (21B total / 3.6B active MoE), 120B [11] | Apache-2.0, on HF [12] | **Yes, by design** | Unlikely: no vLLM backend for Turing according to a community reply (unverified) [42] | Probably: about 14 GB of MXFP4 weights, but vLLM lists Ada support as "in progress" [42] |
| **Granite Guardian 3.3 / 4.1** (IBM) | Prompt + response harm, jailbreak, RAG groundedness, function-call hallucination [13][14] | IBM AI Risk Atlas [13] | 3.3: 8B. 4.1: 8B. Earlier: 2B, 5B, 3B-A800M | Apache-2.0 (per listings) [14] | **Yes ("bring your own criteria")**, with thinking / non-thinking modes [13][14] | Only quantised | Yes |
| **Llama-3.1-Nemotron-Safety-Guard-8B-v3** (NVIDIA) | Prompt + response, 9 languages | 23 categories (Aegis 2.0 / Nemotron Content Safety v2) [15] | 8B | NVIDIA Open Model License + Llama 3.1 license [15] | No (fixed taxonomy) | Only quantised | Yes |
| **Nemotron-Content-Safety-Reasoning-4B** (NVIDIA) | Prompt + response | Default Nemotron taxonomy or **custom policy** [17] | 4B (Gemma-3-4B-it) | NVIDIA Open Model License + Gemma terms [17] | **Yes**, with reasoning on/off [17] | Yes | Yes |
| **Shieldstral 1.0** (Mistral, Aug 2026) | Prompt, response, refusal, toxicity; text + image [19][20] | Plain-language yes/no policies [19] | 3B | Apache-2.0, open weights, self-hosted only [19] | **Yes** [19] | Yes (Mistral says one 16 GB GPU) [19] | Yes |
| **Aegis 1.0 guards** (NVIDIA, 2024) | Prompt + response | 13 categories [39] | 7B (LoRA on LlamaGuard-7b) | Needs the gated Meta LlamaGuard-7b base [39] | No | Older; superseded by the Nemotron guards above | |
| **PolyGuard** (CMU et al.) | Prompt, response, refusal, 17 languages [30] | | Qwen-based (size unverified) | Datasets CC-BY-4.0 [30] | No | Probably | Yes |

Also seen, not checked in detail: GLiGuard (300M encoder, Fastino) [48], DynaGuard-8B (user-defined
policies) [41], YuFeng-XGuard [49], OpenGuardrails [50]. **I found no evidence of a Llama Guard 5, a
ShieldGemma 3 or a Qwen3.5Guard** as of this search [48].

### 2b. API and system-level guardrails

| System | What it is | Input / output | Configurable? | Notes for PRIME |
|---|---|---|---|---|
| **OpenAI Moderation** (`omni-moderation-latest`) | Classifier API based on GPT-4o; 13 categories (harassment, hate, illicit, self-harm, sexual, violence and subcategories) [26] | Any text (so both), plus images for some categories [26] | No (per-category scores; you choose thresholds) | **Free**, subject to rate limits [26]. Cheap commercial reference point. Sends data to OpenAI. |
| **Google Cloud Model Armor** | Managed screening service: responsible-AI filters, prompt injection / jailbreak, sensitive data, malicious URLs [51] | **Separate input and output templates** [51] | Confidence thresholds per filter (High / Medium+ / Low+) [51] | Closest commercial analogue to PRIME's "policy plus input/output gate". Needs GCP billing; the owner is already on GCP. |
| **Azure AI Content Safety** | Hate, sexual, violence, self-harm at severity 0–7; Prompt Shields for jailbreak / indirect attacks; custom categories trained from examples [52] | Text (both) | Per-category severity thresholds; custom categories [52] | Needs an Azure account. |
| **Perspective API** (Jigsaw) | Toxicity scoring | Text | No | **Shuts down 31 Dec 2026** [53]. Do not use it as a baseline. |
| **NeMo Guardrails** (NVIDIA) | Open-source *framework*: Colang flows, input/output rails, "self-check" rails using any LLM, or Llama Guard / Nemotron as the checker [36][17] | Both | **Yes** (rails and prompts are configuration) | The closest **system-level** open-source peer to PRIME. NVIDIA reports Llama Guard rails beat self-check rails [36]. |
| **LLM-as-judge** | A general instruct model with a zero-shot safety prompt | Both | Yes (via the prompt) | GuardBench found a general instruct model of comparable size competitive with fine-tuned guards [34]. PRIME's judge *is* this, so a "plain judge, no policy layer" ablation is required. |

---

## 3. Benchmarks

"P" = prompt-level labels, "R" = response-level labels. "Gate" = access request on HF.

### 3a. Harmful prompt / response classification

| Benchmark | Size | Labels | Level | License / access | Notes |
|---|---|---|---|---|---|
| **WildGuardTest** [6][7] | Paper: 5,299 human-annotated items across 3 tasks. HF card: 1,725 items (**the counts conflict; check**) | Prompt harm, response harm, refusal; includes an adversarial (jailbreak) subset | P + R | Gate: automatic after accepting Ai2 terms [7] | The de facto standard for open guards since 2024. Qwen3Guard follows WildGuard's English settings [24]. |
| **Aegis 2.0 / Nemotron Content Safety v2** [16] | Paper: 34,248. HF release: 33,416 (30,007 / 1,445 / **1,964 test**) | 12 top-level categories + 9 fine-grained | P + R | CC-BY-4.0 (per HF card) | Commercially usable. Taxonomy differs from MLCommons. |
| **OpenAI Moderation eval** [28][3] | 1,680 prompts | 8 categories (S, H, V, HR, SH, S3, H2, V2), binary; some labels missing | P | MIT (repo) | Small and widely reported (ShieldGemma, Llama Guard). From 2022. |
| **ToxicChat** [29] | 10,165–10,166 real user prompts (version-dependent); about 7% toxic, about 2% jailbreak | Toxicity, jailbreaking | P | CC-BY-NC-4.0 (current card) | Real traffic and a low base rate, so AUPRC matters. Train/test split sizes not verified here. |
| **BeaverTails** [54] | 330k QA pairs (30k subset: 30,207) | 14 harm categories | R (QA pair) | CC-BY-NC-4.0 | Also used as guard training data, so contamination is likely. |
| **SALAD-Bench / MD-Judge** [55] | Not verified here | Hierarchical taxonomy | P + R | Not verified | MD-Judge is trained on BeaverTails, LMSYS and ToxicChat [55]. |
| **PolyGuardPrompts** [30] | About 29k | Prompt harm, response harm, refusal; 17 languages | P + R | CC-BY-4.0 | Only if multilingual claims matter. |
| **HarmBench classifier** [23] | 510 behaviours (standard / contextual / copyright / multimodal) | Its classifier `cais/HarmBench-Llama-2-13b-cls` grades completions | R (completion) | MIT | Later studies find the HarmBench judge agrees with human labels better than GPT-4 or LLM judges [56][57]. That makes it the right *grader* for PRIME's outputs. |
| **DynaBench** (DynaGuard) [41] | 40k user-defined policies with simulated conversations | Policy-violation labels | Dialogue | Not verified | **Tests policy-following.** One follow-up warns that DynaGuard overfits to its surface form [41]. |
| **CoSApien** (CoSA) [40] | Human-written safety configs plus evaluation prompts | CoSA-Score (helpfulness × config adherence) | System | Not verified | **Tests configurable safety at the system level.** Closest existing match to PRIME's claim. |

### 3b. Over-refusal

| Benchmark | Size | What it measures | License | Notes |
|---|---|---|---|---|
| **XSTest** [31] | 250 safe + 200 unsafe contrast prompts, 10 safe prompt types | Refusal of safe-but-scary prompts; responses labelled full compliance / full refusal / partial refusal (label scheme from the paper; I did not re-check it here) | CC-BY-4.0 (HF mirror) | Already in PRIME. Small; models saturate it. |
| **OR-Bench** [32] | 80k "seemingly toxic" prompts; **Hard-1K** subset; 600 toxic prompts | Over-refusal vs. toxic rejection, 10 categories | CC-BY-4.0 | Hard-1K is the usual choice. **Contamination risk** [45]. |
| **FalseReject** [38] | 16k queries, 44 categories; 1.1k human-annotated test set | Over-refusal; includes *structured reference responses* | Not verified | Its reference responses could help grade helpfulness. |
| **JailbreakBench benign** [25] | 100 benign twins of the harmful behaviours | Over-refusal by keyword-matching defences | MIT | Free if JailbreakBench is used. Contamination risk [45]. |

### 3c. Jailbreak robustness (system level)

| Benchmark | Size | Metric | License | Notes |
|---|---|---|---|---|
| **HarmBench** [23] | 510 behaviours; PRIME already uses 200 standard ones | ASR graded by the HarmBench classifier | MIT | Already in PRIME (direct requests only). Adding the 100 contextual behaviours is cheap. |
| **JailbreakBench** [25][58] | 100 harmful + 100 benign behaviours; **pre-generated jailbreak artifacts** (PAIR, GCG, etc.) | ASR (Llama-3-70B judge in the paper) | MIT | Ready-made attack prompts, **no attack compute needed**. Its judge agrees less with humans than HarmBench's or StrongREJECT's [57]. |
| **StrongREJECT** [27] | 313 forbidden prompts; about 38 jailbreak wrappers in later use | Score combining refusal and how specific / convincing the answer is; rubric (API LLM) or fine-tuned Gemma-2B evaluator | (check repo) | Shows that many jailbreaks yield "empty" low-quality answers. The Gemma-2B evaluator runs locally. |
| **WildJailbreak** [59] | 262k synthetic vanilla / adversarial, harmful / benign | Training set mostly; an eval split exists (unverified) | Gate (Ai2 terms) | Better as a source than as a headline benchmark. |
| **SORRY-Bench** [33] | 440 base unsafe instructions (44 categories) × 20 linguistic mutations (about 8.8k) | Fulfilment rate; fine-tuned 7B judge | Check HF (gated, unverified) | Good for mutation/encoding robustness of the *input* judge. |

### 3d. Aggregate suites

| Suite | What | Notes |
|---|---|---|
| **GuardBench** (Bassani & Sanchez, EMNLP 2024) [34][35] | 40 prompt and conversation safety datasets, 13 models evaluated; `pip install guardbench` | IBM reports Granite Guardian holding 6 of the top 10 places on its leaderboard (vendor claim) [13]. Plugging PRIME's judge in as a classifier gives broad coverage cheaply. **Don't confuse it** with a different 2025 preprint also called "GuardBench" (4,200 jailbreak prompts; ASR + FPR + P95 latency against GPT-4o-mini) [44]. |
| **TRACE** [60] | 18 guard models at prompt, reasoning-trace and response stages | Reports FNR and FPR separately. Finds ShieldGemma and LlamaGuard-2 over-refuse heavily [60]. |
| Vendor leaderboards (e.g. ModernGuard-1 card) [49] | Self-reported | Don't cite as independent. |

**I found no single, maintained, independent guard leaderboard covering both prompt and response
classification.** Papers each pick their own subset of the benchmarks above [49].

### 3e. Helpfulness of refusals / safe completion

| Work | What it offers | Usable for PRIME? |
|---|---|---|
| **OpenAI "From Hard Refusals to Safe-Completions"** (GPT-5) [37] | Output-centric safety: maximise helpfulness within policy. Rewards "informative refusal with safe alternatives". Reports that errors are less severe than with refusal training | Conceptual framing and grading criteria. Evaluations are internal, not released. **This is the closest prior work to PRIME's helpful refusals; cite it.** |
| **XSTest partial-refusal label** [31] | Three-way compliance label | A weak proxy only. |
| **FalseReject** [38] | Structured reference responses for borderline queries | Possible reference answers for a judge. |
| **CoSA-Score** [40] | Helpfulness only counts when the response follows the config | Good template for a "helpful **and** within policy" metric. |
| **HELP benchmark, RefusalBench, IHL refusal-explanation benchmark** [61] | Partial-credit helpfulness (0 / 0.5 / 1); explanation rates | Small, not established; judges often unvalidated [61]. |

**Bottom line:** no established benchmark scores *how good a refusal is*. PRIME should define a short
rubric, apply it with an LLM judge and validate it against about 100 human-rated items.

---

## 4. Metrics and protocol in the literature

**Standalone classifiers** (Llama Guard, ShieldGemma, WildGuard, Qwen3Guard papers):
- **F1 with "unsafe" as the positive class**, reported per benchmark and as an average, separately for
  prompt and response classification [6][24].
- **AUPRC**, threshold-free, for models with a probability output. ShieldGemma reports "Optimal F1 /
  AUPRC" [3]. Llama Guard reports F1, AUPRC and **false positive rate** [2]. Granite Guardian reports
  AUC / AUPRC / F1 [13].
- Threshold policy matters. Llama Guard takes P(unsafe) from the first token and thresholds it [2].
  Qwen3Guard is reported in strict *and* loose modes [18][24]. Papers differ on macro vs. unsafe-class
  F1 and on how they binarise outputs like "controversial", which breaks cross-paper comparisons
  [46][49].

**Systems (guard + protected model)**:
- **Attack success rate (ASR)**: the share of harmful behaviours whose *final* output a fixed grader
  calls harmful. Use HarmBench's classifier [23] or StrongREJECT's score [27]. JailbreakBench uses an
  LLM judge [25].
- **Over-refusal / false refusal rate** on safe prompts (XSTest safe, OR-Bench-Hard, JBB-benign), plus
  the **toxic-prompt refusal rate** so that refusing everything doesn't look ideal [31][32].
- **Latency overhead** (mean and P95) and number of extra model calls [44].
- Useful extra metric: the **pass-guardrail rate**, which separates blocks by the guard from refusals by
  the protected model [62]. PRIME's traces already allow this.
- Harness papers find trade-offs. In one layered-defence harness, stacking defences cut ASR from 35% to
  2.5% while false refusals rose from 0% to 15% [63] (GitHub project, not peer reviewed).

**Protocol consequence for PRIME.** Report both views:
1. **Classifier view.** Use PRIME's judge plus policy as a classifier: REFUSE (and REWRITE, reported
   both ways) = unsafe. The raw score gives AUPRC. Compare against guard models on the same labelled
   sets.
2. **System view.** Keep the same protected model (Zephyr-7B-beta), harness, grader, decoding settings
   and prompts, and change only the gate: none / guard X on input / guard X on input+output / PRIME.
   Every guard gets the same fixed refusal text unless the helpful-refusal feature is being tested.
   That way the comparison isolates *detection*, and PRIME's extra features are measured separately.

---

## 5. Recommended plan (small to medium, one T4/L4)

Prefer the **L4**: it fits every recommended model in fp16/bf16 one at a time. On a T4, use quantised
8B models or the smaller sizes.

### 5a. Baselines (pick 4, plus 1 optional)

| # | Baseline | Why | Cost / friction |
|---|---|---|---|
| 1 | **Llama Guard 3 8B** (1B on T4) | Most-cited guard; MLCommons taxonomy; input + output | **Request Meta access on HF now** (can be slow or denied). If refused, fall back to Qwen3Guard alone. |
| 2 | **ShieldGemma 9B** (2B on T4) | Owner asked for it; Google; policy-in-prompt | Instant license acknowledgement. Check fp16 numerics on the T4. |
| 3 | **WildGuard 7B** | Strong on WildGuardTest; also detects refusals (useful as a grader cross-check) | Auto-approved gate. |
| 4 | **Qwen3Guard-Gen-4B or -8B** | Recent state of the art, Apache-2.0, three-tier severity similar to PRIME's ALLOW/REWRITE/REFUSE | No gate (verify). Same family as PRIME's judge, so call that out. |
| 5 (opt.) | **One policy-following guard: gpt-oss-safeguard-20b** (L4 only, if vLLM runs it on Ada), else **Nemotron-Content-Safety-Reasoning-4B** or **Shieldstral 3B** | The direct competitor for the "configurable policy" claim | gpt-oss on L4 is uncertain [42]. The two 4B/3B options fit either GPU. |

Plus two cheap internal baselines that reviewers will expect:
- **Plain judge**: Qwen2.5-7B with a zero-shot "is this unsafe?" prompt and no policy layer, rewrite or
  topic rules. This is the ablation that shows what the "P" in PRIME adds.
- **OpenAI omni-moderation** (free) as a commercial reference on classifier benchmarks only, if sending
  benchmark prompts to OpenAI is acceptable. Model Armor is the better commercial analogue if a GCP
  budget allows.

### 5b. Benchmarks (5 core, 1 constructed)

| # | Benchmark | Track | What it shows |
|---|---|---|---|
| B1 | **WildGuardTest** (prompt + response) | Classifier | Detection quality vs. guards on the most standard set, including adversarial prompts |
| B2 | **OpenAI Mod + ToxicChat test** (or **Aegis 2.0 test** if a commercial-friendly license matters) | Classifier | Comparability with numbers already published for ShieldGemma and Llama Guard [2][3] |
| B3 | **HarmBench** (200 standard + 100 contextual), graded by the HarmBench classifier | System | Harm reaching the user: none vs. guard gates vs. PRIME |
| B4 | **JailbreakBench artifacts** (PAIR/GCG prompts) **or StrongREJECT** with a few wrappers | System | Robustness when the attack is in the prompt. **Tests the output gate**: jailbreaks that get past the input judge should be caught at the output. |
| B5 | **XSTest + OR-Bench-Hard-1K** (+ OR-Bench-toxic) | System + classifier | Over-refusal cost, especially for STRICT mode and topic rules |
| B6 | **Policy-switch set** (constructed; seed from CoSApien [40] or a DynaBench subset [41]) | System | **Configurable policy**: same prompts, 2–3 policies, check the decision follows the policy |

Optional breadth: run PRIME's judge through **GuardBench**'s library [35] for a 40-dataset table in the
appendix.

### 5c. PRIME's distinctive claims and how to test each

| Claim | Test | Metric | Fair comparator |
|---|---|---|---|
| **Configurable policy** (thresholds, per-topic rules, STRICT/LOOSE) | B6: for example, "Competitors: REFUSE" on vs. off, "Mental health: rewrite with helpline" on vs. off, a STRICT vs. LOOSE sweep on B3 + B5 | Policy-conditional accuracy (did the action match what the active policy says?); ASR / over-refusal trade-off curve as thresholds move | gpt-oss-safeguard / Nemotron-Reasoning / Shieldstral given the *same policy text*; Qwen3Guard strict/loose; Llama Guard with edited categories |
| **Output gate** catches what the input check misses | `output_only` and `input_output` conditions on B3 + B4 (jailbreak prompts get past input checks more often) | ASR(input) − ASR(input+output); share of harmful outputs caught only at the output stage; added latency | Llama Guard / WildGuard / Qwen3Guard used as response classifiers in the same position |
| **Helpful refusals** | All refusals from B3, B5-toxic and XSTest-unsafe, under `refusal_style: fixed` vs. `helpful` (and Zephyr's own refusals) | (1) **Leak rate**: HarmBench classifier on the refusal text. (2) **Helpfulness rubric** (names what it declines, offers a relevant safe alternative, no lecturing, factually correct), 1–5 or pairwise, by a judge from a different family. (3) About 100 items double-rated by humans; report agreement | Fixed refusal; Zephyr's own refusal; optionally a safety-tuned model's native refusal |
| **Low over-refusal at equal safety** | B3 + B5 across thresholds | ASR vs. over-refusal curve (one point per policy setting); report the operating point | All baselines at their default thresholds *and* at a threshold matched to PRIME's over-refusal rate |
| **Practical cost** | All system runs | Per-request P50/P95 latency added, extra calls per request | Single-pass guards |

### 5d. Rough effort

Classifier runs (B1, B2) are a few thousand short forward passes per guard. Each should take minutes on an
L4 with vLLM, with guards loaded one at a time (my estimate, not measured). System runs reuse the existing
harness: generations from the protected model can be **cached once per prompt** and re-gated by each
guard, so adding a baseline costs only its classification calls. Plan on about 1–2 GPU-days in total,
dominated by B4 and the helpful-refusal judging.

---

## 6. Pitfalls

1. **System vs. classifier.** PRIME has a rewrite path, topic rules and an output gate, so on system
   metrics it will "beat" a bare classifier for structural reasons. Put each baseline into the same
   harness in the same slots, and report classifier-track numbers separately.
2. **Taxonomy and label mismatch.** Each benchmark encodes its own definition of "unsafe". A NeurIPS 2026
   paper argues some safety benchmarks measure *which definition you trained on*, not capability [45].
   GuardSet-X makes a similar point about ad hoc taxonomies [47]. PRIME's categories (including
   Competitors and Geopolitical) don't map onto MLCommons, Aegis or OpenAI categories. Report binary
   safe/unsafe for headline numbers, publish the category mapping used, and don't count business-rule
   topics as "harm" on public benchmarks.
3. **Contamination.** XSTest, OR-Bench, JailbreakBench, BeaverTails and ToxicChat are widely used as
   training data. One paper found 88% of JBB-benign and 82% of OR-Bench-hard in guard training pools
   [45]. Baselines may look better than they generalise. Include at least one set the guards could not
   have trained on (PRIME's constructed policy-switch set; newer releases).
4. **Same family and self-grading.** PRIME's judge (Qwen2.5-7B) both writes and checks helpful refusals
   (DESIGN.md §5). Qwen3Guard shares the family. Use a grader from a different family (the HarmBench
   classifier is Llama-2-based) and human spot-checks. In one 2026 study, general instruct judges
   (including Qwen2.5-7B) agreed with human labels far less than the HarmBench classifier did [56][57]
   (search snippet; exact paper attribution unverified).
5. **Threshold choice.** Guard papers report F1 at their default threshold or at an "optimal" threshold
   tuned on the test set [3]. Fix thresholds on a dev split, and also report AUPRC. PRIME's judge scores
   are saturated (DESIGN.md P5), which will hurt AUPRC. Calibrate first (Option 5) or report it
   honestly.
6. **REWRITE is ambiguous.** In a binary comparison, REWRITE has to count as either "flagged" or
   "allowed". Report both, or, better, let the system track decide by grading the final output.
7. **Ceiling effects.** On HarmBench direct requests PRIME blocked 20/20 at the input check. Easy sets
   can't separate systems. Adversarial prompts (B4, WildGuardTest adversarial subset) and borderline sets
   (OR-Bench-Hard) are where differences show.
8. **Gating and licenses.** Llama Guard needs Meta approval. WildGuard, WildGuardTest and WildJailbreak
   need Ai2's form. ToxicChat and BeaverTails are non-commercial. Fine for a paper, but state it.
9. **Perspective API** shuts down at the end of 2026 [53]. Results with it would not be reproducible.
10. **Version drift.** Record exact model revisions and dataset versions. WildGuardTest (5,299 vs. 1,725),
    ToxicChat (10,165 vs. 10,166) and Aegis 2.0 (34,248 vs. 33,416) already have conflicting counts
    across sources [7][16][29].
11. **API baselines change silently.** `omni-moderation-latest` is an alias [26]. Pin the snapshot
    (`omni-moderation-2024-09-26`) and the run date.

---

## 7. Sources

Model cards and official docs
1. Mozilla any-guardrail, Llama Guard page (gating, licenses, LG4 not supported): https://docs.mozilla.ai/any-guardrail/api-reference/index/content-safety/llama-guard
2. Llama Guard 3 8B model card (14 categories, F1/AUPRC/FPR, first-token scoring), Azure/HF mirrors: https://ai.azure.com/catalog/models/Llama-Guard-3-8B , https://huggingface.co/mav23/Llama-Guard-3-8B-GGUF , https://ai.azure.com/catalog/models/Llama-Guard-3-1B
3. ShieldGemma model card (harm types, Optimal F1/AUPRC table, OpenAI Mod 1,680, ToxicChat 10k): https://ai.google.dev/gemma/docs/shieldgemma/model_card?hl=en ; paper https://arxiv.org/pdf/2407.21772
4. ShieldGemma on HF (Gemma license gate, instant acknowledgement): https://huggingface.co/google/shieldgemma-2b , https://huggingface.co/google/shieldgemma-2-4b-it
5. Llama Guard 4 12B model card (NVIDIA mirror) and Meta docs: https://build.nvidia.com/meta/llama-guard-4-12b/modelcard , https://developer.meta.com/ai/docs/model-cards-and-prompt-formats/llama-guard-4/
6. WildGuard paper (arXiv 2406.18495, NeurIPS 2024): https://arxiv.org/abs/2406.18495v3 , https://arxiv.org/html/2406.18495v1
7. WildGuard / WildGuardMix HF cards and Ai2 safety toolkit blog: https://huggingface.co/allenai/wildguard/blob/main/README.md , https://huggingface.co/datasets/allenai/wildguardmix/blob/main/README.md , https://allenai.org/blog/the-ai2-safety-toolkit-datasets-and-models-for-safe-and-responsible-llms-development-10abc05f6c80
8. ShieldGemma 2 model card: https://ai.google.dev/gemma/docs/shieldgemma/model_card_2?hl=en
9. Qwen3Guard Technical Report (arXiv 2510.14276) and HF cards: https://arxiv.org/abs/2510.14276v1 , https://huggingface.co/Qwen/Qwen3Guard-Stream-8B , https://huggingface.co/Qwen/Qwen3Guard-Gen-4B
10. Qwen3Guard blog and GitHub: https://qwenlm.github.io/blog/qwen3guard/ , https://github.com/QwenLM/Qwen3Guard
11. OpenAI, Introducing gpt-oss-safeguard (sizes, license, results, limitations): https://openai.com/index/introducing-gpt-oss-safeguard/ ; technical report https://cdn.openai.com/pdf/08b7dee4-8bc6-4955-a219-7793fb69090c/Technical_report__Research_Preview_of_gpt_oss_safeguard.pdf
12. gpt-oss-safeguard HF card and user guide: https://huggingface.co/openai/gpt-oss-safeguard-20b/blob/main/README.md , https://developers.openai.com/cookbook/articles/gpt-oss-safeguard-guide
13. IBM Granite Guardian docs, GuardBench blog, paper: https://www.ibm.com/granite/docs/models/guardian , https://research.ibm.com/blog/granite-guardian-tops-guardbench , https://arxiv.org/pdf/2412.07724
14. Granite Guardian 3.3 / 4.1 listings (license, BYOC, thinking mode): https://featherless.ai/models/ibm-granite/granite-guardian-3.3-8b , https://ollama.com/library/granite4.1-guardian , https://docs.mozilla.ai/any-guardrail/api-reference/index/granite-guardian
15. Llama-3.1-Nemotron-Safety-Guard-8B-v3 (23 categories, 9 languages, license): https://build.nvidia.com/nvidia/llama-3_1-nemotron-safety-guard-8b-v3/modelcard ; CultureGuard paper https://arxiv.org/pdf/2508.01710v3
16. Aegis 2.0 paper (NAACL 2025) and dataset card: https://arxiv.org/html/2501.09004v1 , https://aclanthology.org/2025.naacl-long.306 , https://huggingface.co/datasets/nvidia/Aegis-AI-Content-Safety-Dataset-2.0
17. Nemotron-Content-Safety-Reasoning-4B (custom policy, license) and NeMo Guardrails tutorial: https://build.nvidia.com/nvidia/nemotron-content-safety-reasoning-4b/modelcard , https://docs.nvidia.com/nemo/guardrails/latest/get-started/tutorials/nemotron-content-safety-reasoning-deployment
18. Qwen3Guard categories and strict/loose (third-party docs): https://docs.mozilla.ai/any-guardrail/api-reference/index/content-safety/qwen3-guard , https://www.alibabacloud.com/blog/602582
19. Mistral, Introducing Shieldstral; model card; cookbook: https://mistral.ai/news/shieldstral/ , https://docs.mistral.ai/models/model-cards/shieldstral-1-0 , https://docs.mistral.ai/resources/cookbooks/mistral-moderation-shieldstral_policy_moderation
20. Mistral legal page (release date): https://legal.mistral.ai/ai-governance/models/shieldstral/
21. Llama Guard 4 HF gating; access-denied anecdote: https://huggingface.co/meta-llama/Llama-Guard-4-12B , https://huggingface.co/spaces/huggingface/InferenceSupport/discussions/1886
22. Llama Guard paper (taxonomy as input, zero/few-shot) and custom-category discussions: https://arxiv.org/abs/2312.06674v1 , https://huggingface.co/meta-llama/Meta-Llama-Guard-2-8B/discussions/17 , https://huggingface.co/meta-llama/Meta-Llama-Guard-2-8B/discussions/9

Benchmarks
23. HarmBench (arXiv 2402.04249): https://arxiv.org/pdf/2402.04249
24. Qwen3Guard report tables (English settings follow WildGuard; strict/loose): https://arxiv.org/html/2510.14276v1
25. JailbreakBench (NeurIPS 2024 D&B) and dataset card: https://www.arxiv.org/pdf/2404.01318 , https://huggingface.co/datasets/JailbreakBench/JBB-Behaviors/raw/main/README.md
26. OpenAI moderation guide, model page, omni-moderation announcement: https://platform.openai.com/docs/guides/moderation , https://developers.openai.com/api/docs/models/omni-moderation-latest , https://openai.com/index/upgrading-the-moderation-api-with-our-new-multimodal-moderation-model/
27. StrongREJECT paper and BAIR blog: https://arxiv.org/abs/2402.10260 , https://bair.berkeley.edu/blog/2024/08/28/strong-reject/ , https://aimslab.stanford.edu/measurement-db/strongreject
28. OpenAI moderation eval set and paper: https://github.com/openai/moderation-api-release , https://arxiv.org/pdf/2208.03274
29. ToxicChat paper and card: https://arxiv.org/pdf/2310.17389 , https://huggingface.co/datasets/lmsys/toxic-chat/blob/main/README.md
30. PolyGuard (COLM 2025): https://arxiv.org/abs/2504.04377v2 , https://huggingface.co/datasets/ToxicityPrompts/PolyGuardMix/blob/main/README.md
31. XSTest (NAACL 2024) and HF mirror: https://aclanthology.org/2024.naacl-long.301 , https://arxiv.org/abs/2308.01263v3 , https://huggingface.co/datasets/walledai/XSTest
32. OR-Bench (ICML 2025): https://arxiv.org/html/2405.20947v5 , https://huggingface.co/datasets/bench-llm/or-bench/raw/main/README.md
33. SORRY-Bench (ICLR 2025): https://arxiv.org/abs/2406.14598 , https://sorry-bench.github.io
34. GuardBench (EMNLP 2024): https://aclanthology.org/2024.emnlp-main.1022
35. guardbench Python package: https://pypi.org/project/guardbench/
36. NeMo Guardrails Llama Guard integration / self-check rails: https://docs.nvidia.com/nemo/guardrails/latest/user-guides/community/llama-guard.html , https://docs.nvidia.com/nemo/guardrails/
37. OpenAI safe-completions (blog + arXiv 2508.09224): https://openai.com/index/gpt-5-safe-completions , https://arxiv.org/pdf/2508.09224
38. FalseReject: https://arxiv.org/html/2505.08054v2 , https://false-reject.github.io
39. Aegis 1.0 (arXiv 2404.05993) and models: https://arxiv.org/html/2404.05993v1 , https://huggingface.co/nvidia/Aegis-AI-Content-Safety-LlamaGuard-Defensive-1.0
40. Controllable Safety Alignment / CoSApien / CoSA-Score (ICLR 2025): https://arxiv.org/abs/2410.08968
41. DynaGuard / DynaBench (ICLR 2026) and follow-ups: https://arxiv.org/abs/2509.02563v3 , https://iclr.cc/virtual/2026/poster/10008138 , https://arxiv.org/pdf/2605.17329 , https://arxiv.org/pdf/2609.34241
42. vLLM gpt-oss support (Ampere/Ada status, MXFP4 size) and T4 forum thread: https://docs.vllm.ai/projects/recipes/en/latest/OpenAI/GPT-OSS.html , https://vllm.ai/blog/2025-08-05-gpt-oss , https://discuss.vllm.ai/t/build-issues-when-serving-gpt-oss-20b-on-tesla-t4-gpus-with-vllm/1673 , https://developers.openai.com/cookbook/articles/gpt-oss/run-vllm
43. WildGuard HF gate: https://huggingface.co/allenai/wildguard/tree/main

Evaluation methodology and critiques
44. "GuardBench: A Systematic Framework…" preprint (ASR, FPR, P95 latency): https://www.preprints.org/frontend/manuscript/9d4a3653e225ac55ef126da714bc0eed/download_pub
45. "Policy Is Not Capability: Some Safety Benchmarks Measure Which Definition of 'Unsafe' You Trained On" (NeurIPS 2026): https://neurips.cc/virtual/2026/178203
46. Robustness of guardrails against adversarial attacks (label mapping, contamination): https://arxiv.org/abs/2511.22047v1
47. GuardSet-X (policy-grounded benchmark; ad hoc taxonomies): https://arxiv.org/html/2506.19054v2
48. any-guardrail tracking issue (June 2026 open guard sweep; GLiGuard; LG4 latest): https://github.com/mozilla-ai/any-guardrail/issues/179
49. Recent guard comparisons (YuFeng-XGuard; LLaDA-Guard table; vendor ModernGuard card): https://arxiv.org/pdf/2601.15588 , https://arxiv.org/pdf/2609.33634 , https://huggingface.co/guardion/ModernGuard-1
50. OpenGuardrails: https://arxiv.org/pdf/2510.19169
51. Google Cloud Model Armor overview: https://docs.cloud.google.com/model-armor/overview
52. Azure AI Content Safety harm categories / custom categories: https://learn.microsoft.com/en-au/Azure/ai-services/content-safety/concepts/harm-categories , https://azure.microsoft.com/products/ai-services/ai-content-safety
53. Perspective API shutdown notice: https://perspectiveapi.com/
54. BeaverTails (NeurIPS 2023) and card: https://arxiv.org/pdf/2307.04657 , https://huggingface.co/datasets/PKU-Alignment/BeaverTails/blob/main/README.md
55. SALAD-Bench / MD-Judge: https://arxiv.org/pdf/2402.05044
56. Judge agreement studies (HarmBench judge highest κ vs. humans): https://arxiv.org/html/2511.06396v3
57. Jailbreak-evaluator measurement studies (HarmBench / StrongREJECT vs. JailbreakBench agreement; LLM-judge accuracy): https://arxiv.org/pdf/2609.10594 , https://arxiv.org/pdf/2606.25487
58. JailbreakBench artifacts repo: https://github.com/JailbreakBench/jailbreakbench
59. WildTeaming / WildJailbreak: https://arxiv.org/abs/2406.18510 , https://huggingface.co/datasets/allenai/wildjailbreak
60. TRACE benchmark (18 guards, prompt/trace/response): https://arxiv.org/pdf/2608.24232
61. Refusal-helpfulness work (HELP benchmark; IHL refusal explanations; RefusalBench summary): https://aclanthology.org/2025.findings-ijcnlp.7.pdf , https://pith.science/paper/2506.06391 , https://www.emergentmind.com/topics/refusalbench
62. HE-Guardrail (pass-guardrail rate, latency overhead, false rejection): https://arxiv.org/pdf/2609.21484
63. llm-guardrail-eval harness (layered defences: ASR vs. false-refusal trade-off; not peer reviewed): https://github.com/JohnsonManuel/llm-guardrail-eval
