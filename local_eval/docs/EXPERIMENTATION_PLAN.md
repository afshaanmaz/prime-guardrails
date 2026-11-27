# PRIME experimentation plan (live)

A running log: **problem → experiment → result → next step.** Newest entries at the bottom of the log.
The proposed flow at the top is updated whenever a run changes the picture. All times are **Pacific (PST)**.
Supersedes `EXPERIMENT_PLAN.md` (pre-V1). Decisions: `DECISIONS.md`. Claims: `NARRATIVE.md`.

---

## Proposed flow (as of Thu 26 Nov, 8:15 pm PST)

Goal for this session: **one full run on several protected models** with frozen PRIME code, then the
paper's results.

| # | Step | Why | Status |
|---|---|---|---|
| 1 | **M0b:** does the MEDIUM band bring REWRITE back? (40 pilot requests + 50 OR-Bench borderline) | REWRITE vanished in M0; graduated response is a core claim | **Running** (started 8:07 pm) |
| 2 | **Fix any red flags from M0b, then freeze the V1 config** (tag the commit) | Main runs need fixed code | Pending M0b |
| 3 | **Engineering for multi-model runs** (small): (a) compute PRIME's decisions once per request and reuse them for every protected model; (b) serve each protected model alone on the GPU (4-bit where needed); (c) higher concurrency for quality runs (latency comes from the dedicated benchmark) | PRIME's risk sensor and intervention only see the request, so its decisions don't depend on the protected model. Reusing them is faster and makes the comparison across models exact | Not started |
| 4 | **Main run, 3-4 open-weight protected models from different providers × {model alone, model + PRIME}** on full HarmBench (200) + full XSTest (450) + OR-Bench-Hard (sample now; full 1K later) | The core claims: does PRIME help, at what cost, and on which models | Not started |
| 5 | **Evaluator (Llama 4 Maverick) on all pairs**, then reports and side-by-sides per model | Quality and over-refusal labels | Not started |
| 6 | **Guard-alone baseline** (Qwen3Guard on each request → stock refusal, else the model-alone answer; no new generation) | Is steering better than block-or-allow? | Not started |
| 7 | **Offline policy re-application** (LOOSE / STRICT / topic rules) on logged scores; **decision re-derivation check** | Configurability and auditability claims, no GPU | Not started |
| 8 | **Latency summary** for the paper from the latency benchmark plus per-request timings | Characterize, not claim, latency | Data exists |

**Protected models: open-weight only, several providers** (decided 8:35 pm, from the side-chat discussion; D17)
Gemini is dropped: its platform filters can't be fully turned off without an exception from Google, and
they confound results (the August paper saw 73-89% suppression, varying between runs). Open-weight models
served with vLLM have no provider filters, so the only safety is what's trained into the weights, which
is exactly what we want to measure.

| Family | Model | Gated? | Fits the T4 (protected model alone, using decision reuse) | Status |
|---|---|---|---|---|
| Mistral-based | Zephyr-7B-beta (AWQ), weak safety tuning | No | Yes | In use |
| Microsoft | Phi-3.5-mini-instruct (3.8B) | No | Yes (fp16) | Proposed for today |
| IBM | Granite 3.3 8B Instruct | No | With 4-bit quantization (to verify on the VM) | Proposed for today |
| Google | Gemma 2/3 (e.g. 9B, 4-bit) | **Yes (needs HF token)** | Yes | After the token is set up |
| Meta | Llama 3.x 8B | **Yes (needs HF token)** | Yes | Risk sensor only, or score with a second evaluator (the Maverick evaluator is also Llama) |
| OpenAI | gpt-oss-20b | No | Probably needs an L4 and a newer vLLM | Later |

**Roles (D18):**
- **Protected model:** rotate across 3-4 families. That's the main axis, and the basis for the generality claim.
- **Evaluator:** one fixed evaluator (Llama 4 Maverick) for all main results. Check it by re-scoring about 100 pairs with a second evaluator from another family, reporting agreement and any bias toward its own family.
- **Risk sensor:** fixed for the main results (Qwen2.5-7B). Rotating it is an ablation: a protected model × risk sensor grid (e.g. 3 × 2) shown as a heat map. Cheap, because PRIME's decisions depend only on the request and the risk sensor.
- **Constraint:** the evaluator must differ from the protected model's family. The risk sensor may share a family with the protected model (it never sees the model's output).

**Hugging Face token** (unlocks Llama, Gemma, Llama Guard, ShieldGemma), steps for the user:
1. Create a **read-only, fine-grained** token on Hugging Face. Never paste it in chat.
2. In Cloud Shell: `printf %s "<token>" | gcloud secrets create hf-token --data-file=- --project afshaan-trial-1`.
3. Accept each gated model's license on Hugging Face (Meta's approval can take time, or be refused).
4. Then, from the main thread: give the VM's service account read access to that one secret, and the VM
   permission to call Secret Manager (a settings change while the VM is stopped). Jobs fetch the token at runtime.

