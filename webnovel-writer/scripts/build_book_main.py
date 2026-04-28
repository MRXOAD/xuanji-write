#!/usr/bin/env python3
"""
build_book_main.py — 全书主线骨架(~5000 字)

为什么:state_summary 只有"角色实力/strand 序列/伏笔标题",没有
叙事性主线。LLM 续写到 800 章后,所谓"全书脉络"完全靠零散
元数据拼。这份脚本基于已有卷摘要(vol_*.md)合成 ~5000 字的
"截至当前已发生的主线骨架",每章 draft 时塞 prompt 顶端。

输出:`.webnovel/summaries/book_main.md`

建议节奏:每完成 4 卷(~200 章)重写一份。

用法:
    python build_book_main.py --project-root <BOOK>
    python build_book_main.py --project-root <BOOK> --through-volume 12
    python build_book_main.py --project-root <BOOK> --rebuild
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _vol_path(project_root: Path, vol_num: int) -> Path:
    return project_root / ".webnovel" / "summaries" / f"vol_{vol_num:02d}.md"


def _book_path(project_root: Path) -> Path:
    return project_root / ".webnovel" / "summaries" / "book_main.md"


def _load_volumes_planned(project_root: Path) -> list[dict]:
    state_path = project_root / ".webnovel" / "state.json"
    if not state_path.is_file():
        return []
    state = json.loads(state_path.read_text(encoding="utf-8"))
    return list((state.get("progress") or {}).get("volumes_planned") or [])


def _load_existing_vol_summaries(project_root: Path, through_vol: int | None) -> list[tuple[int, str, str]]:
    vols = _load_volumes_planned(project_root)
    out: list[tuple[int, str, str]] = []
    for v in vols:
        try:
            vn = int(v.get("volume") or 0)
        except (TypeError, ValueError):
            continue
        if not vn:
            continue
        if through_vol is not None and vn > through_vol:
            break
        p = _vol_path(project_root, vn)
        if not p.is_file():
            continue
        text = p.read_text(encoding="utf-8")
        title = str(v.get("title") or "")
        out.append((vn, title, text))
    return out


def build_book_main(project_root: Path, through_vol: int | None = None) -> dict:
    vols = _load_existing_vol_summaries(project_root, through_vol)
    if not vols:
        return {"status": "skip", "reason": "no volume summaries; run build_volume_summaries first"}

    block = "\n\n".join(f"=== 第{vn}卷《{title}》===\n{body}" for vn, title, body in vols)

    last_vn = vols[-1][0]
    prompt = (
        f"下面是网文截至第 {last_vn} 卷的卷摘要序列。把它合并成一份 4500-5500 字"
        "的全书主线骨架,目的是让续写下一卷的 LLM 把整本书的来龙去脉一次看清,"
        "不再依赖零散段摘要。\n\n"
        "结构(按这 7 节写):\n"
        "## 一、世界观与设定锚点\n"
        "  300-400 字。时代背景、力量体系、地理范围、最关键的设定规则。\n\n"
        "## 二、主角许三更的成长曲线\n"
        "  500-600 字。从槐阴县抬棺学徒到当前章状态,关键节点带卷号(如'第 3 卷起进入州城')。\n\n"
        "## 三、主线核心冲突\n"
        "  800-1000 字。本书在围绕什么打,谁是核心反派阵营,主角要解决的最深问题。\n"
        "  按时序写关键事件,每个事件标卷号 + 一句话。\n\n"
        "## 四、人物谱系与关系网\n"
        "  600-800 字。主角团 + 主要反派 + 红颜线 + 师长辈,各自定位 + 与主角的债/恩。\n"
        "  分小节:主角团 / 反派阵营 / 红颜线 / 长辈与师承 / 中立第三方。\n\n"
        "## 五、关键伏笔(已埋未收 + 已收)\n"
        "  500-700 字。按重要性排,每条:'第 N 章埋什么 → 第 M 章 [已收/未收]'。\n"
        "  优先列主线钩子,不堆细节。\n\n"
        "## 六、当前阵营势力分布\n"
        "  500-600 字。各反派阵营的目前实力、领地、核心人物;主角团掌握的资源。\n\n"
        "## 七、当前停在哪 + 下卷开口\n"
        "  300-400 字。最后一卷尾声状态 + 留给下卷的核心矛盾。\n\n"
        "要求:\n"
        "- 每节用 ## 标题,不要再细分 ###(除节四角色谱系)\n"
        "- 保留人名、地名、物件名、章号\n"
        "- 不写'综上''本书是一部''让我们一起'之类\n"
        "- 不要罗列每一卷,要按主题重组\n\n"
        f"卷摘要序列:\n{block}\n"
    )

    from data_modules.config import DataModulesConfig
    from llm_adapter import _call_llm

    config = DataModulesConfig.from_project_root(project_root)
    started = time.time()
    try:
        resp = _call_llm(
            config,
            messages=[
                {"role": "system", "content": "你是网文主编,合成全书主线骨架,输出 markdown。"},
                {"role": "user", "content": prompt},
            ],
            model=config.llm_chat_model,
            temperature=0.25,
            max_tokens=10000,
            role="writing",
        )
    except Exception as exc:
        return {"status": "error", "reason": str(exc)[:300]}
    elapsed = time.time() - started

    body = (resp or "").strip()
    if body.startswith("```"):
        lines = body.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        body = "\n".join(lines).strip()
    if len(body) < 2000:
        return {"status": "error", "reason": f"too short ({len(body)}字)"}

    out = _book_path(project_root)
    out.parent.mkdir(parents=True, exist_ok=True)
    header = (
        f"# 全书主线骨架(截至第 {last_vn} 卷)\n\n"
        f"> 自动生成,基于 {len(vols)} 份卷摘要合并。\n"
        f"> 续写时塞 prompt 顶端,让 LLM 看清整本书的来龙去脉。\n\n"
    )
    out.write_text(header + body + "\n", encoding="utf-8")
    return {"status": "ok", "through_volume": last_vn, "chars": len(body), "elapsed": elapsed}


def load_book_main(project_root: Path) -> str:
    p = _book_path(project_root)
    if not p.is_file():
        return ""
    return p.read_text(encoding="utf-8").strip()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--project-root", required=True)
    p.add_argument("--through-volume", type=int, help="只用前 N 卷")
    p.add_argument("--rebuild", action="store_true")
    args = p.parse_args()

    project_root = Path(args.project_root).expanduser().resolve()
    if not args.rebuild and _book_path(project_root).is_file():
        print(f"已存在 {_book_path(project_root).name}, 用 --rebuild 强制重做")
        return 0

    print("生成全书主线骨架(调主写作模型,~30-60 秒)...")
    r = build_book_main(project_root, through_vol=args.through_volume)
    if r["status"] == "ok":
        print(f"✓ book_main.md 生成,{r['chars']} 字 (覆盖到第 {r['through_volume']} 卷,{r['elapsed']:.1f}s)")
        return 0
    if r["status"] == "skip":
        print(f"- 跳过: {r['reason']}")
        return 0
    print(f"✗ 失败: {r['reason']}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
