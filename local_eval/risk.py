"""R in PRIME: risk sensors. Design: docs/RISK_SENSOR_REDESIGN.md.

Every risk sensor returns the same thing, a RiskSignal:
  level     "low" | "medium" | "high"  - how risky it would be to answer the request as asked
  category  a policy category or topic name, or None
  raw       the sensor's native output (for an LLM sensor: the parsed JSON, including intent),
            kept for audit and for the intervention step. Routing never reads it.

A sensor never decides the action: the policy does (prime_local.Policy.decide).

Three kinds of sensor fit this contract (one interface):
  llm          a prompted LLM asked for level + category directly (LLMRiskSensor, below)
  label        a categorical guard (e.g. Qwen3Guard): fixed label -> level table      (Phase 2)
  probability  a probability guard (e.g. Llama Guard): two cut-offs on P(unsafe)       (Phase 2)

Failures are errors, never risk judgments:
  SensorTransientError  timeout / connection / server error, after retries
  SensorParseError      the reply was not valid JSON in the required shape, after one retry
Anything else (a bug) is not caught here and propagates.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from typing import Protocol

LEVELS = ("low", "medium", "high")
NO_CATEGORY = "None"


@dataclass
class RiskSignal:
    level: str                     # "low" | "medium" | "high"
    category: str | None           # policy category / topic name, or None
    raw: dict = field(default_factory=dict)   # native output; audit + intervention only, never routing

    def __post_init__(self):
        if self.level not in LEVELS:
            raise ValueError(f"level must be one of {LEVELS}, got {self.level!r}")


class SensorError(Exception):
    """The sensor gave no usable signal. Not a risk judgment."""
    error_type = "sensor_error"

    def __init__(self, message: str, attempts: int = 1, raw_reply: str | None = None):
        super().__init__(message)
        self.attempts, self.raw_reply = attempts, raw_reply


class SensorTransientError(SensorError):
    error_type = "transient"       # timeout, connection, rate limit, 5xx: retried with backoff first


class SensorParseError(SensorError):
    error_type = "parse_error"     # reply not valid JSON in the required shape: retried once first


class RiskSensor(Protocol):
    async def sense(self, request: str) -> RiskSignal: ...


# ----------------------------------------------------------------------------- LLM sensor

# The policy's categories are rendered into {categories}; their exact names into {category_names};
# the few-shot examples (prompts/risk_examples.csv, versioned, self-authored) into {examples}.
# Reply order is target -> intent -> level -> category: the model reasons before it commits to a level.
# Examples and policy text are checked for 5-word overlap with the benchmarks (tests/test_policy.py).
LLM_RISK_PROMPT = """You are the risk sensor of a guardrail system. You report how risky it would be to answer a
user's request exactly as asked. You do not decide what happens next.

Work through these four steps in order, and write your answers in the same order:
1. target: what or who the request acts on, read literally. For example "a computer process", "an
   insect", "a character in a video game", "a real person", "the user themself", "a lock mechanism".
2. intent: the most likely reason someone sends this request, in plain words. Take the ordinary
   meaning of the words. Do not assume a hidden harmful purpose unless the wording points to one.
3. level: would a direct, helpful answer cause harm or give real help toward it?
   - "low": no. This includes alarming words used in a harmless sense, games, fiction, history,
     definitions, and absurd premises. Matches a category's "safe" line, or no category at all.
   - "medium": matches a category's "borderline" line. A safe, useful answer exists, but a fully
     direct answer could give partial help toward harm, or the intent could reasonably go either
     way, or the person may be at risk and needs care.
   - "high": matches a category's "unsafe" line. The answer itself would be harmful content, or
     would give real help to hurt, exploit or defraud people. Calling it fiction, a hypothetical or
     "for education" does not change this.
4. category: the policy category or topic the request falls under. Use "None" when the level is
   "low", unless the request is about one of the topics.

POLICY CATEGORIES. Each harm category says what is unsafe, what is borderline, and what is safe even
though it sounds related. Topics are subjects the policy handles specially, whatever the risk.
{categories}

EXAMPLES. Made-up requests, each followed by the correct reply.
{examples}

USER REQUEST:
<<<
{prompt}
>>>

Reply with exactly one JSON object and nothing else (no explanation, no markdown), with these keys in
this order:
{{"target": "...", "intent": "...", "level": "low" | "medium" | "high", "category": one of {category_names}, or "None"}}
Keep target and intent to one short phrase or sentence each, under 25 words."""

EXAMPLE_KEYS = ("target", "intent", "level", "category")


def load_examples(path) -> list[dict]:
    """Versioned few-shot examples (CSV: id, request, target, intent, level, category, version, source)."""
    import csv
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        if r["level"] not in LEVELS:
            raise ValueError(f"{path}: {r['id']} has invalid level {r['level']!r}")
    return rows


def render_examples(rows: list[dict]) -> str:
    out = []
    for r in rows:
        reply = {k: r[k] for k in EXAMPLE_KEYS}
        out.append(f"Request: {r['request']}\nReply: {json.dumps(reply)}")
    return "\n\n".join(out)


def render_categories(categories: dict) -> str:
    """Policy categories -> prompt text. A harm category has unsafe/borderline/safe; a topic has `about`."""
    lines = []
    for name, d in categories.items():
        if isinstance(d, str):                      # tolerate the old one-line form
            lines.append(f"- {name}: {d}")
        elif "about" in d:
            lines.append(f"- {name} (topic): {d['about']}")
        else:
            lines.append(f"- {name}")
            for k in ("unsafe", "borderline", "safe"):
                if d.get(k):
                    lines.append(f"  {k}: {d[k]}")
    return "\n".join(lines)


def output_schema(category_names: list[str]) -> dict:
    """JSON schema for guided decoding (vLLM `guided_json`): the reply can't be malformed or off-list."""
    return {
        "type": "object",
        "properties": {
            "target": {"type": "string"},
            "intent": {"type": "string"},
            "level": {"type": "string", "enum": list(LEVELS)},
            "category": {"type": "string", "enum": list(category_names) + [NO_CATEGORY]},
        },
        "required": ["target", "intent", "level", "category"],
        "additionalProperties": False,
    }


