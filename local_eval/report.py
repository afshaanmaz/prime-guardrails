"""E: turn a run (traces.jsonl + ab.jsonl) into a report and a side-by-side table.

  python report.py results/<run_id>
Writes REPORT.md (summary, PRIME action mix, win/tie/loss, harm and over-refusal rates, failure
modes, every loss), COMPARISON.md (one row per request) and summary.json. Works without
ab.jsonl too (no verdict columns then).
"""
from __future__ import annotations

import argparse
import html
import json
from collections import Counter, defaultdict
from pathlib import Path


def cell(text) -> str:
    if text is None or text == "":
        return ""
    return html.escape(str(text).strip(), quote=False).replace("|", "&#124;").replace("\n", "<br>")


def pct(n, d) -> str:
    return f"{100 * n / d:.0f}%" if d else ""


def quant(xs, q):
    xs = sorted(x for x in xs if x is not None)
    return round(xs[min(len(xs) - 1, int(q * len(xs)))]) if xs else None


def load(run_dir: Path):
    meta = json.load(open(run_dir / "meta.json"))
    traces = [json.loads(line) for line in open(run_dir / "traces.jsonl")]
    by: dict = {}
    for t in traces:
        by.setdefault(t["id"], {})[t["condition"]] = t
    ab_path = run_dir / "ab.jsonl"
    ab = {r["id"]: r for r in map(json.loads, open(ab_path))} if ab_path.exists() else {}
    return meta, by, ab


def slice_of(t: dict) -> str:
    return f"{t['dataset']}/{t['label']}"


def summarize(by: dict, ab: dict) -> list[dict]:
    groups = defaultdict(list)
    for rid, c in by.items():
        if "prime" in c:
            groups[slice_of(c["prime"])].append(rid)
    groups["ALL"] = [rid for rid in by if "prime" in by[rid]]
    table = []
    for sl in sorted(groups, key=lambda s: (s == "ALL", s)):
        ids = groups[sl]
        pr = [by[i]["prime"] for i in ids]
        md = [by[i]["none"] for i in ids if "none" in by[i]]
        acts = Counter(t["action"] for t in pr)
        refusals = [t for t in pr if t["action"] == "REFUSE"]
        v = [ab[i] for i in ids if i in ab and "error" not in ab[i]]
        w = Counter(x["winner"] for x in v)
        row = {
            "slice": sl, "n": len(ids),
            "allow": pct(acts["ALLOW"], len(pr)), "rewrite": pct(acts["REWRITE"], len(pr)),
            "refuse": pct(acts["REFUSE"], len(pr)),
            "template_fallback": f"{sum(t['refusal_source'] == 'template' for t in refusals)}/{len(refusals)}",
            "risk_judge_errors": sum(any(e.startswith("risk_judge") for e in t["errors"]) for t in pr),
            "judged": len(v), "ab_errors": sum(1 for i in ids if i in ab and "error" in ab[i]),
        }
        if v:
            row.update({
                "prime_wins": pct(w["prime"], len(v)), "ties": pct(w["tie"], len(v)), "model_wins": pct(w["model"], len(v)),
                "harmful_model": pct(sum(x["model"]["safety"] == "harmful" for x in v), len(v)),
                "harmful_prime": pct(sum(x["prime"]["safety"] == "harmful" for x in v), len(v)),
                "over_refusal_model": pct(sum(x["model"]["label"] == "over_refusal" for x in v), len(v)),
                "over_refusal_prime": pct(sum(x["prime"]["label"] == "over_refusal" for x in v), len(v)),
                "helpful_model": round(sum(x["model"]["helpfulness"] for x in v) / len(v), 2),
                "helpful_prime": round(sum(x["prime"]["helpfulness"] for x in v) / len(v), 2),
            })
        row.update({"prime_ms_p50": quant([t["prime_ms"] for t in pr], .5), "prime_ms_p90": quant([t["prime_ms"] for t in pr], .9),
                    "total_ms_p50_model": quant([t["total_ms"] for t in md], .5),
                    "total_ms_p50_prime": quant([t["total_ms"] for t in pr], .5)})
        table.append(row)
    return table


def md_table(rows: list[dict], cols: list[str]) -> list[str]:
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    out += ["| " + " | ".join("" if r.get(c) is None else str(r.get(c)) for c in cols) + " |" for r in rows]
    return out


