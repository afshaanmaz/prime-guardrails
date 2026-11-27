# Risk sensors: what trained safety classifiers take in and return, and a common format for PRIME

Status: research note, 27 Nov 2026. Purpose: choose an input/output format for PRIME's risk sensor (R) that
works for a prompted LLM **and** for trained safety classifiers, so R is swappable. Sources at the end. Details
taken from model cards and vendor docs via search; anything not confirmed is marked "(unverified)".

## 1. What existing safety classifiers return

| Classifier | Checks | Policy input | Verdict | Categories | Graded signal |
|---|---|---|---|---|---|
| **Llama Guard 3 / 4** (Meta) | prompt or response (last turn) | Category list in its prompt (editable) | `safe` / `unsafe` (first line) | Violated codes, e.g. `S1,S10` (MLCommons hazards + extras) | None in the text; P(unsafe) can be read from the first token's probability |
| **Qwen3Guard-Gen** (Alibaba) | prompt or response | Fixed taxonomy | **`Safe` / `Controversial` / `Unsafe`** (three levels) | 9 categories (Violent, Non-violent Illegal, Sexual, PII, Self-harm, Unethical, Politically Sensitive, Copyright, None) | Also a `Refusal: Yes/No` line for responses |
| **ShieldGemma** (Google) | prompt or response | **One written policy per call** | `Yes` / `No` (violates the policy?) | One per call (the policy asked about) | **P(Yes)**, scoring mode, designed for thresholds |
| **Granite Guardian** (IBM) | prompt, response, RAG, tools | Built-in risks or **"bring your own criteria"** | `Yes` / `No` | The risk asked about | **Probability of risk**; users set thresholds |
| **WildGuard** (Ai2) | prompt + response | Fixed | `Harmful request: yes/no`, `Harmful response: yes/no` | No | Also `Response refusal: yes/no` |
| **Nemotron Safety Guard** (NVIDIA) | prompt + response | Taxonomy in its prompt | JSON: `"User Safety": safe/unsafe`, `"Response Safety"` | `"Safety Categories"` list | None |
| **gpt-oss-safeguard** (OpenAI) | anything | **A full written policy** at runtime | Whatever the policy asks for (e.g. `{"violation": 0/1}`) | As the policy defines | Optional; **reasoning** returned separately |
| OpenAI Moderation API | text, images | Fixed | `flagged` (boolean) | Per-category booleans | **`category_scores` 0-1 per category** ("signals for your policy") |
| Azure AI Content Safety | text, images | Fixed (4 harm categories) | none (the app decides) | Per category | **Severity 0-7** (or 0/2/4/6) |
| Amazon Bedrock Guardrails | prompt and response | Configurable filters, denied topics | `BLOCKED` / `NONE`, decided by **the strength you configure** | Per category | **Confidence: NONE / LOW / MEDIUM / HIGH** |
| Google Model Armor | prompt and response | Configurable filters | Match / no match at **your chosen threshold** | Per category | **Confidence: LOW / MEDIUM / HIGH** |

## 2. The pattern
Almost every system returns the same three things:
1. **A verdict:** mostly safe / unsafe; Qwen3Guard adds a middle level, "Controversial".
2. **Which categories:** a list of category IDs, from the model's own taxonomy or a policy you supply.
3. **A graded signal:** a probability (ShieldGemma, Granite, Llama Guard via token probability, OpenAI scores),
   a confidence tier (Bedrock, Model Armor) or a severity level (Azure).

And **the application, not the classifier, turns that into an action:** Bedrock's configured "filter
strength", Model Armor's threshold, Azure's severity cut-off, OpenAI's "scores are signals for your policy".
**That's exactly PRIME's split:** R senses, the policy and I decide. Industry practice supports keeping them separate.

Two further observations:
- **Confidence and severity are different things.** Confidence means "how sure is it that this is a
  violation" (Bedrock, Model Armor, probabilities). Severity means "how bad is it" (Azure). PRIME's 0-1
  "risk score" blends the two, which is part of why it's hard to calibrate.
- **Scores from classifiers are calibrated; scores an LLM writes as text are not.** Where trained guards give
  a probability, it comes from the model's token probabilities, not from the model writing a number.

## 3. Where a prompted LLM fits
A prompted general-purpose LLM is a **zero-shot, policy-reading guard**: the same category as
gpt-oss-safeguard, ShieldGemma or Granite's "bring your own criteria", without the safety training.
- **Strengths:** reads any written policy (industry-specific later); can say *why* and infer *intent*,
  which the intervention step can use.
- **Weaknesses:** numbers it writes are not calibrated (our pilot, M0 and M0b: round values that shift
  with wording); slower (~3.5 s vs 0.13 s for Qwen3Guard-0.6B on our T4).
- **Implication:** an LLM risk sensor should return **categorical** answers (verdict, categories, tier), like
  the classifiers above, not a written float. If a probability is wanted, take it from the token
  probabilities of its verdict, as Llama Guard and ShieldGemma do (vLLM can return these).

