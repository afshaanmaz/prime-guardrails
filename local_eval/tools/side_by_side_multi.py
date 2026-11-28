"""Build one filterable side-by-side HTML for several protected models that share the same PRIME decisions.

Each request shows the question, PRIME's decision (action, rewrite, risk) once, then one column per protected
model: its answer alone, its answer with PRIME, and the evaluator's preference.
Usage: python tools/side_by_side_multi.py OUT.html results/<run_zephyr> results/<run_llama> ...
"""
import ast, json, sys, pathlib

NAMES = {"zephyr": "Zephyr-7B", "llama": "Llama 3.1 8B", "gemma2b": "Gemma 2 2B", "deepseek": "DeepSeek V4.1-Flash"}
WIN = {"prime": "PRIME", "model": "Model", "tie": "Tie"}


def _risk(t):
    r = t.get("risk")
    if isinstance(r, str):
        try: r = ast.literal_eval(r)
        except Exception: r = {}
    return r or {}


def build(out: pathlib.Path, runs: list[pathlib.Path]) -> pathlib.Path:
    models, reqs = [], {}
    for run in map(pathlib.Path, runs):
        meta = json.load(open(run / "meta.json"))
        key = meta.get("generator") or run.name
        name = NAMES.get(key, key)
        models.append({"key": key, "name": name, "run": run.name})
        ev_path = run / "evaluator.jsonl"
        evals = {e["id"]: e for e in map(json.loads, open(ev_path))} if ev_path.exists() else {}
        by = {}
        for t in map(json.loads, open(run / "traces.jsonl")):
            by.setdefault(t["id"], {})[t["condition"]] = t
        for rid, d in by.items():
            m, p, e = d.get("none", {}), d.get("prime", {}), evals.get(rid, {})
            r = _risk(p)
            row = reqs.setdefault(rid, {
                "id": rid, "slice": f'{p.get("dataset")}/{p.get("label")}', "question": p.get("prompt") or m.get("prompt"),
                "rewrite": p.get("rewritten_request") or "", "action": p.get("action"), "level": r.get("level") or "—",
                "category": r.get("category") or "None", "intent": r.get("intent") or "", "m": {}})
            row["m"][key] = {
                "alone": m.get("final_output") or "", "prime": p.get("final_output") or "",
                "win": WIN.get(e.get("winner"), "Not scored"), "reason": e.get("reason", ""),
                "alone_safety": (e.get("model") or {}).get("safety", "—"), "prime_safety": (e.get("prime") or {}).get("safety", "—"),
                "alone_label": (e.get("model") or {}).get("label", ""), "prime_label": (e.get("prime") or {}).get("label", "")}
    rows = list(reqs.values())
    for i, r in enumerate(rows):
        r["n"] = i + 1
    data = json.dumps({"models": models, "rows": rows}).replace("</", "<\\/")
    tpl = open(pathlib.Path(__file__).with_name("side_by_side_multi.html.tpl")).read()
    out = pathlib.Path(out)
    out.write_text(tpl.replace("__DATA__", data).replace("__MODELS__", ", ".join(m["name"] for m in models)))
    return out


if __name__ == "__main__":
    print(build(pathlib.Path(sys.argv[1]), [pathlib.Path(a) for a in sys.argv[2:]]))
