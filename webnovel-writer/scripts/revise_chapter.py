#!/usr/bin/env python3
"""
revise_chapter.py — 单章改稿(扩写 + 强化章末钩子)

用 deepseek-v4-pro 重写单章,目标:
1. 字数从 ~2300 拉到目标(默认 4200)
2. 章末钩子从情绪钩升级到 strong 钩(实物揭示 / 身份反转 / 死活悬念)
3. 保留原章核心事件、人物、地点,不另起情节
4. 保留原章红色强调关键词,不丢主线

约束:
- 备份原章到 .webnovel/backups/原章_<时间戳>.md
- 自动同步重写章节摘要文件 .webnovel/summaries/chNNNN.md
- 不动 state.json 的伏笔 / strand 序列(避免 read-modify-write 竞争)

用法:
    python revise_chapter.py --project-root <BOOK> --chapter 100
    python revise_chapter.py --project-root <BOOK> --from-chapter 81 --to-chapter 120 --parallel 3
    python revise_chapter.py --project-root <BOOK> --chapter 100 --target-words 4500 --dry-run
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _find_chapter_file(project_root: Path, ch: int) -> Path | None:
    text_dir = project_root / "正文"
    matches = list(text_dir.glob(f"第{ch:04d}章*.md"))
    return matches[0] if matches else None


def _backup_chapter(project_root: Path, ch_path: Path) -> Path:
    backup_dir = project_root / ".webnovel" / "backups" / "revise"
    backup_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    backup = backup_dir / f"{ch_path.stem}_{ts}.md"
    shutil.copy2(ch_path, backup)
    return backup


def _cn_chars(text: str) -> int:
    return len(re.findall(r"[一-鿿]", text))


def _build_revise_prompt(orig_text: str, chapter_num: int, target_words: int, context: dict) -> list[dict]:
    book_main = context.get("book_main") or ""
    vol_summaries = context.get("volume_summaries") or []
    seg_summaries = context.get("segment_summaries") or []
    voice_block = context.get("voice_block") or ""

    sys_prompt = (
        "你是网文资深编辑,负责给定稿章节做扩写改稿。\n"
        "原则:\n"
        "1. 不另起情节 — 原章发生的事件、出场人物、地点、物件,改稿后必须全部保留\n"
        "2. 不改主线方向 — 章末把读者带到的状态不变\n"
        "3. 改稿核心是把字数密度做厚:加场景细节、加动作描写、加内心独白、加对白节奏感\n"
        "4. 章末钩子升级:把原章的情绪钩(他闭上眼睛 / 他不知道 / 他叹了口气)改成强钩之一:\n"
        "   a) 实物揭示:某物件露出之前没看见的字 / 痕迹 / 印记\n"
        "   b) 身份反转:某人是另一个身份 / 名字 / 派系\n"
        "   c) 死活悬念:某人此刻处境危急 / 失踪 / 不在了\n"
        "5. 保留原章红字强调的关键词\n"
        "6. 不写'本章完''作者的话'\n"
        "7. 不写'综上''最后'式总结句\n"
        "8. 直接输出 markdown 章节正文,首行 '# 第N章 标题'(标题可保留原标题或微调)"
    )

    parts = [f"目标字数: {target_words} 字汉字(原章约 {_cn_chars(orig_text)} 字)。"]
    if book_main:
        parts.append("【全书主线骨架】\n" + book_main[:3500])
    if vol_summaries:
        parts.append(
            "【近卷卷摘要】\n"
            + "\n\n".join(f"第{v.get('volume')}卷:\n{v.get('body', '')[:1500]}" for v in vol_summaries[-2:])
        )
    if seg_summaries:
        parts.append(
            "【近段段摘要】\n"
            + "\n\n".join(f"{s.get('start')}-{s.get('end')}: {s.get('body', '')[:600]}" for s in seg_summaries[-3:])
        )
    if voice_block:
        parts.append("【角色言行样本(模仿语气,不要照抄)】\n" + voice_block)

    parts.append("【原章正文】\n" + orig_text)
    parts.append("\n现在重写本章,严格按要求输出。")

    user_prompt = "\n\n".join(parts)
    return [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": user_prompt},
    ]


def _build_context_for(project_root: Path, ch: int) -> dict:
    """复用 build_chapter_context_payload 的部分上下文。"""
    try:
        from extract_chapter_context import build_chapter_context_payload

        payload = build_chapter_context_payload(project_root, ch)
    except Exception:
        return {}
    # 角色 voice
    voice_block = ""
    try:
        from llm_prompt_builder import _detect_chapter_characters, _load_voice_samples

        outline = str(payload.get("outline") or "")
        chars = _detect_chapter_characters(outline, project_root)
        voice_block = _load_voice_samples(project_root, chars, k=4, chapter_num=ch, window=100)
    except Exception:
        pass
    return {
        "book_main": payload.get("book_main") or "",
        "volume_summaries": payload.get("volume_summaries") or [],
        "segment_summaries": payload.get("segment_summaries") or [],
        "voice_block": voice_block,
    }


def _resync_summary(project_root: Path, ch: int, new_text: str) -> None:
    """重写后同步重生成单章摘要(让段/卷摘要后续重建可用)。"""
    try:
        from data_modules.config import DataModulesConfig
        from llm_adapter import _call_llm
    except Exception:
        return
    sample = new_text[:5000]
    prompt = (
        "下面是一章网文正文,请抽 3-5 句的剧情摘要,涵盖:场景 + 推进 + 章末钩子。"
        "不写'综上',不写'本章讲述',只输出叙述句。\n\n"
        f"【正文】\n{sample}"
    )
    try:
        config = DataModulesConfig.from_project_root(project_root)
        view = config.role_view("monitoring")
        resp = _call_llm(
            config,
            messages=[
                {"role": "system", "content": "你是网文编辑,只输出摘要句。"},
                {"role": "user", "content": prompt},
            ],
            model=view.chat_model or config.llm_chat_model,
            temperature=0.3,
            max_tokens=400,
            role="monitoring",
        )
    except Exception:
        return
    summary = (resp or "").strip()
    if not summary:
        return
    out = project_root / ".webnovel" / "summaries" / f"ch{ch:04d}.md"
    head = re.search(r"#[^\n]*", new_text)
    title_line = head.group(0) if head else f"# 第{ch}章摘要"
    out.write_text(f"{title_line}\n\n## 剧情摘要\n{summary}\n", encoding="utf-8")


def revise_one(project_root: Path, ch: int, target_words: int, *, dry_run: bool, model: str) -> dict:
    ch_path = _find_chapter_file(project_root, ch)
    if not ch_path:
        return {"chapter": ch, "status": "skip", "reason": "no chapter file"}
    orig = ch_path.read_text(encoding="utf-8")
    orig_chars = _cn_chars(orig)

    context = _build_context_for(project_root, ch)
    messages = _build_revise_prompt(orig, ch, target_words, context)

    try:
        from data_modules.config import DataModulesConfig
        from llm_adapter import _call_llm

        config = DataModulesConfig.from_project_root(project_root)
        resp = _call_llm(
            config,
            messages=messages,
            model=model,
            temperature=0.7,
            max_tokens=int(target_words * 2.2),
            role="writing",
        )
    except Exception as exc:
        return {"chapter": ch, "status": "error", "reason": str(exc)[:200]}

    new_text = (resp or "").strip()
    if new_text.startswith("```"):
        lines = new_text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        new_text = "\n".join(lines).strip()

    new_chars = _cn_chars(new_text)
    if new_chars < int(target_words * 0.6):
        return {
            "chapter": ch,
            "status": "error",
            "reason": f"too short: {new_chars} 字 (target {target_words})",
        }

    if not new_text.startswith("#"):
        m = re.match(r"# 第\d+章[^\n]*", orig)
        new_text = (m.group(0) if m else f"# 第{ch}章") + "\n\n" + new_text

    if dry_run:
        return {
            "chapter": ch,
            "status": "dry-run",
            "orig_chars": orig_chars,
            "new_chars": new_chars,
            "preview": new_text[:300],
        }

    backup = _backup_chapter(project_root, ch_path)
    ch_path.write_text(new_text, encoding="utf-8")
    _resync_summary(project_root, ch, new_text)
    return {
        "chapter": ch,
        "status": "ok",
        "orig_chars": orig_chars,
        "new_chars": new_chars,
        "backup": backup.name,
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--project-root", required=True)
    p.add_argument("--chapter", type=int)
    p.add_argument("--from-chapter", type=int, dest="from_ch")
    p.add_argument("--to-chapter", type=int, dest="to_ch")
    p.add_argument("--target-words", type=int, default=4200)
    p.add_argument("--model", default="deepseek-v4-pro")
    p.add_argument("--parallel", type=int, default=2)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    project_root = Path(args.project_root).expanduser().resolve()
    if args.chapter:
        chapters = [args.chapter]
    elif args.from_ch and args.to_ch:
        chapters = list(range(args.from_ch, args.to_ch + 1))
    else:
        p.error("需要 --chapter 或 --from-chapter/--to-chapter")

    print(
        f"改稿 {len(chapters)} 章,model={args.model},target={args.target_words},"
        f"parallel={args.parallel}{', dry-run' if args.dry_run else ''}"
    )

    results = []
    with ThreadPoolExecutor(max_workers=args.parallel) as pool:
        futures = {
            pool.submit(revise_one, project_root, ch, args.target_words, dry_run=args.dry_run, model=args.model): ch
            for ch in chapters
        }
        for fut in as_completed(futures):
            r = fut.result()
            results.append(r)
            ch = r["chapter"]
            st = r["status"]
            if st == "ok":
                print(f"✓ ch{ch:04d} {r['orig_chars']} → {r['new_chars']} 字 (备份 {r['backup']})")
            elif st == "dry-run":
                print(f"… ch{ch:04d} {r['orig_chars']} → {r['new_chars']} 字 [dry-run]")
            elif st == "skip":
                print(f"- ch{ch:04d} 跳过: {r['reason']}")
            else:
                print(f"✗ ch{ch:04d} {r['reason']}", file=sys.stderr)

    ok = sum(1 for r in results if r["status"] == "ok")
    err = sum(1 for r in results if r["status"] == "error")
    skip = sum(1 for r in results if r["status"] == "skip")
    dry = sum(1 for r in results if r["status"] == "dry-run")
    print(f"\n汇总: ok={ok} dry={dry} skip={skip} error={err}")
    return 0 if err == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
