"""M: PRIME's monitoring. One record per interaction, end to end, batched to the bucket.

Every request PRIME handles (and every model-alone baseline answer in an eval run) becomes one
**interaction record**. The evaluator LLM adds **evaluation records** later, linked by `pair_id`
and `request_id`. Records are buffered and written as new JSONL files (never rewritten) to

  gs://<bucket>/monitoring/<table>/dt=YYYY-MM-DD/<run_id>-<tag>-<seq>.jsonl     (sink: gcs)
  <local_dir>/<table>/dt=YYYY-MM-DD/<run_id>-<tag>-<seq>.jsonl                  (sink: local)

BigQuery reads those files as external tables (infra/setup-monitoring.sh). See docs/MONITORING.md.

  python monitor.py ddl     # print the BigQuery DDL (dataset, tables, view) built from the schemas below
"""
from __future__ import annotations

import atexit
import datetime as dt
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

HERE = Path(__file__).parent

# Column name -> BigQuery type. The single source of truth for the record shape and the tables.
INTERACTION_SCHEMA = {
    # Request
    "request_id": "STRING", "pair_id": "STRING", "ts": "TIMESTAMP", "source": "STRING", "run_id": "STRING",
    "condition": "STRING", "dataset": "STRING", "dataset_id": "STRING", "dataset_label": "STRING",
    "dataset_category": "STRING", "original_request": "STRING",
    # R: risk
    "risk_score": "FLOAT64", "risk_category": "STRING", "risk_reason": "STRING", "risk_intent": "STRING",
    "risk_error": "STRING", "risk_model": "STRING",
    # P: policy
    "action": "STRING", "policy_mode": "STRING", "policy_hash": "STRING", "topic_rule": "STRING",
    # I: intervention
    "rewritten_request": "STRING", "refusal_source": "STRING", "fallback_reason": "STRING",
    "intervention_model": "STRING",
    # Protected model
    "model_input": "STRING", "model_output": "STRING", "protected_model": "STRING",
    # Outcome
    "final_response": "STRING", "risk_ms": "FLOAT64", "intervention_ms": "FLOAT64", "gen_ms": "FLOAT64",
    "prime_ms": "FLOAT64", "total_ms": "FLOAT64", "errors": "ARRAY<STRING>",
}

EVALUATION_SCHEMA = {
    "eval_id": "STRING", "pair_id": "STRING", "prime_request_id": "STRING", "model_request_id": "STRING",
    "ts": "TIMESTAMP", "source": "STRING", "run_id": "STRING", "dataset": "STRING", "dataset_id": "STRING",
    "evaluator_model": "STRING", "winner": "STRING", "prime_was": "STRING", "identical": "BOOL",
    "prime_safety": "STRING", "prime_helpfulness": "INT64", "prime_label": "STRING",
    "model_safety": "STRING", "model_helpfulness": "INT64", "model_label": "STRING",
    "failure_mode": "STRING", "reason": "STRING", "evaluator_ms": "FLOAT64", "error": "STRING",
}


def iso(epoch: float | None = None) -> str:
    """UTC ISO timestamp with milliseconds, e.g. 2026-11-26T10:42:23.123Z."""
    d = dt.datetime.fromtimestamp(time.time() if epoch is None else epoch, dt.timezone.utc)
    return d.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def policy_hash(policy: dict | None) -> str | None:
    if not policy:
        return None
    return hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest()[:12]


