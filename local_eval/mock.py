"""Fake OpenAI-compatible client so the pipeline can be tested without a GPU."""
import asyncio
import json
import random
from types import SimpleNamespace as NS


class MockClient:
    def __init__(self, role: str, seed: int = 0):
        self.role, self.rng = role, random.Random(seed)
        self.chat = NS(completions=NS(create=self._create))

    async def _create(self, model, messages, max_tokens, temperature, **kw):
        await asyncio.sleep(self.rng.uniform(0.001, 0.005))
        text = messages[0]["content"]
        if self.role == "generator":
            out = f"[mock answer to: {text[:40]}]"
        elif self.role == "risk_sensor" and "Rewrite the request" in text:
            out = "[mock rewritten request] " + text.split("<<<")[1].split(">>>")[0].strip()[:60]
        elif self.role == "risk_sensor" and "Write the reply the user will see" in text:
            out = "I can't help with that, but here is a safe alternative. [mock generated refusal]"
        elif self.role == "risk_sensor":
            if self.rng.random() < 0.05:
                out = "not json"                      # exercise the parse-retry / parse-error path
            else:
                level = self.rng.choice(["low", "low", "medium", "high"])
                cat = self.rng.choice(["None", "Violence", "Mental Health", "Competitors", "Mass-casualty weapons"])
                out = json.dumps({"level": level, "category": cat, "intent": "mock intent"})
        elif self.role == "evaluator":
            labels = ["harmful", "safe_helpful", "refusal_with_alternative", "bare_refusal", "over_refusal", "off_target"]
            side = lambda: {"safety": self.rng.choice(["safe", "harmful"]), "helpfulness": self.rng.randint(1, 5),
                            "label": self.rng.choice(labels)}
            out = "not json" if self.rng.random() < 0.03 else json.dumps(
                {"a": {**side(), "addresses_request": self.rng.choice(["yes", "partly", "no"])},
                 "b": {**side(), "addresses_request": self.rng.choice(["yes", "partly", "no"])}, "winner": self.rng.choice(["A", "B", "tie"]),
                 "failure_mode": self.rng.choice(["over_refusal", "harmful_content", "lost_intent", "none"]), "reason": "mock"})
        else:  # grader
            out = self.rng.choice(["yes", "no"])
        return NS(choices=[NS(message=NS(content=out))])
