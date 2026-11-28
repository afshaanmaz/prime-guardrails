"""PRIME guardrails on local models (V1, text).

PRIME = Policy, Risk, Intervention, Monitoring, Evaluation. Ported from
bhagwat-shubham/prime-guardrails to OpenAI-compatible local servers. Per request:

  P  Policy:        one declarative policy (config.yaml): categories with unsafe / borderline / safe
                    definitions, an action table per mode, the always-refuse floor, canned refusals,
                    per-topic rules. Every module reads it.
  R  Risk:          the risk sensor (risk.py) MEASURES the request against the policy's categories and
                    returns a RiskSignal: level (low / medium / high) + category (+ raw, for audit).
                    It never decides.
  I  routing:       plain code applies the policy to the signal (Policy.decide): ALLOW / REWRITE / REFUSE.
  I  Intervention:  ALLOW   -> the protected model gets the original request.
                    REWRITE -> one Intervention call rewrites the REQUEST into the nearest legitimate
                               request; the protected model answers the rewrite (silently).
                    REFUSE  -> the category's canned refusal from the policy; no model call. (An
                               LLM-written refusal is available as `policy.refusal: generated`, an ablation.)
  M  Monitoring:    every Trace records the original request, the risk signal, the action, the rewrite or
                    refusal, errors and per-step latency.
  E  Evaluation:    run.py (model alone vs model + PRIME), evaluate.py (evaluator LLM), report.py.

Errors are not risk judgments. If the risk sensor fails (after retries), the trace's action is ERROR
with error_stage/error_type, and the user gets the policy's `on_sensor_error` fallback. Code bugs are
not caught: they raise. Design: docs/RISK_SENSOR_REDESIGN.md; decisions: docs/DECISIONS.md.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field, asdict

from risk import RiskSensor, RiskSignal, SensorError, _is_transient

ACTIONS = ("ALLOW", "REWRITE", "REFUSE")
LEVELS = ("low", "medium", "high")
STRICTNESS = {"ALLOW": 0, "REWRITE": 1, "REFUSE": 2}

# I (steer): rewrite the request into the nearest legitimate request. Reads the same definition of harm
# as R (the category's unsafe / safe text), so the three steps agree on what to remove and what to keep.
REWRITE_REQUEST = """You are the intervention step of a guardrail system. The USER REQUEST below was judged
{level} risk{category_note}. Likely intent: {intent}.{definition}{instruction}

USER REQUEST:
<<<
{prompt}
>>>

Rewrite the request so a downstream model produces a safe and genuinely useful result:
- keep the user's legitimate goal and as much of their wording as possible;
- remove or reframe only what could lead to harmful output (what the policy calls unsafe above);
- steer toward the nearest version the policy treats as safe; where useful, ask for safety, legal or
  support information;
- write it as the user's own request; it must make sense on its own to a model that never sees
  the original.

Return only the rewritten request."""

# I (respond), ablation only (`policy.refusal: generated`): an LLM-written contextual refusal.
REFUSAL = """You are the intervention step of a guardrail system. The USER REQUEST below was declined
({level} risk{category_note}). Likely intent: {intent}.{instruction}

USER REQUEST:
<<<
{prompt}
>>>

Write the reply the user will see. Be warm, direct and genuinely useful: a knowledgeable person who won't
help with the harmful part but does want to help the person.
- Say clearly what you won't help with, in your own words. Do not open with "I can't assist with that request".
- Briefly explain why, in a sentence or two, without moralizing.
- Then give real, specific help for any legitimate need behind the request: safe information, lawful
  alternatives, or where to get qualified help. Give that help directly. Never just offer it.
- If the request involves self-harm, or someone may be in danger, respond with care and include a crisis
  resource (for example, in the US call or text 988; in an emergency call 911).
- Do NOT include instructions, steps, ingredients, code, names of methods, or persuasive or hateful text
  that would help with the declined request, even partially or "hypothetically".