def stable_request_id(run_id: str, dataset: str, item_id: str, condition: str) -> str:
    """Deterministic id for records rebuilt from an old run (backfill, or evaluating a run made
    before monitoring existed), so re-running doesn't create duplicates."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"prime/{run_id}/{dataset}/{item_id}/{condition}"))


def request_context(run_id: str, item: dict) -> dict:
    """An eval item plus the ids monitoring needs. run.py passes this to Prime.run and also writes
    request_id and pair_id into traces.jsonl, so evaluate.py can link its verdicts."""
    return {**item, "request_id": str(uuid.uuid4()), "pair_id": f"{run_id}:{item['id']}"}


def _ms(x):
    return None if x is None else round(float(x), 1)


def interaction_record(trace: dict, ctx: dict | None, *, prompt: str, run_id: str, source: str,
                       models: dict, policy: dict | None, ts: str | None = None) -> dict:
    """Flatten one Trace (as a dict) plus its context into an interaction record."""
    ctx = ctx or {}
    prime = trace.get("condition") == "prime"
    risk = trace.get("risk") or {}
    action = trace.get("action")
    if not prime and action != "ERROR":
        action = None                      # model alone: no policy decision was made
    model_called = trace.get("action") != "REFUSE"
    intervened = prime and trace.get("action") in ("REWRITE", "REFUSE")
    return {
        "request_id": ctx.get("request_id") or str(uuid.uuid4()),
        "pair_id": ctx.get("pair_id"),
        "ts": ts or iso(),
        "source": source,
        "run_id": run_id,
        "condition": trace.get("condition"),
        "dataset": ctx.get("dataset"),
        "dataset_id": ctx.get("id"),
        "dataset_label": ctx.get("label"),
        "dataset_category": ctx.get("category"),
        "original_request": prompt,
        "risk_score": risk.get("score"),
        "risk_category": risk.get("category"),
        "risk_reason": risk.get("reason"),
        "risk_intent": risk.get("intent") or None,
        "risk_error": risk.get("error"),
        "risk_model": models.get("risk") if prime else None,
        "action": action,
        "policy_mode": (policy or {}).get("mode") if prime else None,
        "policy_hash": policy_hash(policy) if prime else None,
        "topic_rule": risk.get("topic_rule"),
        "rewritten_request": trace.get("rewritten_request"),
        "refusal_source": trace.get("refusal_source"),
        "fallback_reason": trace.get("fallback_reason"),
        "intervention_model": models.get("intervention") if intervened else None,
        "model_input": (trace.get("rewritten_request") or prompt) if model_called else None,
        "model_output": trace.get("raw_generation"),
        "protected_model": models.get("protected"),
        "final_response": trace.get("final_output"),
        "risk_ms": _ms(trace.get("risk_ms")) if prime else None,
        "intervention_ms": _ms(trace.get("intervention_ms")) if prime else None,
        "gen_ms": _ms(trace.get("gen_ms")) if model_called else None,
        "prime_ms": _ms(trace.get("prime_ms")) if prime else None,
        "total_ms": _ms(trace.get("total_ms")),
        "errors": list(trace.get("errors") or []),
    }


def evaluation_record(result: dict, model_row: dict, prime_row: dict, *, run_id: str, source: str,
                      evaluator_model: str, ts: str | None = None) -> dict:
    """Flatten one evaluate.py verdict (or an evaluator.jsonl row) into an evaluation record."""
    def rid(row, cond):
        return row.get("request_id") or stable_request_id(run_id, row["dataset"], row["id"], cond)
    p, m = result.get("prime") or {}, result.get("model") or {}
    return {
        "eval_id": str(uuid.uuid4()),
        "pair_id": prime_row.get("pair_id") or f"{run_id}:{prime_row['id']}",
        "prime_request_id": rid(prime_row, "prime"),
        "model_request_id": rid(model_row, "none"),
        "ts": ts or iso(),
        "source": source,
        "run_id": run_id,
        "dataset": result.get("dataset"),
        "dataset_id": result.get("id"),
        "evaluator_model": evaluator_model,
        "winner": result.get("winner"),
        "prime_was": result.get("prime_was"),
        "identical": result.get("identical"),
        "prime_safety": p.get("safety"), "prime_helpfulness": p.get("helpfulness"), "prime_label": p.get("label"),
        "model_safety": m.get("safety"), "model_helpfulness": m.get("helpfulness"), "model_label": m.get("label"),
        "failure_mode": result.get("failure_mode"),
        "reason": result.get("reason"),
        "evaluator_ms": result.get("evaluator_ms"),
        "error": result.get("error"),
    }


def console_line(r: dict) -> str:
    risk = "" if r["risk_score"] is None else r["risk_score"]
    return (f"[M] {r['run_id']} {r['dataset'] or '-'}/{r['dataset_id'] or r['request_id'][:8]} {r['condition']} "
            f"action={r['action'] or '-'} risk={risk} cat={r['risk_category'] or '-'} ms={round(r['total_ms'] or 0)}")


# ---------------------------------------------------------------- sinks

class LocalSink:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        if not self.root.is_absolute():
            self.root = HERE / self.root

    def write(self, relpath: str, data: bytes) -> str:
        path = self.root / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return str(path)


class GcsSink:
    """Writes with google-cloud-storage if it is installed and has credentials, else `gcloud storage cp`."""

    def __init__(self, prefix: str):
        if not prefix.startswith("gs://"):
            raise ValueError(f"gcs_prefix must start with gs://, got {prefix!r}")
        self.prefix = prefix.rstrip("/")
        self.bucket, _, self.base = self.prefix[5:].partition("/")
        self._client = None
        self._use_lib = True   # set to False once the library turns out to be missing or has no credentials

    def write(self, relpath: str, data: bytes) -> str:
        uri = f"{self.prefix}/{relpath}"
        if self._use_lib:
            try:
                from google.cloud import storage  # optional dependency
                self._client = self._client or storage.Client()
            except Exception:  # noqa: BLE001 - not installed or no credentials: use the CLI from now on
                self._use_lib = False
        if self._use_lib:
            name = f"{self.base}/{relpath}" if self.base else relpath
            self._client.bucket(self.bucket).blob(name).upload_from_string(data, content_type="application/json")
            return uri
        if not shutil.which("gcloud"):
            raise RuntimeError("neither google-cloud-storage nor the gcloud CLI can write to GCS")
        with tempfile.NamedTemporaryFile(suffix=".jsonl") as f:
            f.write(data)
            f.flush()
            subprocess.run(["gcloud", "storage", "cp", "--quiet", f.name, uri],
                           check=True, capture_output=True, text=True, timeout=120)
        return uri


# ---------------------------------------------------------------- monitor

class Monitor:
    """Buffers records and writes each batch as one new JSONL file.

    Flushes every `flush_every` records, when the oldest buffered record is `flush_seconds` old
    (checked by a background thread), and on close() (also registered with atexit). A failed GCS
    write falls back to the local directory, so a record is never silently dropped."""

    def __init__(self, sink, table: str, run_id: str, source: str, *, flush_every: int = 20,
                 flush_seconds: float = 60, console: bool = True, tag: str | None = None,
                 fallback: LocalSink | None = None):
        self.sink, self.table, self.run_id, self.source = sink, table, run_id, source
        self.flush_every, self.flush_seconds, self.console = flush_every, flush_seconds, console
        self.tag = tag or uuid.uuid4().hex[:6]   # keeps file names unique if a run_id is reused
        self.fallback = fallback
        self.buf: list[dict] = []
        self.first_at: float | None = None
        self.seq = 0
        self.written: list[str] = []
        self.models: dict = {}
        self.policy: dict | None = None
        self._lock = threading.Lock()
        self._closed = False
        if flush_seconds:
            threading.Thread(target=self._timer, daemon=True).start()
        atexit.register(self.close)

    @classmethod
    def from_config(cls, cfg: dict, run_id: str, *, mock: bool = False, table: str = "interactions"):
        """Build from config.yaml's `monitoring:` section. Returns None when monitoring is off.
        Env overrides: PRIME_MONITOR_SINK (gcs / local / off), PRIME_MONITOR_SOURCE.
        Mock runs are always tagged source "test" and write locally unless PRIME_MONITOR_SINK says otherwise."""
        m = cfg.get("monitoring") or {}
        sink_name = os.environ.get("PRIME_MONITOR_SINK") or ("local" if mock else m.get("sink", "local"))
        if not m.get("enabled", True) and "PRIME_MONITOR_SINK" not in os.environ or sink_name == "off":
            return None
        local = LocalSink(m.get("local_dir", "results/monitoring"))
        if sink_name == "gcs":
            prefix = m.get("gcs_prefix") or f"gs://{cfg['infra']['results_bucket']}/monitoring"
            sink, fallback = GcsSink(prefix), local
        elif sink_name == "local":
            sink, fallback = local, None
        else:
            raise ValueError(f"monitoring sink must be gcs, local or off, got {sink_name!r}")
        source = "test" if mock else os.environ.get("PRIME_MONITOR_SOURCE") or m.get("source", "v1")
        return cls(sink, table, run_id, source, flush_every=m.get("flush_every", 20),
                   flush_seconds=m.get("flush_seconds", 60), console=m.get("console", True), fallback=fallback)

    def record(self, rec: dict) -> None:
        with self._lock:
            self.buf.append(rec)
            self.first_at = self.first_at or time.monotonic()
            full = len(self.buf) >= self.flush_every
        if self.console and self.table == "interactions":
            print(console_line(rec), flush=True)
        if full:
            self.flush()

    def record_interaction(self, prime, prompt: str, trace, context: dict | None, started: float) -> dict:
        """Called by Prime.run at the end of each request. `started`: epoch seconds when it arrived."""
        from dataclasses import asdict
        if not self.models:
            self.models = {"risk": prime.sensor.model, "intervention": prime.intervener.model,
                           "protected": prime.gen.model}
            self.policy = asdict(prime.policy)
        rec = interaction_record(asdict(trace), context, prompt=prompt, run_id=self.run_id, source=self.source,
                                 models=self.models, policy=self.policy, ts=iso(started))
        self.record(rec)
        return rec

    def flush(self) -> str | None:
        with self._lock:
            batch, self.buf, self.first_at = self.buf, [], None
            if not batch:
                return None
            seq, self.seq = self.seq, self.seq + 1
        day = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
        relpath = f"{self.table}/dt={day}/{self.run_id}-{self.tag}-{seq:04d}.jsonl"
        data = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in batch).encode()
        try:
            where = self.sink.write(relpath, data)
        except Exception as e:  # noqa: BLE001 - monitoring must never break serving
            if not self.fallback:
                print(f"[M] WARNING: could not write {len(batch)} records: {e}", file=sys.stderr)
                return None
            where = self.fallback.write(relpath, data)
            print(f"[M] WARNING: GCS write failed ({type(e).__name__}: {str(e)[:200]}); kept locally at {where}",
                  file=sys.stderr)
        self.written.append(where)
        if self.console:
            print(f"[M] wrote {len(batch)} {self.table} records -> {where}", flush=True)
        return where

    def _timer(self) -> None:
        while not self._closed:
            time.sleep(1)
            if self.first_at and time.monotonic() - self.first_at >= self.flush_seconds:
                self.flush()

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self.flush()


def record_evaluations(cfg: dict, run_dir: Path, pairs: list, results: list, *, mock: bool = False) -> None:
    """Called by evaluate.py: one evaluation record per verdict. `pairs` holds (item, model_row, prime_row)
    in the same order as `results`."""
    run_dir = Path(run_dir)
    meta_path = run_dir / "meta.json"
    run_mock = mock or (json.load(open(meta_path)).get("mock", False) if meta_path.exists() else False)
    mon = Monitor.from_config(cfg, run_dir.name, mock=run_mock, table="evaluations")
    if not mon:
        return
    evaluator_model = "mock" if mock else cfg["evaluator"]["model"]
    for (_, model_row, prime_row), res in zip(pairs, results):
        mon.record(evaluation_record(res, model_row, prime_row, run_id=run_dir.name, source=mon.source,
                                     evaluator_model=evaluator_model))
    mon.close()


# ---------------------------------------------------------------- BigQuery DDL

def ddl(project: str, dataset: str, prefix: str, location: str = "US") -> str:
    def cols(schema):
        return ",\n  ".join(f"`{k}` {v}" for k, v in schema.items())

    out = [f"CREATE SCHEMA IF NOT EXISTS `{project}.{dataset}` OPTIONS (location = '{location}');"]
    for table, schema in (("interactions", INTERACTION_SCHEMA), ("evaluations", EVALUATION_SCHEMA)):
        out.append(f"""CREATE OR REPLACE EXTERNAL TABLE `{project}.{dataset}.{table}` (
  {cols(schema)}
)
WITH PARTITION COLUMNS (dt DATE)
OPTIONS (
  format = 'NEWLINE_DELIMITED_JSON',
  uris = ['{prefix}/{table}/*'],
  hive_partition_uri_prefix = '{prefix}/{table}',
  require_hive_partition_filter = false,
  ignore_unknown_values = true
);""")
    # Latest verdict per pair, then each interaction gets the verdict for its own side.
    out.append(f"""CREATE OR REPLACE VIEW `{project}.{dataset}.interactions_with_eval` AS
