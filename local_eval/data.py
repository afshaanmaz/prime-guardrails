"""Benchmark loaders. Files are downloaded once into data/ and read as plain CSV."""
from __future__ import annotations

import csv
import urllib.request
from pathlib import Path

DATA = Path(__file__).parent / "data"
SOURCES = {
    # 400 text behaviors; we use the 200 "standard" ones by default
    "harmbench": "https://raw.githubusercontent.com/centerforaisafety/HarmBench/main/data/behavior_datasets/harmbench_behaviors_text_all.csv",
    # 450 prompts: 250 safe prompts that look risky, 200 unsafe contrasts
    "xstest": "https://raw.githubusercontent.com/paul-rottger/xstest/main/xstest_prompts.csv",
}


def _fetch(name: str) -> Path:
    DATA.mkdir(exist_ok=True)
    path = DATA / f"{name}.csv"
    if not path.exists():
        urllib.request.urlretrieve(SOURCES[name], path)
    return path


def load(name: str, limit: int | None = None) -> list[dict]:
    """Rows of {id, dataset, prompt, label, category}. label: 'unsafe' or 'safe'."""
    rows = list(csv.DictReader(open(_fetch(name), encoding="utf-8")))
    if name == "harmbench":
        items = [{"id": r["BehaviorID"], "dataset": name, "prompt": r["Behavior"],
                  "label": "unsafe", "category": r["SemanticCategory"]}
                 for r in rows if r["FunctionalCategory"] == "standard"]
    elif name == "xstest":
        items = [{"id": f"xstest-{r['id']}", "dataset": name, "prompt": r["prompt"],
                  "label": r["label"], "category": r["type"]} for r in rows]
    else:
        raise ValueError(name)
    return items[:limit] if limit else items
