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
    # OR-Bench-Hard-1K: prompts that sound harmful but mostly have a legitimate answer (borderline /
    # dual-use); used to exercise the REWRITE tier. Labelled "borderline".
    "orbench": "https://huggingface.co/datasets/bench-llm/or-bench/resolve/main/or-bench-hard-1k.csv",
}


def _fetch(name: str) -> Path:
    DATA.mkdir(exist_ok=True)
    path = DATA / f"{name}.csv"
    if not path.exists():
        urllib.request.urlretrieve(SOURCES[name], path)
    return path


def load(name: str, limit: int | None = None, exclude: set | None = None) -> list[dict]:
    """Rows of {id, dataset, prompt, label, category}. label: 'unsafe' or 'safe'."""
    rows = list(csv.DictReader(open(_fetch(name), encoding="utf-8")))
    if name == "harmbench":
        items = [{"id": r["BehaviorID"], "dataset": name, "prompt": r["Behavior"],
                  "label": "unsafe", "category": r["SemanticCategory"]}
                 for r in rows if r["FunctionalCategory"] == "standard"]
    elif name == "xstest":
        items = [{"id": f"xstest-{r['id']}", "dataset": name, "prompt": r["prompt"],
                  "label": r["label"], "category": r["type"]} for r in rows]
    elif name == "orbench":
        key = next(k for k in rows[0] if k.strip().lower() in ("prompt", "text", "question"))
        cat = next((k for k in rows[0] if k.strip().lower() == "category"), None)
        items = [{"id": f"orbench-{n}", "dataset": name, "prompt": r[key], "label": "borderline",
                  "category": (r[cat] if cat else "unknown")} for n, r in enumerate(rows)]
    else:
        raise ValueError(name)
    if exclude:  # e.g. the pilot's items, so evaluation runs don't reuse what we tuned on
        items = [it for it in items if it["id"] not in exclude]
    return _spread(items, limit) if limit else items


def _spread(items: list[dict], limit: int) -> list[dict]:
    """First `limit` items taken round-robin across (label, category), in file order, so a
    small sample covers every category instead of only the first few in the file."""
    groups: dict = {}
    for it in items:
        groups.setdefault((it["label"], it["category"]), []).append(it)
    out, i = [], 0
    while len(out) < limit and any(i < len(g) for g in groups.values()):
        out += [g[i] for g in groups.values() if i < len(g)]
        i += 1
    return out[:limit]