def report(meta, by, ab, table) -> str:
    cfg, pol = meta["config"], meta["config"]["policy"]
    th = pol["thresholds"][pol["mode"]]
    L = [f"# PRIME run {meta['run_id']}", "",
         f"- Protected model: `{cfg['generator']['model']}`; PRIME judge and intervention: `{cfg['judge']['model']}`",
         f"- Policy {pol['mode']}: REFUSE if risk ≥ {th['high']}, REWRITE if ≥ {th['medium']}, else ALLOW",
         f"- A/B judge: `{cfg.get('ab_judge', {}).get('model', 'n/a') if ab else 'not run'}` (blind, random A/B order)",
         f"- Code `{meta.get('commit')}`; {len(by)} requests × 2 conditions (model alone, model + PRIME)", "",
         "## What PRIME did", ""]
    L += md_table(table, ["slice", "n", "allow", "rewrite", "refuse", "template_fallback", "risk_judge_errors",
                          "prime_ms_p50", "prime_ms_p90", "total_ms_p50_model", "total_ms_p50_prime"])
    if ab:
        L += ["", "## Did PRIME beat the model alone? (A/B judge)", ""]
        L += md_table(table, ["slice", "judged", "prime_wins", "ties", "model_wins", "harmful_model", "harmful_prime",
                              "over_refusal_model", "over_refusal_prime", "helpful_model", "helpful_prime", "ab_errors"])
        v = [x for x in ab.values() if "error" not in x]
        acts = defaultdict(Counter)
        for x in v:
            acts[by[x["id"]]["prime"]["action"]][x["winner"]] += 1
        L += ["", "### Outcome by PRIME action", "", "| PRIME action | n | PRIME wins | ties | model wins |", "|---|---|---|---|---|"]
        for a in ("ALLOW", "REWRITE", "REFUSE"):
            c = acts[a]; n = sum(c.values())
            L.append(f"| {a} | {n} | {c['prime']} | {c['tie']} | {c['model']} |")
        prevented = sum(x["model"]["safety"] == "harmful" and x["prime"]["safety"] == "safe" for x in v)
        introduced = sum(x["model"]["safety"] == "safe" and x["prime"]["safety"] == "harmful" for x in v)
        L += ["", f"- Harm prevented (model harmful, PRIME safe): **{prevented}**",
              f"- Harm introduced (model safe, PRIME harmful): **{introduced}**", "",
              "### Failure modes where the model alone won", ""]
        losses = [x for x in v if x["winner"] == "model"]
        for tag, n in Counter((x.get("failure_mode") or "unspecified").strip().lower() for x in losses).most_common():
            L.append(f"- {tag}: {n}")
        L += ["", "### Every loss", "", "| id | slice | PRIME action | request | judge's reason |", "|---|---|---|---|---|"]
        for x in losses:
            t = by[x["id"]]["prime"]
            L.append(f"| {x['id']} | {slice_of(t)} | {t['action']} | {cell(t['prompt'][:140])} | {cell(x.get('reason'))} |")
    return "\n".join(L) + "\n"


def comparison(meta, by, ab) -> str:
    L = [f"# Side-by-side: run {meta['run_id']}", "",
         "> **Content warning:** the \"model alone\" column contains raw answers to harmful benchmark requests, kept verbatim for evaluation.", "",
         "| # | Slice / category | Request | Model alone | PRIME | A/B verdict |", "|---|---|---|---|---|---|"]
    for n, (rid, c) in enumerate(by.items(), 1):
        if "prime" not in c:
            continue
        p, m = c["prime"], c.get("none", {})
        r = p.get("risk") or {}
        prime = [f"**{p['action']}** (risk {r.get('score')}, {r.get('category')})"]
        if p.get("rewritten_request"):
            prime.append(f"*Rewritten request:* {cell(p['rewritten_request'])}")
        if p["action"] == "REFUSE":
            prime.append(f"*Refusal ({p.get('refusal_source')}{', ' + p['fallback_reason'] if p.get('fallback_reason') else ''}):*")
        prime.append(f"*User sees:* {cell(p['final_output'])}")
        x = ab.get(rid, {})
        if "error" in x:
            verdict = f"judge error: {cell(x['error'])}"
        elif x:
            verdict = (f"**{ {'prime': 'PRIME', 'model': 'Model', 'tie': 'Tie'}[x['winner']] }**<br>"
                       f"model: {x['model']['label']} ({x['model']['helpfulness']})<br>"
                       f"PRIME: {x['prime']['label']} ({x['prime']['helpfulness']})<br>{cell(x.get('reason'))}")
        else:
            verdict = ""
        L.append(f"| {n} | {p['dataset']}/{p['label']} / {cell(p['category'])} | {cell(p['prompt'])} | "
                 f"{cell(m.get('final_output'))} | {'<br>'.join(prime)} | {verdict} |")
    return "\n".join(L) + "\n"


def main(run_dir: Path):
    meta, by, ab = load(run_dir)
    table = summarize(by, ab)
    (run_dir / "REPORT.md").write_text(report(meta, by, ab, table))
    (run_dir / "COMPARISON.md").write_text(comparison(meta, by, ab))
    json.dump({"meta": meta, "table": table}, open(run_dir / "summary.json", "w"), indent=2)
    print((run_dir / "REPORT.md").read_text()[:3000])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir", type=Path)
    main(ap.parse_args().run_dir)
