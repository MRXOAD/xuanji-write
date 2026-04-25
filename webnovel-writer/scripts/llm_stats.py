#!/usr/bin/env python3
"""LLM 调用日志聚合统计(P1-5)。

读 .webnovel/logs/llm_calls.jsonl,输出:
- total_calls / success_rate
- p50 / p95 / p99 latency
- token 总量 / 估算总费用
- 按 task / model 拆分

用法:
  python llm_stats.py --project-root <BOOK_ROOT>
  python llm_stats.py --project-root <BOOK_ROOT> --since-hours 24
  python llm_stats.py --project-root <BOOK_ROOT> --by-task
  python llm_stats.py --project-root <BOOK_ROOT> --by-chapter
  python llm_stats.py --project-root <BOOK_ROOT> --json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path


def _read_log(log_path: Path, since_ts: int = 0) -> list[dict]:
    if not log_path.is_file():
        return []
    rows: list[dict] = []
    with log_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if since_ts and int(row.get("ts") or 0) < since_ts:
                continue
            rows.append(row)
    return rows


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round(p / 100 * (len(s) - 1)))))
    return s[k]


def _aggregate(rows: list[dict]) -> dict:
    if not rows:
        return {"total": 0}
    total = len(rows)
    success = sum(1 for r in rows if r.get("success"))
    latencies = [int(r.get("latency_ms") or 0) for r in rows if r.get("latency_ms")]
    prompt_tokens = sum(int((r.get("usage") or {}).get("prompt_tokens") or 0) for r in rows)
    completion_tokens = sum(int((r.get("usage") or {}).get("completion_tokens") or 0) for r in rows)
    total_tokens = sum(int((r.get("usage") or {}).get("total_tokens") or 0) for r in rows)
    cost = sum(float(r.get("estimated_cost_usd") or 0) for r in rows)
    return {
        "total": total,
        "success": success,
        "success_rate": round(success / total, 3) if total else 0.0,
        "latency_p50_ms": _percentile(latencies, 50),
        "latency_p95_ms": _percentile(latencies, 95),
        "latency_p99_ms": _percentile(latencies, 99),
        "latency_mean_ms": round(sum(latencies) / len(latencies), 1) if latencies else 0,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "estimated_cost_usd": round(cost, 4),
    }


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--project-root", required=True)
    p.add_argument("--since-hours", type=float, default=0)
    p.add_argument("--by-task", action="store_true")
    p.add_argument("--by-model", action="store_true")
    p.add_argument("--by-chapter", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    log_path = Path(args.project_root) / ".webnovel" / "logs" / "llm_calls.jsonl"
    since_ts = int(time.time() - args.since_hours * 3600) if args.since_hours else 0
    rows = _read_log(log_path, since_ts)

    overall = _aggregate(rows)

    by_dim: dict[str, dict] = {}
    if args.by_task:
        groups = defaultdict(list)
        for r in rows:
            groups[r.get("task") or "?"].append(r)
        by_dim["by_task"] = {k: _aggregate(v) for k, v in groups.items()}
    if args.by_model:
        groups = defaultdict(list)
        for r in rows:
            groups[r.get("model") or "?"].append(r)
        by_dim["by_model"] = {k: _aggregate(v) for k, v in groups.items()}
    if args.by_chapter:
        groups = defaultdict(list)
        for r in rows:
            groups[int(r.get("chapter") or 0)].append(r)
        by_dim["by_chapter"] = {k: _aggregate(v) for k, v in sorted(groups.items())}

    out = {"overall": overall, "log_path": str(log_path)}
    out.update(by_dim)
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    print(f"log: {log_path}")
    print(f"window: {'all time' if not args.since_hours else f'last {args.since_hours}h'}")
    print(f"total_calls={overall.get('total')} success_rate={overall.get('success_rate')}")
    print(
        f"latency p50/p95/p99 (ms) = {overall.get('latency_p50_ms')}/{overall.get('latency_p95_ms')}/{overall.get('latency_p99_ms')} mean={overall.get('latency_mean_ms')}"
    )
    print(
        f"tokens: prompt={overall.get('prompt_tokens')} completion={overall.get('completion_tokens')} total={overall.get('total_tokens')}"
    )
    print(f"estimated_cost_usd={overall.get('estimated_cost_usd')}")
    for label, d in by_dim.items():
        print(f"\n--- {label} ---")
        for k, v in d.items():
            print(f"  {k}: total={v.get('total')} success={v.get('success_rate')} cost=${v.get('estimated_cost_usd')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
