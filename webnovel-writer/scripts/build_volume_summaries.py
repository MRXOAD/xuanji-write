#!/usr/bin/env python3
"""
build_volume_summaries.py — 卷摘要(每卷 ~2000 字)

为什么:写到第 N 卷头时,LLM 只看到上一卷"最后一章 700 字"
+ 1500 字写作支架(那是计划,不是事后摘要)。一卷 40 章中
间发生的事 LLM 不知道。本脚本基于已有的段摘要(seg_*.md)
合并为整卷 ~2000 字事后叙述,新卷 draft 时塞 prompt。

输出:`.webnovel/summaries/vol_<N>.md`

依赖:state.json 的 progress.volumes_planned

用法:
    python build_volume_summaries.py --project-root <BOOK> --all
    python build_volume_summaries.py --project-root <BOOK> --volume 5
    python build_volume_summaries.py --project-root <BOOK> --rebuild
    python build_volume_summaries.py --project-root <BOOK> --parallel 3
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _load_volumes(project_root: Path) -> list[dict]:
    state_path = project_root / ".webnovel" / "state.json"
    if not state_path.is_file():
        return []
    state = json.loads(state_path.read_text(encoding="utf-8"))
    return list((state.get("progress") or {}).get("volumes_planned") or [])


def _vol_path(project_root: Path, vol_num: int) -> Path:
    return project_root / ".webnovel" / "summaries" / f"vol_{vol_num:02d}.md"


def _vol_range(vol: dict) -> tuple[int, int] | None:
    rng = str(vol.get("chapters_range") or "")
    if "-" not in rng:
        return None
    try:
        a, b = rng.split("-", 1)
        return int(a), int(b)
    except ValueError:
        return None


def _load_seg_bodies(project_root: Path, start: int, end: int) -> list[str]:
    """读取该范围内全部段摘要(seg_*.md)的正文,按段顺序。"""
    sums_dir = project_root / ".webnovel" / "summaries"
    bodies: list[str] = []
    seg_size = 5
    s = ((start - 1) // seg_size) * seg_size + 1
    while s <= end:
        p = sums_dir / f"seg_{s:04d}_{s + seg_size - 1:04d}.md"
        if p.is_file():
            text = p.read_text(encoding="utf-8")
            m = re.search(r"##\s*段摘要\s*\r?\n(.+?)(?=\r?\n##|$)", text, re.DOTALL)
            body = (m.group(1) if m else text).strip()
            bodies.append(f"第{s}-{s + seg_size - 1}章: {body}")
        s += seg_size
    return bodies


def _build_one_volume(project_root: Path, vol: dict) -> dict:
    rng = _vol_range(vol)
    if not rng:
        return {"volume": vol.get("volume"), "status": "skip", "reason": "no chapters_range"}
    start, end = rng
    vol_num = int(vol.get("volume") or 0)
    title = str(vol.get("title") or "")

    seg_bodies = _load_seg_bodies(project_root, start, end)
    if not seg_bodies:
        return {"volume": vol_num, "status": "skip", "reason": f"no seg summaries in {start}-{end}"}

    block = "\n\n".join(seg_bodies)
    prompt = (
        f"下面是网文《一卷 {vol_num}《{title}》(第 {start}-{end} 章)的段摘要序列。"
        "把它合并成一份 1800-2400 字的事后卷摘要,目的是让续写下一卷的 LLM 知道"
        "这一卷究竟发生了什么。\n\n"
        "结构(按这 6 节写,每节占比大致均衡):\n"
        "1. 卷主题与核心冲突(150-200 字):一句话定调,这卷在讲什么\n"
        "2. 主线推进(400-500 字):事件链条,人名地名物件保留\n"
        "3. 关键转折(300-400 字):至少 3 个本卷反转或揭露\n"
        "4. 角色弧线(300-400 字):许三更 + 主要角色这卷的变化和关系演进\n"
        "5. 引入和回收的悬念(200-300 字):本卷新埋的钩子、回收的旧线索\n"
        "6. 卷尾状态与下卷开口(200-300 字):停在哪儿,留了什么悬念给下卷\n\n"
        "要求:\n"
        "- 每节用 ## 标题分割\n"
        "- 不要写'综上''本卷讲述了'这类\n"
        "- 保留具体人名、地名、物件、章号\n"
        "- 角色名字第一次出现可标章号(如'许三更(第387章)'),不强制\n\n"
        f"段摘要序列:\n{block}\n"
    )

    from data_modules.config import DataModulesConfig
    from llm_adapter import _call_llm

    config = DataModulesConfig.from_project_root(project_root)
    try:
        resp = _call_llm(
            config,
            messages=[
                {"role": "system", "content": "你是网文编辑,合并卷摘要,输出 markdown 多段叙述。"},
                {"role": "user", "content": prompt},
            ],
            model=config.llm_chat_model,
            temperature=0.3,
            max_tokens=4000,
            role="writing",
        )
    except Exception as exc:
        return {"volume": vol_num, "status": "error", "reason": str(exc)[:200]}

    body = (resp or "").strip()
    if body.startswith("```"):
        lines = body.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        body = "\n".join(lines).strip()
    if len(body) < 800:
        return {"volume": vol_num, "status": "error", "reason": f"too short ({len(body)}字)"}

    out = _vol_path(project_root, vol_num)
    out.parent.mkdir(parents=True, exist_ok=True)
    header = f"# 第 {vol_num} 卷《{title}》(第 {start}-{end} 章)卷摘要\n\n{body}\n"
    out.write_text(header, encoding="utf-8")
    return {"volume": vol_num, "status": "ok", "chars": len(body), "path": out.name}


def load_volume_summary(project_root: Path, vol_num: int) -> str:
    p = _vol_path(project_root, vol_num)
    if not p.is_file():
        return ""
    return p.read_text(encoding="utf-8").strip()


def find_volume_for_chapter(project_root: Path, ch: int) -> int | None:
    for v in _load_volumes(project_root):
        rng = _vol_range(v)
        if rng and rng[0] <= ch <= rng[1]:
            try:
                return int(v.get("volume"))
            except (TypeError, ValueError):
                return None
    return None


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--project-root", required=True)
    p.add_argument("--all", action="store_true")
    p.add_argument("--volume", type=int)
    p.add_argument("--parallel", type=int, default=2)
    p.add_argument("--rebuild", action="store_true")
    args = p.parse_args()

    project_root = Path(args.project_root).expanduser().resolve()
    vols = _load_volumes(project_root)
    if args.volume:
        vols = [v for v in vols if int(v.get("volume") or 0) == args.volume]

    pending: list[dict] = []
    for v in vols:
        vol_num = int(v.get("volume") or 0)
        if not vol_num:
            continue
        if not args.rebuild and _vol_path(project_root, vol_num).is_file():
            continue
        pending.append(v)

    print(f"卷摘要: 候选 {len(vols)} 卷, 待跑 {len(pending)} 卷, parallel={args.parallel}")
    if not pending:
        print("全部已存在, 用 --rebuild 强制重做")
        return 0

    ok = err = skip = 0
    with ThreadPoolExecutor(max_workers=args.parallel) as pool:
        futures = {pool.submit(_build_one_volume, project_root, v): v for v in pending}
        for fut in as_completed(futures):
            r = fut.result()
            vn = r.get("volume")
            if r["status"] == "ok":
                print(f"✓ vol_{vn:02d} ({r['chars']}字)")
                ok += 1
            elif r["status"] == "skip":
                print(f"- vol_{vn:02d} 跳过: {r['reason']}")
                skip += 1
            else:
                print(f"✗ vol_{vn:02d} {r['reason']}", file=sys.stderr)
                err += 1
    print(f"\n汇总: ok={ok} skip={skip} error={err}")
    return 0 if err == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
