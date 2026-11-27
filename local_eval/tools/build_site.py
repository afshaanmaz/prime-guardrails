"""Build the experiments site: an index page plus one side-by-side page per run.

Usage: python tools/build_site.py OUT_DIR RESULTS_DIR [RESULTS_DIR ...]
Runs are listed in tools/experiments.json (name, branch, verbal description of code changes, finding).
Each run's results/<run_id>/ (traces.jsonl, evaluator.jsonl, meta.json) is looked up in the RESULTS_DIRs.
"""
import json, statistics, sys, pathlib, ast, html
from datetime import datetime, timezone, timedelta
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import side_by_side

REPO = "https://github.com/afshaanmaz/prime-guardrails"
PST = timezone(timedelta(hours=-8))


def find(run_id, roots):
    for r in roots:
        p = pathlib.Path(r) / run_id
        if (p / "traces.jsonl").exists():
            return p
    raise SystemExit(f"run {run_id} not found in {roots}")


def metrics(run):
    tr = [json.loads(l) for l in open(run / "traces.jsonl")]
    ev = [json.loads(l) for l in open(run / "evaluator.jsonl")]
    p = [t for t in tr if t["condition"] == "prime"]
    win = {k: sum(e.get("winner") == k for e in ev) for k in ("prime", "tie", "model")}
    safe = [t for t in p if t["dataset"] == "xstest" and t["label"] == "safe"]
    return {
        "n": len(p), "win": win,
        "harm_model": sum((e.get("model") or {}).get("safety") == "harmful" for e in ev),
        "harm_prime": sum((e.get("prime") or {}).get("safety") == "harmful" for e in ev),
        "xs_safe": len(safe),
        "xs_refused": sum(t["action"] == "REFUSE" for t in safe),
        "xs_rewritten": sum(t["action"] == "REWRITE" for t in safe),
        "rewrites": sum(t["action"] == "REWRITE" for t in p),
        "risk_ms": statistics.median(float(t.get("risk_ms") or 0) for t in p),
        "datasets": sorted({t["dataset"] for t in p}),
    }


def when(run_id):
    t = datetime.strptime(run_id, "%Y%m%d-%H%M%S").replace(tzinfo=timezone.utc).astimezone(PST)
    return t.strftime("%a %d %b %Y, %-I:%M %p PST")


def main(out, roots):
    out = pathlib.Path(out); out.mkdir(parents=True, exist_ok=True)
    runs = json.load(open(pathlib.Path(__file__).with_name("experiments.json")))
    cards = []
    for x in reversed(runs):                       # newest first
        run = find(x["run_id"], roots)
        meta = json.load(open(run / "meta.json"))
        commit = meta.get("commit", "?")
        m = metrics(run)
        side_by_side.build(run, out / f"{x['run_id']}.html")
        e = html.escape
        res = f"{REPO}/tree/{x['branch']}/local_eval/results/{x['run_id']}"
        cards.append(f"""
<article class="run">
  <div class="head"><h2>{e(x['name'])}</h2><span class="when">{when(x['run_id'])}</span></div>
  <div class="meta">run <code>{x['run_id']}</code> · branch <a href="{REPO}/tree/{e(x['branch'])}"><code>{e(x['branch'])}</code></a>
   · commit <a href="{REPO}/commit/{commit}"><code>{commit}</code></a> · {m['n']} requests ({', '.join(m['datasets'])})</div>
  <p><b>What changed in the code.</b> {e(x['changes'])}</p>
  <p><b>What we found.</b> {e(x['finding'])}</p>
  <div class="stats">
    <div><span>{m['win']['prime']} / {m['win']['tie']} / {m['win']['model']}</span>PRIME / tie / model alone preferred</div>
    <div><span>{m['harm_model']} → {m['harm_prime']}</span>harmful answers, model alone → PRIME</div>
    <div><span>{m['xs_refused']} / {m['xs_safe']}</span>harmless XSTest prompts refused ({m['xs_rewritten']} rewritten)</div>
    <div><span>{m['rewrites']}</span>REWRITEs</div>
    <div><span>{m['risk_ms']/1000:.1f} s</span>median risk sensor time</div>
  </div>
  <div class="links"><a class="btn" href="{x['run_id']}.html">Side by side →</a>
    <a href="{res}/REPORT.md">Report</a> <a href="{res}/COMPARISON.md">All rows (markdown)</a> <a href="{res}">Raw files</a></div>
</article>""")
    page = TEMPLATE.replace("__CARDS__", "\n".join(cards)).replace(
        "__UPDATED__", datetime.now(PST).strftime("%a %d %b %Y, %-I:%M %p PST"))
    (out / "index.html").write_text(page)
    (out / "robots.txt").write_text("User-agent: *\nDisallow: /\n")
    (out / ".nojekyll").write_text("")
    print(f"built {len(runs)} runs -> {out}")


TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex, nofollow"><title>PRIME experiments</title>
<style>
:root{--bg:#fafaf9;--card:#fff;--ink:#1c1917;--mute:#78716c;--line:#e7e5e4;--acc:#1d4ed8;--chip:#f5f5f4}
@media (prefers-color-scheme:dark){:root{--bg:#0c0a09;--card:#1c1917;--ink:#f5f5f4;--mute:#a8a29e;--line:#292524;--acc:#93c5fd;--chip:#292524}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}
.wrap{max-width:920px;margin:0 auto;padding:24px 16px 48px}h1{font-size:22px;margin:0}
.sub{color:var(--mute);font-size:13px;margin:4px 0 20px}a{color:var(--acc)}code{font-size:12.5px}
.run{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;margin-bottom:16px}
.head{display:flex;justify-content:space-between;align-items:baseline;gap:8px;flex-wrap:wrap}.head h2{margin:0;font-size:18px}
.when{color:var(--mute);font-size:13px}.meta{color:var(--mute);font-size:12.5px;margin:4px 0 8px}
.run p{margin:6px 0}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px;margin:12px 0}
.stats div{background:var(--chip);border-radius:8px;padding:8px;font-size:12px;color:var(--mute)}
.stats span{display:block;font-size:18px;font-weight:650;color:var(--ink)}
.links{display:flex;gap:14px;align-items:center;flex-wrap:wrap;font-size:13.5px}
.btn{background:var(--ink);color:var(--bg);padding:6px 12px;border-radius:8px;text-decoration:none;font-weight:600}
</style></head><body><div class="wrap">
<h1>PRIME experiments</h1>
<div class="sub">Zephyr-7B alone vs Zephyr + PRIME, scored by a blind evaluator (Llama 4 Maverick). Newest first. Updated __UPDATED__.
Plan and decisions: <a href="https://github.com/afshaanmaz/prime-guardrails/blob/eval/prime-v1/local_eval/docs/EXPERIMENTATION_PLAN.md">EXPERIMENTATION_PLAN.md</a>.
Side-by-side pages include harmful model outputs.</div>
__CARDS__
</div></body></html>"""

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:])
