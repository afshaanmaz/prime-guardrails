from pathlib import Path
"""R: the LLM risk sensor's parsing, JSON enforcement and retry behaviour."""
import asyncio
import json

import pytest

from risk import (LLMRiskSensor, RiskSignal, SensorParseError, SensorTransientError, output_schema,
                  parse_signal, render_categories)

CATS = {"Violence": {"unsafe": "u", "borderline": "b", "safe": "s"}, "Competitors": {"about": "rival companies"}}
NAMES = list(CATS)


def test_parse_valid():
    s = parse_signal('{"level": "medium", "category": "Violence", "intent": "Wants  advice.\\n"}', NAMES)
    assert (s.level, s.category, s.raw["intent"]) == ("medium", "Violence", "Wants advice.")


def test_parse_none_category_and_code_fence():
    s = parse_signal('```json\n{"level": "low", "category": "None", "intent": "x"}\n```', NAMES)
    assert (s.level, s.category) == ("low", None)


@pytest.mark.parametrize("text", [
    "not json", '{"level": "severe", "category": "None", "intent": "x"}',
    '{"level": "low", "category": "Weather", "intent": "x"}', '["low"]', '{"category": "None"}',
])
def test_parse_rejects_off_spec(text):
    with pytest.raises(ValueError):
        parse_signal(text, NAMES)


def test_risk_signal_validates_level():
    with pytest.raises(ValueError):
        RiskSignal("none", None)


def test_schema_enums():
    sch = output_schema(NAMES)
    assert sch["properties"]["level"]["enum"] == ["low", "medium", "high"]
    assert sch["properties"]["category"]["enum"] == NAMES + ["None"]


def test_prompt_lists_exact_categories():
    sensor = LLMRiskSensor(FakeChat([]), CATS)
    p = sensor.prompt("hello")
    assert '"Violence", "Competitors"' in p and "- Competitors (topic): rival companies" in p
    assert "{" not in render_categories(CATS)
    assert "EXAMPLES" in p and "(none)" in p    # no examples passed -> placeholder


def test_examples_file_renders_valid_json_in_reply_order():
    import risk
    rows = risk.load_examples(Path(__file__).resolve().parents[1] / "prompts" / "risk_examples.csv")
    assert {r["level"] for r in rows} == {"low", "medium", "high"}
    for line in risk.render_examples(rows).splitlines():
        if line.startswith("Reply: "):
            obj = json.loads(line[len("Reply: "):])
            assert list(obj) == ["target", "intent", "level", "category"]
    sensor = LLMRiskSensor(FakeChat([]), CATS, rows)
    p = sensor.prompt("hello")
    assert p.index("EXAMPLES") < p.index("USER REQUEST") < p.index("Reply with")


class FakeChat:
    model = "fake"

    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    async def __call__(self, content, system=None, extra_body=None):
        self.calls.append(extra_body)
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r, 1.0


def run(coro):
    return asyncio.run(coro)


def test_sense_ok_with_guided_json():
    chat = FakeChat(['{"level": "high", "category": "Violence", "intent": "x"}'])
    sig = run(LLMRiskSensor(chat, CATS, guided_json=True).sense("r"))
    assert sig.level == "high" and chat.calls[0]["guided_json"]["properties"]["level"]["enum"]


def test_guided_json_can_be_off():
    chat = FakeChat(['{"level": "low", "category": "None", "intent": "x"}'])
    run(LLMRiskSensor(chat, CATS, guided_json=False).sense("r"))
    assert chat.calls == [None]


def test_parse_error_retried_once_then_raised():
    chat = FakeChat(["oops", '{"level": "low", "category": "None", "intent": "x"}'])
    assert run(LLMRiskSensor(chat, CATS).sense("r")).raw["attempts"] == 2
    with pytest.raises(SensorParseError) as e:
        run(LLMRiskSensor(FakeChat(["oops", "still not json"]), CATS).sense("r"))
    assert e.value.error_type == "parse_error" and e.value.attempts == 2


def test_transient_retried_then_raised():
    ok = '{"level": "low", "category": "None", "intent": "x"}'
    assert run(LLMRiskSensor(FakeChat([TimeoutError(), ok]), CATS, backoff_s=0).sense("r")).level == "low"
    with pytest.raises(SensorTransientError):
        run(LLMRiskSensor(FakeChat([TimeoutError()] * 3), CATS, backoff_s=0).sense("r"))


def test_bug_is_not_swallowed():
    with pytest.raises(KeyError):
        run(LLMRiskSensor(FakeChat([KeyError("bug")]), CATS).sense("r"))
