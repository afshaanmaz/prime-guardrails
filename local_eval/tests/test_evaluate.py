import json
import pytest
from evaluate import parse


def verdict(h_a=4, h_b=2):
    side = lambda h: {"safety": "safe", "helpfulness": h, "label": "safe_helpful", "addresses_request": "yes"}
    return json.dumps({"a": side(h_a), "b": side(h_b), "winner": "A", "failure_mode": "none", "reason": "r"})


def test_parse_accepts_integer_helpfulness():
    assert parse(verdict())["a"]["helpfulness"] == 4


@pytest.mark.parametrize("bad", ["3", 3.0, 0, 6, None, True])
def test_parse_rejects_non_integer_or_out_of_range_helpfulness(bad):
    with pytest.raises(ValueError):
        parse(verdict(h_a=bad))
