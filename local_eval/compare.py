"""Side-by-side table for one run: question, what the protected model said with no
guardrail, and what PRIME did with it (decision, judge score, what the user would see).

  python compare.py results/<run_id>        # writes results/<run_id>/COMPARISON.md
"""
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path


def cell(text: str | None) -> str:
    """Make text safe inside a Markdown table cell."""
    if not text:
        return ""
    return html.escape(text.strip(), quote=False).replace("|", "&#124;").replace("\n", "<br>")


def prime_cell(tr: dict) -> str:
    iv, ov = tr.get("input_verdict"), tr.get("output_verdict")
    parts = []
    if iv:
        parts.append(f"input judge: {iv['score']} ({iv['category']}) → {iv['action']}")
    if ov:
        parts.append(f"output judge: {ov['score']} ({ov['category']}) → {ov['action']}")
    elif tr["condition"] == "input_output" and tr["gated_by"] == "input":
        parts.append("output judge: not reached (blocked at input)")
    if tr["errors"]:
        parts.append("errors: " + "; ".join(tr["errors"]))
    head = f"**{tr['final_action']}**" + (f" (at {tr['gated_by']})" if tr["gated_by"] else "")
    return head + "<br>" + "<br>".join(cell(p) for p in parts) + "<br><br>*User sees:* " + cell(tr["final_output"])


def main(run_dir: Path):
    meta = json.load(open(run_dir / "meta.json"))
    rows = [json.loads(line) for line in open(run_dir / "traces.jsonl")]
    by_prompt: dict = {}
    for r in rows:
        by_prompt.setdefault((r["dataset"], r["id"]), {})[r["condition"]] = r
    cfg = meta["config"]
    pol = cfg["policy"]
    th = pol["thresholds"][pol["mode"]]
    out = [
        f"# Side-by-side: run {meta['run_id']}",
        "",
        "> **Content warning:** the \"no guardrail\" column contains the model's raw answers to harmful "
        "benchmark requests (hate speech, defamation, phishing, etc.), kept verbatim for evaluation.",
        "",
        f"- Protected model: `{cfg['generator']['model']}`",
        f"- PRIME judge: `{cfg['judge']['model']}`. Policy {pol['mode']}: "
        f"REFUSE if score ≥ {th['high']}, REWRITE if ≥ {th['medium']}, else ALLOW",
        f"- Code: `{meta.get('commit')}`. Columns: **No guardrail** = condition `none`; "
        "**PRIME (input check)** = condition `input`; **PRIME (input + output check)** = condition `input_output`.",
        "",
        "| # | Dataset / category | Question | No guardrail: model's answer | PRIME (input check) | PRIME (input + output check) |",
        "|---|---|---|---|---|---|",
    ]
    for n, ((ds, _), conds) in enumerate(by_prompt.items(), 1):
        base = conds.get("none") or next(iter(conds.values()))
        orig = conds["none"]["raw_generation"] if "none" in conds else ""
        out.append("| " + " | ".join([
            str(n), f"{ds} / {base['category']} ({base['label']})", cell(base["prompt"]), cell(orig),
            prime_cell(conds["input"]) if "input" in conds else "",
            prime_cell(conds["input_output"]) if "input_output" in conds else "",
        ]) + " |")
    (run_dir / "COMPARISON.md").write_text("\n".join(out) + "\n")
    print(f"wrote {run_dir / 'COMPARISON.md'} ({len(by_prompt)} prompts)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir", type=Path)
    main(ap.parse_args().run_dir)