**Not blocking (backlog, in `DECISIONS.md`):** Pattern 2 / trained guard as R (Q21), streaming and
TTFT/TTLT metrics, protected-model-written refusals (Q6), industry policies (Q20), NeMo head-to-head,
our own authored tuning set, full OR-Bench, human ratings (Q13).

**Open items not yet decided or backlogged:**
- Second evaluator for the ~100-pair check: which model (must differ from the protected models' families).
- Final dataset sizes: full HarmBench + full XSTest; how much of OR-Bench today.
- When to tag the V1 freeze: after M0b.
- Evaluator check: the human spot-check (about 30 pairs) and when.

**Known weak spots in the code and setup:**
- The VM's console sometimes stops showing job progress (jobs still run). Monitoring now records
  progress in the bucket and BigQuery.
- Spot T4 capacity can disappear; `run-job.sh` recreates the VM elsewhere if a restart fails.
- The evaluator under-uses the "over-refusal" label (still seen in M0).
- The risk sensor still mis-scored "kill" in three harmless prompts in M0 (targeted in M0b).

---

## Log

### Wed 25 Nov, 11:20 pm: GPU availability
- **Problem:** No L4 GPUs could be started in the US.
- **Experiment:** A one-pass check across regions (`infra/create-gpu-vm.sh`), then T4, then Spot T4.
- **Result:** Standard L4 and T4 were unavailable in every US region. A Spot T4 was available in us-central1-c.
- **Next:** Use a Spot T4 (`prime-lab-t4`).

### Thu 26 Nov, 12:51 am: smoke run (20 HarmBench, older harness): `results/20261126-084321`
- **Problem:** Does anything run end to end on a real GPU? Does the protected model comply on its own?
- **Result:** Zephyr complied with 16 of 20 harmful requests. PRIME's input check refused all 20, with a fixed "I can't help" sentence.
- **Next:** Redesign PRIME to V1 (one risk call; intervention only for REWRITE or REFUSE; evaluator LLM).

### Thu 26 Nov, 2:55 am: V1 pilot (40 requests): `results/20261126-104223`
- **Problem:** Does V1 add value over the model alone?
- **Result:** HarmBench harmful answers went from 9/10 to 0/10. But the model alone won overall (17 vs 10, after correcting evaluator errors). The risk sensor flagged 11 of 17 harmless prompts on words like "kill" or "Jewish". Refusals were terse (19-46 words). Review: `PILOT_REVIEW.md`.
- **Next:** Fix refusal quality (D12) and risk sensor calibration (D14).

### Thu 26 Nov, ~4:30 am: latency benchmark: `results/latency-20261126-114207`, `LATENCY.md`
- **Problem:** Is PRIME low latency?
- **Result:** Not as is: the risk sensor takes 3.45 s (7B LLM) vs 0.13 s for a trained guard (Qwen3Guard 0.6B). Allowed requests wait about 3.5 s before any output.
- **Next:** Latency is characterized, not claimed. The trained-guard risk sensor (Pattern 2) is in the backlog.

### Thu 26 Nov, 7:53 pm: M0 (same 40 requests; policy-driven, intent-calibrated risk sensor + refusal v2): `results/20261127-034213`
- **Problem:** Do the risk sensor and refusal fixes work?
- **Result:** Clear improvement. Evaluator preferred PRIME / tie / model alone: 16 / 16 / 8, vs 12 / 11 / 17 in the pilot. Harmless prompts flagged: 3/17, vs 11/17. HarmBench stayed 9→0. Refusals were 52-126 words, none opening "I can't assist". **But REWRITE disappeared (0 of 40):** scores went bimodal (0.0 or 0.8-0.9). Three "kill" prompts (Python process, Call of Duty, lights) were still refused. PRIME's median added time rose from 5.0 s to 6.3 s, because refusals are longer. In-sample: these are the tuning items.
- **Next:** Give the MEDIUM band a concrete definition and add borderline prompts (D16), as M0b.

### Thu 26 Nov, 8:07 pm: M0b (40 pilot + 50 OR-Bench-Hard borderline; MEDIUM band): running
- **Problem:** REWRITE vanished in M0.
- **Experiment:** Concrete LOW / MEDIUM / HIGH bands, with two questions before scoring. Adds 50 borderline prompts.
- **Result:** (pending)
- **Next:** (pending)

### Thu 26 Nov, 8:35 pm: protected models and roles (decision, from the side-chat discussion)
- **Problem:** Running only Zephyr can't support a generality claim, and Gemini's platform filters would confound results.
- **Decision:** Open-weight protected models from several providers (D17), with fixed evaluator and risk sensor for main results, and rotation as ablations (D18). The HF token goes in Secret Manager for the gated models.
- **Next:** Zephyr + Phi-3.5-mini + Granite 3.3 8B today (all ungated); Gemma once the token is set up.
