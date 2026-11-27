"""Build a filterable side-by-side HTML for one run: question, rewrite, model alone, PRIME, evaluator preference."""
# Usage: python tools/side_by_side.py results/<run_id>  -> results/<run_id>/SIDE_BY_SIDE.html
import ast, json, sys, pathlib
run = pathlib.Path(sys.argv[1])
traces = [json.loads(l) for l in open(run / "traces.jsonl")]
evals = {e["id"]: e for e in map(json.loads, open(run / "evaluator.jsonl"))}
by = {}
for t in traces:
    by.setdefault(t["id"], {})[t["condition"]] = t
def risk(t):
    r = t.get("risk")
    if isinstance(r, str):
        try: r = ast.literal_eval(r)
        except Exception: r = {}
    return r or {}
rows = []
for i, (k, d) in enumerate(by.items()):
    m, p, e = d.get("none", {}), d.get("prime", {}), evals.get(k, {})
    r = risk(p)
    win = {"prime": "PRIME", "model": "Model", "tie": "Tie"}.get(e.get("winner"), "—")
    rows.append({
        "n": i + 1, "id": k, "slice": f'{p.get("dataset")}/{p.get("label")}',
        "question": p.get("prompt") or m.get("prompt"),
        "rewrite": p.get("rewritten_request") or "",
        "model": m.get("final_output") or "", "prime": p.get("final_output") or "",
        "action": p.get("action"), "level": r.get("level") or "—", "category": r.get("category") or "None",
        "intent": r.get("intent") or "", "win": win, "reason": e.get("reason", ""),
        "model_safety": (e.get("model") or {}).get("safety", "—"), "prime_safety": (e.get("prime") or {}).get("safety", "—"),
        "model_label": (e.get("model") or {}).get("label", ""), "prime_label": (e.get("prime") or {}).get("label", ""),
    })
meta = json.load(open(run / "meta.json")) if (run / "meta.json").exists() else {}
data = json.dumps({"run": run.name, "rows": rows}).replace("</", "<\\/")
html = open(pathlib.Path(__file__).with_name("side_by_side.html.tpl")).read().replace("__DATA__", data).replace("__RUN__", run.name)
out = run / "SIDE_BY_SIDE.html"
out.write_text(html)
print(out, len(rows))
