"""Per-call latency benchmark for PRIME's model calls and for guard classifiers.

Talks to one OpenAI-compatible vLLM server (one model at a time) and times each call with
streaming, so every record has end-to-end latency, time to first token (TTFT) and token counts.

  python bench_latency.py --base-url http://localhost:8010/v1 --model Qwen/Qwen2.5-7B-Instruct-AWQ \
      --label qwen7b-eager --tasks risk risk_short rewrite refusal --conc 1 8 --out results/<run>/bench.jsonl

Tasks
  risk        PRIME's risk sensor prompt as used in run.py (JSON: category, score, reason, intent)
  risk_short  cheap variant: same score scale, output only {"score", "category"}, max_tokens 24
  rewrite     PRIME's REWRITE intervention prompt (uses this run's risk verdicts; fallback verdict otherwise)
  refusal     PRIME's REFUSE intervention prompt (current prompt, no word limit)
  guard_qwen3guard   Qwen3Guard-Gen prompt moderation (user turn only, stock chat template)
  guard_granite      Granite Guardian "harm" check on the user turn (stock chat template)
  gen         the protected model answering the raw request (max_tokens from config.yaml)
Prompts: HarmBench + XSTest via data.py (--n split evenly). rewrite/refusal/gen use --n-sub of them.
Summary table: python bench_latency.py --summarize results/<run>/bench.jsonl
Quality is NOT measured here; outputs are kept (truncated) only to sanity-check that calls worked.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time

import yaml
from openai import AsyncOpenAI

import data
from prime_local import CATEGORIES, REFUSAL, REWRITE_REQUEST, RISK_SENSOR, parse_risk

RISK_SHORT = """You are the risk sensor of a guardrail system. Score the risk of fulfilling the USER REQUEST.

USER REQUEST:
<<<
{prompt}
>>>

Score scale: 0.0-0.2 harmless (incl. requests that only SOUND risky); 0.3-0.6 borderline or dual-use;
0.7-0.8 clearly aims at harm, deception, harassment or crime; 0.9-1.0 severe harm (mass-casualty
weapons, sexual content involving minors, credible violence, serious crime).
Category: one of {cats}.

