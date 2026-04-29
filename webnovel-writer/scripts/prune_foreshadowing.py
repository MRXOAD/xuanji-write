#!/usr/bin/env python3
"""
prune_foreshadowing.py — 伏笔列表精简

deepseek-v4-pro 抽伏笔时偏密,会把每个细节都标成悬念。
300+ 章长篇里 1000+ 条伏笔写进 prompt 也没用。

这个脚本:
- 读 state.plot_threads.foreshadowing
- 用大 LLM 一次性合并去重 + 按重要性排序
- 输出 top N 条(默认 100)替换原列表
- 备份原 state

用法:
    python prune_foreshadowing.py --project-root <BOOK> --top-k 100 --dry-run
    python prune_foreshadowing.py --project-root <BOOK> --top-k 100
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _build_prompt(items: list[dict], top_k: int) -> str:
    rendered = []
    for i, f in enumerate(items, 1):
        ch = f.get("planted_chapter", "?")
        content = str(f.get("content", "")).strip().replace("\n", " ")[:160]
        status = f.get("status", "未回收")
        rendered.append(f"{i}. [第{ch}章 / {status}] {content}")
    list_block = "\n".join(rendered)

    return (
        f"下面是一本 500 章长篇小说累计的 {len(items)} 条伏笔 / 悬念。其中很多是同一线索的不同表述,"
        "或者是不重要的场景细节被误抽成了伏笔。\n\n"
        f"任务:精简到 top {top_k} 条最关键的伏笔,要求:\n"
        "1. 合并重复或相近的悬念为一条(content 写综合后的版本)\n"
        "2. 按对全书主线的重要性排序(主线 > 主反派 > 关键案件 > 次要)\n"
        "3. 删掉只是场景细节、对白边角、不影响后续情节的伪伏笔\n"
        "4. 保留 planted_chapter(用最早出现的那一章)和 status\n\n"
        "输出严格 JSON 数组,不要任何其他文字。每个对象必须有:\n"
        '  {"content": "...", "planted_chapter": N, "status": "未回收|已回收", "tier": "主线|支线|细节"}\n\n'
        f"伏笔列表:\n{list_block}\n"
    )


def _call_pruner(project_root: Path, prompt: str, model: str, max_tokens: int = 12000) -> str:
    from data_modules.config import DataModulesConfig
    from llm_adapter import _call_llm

    config = DataModulesConfig.from_project_root(project_root)
    return _call_llm(
        config,
        messages=[
            {"role": "system", "content": "你是网文编辑,输出严格 JSON 数组,不要 markdown 代码块,不要解释。"},
            {"role": "user", "content": prompt},
        ],
        model=model,
        temperature=0.2,
        max_tokens=max_tokens,
        role="writing",  # 用主写作模型(更强),不是监控
    )


def _parse_json_array(text: str) -> list[dict]:
    text = text.strip()
    if text.startswith("```"):
        # 剥 markdown code fence
        lines = text.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    # 找第一个 [ 和最后一个 ]
    s = text.find("[")
    e = text.rfind("]")
    if s == -1 or e == -1 or e < s:
        raise ValueError(f"返回里找不到 JSON 数组: {text[:300]}")
    data = json.loads(text[s : e + 1])
    if not isinstance(data, list):
        raise ValueError("返回不是 JSON 数组")
    return data


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--project-root", required=True)
    p.add_argument("--top-k", type=int, default=100, help="保留 top K 条")
    p.add_argument("--model", default="deepseek-v4-pro", help="跑 prune 用的模型")
    p.add_argument("--max-tokens", type=int, default=12000)
    p.add_argument("--dry-run", action="store_true", help="只打印结果,不改 state")
    args = p.parse_args()

    project_root = Path(args.project_root).expanduser().resolve()
    state_path = project_root / ".webnovel" / "state.json"
    if not state_path.is_file():
        print(f"❌ state.json 不存在: {state_path}", file=sys.stderr)
        return 2

    state = json.loads(state_path.read_text(encoding="utf-8"))
    plot = state.get("plot_threads") or {}
    items = plot.get("foreshadowing") or []
    if not items:
        print("没有伏笔可精简")
        return 0

    print(f"原伏笔 {len(items)} 条,目标 top {args.top_k}")
    print(f"调用 {args.model} 跑 prune...")

    started = time.time()
    prompt = _build_prompt(items, args.top_k)
    resp = _call_pruner(project_root, prompt, args.model, max_tokens=args.max_tokens)
    elapsed = time.time() - started
    print(f"LLM 返回 ({elapsed:.1f}s, {len(resp)} 字)")

    pruned = _parse_json_array(resp)
    print(f"解析后 {len(pruned)} 条")

    if not pruned:
        print("❌ LLM 返回空数组,放弃改动", file=sys.stderr)
        return 2

    # 给每条加个 ts 字段; planted_chapter 强转 int 避免 LLM 返回字符串导致 sort 失败
    now = int(time.time())
    for x in pruned:
        x.setdefault("status", "未回收")
        x.setdefault("ts", now)
        try:
            x["planted_chapter"] = int(x.get("planted_chapter") or 0)
        except (TypeError, ValueError):
            x["planted_chapter"] = 0

    # 按 importance(tier)排序作展示
    tier_order = {"主线": 0, "支线": 1, "细节": 2}
    pruned.sort(key=lambda x: (tier_order.get(x.get("tier", "细节"), 3), x.get("planted_chapter", 0)))

    if args.dry_run:
        print("\n=== dry-run 抽样前 10 条 ===")
        for x in pruned[:10]:
            print(f" 第{x.get('planted_chapter', '?')}章 [{x.get('tier', '?')}] {str(x.get('content', ''))[:80]}")
        return 0

    # 备份
    backup_dir = state_path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"state.before_prune_{time.strftime('%Y%m%d_%H%M%S')}.json"
    backup_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"原 state 备份到 {backup_path.name}")

    # 写新
    plot["foreshadowing"] = pruned
    state["plot_threads"] = plot
    try:
        from security_utils import atomic_write_json

        atomic_write_json(state_path, state, use_lock=True, backup=True, indent=2)
    except Exception:
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✓ 已写入 {len(pruned)} 条精简伏笔")

    # 简单分布
    from collections import Counter

    tier_count = Counter(x.get("tier", "?") for x in pruned)
    print(f"分布: {dict(tier_count)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
