"""One-off: turn existing runs (results/<run_id>/traces.jsonl + evaluator.jsonl) into monitoring records.

  python infra/backfill_monitoring.py results/20261126-104223 --source pilot            # to the configured sink
  python infra/backfill_monitoring.py results/20261126-104223 --source pilot --sink local

Re-running is safe: request ids are derived from (run, dataset, item, condition) and each run is written
to fixed file names (<run_id>-backfill-0000.jsonl), which are overwritten, not duplicated.
Old traces have no timestamps: `ts` is estimated as the run's start time plus the running sum of
total_ms in file order (the runs used concurrency 1). Evaluation `ts` is the run's finish time.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
from monitor import Monitor, evaluation_record, interaction_record, iso, stable_request_id  # noqa: E402


def parse_time(s: str) -> float:
    return dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%S%z").timestamp()


def backfill(run_dir: Path, cfg: dict, source: str) -> tuple[int, int]:
    run_id = run_dir.name
    meta = json.load(open(run_dir / "meta.json"))
    rc = meta["config"]
    models = {"risk": rc["risk_sensor"]["model"], "intervention": rc["risk_sensor"]["model"],
              "protected": rc["generator"]["model"]}
    t = parse_time(meta["started"])
    end = parse_time(meta["finished"]) if meta.get("finished") else t
    rows = [json.loads(line) for line in open(run_dir / "traces.jsonl")]

    def mon(table):
        m = Monitor.from_config(cfg, run_id, table=table)
        m.source, m.tag, m.console = source, "backfill", False
        m.flush_every, m.flush_seconds = 10**9, float("inf")   # one file per table
        return m

    im = mon("interactions")
    for r in rows:
        ctx = {**r, "request_id": stable_request_id(run_id, r["dataset"], r["id"], r["condition"]),
               "pair_id": f"{run_id}:{r['id']}"}
        im.record(interaction_record(r, ctx, prompt=r["prompt"], run_id=run_id, source=source,
                                     models=models, policy=rc["policy"], ts=iso(t)))
        t += (r.get("total_ms") or 0) / 1000
    im.close()

    n_eval = 0
    ev_path = run_dir / "evaluator.jsonl"
    if ev_path.exists():
        by = {(r["dataset"], r["id"], r["condition"]): r for r in rows}
        em = mon("evaluations")
        for v in map(json.loads, open(ev_path)):
            em.record(evaluation_record(v, by[(v["dataset"], v["id"], "none")], by[(v["dataset"], v["id"], "prime")],
                                        run_id=run_id, source=source,
                                        evaluator_model=rc.get("evaluator", {}).get("model", "unknown"), ts=iso(end)))
            n_eval += 1
        em.close()
    print(f"{run_id}: {len(rows)} interaction records, {n_eval} evaluation records ({source}) -> "
          f"{', '.join(im.written + (em.written if n_eval else []))}")
    return len(rows), n_eval


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dirs", nargs="+", type=Path)
    ap.add_argument("--source", required=True, help="tag for the records, e.g. pilot or v1")
    ap.add_argument("--sink", choices=["gcs", "local"], help="override monitoring.sink in config.yaml")
    ap.add_argument("--config", default=str(HERE / "config.yaml"))
    a = ap.parse_args()
    if a.sink:
        os.environ["PRIME_MONITOR_SINK"] = a.sink
    c = yaml.safe_load(open(a.config))
    for d in a.run_dirs:
        backfill(d, c, a.source)