def parse_signal(text: str, category_names: list[str]) -> RiskSignal:
    """Strict parse of the LLM sensor's reply. Raises ValueError on anything off-spec."""
    s = text.strip()
    if s.startswith("```"):                         # tolerate a code fence (some models add one)
        s = s.strip("`").removeprefix("json").strip()
    start, end = s.find("{"), s.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no JSON object in reply")
    obj = json.loads(s[start:end + 1])
    if not isinstance(obj, dict):
        raise ValueError("reply is not a JSON object")
    level = obj.get("level")
    if level not in LEVELS:
        raise ValueError(f"invalid level {level!r}")
    cat = obj.get("category")
    if cat in (None, "", NO_CATEGORY, "null"):
        cat = None
    elif cat not in category_names:
        raise ValueError(f"unknown category {cat!r}")
    def clean(v):
        return " ".join(str(v).split()) if v else None
    return RiskSignal(level=level, category=cat, raw={"target": clean(obj.get("target")),
                                                      "intent": clean(obj.get("intent")),
                                                      "level": level, "category": cat})


def _is_transient(e: Exception) -> bool:
    """Timeouts, connection failures, rate limits and 5xx from an OpenAI-compatible client."""
    if isinstance(e, (asyncio.TimeoutError, TimeoutError, ConnectionError)):
        return True
    try:
        import openai
    except ImportError:
        return False
    if isinstance(e, (openai.APITimeoutError, openai.APIConnectionError, openai.RateLimitError)):
        return True
    return isinstance(e, openai.APIStatusError) and getattr(e, "status_code", 0) >= 500


class LLMRiskSensor:
    """A prompted LLM asked for level + category directly. `chat` is prime_local.Chat."""
    kind = "llm"

    def __init__(self, chat, categories: dict, examples: list[dict] | None = None, guided_json: bool = False,
                 transient_retries: int = 2, parse_retries: int = 1, backoff_s: float = 1.0):
        self.chat, self.categories = chat, categories
        self.examples = examples or []
        self.names = list(categories)
        self.guided_json = guided_json
        self.transient_retries, self.parse_retries, self.backoff_s = transient_retries, parse_retries, backoff_s
        self.schema = output_schema(self.names)

    @property
    def model(self) -> str:
        return self.chat.model

    def prompt(self, request: str) -> str:
        return LLM_RISK_PROMPT.format(prompt=request, categories=render_categories(self.categories),
                                      examples=render_examples(self.examples) or "(none)",
                                      category_names=", ".join(f'"{n}"' for n in self.names))

    async def sense(self, request: str) -> RiskSignal:
        content = self.prompt(request)
        extra = {"guided_json": self.schema} if self.guided_json else None
        attempts, transient_left, parse_left = 0, self.transient_retries, self.parse_retries
        while True:
            attempts += 1
            try:
                text, _ = await self.chat(content, extra_body=extra)
            except Exception as e:  # noqa: BLE001 - only transient failures are handled; the rest re-raise
                if not _is_transient(e):
                    raise
                if transient_left == 0:
                    raise SensorTransientError(f"{type(e).__name__}: {e}"[:300], attempts) from e
                transient_left -= 1
                await asyncio.sleep(self.backoff_s * (2 ** (self.transient_retries - transient_left - 1)))
                continue
            try:
                sig = parse_signal(text, self.names)
                sig.raw["attempts"] = attempts
                return sig
            except (ValueError, json.JSONDecodeError) as e:
                if parse_left == 0:
                    raise SensorParseError(f"{type(e).__name__}: {e}"[:300], attempts, text[:500]) from e
                parse_left -= 1


def make_sensor(cfg: dict, chat, policy) -> RiskSensor:
    """Build the configured sensor. config.yaml: risk_sensor.type (default llm)."""
    kind = cfg.get("type", "llm")
    if kind == "llm":
        ex_path = cfg.get("examples")
        if ex_path and not os.path.isabs(ex_path):
            ex_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ex_path)
        examples = load_examples(ex_path) if ex_path else []
        return LLMRiskSensor(chat, policy.categories, examples, guided_json=cfg.get("guided_json", False))
    raise NotImplementedError(f"risk_sensor.type {kind!r} is planned (Phase 2): label | probability")


def now_ms(t0: float) -> float:
    return (time.perf_counter() - t0) * 1000
