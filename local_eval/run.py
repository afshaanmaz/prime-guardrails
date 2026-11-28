"""Run PRIME conditions over the benchmarks and save every trace.

  python run.py                                   # real run against the vLLM servers in config.yaml
  python run.py --sizes harmbench=50 xstest=150   # per-dataset sample sizes (spread across categories)
  python run.py --mock --limit 20                 # plumbing test, no GPU

Several protected models, PRIME computed once (its risk sensor and intervention see only the request):
  python run.py --decide-only --datasets harmbench xstest orbench    # needs only the risk sensor server
  python run.py --decisions results/<decide_run>/decisions.jsonl --generator llama   # needs only that model
Writes results/<run_id>/traces.jsonl (or decisions.jsonl) and meta.json.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import time
from dataclasses import asdict
from pathlib import Path

import yaml

import data
from monitor import Monitor, request_context
from prime_local import Chat, Policy, Prime, gather_limited
from risk import make_sensor

CONDITIONS = ["none", "prime"]   # model alone vs model + PRIME


def make_client(section: dict, role: str, mock: bool):
    if mock:
        from mock import MockClient
        return MockClient(role)
    from openai import AsyncOpenAI
    return AsyncOpenAI(base_url=section["base_url"], api_key="EMPTY", timeout=120)


async def main(args):
    cfg = yaml.safe_load(open(args.config))
    if args.generator:                       # pick a protected model from `generators:`
        cfg["generator"] = {**cfg["generator"], **cfg["generators"][args.generator], "name": args.generator}
    g, j = cfg["generator"], cfg["risk_sensor"]
    policy = Policy(**cfg["policy"])
    # The risk sensor's model also runs the Intervention step (separate prompts).
    rchat = Chat(make_client(j, "risk_sensor", args.mock), j["model"], j["max_tokens"], j["temperature"])
    prime = Prime(
        Chat(make_client(g, "generator", args.mock), g["model"], g["max_tokens"], g["temperature"]),
        make_sensor(j, rchat, policy),
        policy,
        intervener=rchat,
    )
    decisions = None
    if args.decisions:                       # stored PRIME decisions, keyed by request id
        decisions = {}
        for l in open(args.decisions):
            d = json.loads(l)
            decisions[d["id"]] = d
    limit = args.limit or cfg["run"]["limit"]
    sizes = dict(kv.split("=") for kv in (args.sizes or []))
    exclude = {json.loads(l)["id"] for d in (args.exclude or []) for l in open(Path(d) / "traces.jsonl")}
    suffix = "-decide" if args.decide_only else (f"-{args.generator}" if args.generator else "")
    run_id = time.strftime("%Y%m%d-%H%M%S") + suffix + ("-mock" if args.mock else "")
    out = Path("results") / run_id
    out.mkdir(parents=True)
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    except OSError:
        commit = ""
    meta = {"run_id": run_id, "mock": args.mock, "commit": commit, "config": cfg,
            "conditions": ["decide"] if args.decide_only else CONDITIONS,
            "generator": g.get("name", g["model"]), "decisions_from": args.decisions,
            "started": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    if args.title:
        meta["title"] = args.title
    concurrency = args.concurrency or cfg["run"]["concurrency"]
    # M: interaction records (docs/MONITORING.md); a decide-only run has no user-facing answers to record
    monitor = None if args.decide_only else Monitor.from_config(cfg, run_id, mock=args.mock)

    n = 0
    if decisions is not None:
        order = list(data.SOURCES)
        datasets = sorted({d["dataset"] for d in decisions.values()},
                          key=lambda x: order.index(x) if x in order else len(order))
    else:
        datasets = list(sizes) or args.datasets or cfg["run"]["datasets"]
    with open(out / ("decisions.jsonl" if args.decide_only else "traces.jsonl"), "w") as f:
        for ds in datasets:
            if decisions is not None:        # exactly the requests PRIME decided on, in the same order
                items = [d for d in decisions.values() if d["dataset"] == ds]
            else:
                items = data.load(ds, int(sizes[ds]) if ds in sizes else limit, exclude)
            if args.decide_only:
                t0 = time.time()
                ctxs = [request_context(run_id, it) for it in items]
                trs = await gather_limited([prime.decide(it["prompt"]) for it in ctxs], concurrency)
                for it, tr in zip(ctxs, trs):
                    f.write(json.dumps({**it, **asdict(tr)}) + "\n")
                n += len(items)
                print(f"{ds:10s} decide        {len(items):4d} prompts  {time.time()-t0:6.1f}s", flush=True)
                continue
            for cond in CONDITIONS:
                t0 = time.time()
                ctxs = [request_context(run_id, _item(it)) for it in items]
                traces = await gather_limited(
                    [prime.run(it["prompt"], cond, monitor, it,
                               decisions[it["id"]] if (decisions is not None and cond == "prime") else None)
                     for it in ctxs], concurrency)
                for it, tr in zip(ctxs, traces):
                    f.write(json.dumps({**it, **asdict(tr)}) + "\n")
                n += len(items)
                print(f"{ds:10s} {cond:13s} {len(items):4d} prompts  {time.time()-t0:6.1f}s", flush=True)
    if monitor:
        monitor.close()
    meta["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    meta["traces"] = n
    json.dump(meta, open(out / "meta.json", "w"), indent=2)
    if args.decide_only:
        print(f"\nSaved {n} decisions to {out}/decisions.jsonl. Next: python run.py --decisions {out}/decisions.jsonl --generator NAME")
    else:
        print(f"\nSaved {n} traces to {out}. Next: python evaluate.py {out} && python report.py {out}")


ITEM_KEYS = ("id", "dataset", "prompt", "label", "category")


def _item(d: dict) -> dict:
    """A benchmark item, from a data.load() row or a stored decision row."""
    return {k: d[k] for k in ITEM_KEYS if k in d}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--datasets", nargs="+", help="override run.datasets, e.g. --datasets harmbench")
    ap.add_argument("--sizes", nargs="+", metavar="DATASET=N", help="per-dataset sizes; implies --datasets")
    ap.add_argument("--exclude", nargs="+", metavar="RUN_DIR", help="skip requests used in these runs (e.g. the pilot)")
    ap.add_argument("--decide-only", action="store_true",
                    help="run only PRIME's decision (R + P + I) for each request; writes decisions.jsonl")
    ap.add_argument("--decisions", metavar="FILE", help="reuse stored PRIME decisions (decisions.jsonl) for the prime condition")
    ap.add_argument("--generator", metavar="NAME", help="protected model from config `generators:` (default: `generator:`)")
    ap.add_argument("--concurrency", type=int, help="override run.concurrency")
    ap.add_argument("--title", help="short human title for this run (shown on the results site)")
    asyncio.run(main(ap.parse_args()))
