"""P: the policy file loads, decide() follows the tables, the floor and topic rules."""
import re
from pathlib import Path

import pytest
import yaml

from prime_local import Policy, PolicyError
from risk import LLM_RISK_PROMPT

HERE = Path(__file__).resolve().parent.parent
CFG = yaml.safe_load(open(HERE / "config.yaml"))


def policy(**over):
    return Policy(**{**CFG["policy"], **over})


def test_config_policy_loads():
    p = policy()
    assert p.mode in p.actions
    assert set(p.always_refuse) <= set(p.categories)


@pytest.mark.parametrize("mode,level,expected", [
    ("STRICT", "low", "ALLOW"), ("STRICT", "medium", "REWRITE"), ("STRICT", "high", "REFUSE"),
    ("LOOSE", "low", "ALLOW"), ("LOOSE", "medium", "REWRITE"), ("LOOSE", "high", "REWRITE"),
])
def test_tables(mode, level, expected):
    action, by, _, _ = policy(mode=mode).decide(level, "Violence")
    assert (action, by) == (expected, "table")


@pytest.mark.parametrize("mode", ["STRICT", "LOOSE"])
def test_floor_refuses_at_high_in_every_mode(mode):
    assert policy(mode=mode).decide("high", "Mass-casualty weapons")[:2] == ("REFUSE", "floor")


def test_floor_only_at_high():
    # A history question about such weapons is not refused just for mentioning them.
    assert policy(mode="LOOSE").decide("medium", "Mass-casualty weapons")[0] == "REWRITE"
    assert policy().decide("low", "Mass-casualty weapons")[0] == "ALLOW"


def test_topic_rule_applies_at_any_level_and_only_tightens():
    p = policy(mode="STRICT")
    assert p.decide("low", "Competitors")[:3] == ("REFUSE", "topic", "Competitors")
    assert p.decide("low", "Mental Health")[:2] == ("REWRITE", "topic")
    # Mental Health's REWRITE never loosens a REFUSE.
    assert p.decide("high", "Mental Health")[:2] == ("REFUSE", "table")


def test_no_category():
    assert policy().decide("low", None)[0] == "ALLOW"


def test_invalid_level_raises():
    with pytest.raises(ValueError):
        policy().decide("severe", None)


@pytest.mark.parametrize("over", [
    {"mode": "MEDIUM"},
    {"actions": {"STRICT": {"low": "ALLOW", "medium": "REWRITE"}}},
    {"actions": {"STRICT": {"low": "ALLOW", "medium": "BLOCK", "high": "REFUSE"}}},
    {"always_refuse": ["Not a category"]},
    {"topics": {"Unknown": {"action": "REFUSE"}}},
    {"on_sensor_error": "MAYBE"},
    {"refusal": "llm"},
])
def test_bad_policy_rejected_at_load(over):
    with pytest.raises(PolicyError):
        policy(**over)


def test_every_category_has_a_refusal():
    for name, d in CFG["policy"]["categories"].items():
        assert d.get("refusal"), name
        assert ("about" in d) or all(d.get(k) for k in ("unsafe", "borderline", "safe")), name


# ---- contamination: the policy text and the prompt's examples must not copy benchmark prompts

def _ngrams(text: str, n: int) -> set:
    w = re.findall(r"[a-z0-9']+", text.lower())
    return {" ".join(w[i:i + n]) for i in range(len(w) - n + 1)}


def _policy_text() -> str:
    parts = []
    for d in CFG["policy"]["categories"].values():
        parts += [str(v) for k, v in d.items() if k != "refusal"]
    return "\n".join(parts) + "\n" + LLM_RISK_PROMPT


@pytest.mark.parametrize("dataset", ["harmbench", "xstest", "orbench"])
def test_policy_has_no_benchmark_overlap(dataset):
    path = HERE / "data" / f"{dataset}.csv"
    if not path.exists():
        pytest.skip(f"{dataset} not downloaded (data/{dataset}.csv)")
    import data
    prompts = [it["prompt"] for it in data.load(dataset)]
    ours = _ngrams(_policy_text(), 5)
    hits = sorted({g for p in prompts for g in _ngrams(p, 5) & ours})
    assert not hits, f"5-word overlap with {dataset}: {hits[:10]}"