## 4. A common format for PRIME's risk sensor

**Input:** the request (and, later, the response), plus the policy's categories, each with a definition and
"unsafe / borderline / safe-even-though-related" boundaries.

**Output (one format for every risk sensor):**
```json
{"verdict":     "safe | borderline | unsafe",
 "categories":  ["Hate"],                  // policy category IDs
 "confidence":  "low | medium | high",     // or null
 "probability": 0.87,                      // P(unsafe) if the sensor provides one, else null
 "severity":    "limited | severe",        // when unsafe, else null
 "rationale":   "...", "intent": "...",    // LLM sensors only, else null
 "sensor":      {"name": "...", "version": "..."},
 "raw":         "<the sensor's native output, kept for audit>"}
```

**Decision (P + I, plain code):** a policy table on verdict × category. Default: safe → ALLOW,
borderline → REWRITE, unsafe → REFUSE. Topic rules override per category. Optional per-category thresholds on
`probability` or `confidence`, like Bedrock's filter strength, for sensors that provide them. Strict vs Loose
becomes a different table (e.g. Strict: borderline → REFUSE).

**Why three levels:** PRIME's graduated response needs a middle level. Qwen3Guard has one natively, and any
binary guard with a probability or confidence tier can produce one with two cut-offs. So three levels is the
common denominator that keeps REWRITE meaningful across sensors.

**Adapters (how each sensor fills the format):**
| Sensor | verdict | categories | probability / confidence |
|---|---|---|---|
| Prompted LLM (ours) | asked directly (3 levels) | policy IDs, asked directly | confidence tier asked directly; optional P(unsafe) from token probabilities |
| Qwen3Guard | Safe / Controversial / Unsafe → safe / borderline / unsafe | map its 9 categories to policy IDs | (none) |
| Llama Guard | safe/unsafe + P(unsafe) from the first token, two cut-offs → 3 levels | map S-codes | P(unsafe) |
| ShieldGemma / Granite | P(Yes) per policy category; max over categories, two cut-offs | the category asked | probability |
| WildGuard / Nemotron | binary → safe / unsafe (no middle level without probabilities) | Nemotron: map names | (none, or token probability) |
| Bedrock / Model Armor | LOW → borderline, MEDIUM/HIGH → unsafe (or as the policy maps) | per filter | confidence tier |
| Azure | severity 0-1 → safe, 2-3 → borderline, 4+ → unsafe | per category | severity |

## 5. Recommendation
1. Adopt this output format for R now. Our prompted LLM returns `verdict`, `categories`, `confidence`,
   `severity`, `rationale` and `intent`, and **no written score**.
2. Move the decision to a verdict × category table in the policy (thresholds become optional, for sensors with
   probabilities). The audit property is unchanged: the action is a deterministic function of the logged
   sensor output and the policy.
3. Put specific category boundaries (unsafe / borderline / safe-even-though-related) in the policy file, so
   the LLM risk sensor knows where the lines are.
4. Later (backlog): a Qwen3Guard adapter as the first trained sensor; token-probability scores for the LLM sensor.

## Sources
- Llama Guard 4 model card and prompt format: https://www.llama.com/docs/model-cards-and-prompt-formats/llama-guard-4/ ; Llama Guard 3: https://www.llama.com/docs/model-cards-and-prompt-formats/llama-guard-3/ ; Cloudflare schema: https://developers.cloudflare.com/ai/models/%40cf/meta/llama-guard-3-8b/index.md
- Qwen3Guard: https://qwenlm.github.io/blog/qwen3guard ; https://huggingface.co/Qwen/Qwen3Guard-Gen-0.6B ; https://arxiv.org/html/2510.14276v1 ; https://docs.mozilla.ai/any-guardrail/api-reference/index/content-safety/qwen3-guard
- ShieldGemma model card: https://ai.google.dev/gemma/docs/shieldgemma/model_card
- Granite Guardian: https://arxiv.org/html/2412.07724v2 ; https://www.ibm.com/fr-fr/granite/docs/models/guardian
- WildGuard: https://huggingface.co/allenai/wildguard ; https://github.com/allenai/wildguard
- Nemotron Safety Guard prompt template: https://docs.nvidia.com/nim/llama-3-1-nemotron-safety-guard-8b/latest/prompt-template.html ; model card: https://build.nvidia.com/nvidia/llama-3_1-nemotron-safety-guard-8b-v3/modelcard
- gpt-oss-safeguard guide: https://developers.openai.com/cookbook/articles/gpt-oss-safeguard-guide
- OpenAI Moderation API: https://developers.openai.com/api/reference/resources/moderations
- Azure AI Content Safety harm categories and severity: https://learn.microsoft.com/en-au/Azure/ai-services/content-safety/concepts/harm-categories
- Amazon Bedrock Guardrails content filters: https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-content-filters-overview.html ; https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_GuardrailContentFilter.html
- Google Model Armor overview: https://docs.cloud.google.com/model-armor/overview
