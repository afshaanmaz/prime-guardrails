"""Fake OpenAI-compatible client so the pipeline can be tested without a GPU."""
import asyncio
import json
import random
from types import SimpleNamespace as NS


class MockClient:
    def __init__(self, role: str, seed: int = 0):
        self.role, self.rng = role, random.Random(seed)
        self.chat = NS(completions=NS(create=self._create))

    async def _create(self, model, messages, max_tokens, temperature):
        await asyncio.sleep(self.rng.uniform(0.001, 0.005))
        text = messages[0]["content"]
        if self.role == "generator":
            out = f"[mock answer to: {text[:40]}]"
        elif self.role == "judge" and "Rewrite the request" in text:
            out = "[mock rewritten request] " + text.split("<<<")[1].split(">>>")[0].strip()[:60]
        elif self.role == "judge" and "Write the reply the user will see" in text:
            out = "I can't help with that, but here is a safe alternative. [mock contextual refusal]"
        elif self.role == "judge":
            if self.rng.random() < 0.05:
                out = "not json"                      # exercise the judge-error path
            else:
                s = round(self.rng.random(), 2)
                out = json.dumps({"category": self.rng.choice(["Other", "Violence", "Mental Health", "Competitors"]), "score": s, "reason": "mock", "intent": "mock intent"})
        elif self.role == "ab_judge":
            labels = ["harmful", "safe_helpful", "refusal_with_alternative", "bare_refusal", "over_refusal", "off_target"]
            side = lambda: {"safety": self.rng.choice(["safe", "harmful"]), "helpfulness": self.rng.randint(1, 5),
                            "label": self.rng.choice(labels)}
            out = "not json" if self.rng.random() < 0.03 else json.dumps(
                {"a": side(), "b": side(), "winner": self.rng.choice(["A", "B", "tie"]),
                 "failure_mode": self.rng.choice(["over_refusal", "harmful_content", "lost_intent", "none"]), "reason": "mock"})
        else:  # grader
            out = self.rng.choice(["yes", "no"])
        return NS(choices=[NS(message=NS(content=out))])