Return only the reply."""

GENERIC_REFUSAL = "I can't help with that request, but I'm happy to help with a related question."


class PolicyError(ValueError):
    """The policy file is inconsistent (raised at load time, never per request)."""


@dataclass
class Policy:
    """P in PRIME: the declarative policy. `decide()` is the deterministic routing rule that the
    Intervention step (I) applies: plain code, so every action can be re-derived from the logged
    signal + policy."""
    name: str = "general"
    categories: dict = field(default_factory=dict)
    mode: str = "STRICT"
    actions: dict = field(default_factory=lambda: {"STRICT": {"low": "ALLOW", "medium": "REWRITE", "high": "REFUSE"}})
    always_refuse: list = field(default_factory=list)
    on_sensor_error: str = "REFUSE"
    refusal: str = "template"
    topics: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.categories:
            raise PolicyError("policy.categories is empty")
        if self.mode not in self.actions:
            raise PolicyError(f"policy.mode {self.mode!r} has no table in policy.actions {list(self.actions)}")
        for mode, table in self.actions.items():
            if set(table) != set(LEVELS) or any(a not in ACTIONS for a in table.values()):
                raise PolicyError(f"policy.actions.{mode} must map exactly {LEVELS} to {ACTIONS}: {table}")
        for name in self.always_refuse:
            if name not in self.categories:
                raise PolicyError(f"always_refuse names unknown category {name!r}")
        for name, rule in self.topics.items():
            if name not in self.categories:
                raise PolicyError(f"topic rule for unknown category {name!r}")
            if rule.get("action") not in ACTIONS:
                raise PolicyError(f"topic {name!r}: action must be one of {ACTIONS}")
        if self.on_sensor_error not in ("REFUSE", "ALLOW"):
            raise PolicyError("policy.on_sensor_error must be REFUSE or ALLOW")
        if self.refusal not in ("template", "generated"):
            raise PolicyError("policy.refusal must be template or generated")

    @property
    def table(self) -> dict:
        return self.actions[self.mode]

    def decide(self, level: str, category: str | None) -> tuple[str, str, str | None, str | None]:
        """Returns (action, decided_by, topic_rule_name, topic_instruction).
        decided_by: "table" | "floor" (always_refuse at high) | "topic" (a topic rule made it stricter).
        A topic rule can only make the action stricter, never looser."""
        if level not in LEVELS:
            raise ValueError(f"level must be one of {LEVELS}, got {level!r}")
        if level == "high" and category in self.always_refuse:
            return "REFUSE", "floor", None, None
        action = self.table[level]
        rule = self.topics.get(category or "")
        if rule and STRICTNESS[rule["action"]] >= STRICTNESS[action]:
            return rule["action"], "topic", category, rule.get("instruction")
        return action, "table", None, None

    def refusal_text(self, category: str | None) -> str:
        d = self.categories.get(category or "")
        return (d.get("refusal") if isinstance(d, dict) else None) or GENERIC_REFUSAL

    def definition_text(self, category: str | None) -> str:
        """The category's definition, for the rewrite step (the same text R read)."""
        d = self.categories.get(category or "")
        if not isinstance(d, dict):
            return ""
        if "about" in d:
            return f"\nPolicy topic {category}: {d['about']}"
        parts = [f"{k}: {d[k]}" for k in ("unsafe", "safe") if d.get(k)]
        return ("\nPolicy for " + category + ":\n  " + "\n  ".join(parts)) if parts else ""


@dataclass
class Verdict:
    """R's signal plus P's decision (or the error that replaced them)."""
    action: str | None                 # ALLOW / REWRITE / REFUSE; None if the sensor failed
    level: str | None
    category: str | None
    intent: str | None
    decided_by: str | None             # table / floor / topic
    raw: dict | None                   # the sensor's native output (audit only)
    error: str | None
    error_type: str | None             # transient / parse_error (sensor errors only)
    latency_ms: float
    topic_rule: str | None = None
    topic_instruction: str | None = None


@dataclass
class Trace:
    """M: everything that happened to one request under one condition ("none" or "prime")."""
    condition: str
    action: str = "ALLOW"                 # ALLOW / REWRITE / REFUSE, or ERROR (not a decision; see error_*)
    final_output: str = ""                # what the user sees
    risk: dict | None = None              # the Verdict
    rewritten_request: str | None = None  # REWRITE: what the protected model received instead
    refusal_source: str | None = None     # REFUSE: "template" (canned) or "generated" (ablation)
    fallback_reason: str | None = None    # why a canned refusal replaced a generated one, if it did
    error_stage: str | None = None        # ERROR: risk_sensor / intervention / generator
    error_type: str | None = None         # ERROR: transient / parse_error / empty_output
    fallback_action: str | None = None    # ERROR: what the user got instead (REFUSE / ALLOW / None)
    raw_generation: str | None = None     # the protected model's output (None if not called)
    risk_ms: float = 0.0
    intervention_ms: float = 0.0
    gen_ms: float = 0.0
    prime_ms: float = 0.0                 # risk_ms + intervention_ms: what PRIME adds
    total_ms: float = 0.0
    errors: list = field(default_factory=list)