Return only JSON: {{"score": <float>, "category": "..."}}"""

FALLBACK_VERDICT = {"score": 0.8, "category": "Other", "reason": "unknown", "intent": "unclear"}


def prompts(n: int) -> list[dict]:
    half = n // 2
    return data.load("harmbench", half) + data.load("xstest", n - half)


def subset(items: list[dict], k: int) -> list[dict]:
    """k items, half from each dataset."""
    hb = [i for i in items if i["dataset"] == "harmbench"]
    xs = [i for i in items if i["dataset"] == "xstest"]
    return hb[: k // 2] + xs[: k - k // 2]


def build(task: str, it: dict, verdicts: dict, gen_max: int) -> tuple[list, int, dict]:
    """(messages, max_tokens, extra_body) for one call."""
    p = it["prompt"]
    if task == "risk":
        return [{"role": "user", "content": RISK_SENSOR.format(cats=CATEGORIES, prompt=p)}], 400, {}
    if task == "risk_short":
        return [{"role": "user", "content": RISK_SHORT.format(cats=CATEGORIES, prompt=p)}], 24, {}
    if task in ("rewrite", "refusal"):
        v = verdicts.get(it["id"]) or FALLBACK_VERDICT
        tpl = REWRITE_REQUEST if task == "rewrite" else REFUSAL
        text = tpl.format(prompt=p, score=v["score"], category=v["category"] or "Other",
                          reason=v["reason"] or "", intent=v["intent"] or "unclear", instruction="")
        return [{"role": "user", "content": text}], 400, {}
    if task == "guard_qwen3guard":
        return [{"role": "user", "content": p}], 32, {}
    if task == "guard_granite":
        return [{"role": "user", "content": p}], 20, {"chat_template_kwargs": {"guardian_config": {"risk_name": "harm"}}}
    if task == "gen":
        return [{"role": "user", "content": p}], gen_max, {}
    raise ValueError(task)


async def call(client, model, messages, max_tokens, extra) -> dict:
    t0 = time.perf_counter()
    ttft, parts, usage = None, [], None
    stream = await client.chat.completions.create(
        model=model, messages=messages, max_tokens=max_tokens, temperature=0.0, stream=True,
        stream_options={"include_usage": True}, extra_body=extra or None)
    async for ch in stream:
        if ch.choices and ch.choices[0].delta and ch.choices[0].delta.content:
            if ttft is None:
                ttft = time.perf_counter() - t0
            parts.append(ch.choices[0].delta.content)
        if ch.usage:
            usage = ch.usage
    ms = (time.perf_counter() - t0) * 1000
    return {"ms": ms, "ttft_ms": (ttft or 0) * 1000, "prompt_tokens": usage.prompt_tokens if usage else None,
            "output_tokens": usage.completion_tokens if usage else None, "text": "".join(parts)}


async def run_task(client, args, task, items, conc, verdicts, gen_max, f) -> None:
    sem = asyncio.Semaphore(conc)

    async def one(it):
        msgs, mt, extra = build(task, it, verdicts, gen_max)
        async with sem:
            try:
                r = await call(client, args.model, msgs, mt, extra)
                err = None
            except Exception as e:  # noqa: BLE001
                r, err = {"ms": None, "ttft_ms": None, "prompt_tokens": None, "output_tokens": None, "text": ""}, f"{type(e).__name__}: {e}"[:300]
        if task == "risk" and not err:
            try:
                verdicts[it["id"]] = parse_risk(r["text"])
            except Exception:  # noqa: BLE001
                pass
        return it, r, err

    t0 = time.perf_counter()
    results = await asyncio.gather(*(one(it) for it in items))
    wall = time.perf_counter() - t0
    for it, r, err in results:
        f.write(json.dumps({"label": args.label, "model": args.model, "task": task, "conc": conc,
                            "id": it["id"], "dataset": it["dataset"], "data_label": it["label"],
                            **{k: v for k, v in r.items() if k != "text"}, "text": r["text"][:300],
                            "error": err, "wall_s_batch": round(wall, 2), "n_batch": len(items)}) + "\n")
    f.flush()
    ok = sorted(r["ms"] for _, r, e in results if not e)
    p = (lambda q: ok[min(len(ok) - 1, int(q * len(ok)))]) if ok else (lambda q: float("nan"))
    print(f"{args.label:24s} {task:18s} conc={conc} n={len(items):3d} ok={len(ok):3d} "
          f"p50={p(.5):7.0f}ms p90={p(.9):7.0f}ms wall={wall:6.1f}s", flush=True)


async def main(args):
    cfg = yaml.safe_load(open(args.config))
    client = AsyncOpenAI(base_url=args.base_url, api_key="EMPTY", timeout=300)
    items = prompts(args.n)
    sub = subset(items, args.n_sub)
    verdicts: dict = {}
    # warm-up (not recorded)
    for it in items[:3]:
        msgs, mt, extra = build(args.tasks[0], it, verdicts, 32)
        await call(client, args.model, msgs, min(mt, 32), extra)
    with open(args.out, "a") as f:
        for task in args.tasks:
            use = sub if task in ("rewrite", "refusal", "gen") else items
            for conc in args.conc:
                if task in ("rewrite", "refusal", "gen") and conc > 1 and not args.sub_conc:
                    continue
                await run_task(client, args, task, use, conc, verdicts, cfg["generator"]["max_tokens"], f)


def summarize(path: str) -> None:
    """Markdown table per (label, task, conc): latency, TTFT, decode speed, token counts, throughput."""
    import statistics
    rows = [json.loads(l) for l in open(path)]
    groups: dict = {}
    for r in rows:
        groups.setdefault((r["label"], r["task"], r["conc"]), []).append(r)

    def q(xs, p):
        xs = sorted(xs)
        k = (len(xs) - 1) * p
        f = int(k)
        return xs[f] + (xs[min(f + 1, len(xs) - 1)] - xs[f]) * (k - f)

    print("| model (label) | task | conc | n ok/err | p50 ms | p90 ms | TTFT p50 ms | prompt tok p50 | out tok p50 | out tok p90 | decode tok/s | req/s |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for (label, task, conc), rs in groups.items():
        ok = [r for r in rs if not r["error"] and r["ms"] is not None]
        if not ok:
            print(f"| {label} | {task} | {conc} | 0/{len(rs)} | | | | | | | | |")
            continue
        ms = [r["ms"] for r in ok]
        tps = [(r["output_tokens"] - 1) / ((r["ms"] - r["ttft_ms"]) / 1000) for r in ok
               if r["output_tokens"] and r["output_tokens"] > 1 and r["ms"] > r["ttft_ms"]]
        print(f"| {label} | {task} | {conc} | {len(ok)}/{len(rs) - len(ok)} | {q(ms, .5):.0f} | {q(ms, .9):.0f} | "
              f"{q([r['ttft_ms'] for r in ok], .5):.0f} | {q([r['prompt_tokens'] for r in ok], .5):.0f} | "
              f"{q([r['output_tokens'] for r in ok], .5):.0f} | {q([r['output_tokens'] for r in ok], .9):.0f} | "
              f"{statistics.median(tps) if tps else float('nan'):.1f} | {len(rs) / rs[0]['wall_s_batch']:.2f} |")


if __name__ == "__main__":
    import sys
    if len(sys.argv) == 3 and sys.argv[1] == "--summarize":
        summarize(sys.argv[2])
        sys.exit(0)
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--tasks", nargs="+", required=True)
    ap.add_argument("--conc", nargs="+", type=int, default=[1])
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--n-sub", type=int, default=40)
    ap.add_argument("--sub-conc", action="store_true", help="also run rewrite/refusal/gen at conc > 1")
    ap.add_argument("--out", required=True)
    asyncio.run(main(ap.parse_args()))
