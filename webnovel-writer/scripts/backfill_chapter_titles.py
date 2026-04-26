#!/usr/bin/env python3
"""
backfill_chapter_titles.py — 补回章节标题

如果章节文件叫 `第0NNN章.md`(没标题),用监控 LLM 给每章抽 6-12 字标题:
- 改文件第一行 `# 第NNN章` → `# 第NNN章 <标题>`
- 文件 rename 成 `第0NNN章-<标题>.md`
- 同步 state.json 里 chapter_meta[NNNN].title

用法:
    python backfill_chapter_titles.py --project-root <BOOK> --from-chapter 301 --to-chapter 500
    python backfill_chapter_titles.py --project-root <BOOK> --from-chapter 301 --to-chapter 500 --parallel 3
    python backfill_chapter_titles.py --project-root <BOOK> --from-chapter 301 --to-chapter 500 --dry-run
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _load_chapter(project_root: Path, chapter_num: int) -> tuple[Path, str] | None:
    """返回 (path, text) 或 None。优先平铺 第NNNN章.md。"""
    flat = project_root / "正文" / f"第{chapter_num:04d}章.md"
    if flat.is_file():
        return flat, flat.read_text(encoding="utf-8")
    # 已经带标题的就跳过
    return None


def _extract_title_via_llm(project_root: Path, text: str, chapter_num: int) -> str:
    from data_modules.config import DataModulesConfig
    from llm_adapter import _call_llm

    config = DataModulesConfig.from_project_root(project_root)
    view = config.role_view("monitoring")

    # 截前 1500 字给 LLM 抽,后面通常是冗余
    sample = text[:1500]
    prompt = (
        "为下面这一章正文起一个 6-12 字的章节标题,要求:\n"
        "1. 提炼本章最关键的情节 / 物件 / 冲突\n"
        "2. 不要写'未命名'、不要写'第N章'、不要标点\n"
        "3. 只输出标题文本,不要任何解释\n\n"
        f"【正文片段】\n{sample}\n"
    )
    resp = _call_llm(
        config,
        messages=[
            {"role": "system", "content": "你是网文编辑,只输出标题文本本身,不解释。"},
            {"role": "user", "content": prompt},
        ],
        model=view.chat_model or config.llm_chat_model,
        temperature=0.3,
        max_tokens=40,
        role="monitoring",
    )
    title = (resp or "").strip().splitlines()[0].strip()
    # 清掉常见噪音
    title = title.strip("《》「」\"'`：:。.,, ")
    title = re.sub(r"^第\d+章\s*", "", title)
    title = re.sub(r"[#*\-]+", "", title)
    return title.strip()[:14]


def _safe_filename_part(title: str) -> str:
    """去掉文件名不允许的字符。"""
    return re.sub(r"[\\/:*?\"<>|]", "", title).strip()


def _rewrite_first_line(text: str, chapter_num: int, title: str) -> str:
    """改第一行 `# 第301章` → `# 第301章 标题`。"""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.strip().startswith(f"# 第{chapter_num}章"):
            lines[i] = f"# 第{chapter_num}章 {title}"
            return "\n".join(lines)
    return text


def _update_state_meta(project_root: Path, chapter_num: int, title: str) -> None:
    state_path = project_root / ".webnovel" / "state.json"
    if not state_path.is_file():
        return
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return
    chapter_meta = state.setdefault("chapter_meta", {})
    key = f"{chapter_num:04d}"
    meta = chapter_meta.setdefault(key, {})
    meta["title"] = title
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def process_chapter(project_root: Path, chapter_num: int, *, dry_run: bool) -> dict:
    loaded = _load_chapter(project_root, chapter_num)
    if not loaded:
        return {"chapter": chapter_num, "status": "skip", "reason": "no flat file"}
    path, text = loaded
    try:
        title = _extract_title_via_llm(project_root, text, chapter_num)
    except Exception as exc:
        return {"chapter": chapter_num, "status": "error", "reason": str(exc)[:200]}
    if not title:
        return {"chapter": chapter_num, "status": "error", "reason": "empty title"}

    if dry_run:
        return {"chapter": chapter_num, "status": "dry-run", "title": title}

    safe = _safe_filename_part(title)
    new_text = _rewrite_first_line(text, chapter_num, title)
    new_path = path.parent / f"第{chapter_num:04d}章-{safe}.md"

    new_path.write_text(new_text, encoding="utf-8")
    if new_path != path and path.exists():
        path.unlink()

    _update_state_meta(project_root, chapter_num, title)

    return {
        "chapter": chapter_num,
        "status": "ok",
        "title": title,
        "old_path": path.name,
        "new_path": new_path.name,
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--project-root", required=True)
    p.add_argument("--from-chapter", type=int, required=True)
    p.add_argument("--to-chapter", type=int, required=True)
    p.add_argument("--parallel", type=int, default=3)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    project_root = Path(args.project_root).expanduser().resolve()
    chapters = list(range(args.from_chapter, args.to_chapter + 1))

    print(f"backfill {len(chapters)} 章 (parallel={args.parallel}{', dry-run' if args.dry_run else ''})")

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=args.parallel) as pool:
        futures = {pool.submit(process_chapter, project_root, ch, dry_run=args.dry_run): ch for ch in chapters}
        for fut in as_completed(futures):
            r = fut.result()
            results.append(r)
            ch = r["chapter"]
            status = r["status"]
            if status == "ok":
                print(f"✓ ch{ch:04d} → {r['title']} (file: {r['new_path']})")
            elif status == "dry-run":
                print(f"… ch{ch:04d} → {r['title']} (dry-run)")
            elif status == "skip":
                print(f"- ch{ch:04d} 跳过: {r['reason']}")
            else:
                print(f"✗ ch{ch:04d} 错误: {r.get('reason')}", file=sys.stderr)

    ok = sum(1 for r in results if r["status"] == "ok")
    skip = sum(1 for r in results if r["status"] == "skip")
    err = sum(1 for r in results if r["status"] == "error")
    dry = sum(1 for r in results if r["status"] == "dry-run")
    print(f"\n汇总: ok={ok} dry={dry} skip={skip} error={err}")
    return 0 if err == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