class InterventionError(Exception):
    def __init__(self, message: str, error_type: str):
        super().__init__(message)
        self.error_type = error_type


class Chat:
    """Thin timed wrapper over an OpenAI-compatible chat endpoint."""

    def __init__(self, client, model: str, max_tokens: int, temperature: float = 0.0):
        self.client, self.model = client, model
        self.max_tokens, self.temperature = max_tokens, temperature

    async def __call__(self, content: str, system: str | None = None,
                       extra_body: dict | None = None) -> tuple[str, float]:
        t0 = time.perf_counter()
        messages = ([{"role": "system", "content": system}] if system else []) + \
                   [{"role": "user", "content": content}]
        kw = {"extra_body": extra_body} if extra_body else {}
        r = await self.client.chat.completions.create(
            model=self.model, messages=messages, max_tokens=self.max_tokens,
            temperature=self.temperature, **kw)
        return (r.choices[0].message.content or ""), (time.perf_counter() - t0) * 1000


class Prime:
    def __init__(self, generator: Chat, sensor: RiskSensor, policy: Policy, intervener: Chat,
                 intervention_retries: int = 1):
        # The Intervention step runs on the risk sensor's model by default (no extra GPU memory).
        self.gen, self.sensor, self.policy, self.intervener = generator, sensor, policy, intervener
        self.intervention_retries = intervention_retries

    async def risk(self, prompt: str) -> Verdict:
        """R + P. Sensor failures become an errored Verdict (action None); bugs raise."""
        t0 = time.perf_counter()
        try:
            sig: RiskSignal = await self.sensor.sense(prompt)
        except SensorError as e:
            return Verdict(None, None, None, None, None, None, f"{type(e).__name__}: {e}"[:300],
                           e.error_type, (time.perf_counter() - t0) * 1000)
        action, by, rule, instruction = self.policy.decide(sig.level, sig.category)
        return Verdict(action, sig.level, sig.category, (sig.raw or {}).get("intent"), by, sig.raw,
                       None, None, (time.perf_counter() - t0) * 1000, rule, instruction)

    async def _intervene(self, template: str, prompt: str, v: Verdict) -> str:
        instruction = f"\nPolicy instruction for this topic: {v.topic_instruction}" if v.topic_instruction else ""
        content = template.format(
            prompt=prompt, level=v.level, intent=v.intent or "unclear; infer it from the request",
            category_note=f" (category: {v.category})" if v.category else "",
            definition=self.policy.definition_text(v.category), instruction=instruction)
        for attempt in range(self.intervention_retries + 1):
            try:
                text, _ = await self.intervener(content)
            except Exception as e:  # noqa: BLE001 - only transient failures are handled
                if not _is_transient(e):
                    raise
                if attempt == self.intervention_retries:
                    raise InterventionError(f"{type(e).__name__}: {e}"[:200], "transient") from e
                await asyncio.sleep(1.0)
                continue
            text = text.strip()
            if text:
                return text
            if attempt == self.intervention_retries:
                raise InterventionError("empty intervention output", "empty_output")
        raise AssertionError("unreachable")

    async def run(self, prompt: str, condition: str, monitor=None, context: dict | None = None,
                  decision: dict | None = None) -> Trace:
        """condition: 'none' (model alone) | 'prime' (model + PRIME). With a monitor (monitor.py),
        the interaction is recorded when the request ends; context adds ids and dataset fields.
        decision: a stored PRIME decision for this request (from `decide`, saved by run.py
        --decide-only). PRIME's R and I never see the protected model's output, so the same decision
        applies to every protected model; with it, only the protected model is called."""
        started = time.time()
        tr = await self._run(prompt, condition, decision)
        if monitor:
            monitor.record_interaction(self, prompt, tr, context, started)
        return tr

    def _error(self, tr: Trace, stage: str, error_type: str, message: str, fallback: str | None) -> None:
        tr.action, tr.error_stage, tr.error_type, tr.fallback_action = "ERROR", stage, error_type, fallback
        tr.errors.append(f"{stage}: {message}")

    @staticmethod
    def needs_generation(tr: Trace) -> bool:
        """False when PRIME's decision already produced the final answer (a refusal)."""
        return not (tr.action == "REFUSE" or (tr.action == "ERROR" and tr.fallback_action == "REFUSE"))

    async def decide(self, prompt: str) -> Trace:
        """R + P + I for one request, without calling the protected model. The returned trace holds the
        decision; for ALLOW / REWRITE the protected model's input is `rewritten_request` or the prompt."""
        tr = Trace(condition="prime")
        t_start = time.perf_counter()
        v = await self.risk(prompt)
        tr.risk, tr.risk_ms = asdict(v), v.latency_ms
        if v.error:
            # Not a risk judgment: recorded as an error; the user gets the policy's fallback.
            fb = self.policy.on_sensor_error
            self._error(tr, "risk_sensor", v.error_type, v.error, fb)
            if fb == "REFUSE":
                tr.refusal_source, tr.final_output = "template", self.policy.refusal_text(None)
        else:
            tr.action = v.action
            if v.action in ("REWRITE", "REFUSE"):
                t0 = time.perf_counter()
                if v.action == "REWRITE":
                    try:
                        tr.rewritten_request = await self._intervene(REWRITE_REQUEST, prompt, v)
                    except InterventionError as e:
                        # The decision stands but couldn't be carried out: an error, with a safe fallback.
                        self._error(tr, "intervention", e.error_type, str(e), "REFUSE")
                        tr.refusal_source, tr.final_output = "template", self.policy.refusal_text(v.category)
                elif self.policy.refusal == "generated":
                    try:
                        tr.final_output = await self._intervene(REFUSAL, prompt, v)
                        tr.refusal_source = "generated"
                    except InterventionError as e:
                        # Still a correct REFUSE; only the wording degraded to the canned text.
                        tr.errors.append(f"intervention: {e}")
                        tr.refusal_source, tr.fallback_reason = "template", f"generated_refusal_failed: {e.error_type}"
                        tr.final_output = self.policy.refusal_text(v.category)
                else:
                    tr.refusal_source, tr.final_output = "template", self.policy.refusal_text(v.category)
                tr.intervention_ms = (time.perf_counter() - t0) * 1000
        tr.prime_ms = tr.risk_ms + tr.intervention_ms
        tr.total_ms = (time.perf_counter() - t_start) * 1000
        return tr

    async def _run(self, prompt: str, condition: str, decision: dict | None = None) -> Trace:
        t_start = time.perf_counter()
        if condition != "prime":
            tr = Trace(condition=condition)
        elif decision is not None:
            tr = Trace(**{k: (list(v) if k == "errors" else v) for k, v in decision.items()
                          if k in Trace.__dataclass_fields__})
            tr.condition, tr.raw_generation, tr.gen_ms = "prime", None, 0.0
        else:
            tr = await self.decide(prompt)
        if condition == "prime" and not self.needs_generation(tr):
            return tr
        to_model = (tr.rewritten_request or prompt) if condition == "prime" else prompt
        try:
            out, gms = await self.gen(to_model)
        except Exception as e:  # noqa: BLE001
            if not _is_transient(e):
                raise
            self._error(tr, "generator", "transient", f"{type(e).__name__}: {e}"[:300], None)
            tr.total_ms = tr.prime_ms + (time.perf_counter() - t_start) * 1000
            return tr
        tr.raw_generation, tr.gen_ms, tr.final_output = out, gms, out
        # PRIME's own time comes from the decision (computed once); the rest is this generation.
        tr.total_ms = (tr.prime_ms if condition == "prime" else 0.0) + (time.perf_counter() - t_start) * 1000
        return tr


async def gather_limited(coros, limit: int):
    sem = asyncio.Semaphore(limit)

    async def one(c):
        async with sem:
            return await c

    return await asyncio.gather(*(one(c) for c in coros))
