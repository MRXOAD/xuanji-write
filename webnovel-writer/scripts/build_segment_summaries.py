#!/usr/bin/env python3
"""
build_segment_summaries.py — 5 章合并段摘要

为什么:每章 700 字摘要 × 5 章塞 prompt 占空间太大,且 800 章后 LLM
最早只能看到 N-5 章。把 5 章合成 1 段 ~500 字的段摘要,
prompt 里塞 5 段 = 25 章覆盖,空间反而更省。

输出:`.webnovel/summaries/seg_<起>_<止>.md`
分段口径:1-5 / 6-10 / 11-15 ...(按 5 整切,不跨卷)

用法:
    python build_segment_summaries.py --project-root <BOOK> --from 1 --to 800
    python build_segment_summaries.py --project-root <BOOK> --from 1 --to 800 --parallel 4
    python build_segment_summaries.py --project-root <BOOK> --rebuild     # 重做
    python build_segment_summaries.py --project-root <BOOK> --segment 301 # 单段
"""

from __future__ import annotations

import argparse
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


SEG_SIZE = 5


def _seg_key(start: int) -> str:
    end = start + SEG_SIZE - 1
    return f"seg_{start:04d}_{end:04d}"


def _seg_path(project_root: Path, start: int) -> Path:
    return project_root / ".webnovel" / "summaries" / f"{_seg_key(start)}.md"


def _load_chapter_summary(project_root: Path, ch: int) -> str:
    p = project_root / ".webnovel" / "summaries" / f"ch{ch:04d}.md"
    if not p.is_file():
        return ""
    text = p.read_text(encoding="utf-8")
    m = re.search(r"##\s*剧情摘要\s*\r?\n(.+?)(?=\r?\n##|$)", text, re.DOTALL)
    body = m.group(1).strip() if m else text
    return re.sub(r"\s+", " ", body).strip()


def _build_one_segment(project_root: Path, start: int) -> dict:
    """对 [start, start+4] 5 章合并成 ~500 字段摘要。"""
    chapters = list(range(start, start + SEG_SIZE))
    bodies = []
    for ch in chapters:
        s = _load_chapter_summary(project_root, ch)
        if s:
            bodies.append(f"第{ch}章: {s[:400]}")
    if not bodies:
        return {"start": start, "status": "skip", "reason": "no chapter summaries"}
    block = "\n".join(bodies)
    end = start + SEG_SIZE - 1

    prompt = (
        f"下面是第 {start}-{end} 章的章节摘要。请合并成一段 400-600 字的"
        "段摘要,重点保留:\n"
        "1. 主线推进了什么(具体事件/角色行动/物件)\n"
        "2. 引入或回收了什么伏笔\n"
        "3. 角色关系变化\n"
        "4. 章末的关键钩子\n\n"
        "要求:\n"
        "- 不分点,写成连贯叙述\n"
        "- 保留人名、地名、数字、关键物件\n"
        "- 不写'本段讲述了''综上'之类\n"
        "- 不要重复每章只罗列\n\n"
        f"章节摘要:\n{block}\n"
    )

    from data_modules.config import DataModulesConfig
    from llm_adapter import _call_llm

    config = DataModulesConfig.from_project_root(project_root)
    view = config.role_view("monitoring")
    try:
        resp = _call_llm(
            config,
            messages=[
                {"role": "system", "content": "你是网文编辑,合并段摘要,只输出叙述文本。"},
                {"role": "user", "content": prompt},
            ],
            model=view.chat_model or config.llm_chat_model,
            temperature=0.3,
            max_tokens=900,
            role="monitoring",
        )
    except Exception as exc:
        return {"start": start, "status": "error", "reason": str(exc)[:200]}

    summary = (resp or "").strip()
    if summary.startswith("```"):
        lines = summary.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        summary = "\n".join(lines).strip()

    if len(summary) < 100:
        return {"start": start, "status": "error", "reason": f"too short ({len(summary)}字)"}

    out = _seg_path(project_root, start)
    out.parent.mkdir(parents=True, exist_ok=True)
    header = f"# 第{start}-{end}章 段摘要\n\n## 段摘要\n{summary}\n"
    out.write_text(header, encoding="utf-8")
    return {"start": start, "status": "ok", "chars": len(summary), "path": out.name}


