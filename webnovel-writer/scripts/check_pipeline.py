#!/usr/bin/env python3
"""三档检查模板(P1-F)。

- L1 audit:正则,< 1 秒,每章必跑(已在 _sync_written_chapter 集成)
- L2 fact-check:小 LLM,5-10 秒,段尾章(每 10/20/40 章)跑
- L3 segment-review:大 LLM,30-60 秒,卷尾章(每 80 章)跑

用法:
  python check_pipeline.py --project-root <BOOK> --chapter 240        # 自动按 chapter 路由
  python check_pipeline.py --project-root <BOOK> --chapter 240 --level L2  # 强制档位
  python check_pipeline.py --project-root <BOOK> --chapter 320 --level L3
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _decide_level(chapter: int) -> str:
    """按章号决定该跑哪一档。"""
    if chapter % 80 == 0:  # 卷尾
        return "L3"
    if chapter % 10 == 0:  # 段尾
        return "L2"
    return "L1"


def run_l1(project_root: Path, chapter: int) -> dict:
    """正则 audit。"""
    from draft_audit import audit

    return audit(project_root, chapter)


def run_l2(project_root: Path, chapter: int) -> dict:
    """LLM fact-check:本章是否违反大纲/人物/前文。"""
    text_path = next((project_root / "正文").glob(f"第{chapter:04d}章-*.md"), None)
    if text_path is None:
        return {"chapter": chapter, "level": "L2", "verdict": "MISSING"}
    text = text_path.read_text(encoding="utf-8")[:8000]

    outline_path = next((project_root / "大纲").glob(f"第{chapter}章-*.md"), None)
    outline = outline_path.read_text(encoding="utf-8") if outline_path else ""

    prompt = (
        "判断本章是否违反大纲或前后逻辑。只看这三件事:\n"
        "1. 与大纲核心冲突点是否一致(场景/物件/赢面/钩子)\n"
        "2. 人物身份/死活/关系是否与已知设定矛盾\n"
        "3. 时间线/地点是否合理\n\n"
        '输出严格 JSON: {"verdict":"PASS|WARN|FAIL","issues":[{"type":"...","msg":"..."}]}\n\n'
        f"【大纲】\n{outline}\n\n【正文】\n{text}\n"
    )
    try:
        from data_modules.config import DataModulesConfig
        from llm_adapter import _call_llm

        config = DataModulesConfig.from_project_root(project_root)
        view = config.role_view("monitoring")
        resp = _call_llm(
            config,
            messages=[
                {"role": "system", "content": "你是网文编辑,只输出严格 JSON。"},
                {"role": "user", "content": prompt},
            ],
            model=view.chat_model or config.llm_chat_model,
            temperature=0.2,
            max_tokens=1500,
            role="monitoring",
        )
    except Exception as exc:
        return {"chapter": chapter, "level": "L2", "verdict": "ERROR", "error": str(exc)}

    m = re.search(r"\{[\s\S]*\}", resp)
    if not m:
        return {"chapter": chapter, "level": "L2", "verdict": "PARSE_ERROR", "raw": resp[:300]}
    try:
        data = json.loads(m.group(0))
        return {"chapter": chapter, "level": "L2", **data}
    except json.JSONDecodeError:
        return {"chapter": chapter, "level": "L2", "verdict": "PARSE_ERROR", "raw": resp[:300]}


def run_l3(project_root: Path, chapter: int) -> dict:
    """段级 review:本段(N-19 ~ N)是否衔接 + 是否兑现段大纲。"""
    seg_start = max(1, chapter - 19)
    summaries = []
    for ch in range(seg_start, chapter + 1):
        sp = project_root / ".webnovel" / "summaries" / f"ch{ch:04d}.md"
        if sp.is_file():
            summaries.append(f"=== 第{ch}章 ===\n" + sp.read_text(encoding="utf-8")[:300])
    summaries_text = "\n".join(summaries)

    prompt = (
        f"审查 第{seg_start}-{chapter} 章这一段(20 章)。判断:\n"
        "1. 段内主线是否连贯,有没有断链\n"
        "2. 跨段衔接(本段开头 vs 上段结尾)是否自然\n"
        "3. 段尾是否给出新段落的入口\n"
        "4. 重大设定是否有崩坏\n\n"
        '输出严格 JSON: {"verdict":"PASS|WARN|FAIL","section_score":1-10,"issues":[{"type":"...","msg":"..."}]}\n\n'
        f"【近 20 章摘要】\n{summaries_text}\n"
    )
    try:
        from data_modules.config import DataModulesConfig
        from llm_adapter import _call_llm

        config = DataModulesConfig.from_project_root(project_root)
        view = config.role_view("monitoring")
        resp = _call_llm(
            config,
            messages=[
                {"role": "system", "content": "你是网文连载编辑,只输出严格 JSON。"},
                {"role": "user", "content": prompt},
            ],
            model=view.reasoning_model or config.llm_reasoning_model or config.llm_chat_model,
            temperature=0.2,
            max_tokens=2000,
            role="monitoring",
        )
    except Exception as exc:
        return {"chapter": chapter, "level": "L3", "verdict": "ERROR", "error": str(exc)}

    m = re.search(r"\{[\s\S]*\}", resp)
    if not m:
        return {"chapter": chapter, "level": "L3", "verdict": "PARSE_ERROR", "raw": resp[:300]}
    try:
        data = json.loads(m.group(0))
        return {"chapter": chapter, "level": "L3", **data}
    except json.JSONDecodeError:
        return {"chapter": chapter, "level": "L3", "verdict": "PARSE_ERROR", "raw": resp[:300]}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--project-root", required=True)
    p.add_argument("--chapter", type=int, required=True)
    p.add_argument("--level", choices=["L1", "L2", "L3", "auto"], default="auto")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    project_root = Path(args.project_root)
    level = args.level if args.level != "auto" else _decide_level(args.chapter)

    if level == "L1":
        result = run_l1(project_root, args.chapter)
    elif level == "L2":
        result = run_l2(project_root, args.chapter)
    elif level == "L3":
        result = run_l3(project_root, args.chapter)
    else:
        result = {"error": "unknown level"}

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"[ch{args.chapter:04d}] {level} verdict={result.get('verdict', '?')}")
        for issue in result.get("issues", []) or []:
            print(f"  - {issue.get('msg', issue)}")
        if "section_score" in result:
            print(f"  section_score: {result['section_score']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
