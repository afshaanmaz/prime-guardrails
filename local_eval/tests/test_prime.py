"""R + P + I end to end with fake models: actions, canned refusals, and errors kept apart from risk."""
import asyncio
from pathlib import Path

import yaml

from prime_local import Policy, Prime
from risk import RiskSignal, SensorParseError

CFG = yaml.safe_load(open(Path(__file__).resolve().parent.parent / "config.yaml"))


class FakeSensor:
    model = "fake-sensor"

    def __init__(self, result):
        self.result = result

    async def sense(self, request):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeChat:
    model = "fake"

    def __init__(self, reply="answer"):
        self.reply, self.prompts = reply, []

    async def __call__(self, content, system=None, extra_body=None):
        self.prompts.append(content)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply, 1.0


def make(result, **pol):
    gen, inter = FakeChat("model answer"), FakeChat("rewritten request")
    return Prime(gen, FakeSensor(result), Policy(**{**CFG["policy"], **pol}), inter), gen, inter


def run(p, req="req"):
    return asyncio.run(p.run(req, "prime"))


def sig(level, cat=None, intent="wants x"):
    return RiskSignal(level, cat, {"level": level, "category": cat, "intent": intent})


def test_allow():
    p, gen, inter = make(sig("low"))
    t = run(p)
    assert (t.action, t.final_output, inter.prompts) == ("ALLOW", "model answer", [])


def test_rewrite_uses_policy_definition_and_intent():
    p, gen, inter = make(sig("medium", "Violence"))
    t = run(p)
    assert t.action == "REWRITE" and gen.prompts == ["rewritten request"]
    assert "Policy for Violence" in inter.prompts[0] and "wants x" in inter.prompts[0]


def test_rewrite_without_intent_asks_to_infer():
    p, _, inter = make(RiskSignal("medium", "Violence", {}))
    run(p)
    assert "infer it from the request" in inter.prompts[0]


def test_refuse_is_canned_with_no_model_call():
    p, gen, inter = make(sig("high", "Self-harm"))
    t = run(p)
    assert t.action == "REFUSE" and t.refusal_source == "template"
    assert "988" in t.final_output and gen.prompts == [] and inter.prompts == []


def test_floor_under_loose():
    p, gen, _ = make(sig("high", "Child sexual exploitation"), mode="LOOSE")
    t = run(p)
    assert t.action == "REFUSE" and t.risk["decided_by"] == "floor" and gen.prompts == []


def test_loose_rewrites_high_outside_floor():
    assert run(make(sig("high", "Illegal"), mode="LOOSE")[0]).action == "REWRITE"


def test_generated_refusal_ablation():
    p, gen, inter = make(sig("high", "Illegal"), refusal="generated")
    inter.reply = "warm refusal"
    t = run(p)
    assert (t.action, t.refusal_source, t.final_output) == ("REFUSE", "generated", "warm refusal")


def test_sensor_error_is_an_error_not_a_refusal():
    p, gen, _ = make(SensorParseError("bad json", 2))
    t = run(p)
    assert t.action == "ERROR" and t.error_stage == "risk_sensor" and t.error_type == "parse_error"
    assert t.fallback_action == "REFUSE" and t.risk["level"] is None and gen.prompts == []
    assert t.final_output   # the user still gets the canned fallback


def test_sensor_error_fail_open():
    p, gen, _ = make(SensorParseError("bad json", 2), on_sensor_error="ALLOW")
    t = run(p)
    assert (t.action, t.fallback_action, t.final_output) == ("ERROR", "ALLOW", "model answer")


def test_rewrite_failure_is_an_error_with_safe_fallback():
    p, gen, inter = make(sig("medium", "Violence"))
    inter.reply = TimeoutError()
    p.intervention_retries = 0
    t = run(p)
    assert (t.action, t.error_stage, t.error_type, t.fallback_action) == ("ERROR", "intervention", "transient", "REFUSE")
    assert gen.prompts == []


def test_model_alone_condition_untouched():
    p, gen, _ = make(sig("high", "Violence"))
    t = asyncio.run(p.run("req", "none"))
    assert t.action == "ALLOW" and t.risk is None and gen.prompts == ["req"]
