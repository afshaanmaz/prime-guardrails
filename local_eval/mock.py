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
        elif self.role == "judge" and "Write the reply the user will see" in text:
            out = "I can't help with that, but here is a safe alternative. [mock helpful refusal]"
        elif self.role == "judge":
            if self.rng.random() < 0.05:
                out = "not json"                      # exercise the judge-error path
            else:
                s = round(self.rng.random(), 2)
                out = json.dumps({"category": self.rng.choice(["Other", "Violence", "Mental Health", "Competitors"]), "score": s, "reason": "mock", "intent": "mock intent",
                                  "safe_rewrite": "a safer version" if s >= 0.3 else ""})
        else:  # grader
            out = self.rng.choice(["yes", "no"])
        return NS(choices=[NS(message=NS(content=out))])
