"""Run PRIME conditions over the benchmarks and save every trace.

  python run.py                                   # real run against the vLLM servers in config.yaml
  python run.py --sizes harmbench=50 xstest=150   # per-dataset sample sizes (spread across categories)
  python run.py --mock --limit 20                 # plumbing test, no GPU
Writes results/<run_id>/traces.jsonl and meta.json.
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

CONDITIONS = ["none", "prime"]   # model alone vs model + PRIME


def make_client(section: dict, role: str, mock: bool):
    if mock:
        from mock import MockClient
        return MockClient(role)
    from openai import AsyncOpenAI
    return AsyncOpenAI(base_url=section["base_url"], api_key="EMPTY", timeout=120)


async def main(args):
    cfg = yaml.safe_load(open(args.config))
    g, j = cfg["generator"], cfg["risk_sensor"]
    prime = Prime(
        Chat(make_client(g, "generator", args.mock), g["model"], g["max_tokens"], g["temperature"]),
        Chat(make_client(j, "risk_sensor", args.mock), j["model"], j["max_tokens"], j["temperature"]),
        Policy(**cfg["policy"]),
    )
    limit = args.limit or cfg["run"]["limit"]
    sizes = dict(kv.split("=") for kv in (args.sizes or []))
    run_id = time.strftime("%Y%m%d-%H%M%S") + ("-mock" if args.mock else "")
    out = Path("results") / run_id
    out.mkdir(parents=True)
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    except OSError:
        commit = ""
    meta = {"run_id": run_id, "mock": args.mock, "commit": commit, "config": cfg,
            "conditions": CONDITIONS, "started": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    monitor = Monitor.from_config(cfg, run_id, mock=args.mock)   # M: interaction records (docs/MONITORING.md)

    n = 0
    with open(out / "traces.jsonl", "w") as f:
        for ds in list(sizes) or args.datasets or cfg["run"]["datasets"]:
            items = data.load(ds, int(sizes[ds]) if ds in sizes else limit)
            for cond in CONDITIONS:
                t0 = time.time()
                ctxs = [request_context(run_id, it) for it in items]
                traces = await gather_limited([prime.run(it["prompt"], cond, monitor, it) for it in ctxs],
                                              cfg["run"]["concurrency"])
                for it, tr in zip(ctxs, traces):
                    f.write(json.dumps({**it, **asdict(tr)}) + "\n")
                n += len(items)
                print(f"{ds:10s} {cond:13s} {len(items):4d} prompts  {time.time()-t0:6.1f}s")
    if monitor:
        monitor.close()
    meta["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    meta["traces"] = n
    json.dump(meta, open(out / "meta.json", "w"), indent=2)
    print(f"\nSaved {n} traces to {out}. Next: python evaluate.py {out} && python report.py {out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--datasets", nargs="+", help="override run.datasets, e.g. --datasets harmbench")
    ap.add_argument("--sizes", nargs="+", metavar="DATASET=N", help="per-dataset sizes; implies --datasets")
    asyncio.run(main(ap.parse_args()))
