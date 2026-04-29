#!/usr/bin/env python3
"""伏笔自动追踪(P1-B)。

每章 draft 完后跑一次,用 LLM 提"本章引入的悬念"+"本章兑现的旧悬念",
写到 state.json.plot_threads.foreshadowing[]。下章 draft 时 prompt 里注入"未回收伏笔清单"。

用法:
  python foreshadowing_tracker.py --project-root <BOOK> --chapter 232
  python foreshadowing_tracker.py --project-root <BOOK> --chapter 232 --no-llm  # 只用规则,不调 LLM
  python foreshadowing_tracker.py --project-root <BOOK> --list-open --max-age 30
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

# 复用 llm_adapter 的调用 + config
sys.path.insert(0, str(Path(__file__).resolve().parent))


def _state_path(project_root: Path) -> Path:
    return project_root / ".webnovel" / "state.json"


def _load_state(project_root: Path) -> dict:
    sp = _state_path(project_root)
    if not sp.is_file():
        return {}
    return json.loads(sp.read_text(encoding="utf-8"))


def _save_state(project_root: Path, state: dict) -> None:
    sp = _state_path(project_root)
    # 走 atomic_write_json + filelock,避免并发损坏 state.json
    try:
        from security_utils import atomic_write_json

        atomic_write_json(sp, state, use_lock=True, backup=True, indent=2)
    except Exception:
        # 最坏情况退回普通写,至少别死
        sp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _find_chapter_file(project_root: Path, chapter_num: int) -> Path | None:
    text_dir = project_root / "正文"
    matches = list(text_dir.glob(f"第{chapter_num:04d}章-*.md"))
    return matches[0] if matches else None


def extract_via_llm(project_root: Path, chapter_num: int) -> dict | None:
    """调小 LLM 提伏笔,失败返回 None。"""
    chapter_file = _find_chapter_file(project_root, chapter_num)
    if chapter_file is None:
        return None
    text = chapter_file.read_text(encoding="utf-8")
    if len(text) > 10000:
        text = text[:10000]

    prompt = (
        "提取本章里的伏笔信息。两类:\n"
        "A. 引入的新悬念/线索(可能未来才回收)\n"
        "B. 兑现的旧悬念(本章给出了答案)\n\n"
        "输出严格 JSON:\n"
        '{"introduced": [{"clue": "...", "where": "..."}], "resolved": [{"clue": "...", "answer": "..."}]}\n\n'
        f"【正文】\n{text}\n"
    )
    try:
        from data_modules.config import DataModulesConfig
        from llm_adapter import _call_llm

        config = DataModulesConfig.from_project_root(project_root)
        # 监控角色:伏笔抽取走 monitoring API(没配则 fallback 到 writing)
        view = config.role_view("monitoring")
        resp = _call_llm(
            config,
            messages=[
                {"role": "system", "content": "你是网文编辑,只输出严格 JSON,不要解释。"},
                {"role": "user", "content": prompt},
            ],
            model=view.chat_model or config.llm_chat_model,
            temperature=0.3,
            max_tokens=1500,
            role="monitoring",
        )
    except Exception as exc:
        print(f"⚠️ LLM 调用失败: {exc}", file=sys.stderr)
        return None

    # 提 JSON
    match = re.search(r"\{[\s\S]*\}", resp)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def update_state_with_foreshadowing(project_root: Path, chapter_num: int, payload: dict) -> int:
    """把 LLM 提取结果写入 state.plot_threads.foreshadowing[]。返回新增条数。"""
    state = _load_state(project_root)
    plot = state.setdefault("plot_threads", {})
    arr = plot.setdefault("foreshadowing", [])

    added = 0
    for item in payload.get("introduced", []) or []:
        clue = str(item.get("clue") or "").strip()
        if not clue:
            continue
        # 去重:同一 clue 只记一次
        if any(str(x.get("content") or "") == clue for x in arr if isinstance(x, dict)):
            continue
        arr.append(
            {
                "content": clue,
                "status": "未回收",
                "planted_chapter": chapter_num,
                "where": item.get("where", ""),
                "ts": int(time.time()),
            }
        )
        added += 1

    for item in payload.get("resolved", []) or []:
        clue = str(item.get("clue") or "").strip()
        if not clue:
            continue
        # 模糊匹配:resolved 的 clue 跟历史 clue 含同样的词
        for x in arr:
            if not isinstance(x, dict):
                continue
            if x.get("status") == "未回收" and (
                clue in str(x.get("content") or "") or str(x.get("content") or "") in clue
            ):
                x["status"] = "已回收"
                x["resolved_chapter"] = chapter_num
                x["resolved_answer"] = item.get("answer", "")
                break

    _save_state(project_root, state)
    return added


def list_open_foreshadowing(project_root: Path, max_age: int = 30, current_chapter: int = 0) -> list[dict]:
    """列出超过 max_age 章未回收的伏笔。"""
    state = _load_state(project_root)
    if not current_chapter:
        current_chapter = int((state.get("progress") or {}).get("current_chapter") or 0)
    arr = (state.get("plot_threads") or {}).get("foreshadowing") or []
    open_items = []
    for x in arr:
        if not isinstance(x, dict):
            continue
        if x.get("status") != "未回收":
            continue
        planted = int(x.get("planted_chapter") or 0)
        age = current_chapter - planted
        if age >= max_age:
            open_items.append({**x, "age": age})
    return sorted(open_items, key=lambda x: -x["age"])


def render_open_for_prompt(project_root: Path, current_chapter: int, top_k: int = 5) -> str:
    """给 prompt builder 用:输出"未回收伏笔提醒"块。"""
    items = list_open_foreshadowing(project_root, max_age=20, current_chapter=current_chapter)
    if not items:
        return ""
    lines = ["未回收伏笔(超 20 章未提及),本章可考虑兑现或推进:"]
    for x in items[:top_k]:
        lines.append(
            f"- 第{x.get('planted_chapter', '?')}章引入: {x.get('content', '')[:80]} ({x.get('age', '?')} 章未推进)"
        )
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--project-root", required=True)
    p.add_argument("--chapter", type=int, help="提取该章的伏笔")
    p.add_argument("--from-chapter", type=int, help="批量回填起始章")
    p.add_argument("--to-chapter", type=int, help="批量回填结束章")
    p.add_argument("--parallel", type=int, default=3, help="批量回填并发数")
    p.add_argument("--no-llm", action="store_true", help="只更新 state(读已有数据,不调 LLM)")
    p.add_argument("--list-open", action="store_true", help="列出未回收伏笔")
    p.add_argument("--max-age", type=int, default=30, help="多少章未回收算 open")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    project_root = Path(args.project_root)

    # 批量回填模式: LLM 抽取并发, state 写入串行(避免 read-modify-write 竞争)
    if args.from_chapter and args.to_chapter:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        chapters = list(range(args.from_chapter, args.to_chapter + 1))
        print(f"批量回填 {len(chapters)} 章 (parallel={args.parallel}, 写 state 串行)")

        # 阶段 1: 并发跑 LLM 抽取
        payloads: dict[int, dict] = {}
        extract_err = 0

        def _extract(ch: int) -> tuple[int, dict | None, str]:
            try:
                p = extract_via_llm(project_root, ch)
                return ch, p, "" if p is not None else "extract returned None"
            except Exception as exc:
                return ch, None, str(exc)[:120]

        with ThreadPoolExecutor(max_workers=max(1, args.parallel)) as pool:
            futures = {pool.submit(_extract, ch): ch for ch in chapters}
            for fut in as_completed(futures):
                ch, payload, err = fut.result()
                if payload is None:
                    print(f"✗ ch{ch:04d} extract: {err}", file=sys.stderr)
                    extract_err += 1
                else:
                    payloads[ch] = payload

        # 阶段 2: 串行写 state(按章号顺序)
        total_added = 0
        write_err = 0
        for ch in sorted(payloads.keys()):
            try:
                added = update_state_with_foreshadowing(project_root, ch, payloads[ch])
                if added:
                    print(f"✓ ch{ch:04d} +{added} 条伏笔")
                    total_added += added
                else:
                    print(f"- ch{ch:04d} 无新伏笔")
            except Exception as exc:
                print(f"✗ ch{ch:04d} write: {str(exc)[:120]}", file=sys.stderr)
                write_err += 1

        total_err = extract_err + write_err
        print(f"\n汇总: 新增 {total_added} 条伏笔, extract 错 {extract_err}, write 错 {write_err}")
        return 0 if total_err == 0 else 2

    if args.list_open:
        items = list_open_foreshadowing(project_root, max_age=args.max_age)
        if args.json:
            print(json.dumps(items, ensure_ascii=False, indent=2))
        else:
            print(f"未回收伏笔(超 {args.max_age} 章): {len(items)}")
            for x in items:
                print(f"  第{x.get('planted_chapter')}章: {str(x.get('content'))[:80]} ({x.get('age')} 章)")
        return 0

    if args.chapter is None:
        p.error("需要 --chapter 或 --list-open")

    if args.no_llm:
        print("--no-llm 模式,跳过 LLM 调用")
        return 0

    payload = extract_via_llm(project_root, args.chapter)
    if payload is None:
        print(f"⚠️ ch{args.chapter} 提取失败")
        return 1
    added = update_state_with_foreshadowing(project_root, args.chapter, payload)
    if args.json:
        print(json.dumps({"added": added, "payload": payload}, ensure_ascii=False, indent=2))
    else:
        print(f"ch{args.chapter}: 新增伏笔 {added} 条")
        for item in payload.get("introduced", []) or []:
            print(f"  + {item.get('clue', '')[:80]}")
        for item in payload.get("resolved", []) or []:
            print(f"  ✓ resolved: {item.get('clue', '')[:80]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