WITH ev AS (
  SELECT * FROM `{project}.{dataset}.evaluations`
  WHERE error IS NULL
  QUALIFY ROW_NUMBER() OVER (PARTITION BY pair_id ORDER BY ts DESC) = 1
)
SELECT
  i.*,
  ev.eval_id, ev.evaluator_model, ev.ts AS eval_ts, ev.winner, ev.failure_mode, ev.reason AS eval_reason,
  IF(i.condition = 'prime', ev.prime_safety, ev.model_safety) AS safety,
  IF(i.condition = 'prime', ev.prime_helpfulness, ev.model_helpfulness) AS helpfulness,
  IF(i.condition = 'prime', ev.prime_label, ev.model_label) AS eval_label,
  IF(ev.eval_id IS NULL, NULL, IF(i.condition = 'prime', ev.prime_safety, ev.model_safety) = 'harmful') AS is_harmful,
  IF(ev.eval_id IS NULL, NULL, IF(i.condition = 'prime', ev.prime_label, ev.model_label) = 'over_refusal') AS is_over_refusal,
  IF(ev.eval_id IS NULL, NULL, ev.winner = IF(i.condition = 'prime', 'prime', 'model')) AS won,
  IF(i.condition = 'prime', 'model + PRIME', 'model alone') AS condition_name,
  i.fallback_reason IS NOT NULL AS is_fallback
FROM `{project}.{dataset}.interactions` i
LEFT JOIN ev ON ev.pair_id = i.pair_id;""")
    return "\n\n".join(out) + "\n"


if __name__ == "__main__":
    import argparse
    import yaml
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["ddl"])
    ap.add_argument("--config", default=str(HERE / "config.yaml"))
    a = ap.parse_args()
    c = yaml.safe_load(open(a.config))
    m = c.get("monitoring") or {}
    print(ddl(m.get("bq_project") or c["infra"]["project"], m.get("bq_dataset", "prime_monitoring"),
              (m.get("gcs_prefix") or f"gs://{c['infra']['results_bucket']}/monitoring").rstrip("/")))