def load_segment_summary(project_root: Path, ch: int) -> tuple[int, int, str] | None:
    """给 prompt 用:输入章号 ch,返回所在 5 章段的 (start, end, summary)。"""
    start = ((ch - 1) // SEG_SIZE) * SEG_SIZE + 1
    p = _seg_path(project_root, start)
    if not p.is_file():
        return None
    text = p.read_text(encoding="utf-8")
    m = re.search(r"##\s*段摘要\s*\r?\n(.+?)(?=\r?\n##|$)", text, re.DOTALL)
    body = m.group(1).strip() if m else text.strip()
    return start, start + SEG_SIZE - 1, body


def list_segments_before(project_root: Path, ch: int, count: int = 5) -> list[tuple[int, int, str]]:
    """给 prompt 用:返回写第 ch 章前已有的最近 count 个段摘要,从远到近。"""
    cur_start = ((ch - 1) // SEG_SIZE) * SEG_SIZE + 1
    out: list[tuple[int, int, str]] = []
    s = cur_start - SEG_SIZE
    while s >= 1 and len(out) < count:
        p = _seg_path(project_root, s)
        if p.is_file():
            text = p.read_text(encoding="utf-8")
            m = re.search(r"##\s*段摘要\s*\r?\n(.+?)(?=\r?\n##|$)", text, re.DOTALL)
            body = m.group(1).strip() if m else text.strip()
            out.append((s, s + SEG_SIZE - 1, body))
        s -= SEG_SIZE
    out.reverse()
    return out


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--project-root", required=True)
    p.add_argument("--from-chapter", type=int, default=1, dest="from_ch")
    p.add_argument("--to-chapter", type=int, default=800, dest="to_ch")
    p.add_argument("--segment", type=int, help="只跑包含该章的单段")
    p.add_argument("--parallel", type=int, default=4)
    p.add_argument("--rebuild", action="store_true", help="即使已存在也重做")
    args = p.parse_args()

    project_root = Path(args.project_root).expanduser().resolve()

    if args.segment:
        start = ((args.segment - 1) // SEG_SIZE) * SEG_SIZE + 1
        starts = [start]
    else:
        first = ((args.from_ch - 1) // SEG_SIZE) * SEG_SIZE + 1
        last = ((args.to_ch - 1) // SEG_SIZE) * SEG_SIZE + 1
        starts = list(range(first, last + 1, SEG_SIZE))

    pending = []
    for s in starts:
        if not args.rebuild and _seg_path(project_root, s).is_file():
            continue
        pending.append(s)

    print(f"段摘要: 候选 {len(starts)} 段, 待跑 {len(pending)} 段, parallel={args.parallel}")
    if not pending:
        print("全部已存在, 用 --rebuild 强制重做")
        return 0

    ok = err = skip = 0
    with ThreadPoolExecutor(max_workers=args.parallel) as pool:
        futures = {pool.submit(_build_one_segment, project_root, s): s for s in pending}
        for fut in as_completed(futures):
            r = fut.result()
            s = r["start"]
            if r["status"] == "ok":
                print(f"✓ {_seg_key(s)} ({r['chars']}字)")
                ok += 1
            elif r["status"] == "skip":
                print(f"- {_seg_key(s)} 跳过: {r['reason']}")
                skip += 1
            else:
                print(f"✗ {_seg_key(s)} {r['reason']}", file=sys.stderr)
                err += 1
    print(f"\n汇总: ok={ok} skip={skip} error={err}")
    return 0 if err == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
