#!/usr/bin/env python3
"""从已写正文抽角色言行样本(P1-A 角色语料库)。

扫 正文/*.md,匹配 "<角色>说/道/问/答/笑/沉默/皱眉/盯着" + 紧邻引号或动作描述,
按角色聚合,每人取最有代表性的若干条,写入 设定集/语料库/<角色>.md。

prompt builder 在每章 draft 时根据出现的角色名注入 3-5 条样本。

用法:
  python extract_character_voice.py --project-root <BOOK_ROOT>
  python extract_character_voice.py --project-root <BOOK_ROOT> --max-samples 20
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path


# 触发词:角色名后跟这些字立刻进入"言行抽取"模式
ACTION_VERBS = "说道问答笑哭沉默皱眉盯看摇点冷哼站坐转抬伸抓"

# 引号:中文/英文都支持
QUOTE_OPEN = '“"'
QUOTE_CLOSE = '”"'


def _read_anchors(project_root: Path) -> set[str]:
    """主要角色白名单(只对这些抽语料,避免"的人/老人"等噪音)。

    可在 设定集/角色语料白名单.md 项目级配置(每行一名),否则用默认。
    """
    config = project_root / "设定集" / "角色语料白名单.md"
    if config.is_file():
        names: set[str] = set()
        for line in config.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            line = re.sub(r"^[-*+]\s+", "", line)
            if 2 <= len(line) <= 6:
                names.add(line)
        if names:
            return names
    # 默认白名单(适合《香灰照骨》;其他书项目可在 角色语料白名单.md 自定义)
    return {
        "许三更",
        "沈见秋",
        "许灯娘",
        "许怀义",
        "许东来",
        "老鲁头",
        "韩五尺",
        "葛衡秋",
        "周既白",
        "裴天书",
        "钱伯通",
        "刘某",
        "何晚舟",
        "程雁书",
        "祁照壁",
        "季七",
        "温会长",
        "陈守拙",
    }


def extract_voice(project_root: Path, max_samples: int = 12) -> dict[str, list[dict]]:
    """扫全本,返回 {角色名: [{chapter, line, sample}, ...]}。"""
    text_dir = project_root / "正文"
    if not text_dir.is_dir():
        return {}
    anchors = _read_anchors(project_root)
    # 按长度降序,优先匹配长名(避免"许灯娘"被"许"截掉)
    anchors_sorted = sorted(anchors, key=lambda x: -len(x))

    # 编译所有角色的检测正则:<角色名> + 任一动作词
    name_alt = "|".join(re.escape(n) for n in anchors_sorted if len(n) >= 2)
    if not name_alt:
        return {}
    detect_re = re.compile(rf"({name_alt})([{ACTION_VERBS}])")

    samples: dict[str, list[dict]] = defaultdict(list)
    for path in sorted(text_dir.glob("第*.md")):
        m_chap = re.match(r"第(\d+)章", path.name)
        if not m_chap:
            continue
        ch_num = int(m_chap.group(1))
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        for line in text.splitlines():
            line_stripped = line.strip()
            if not line_stripped or line_stripped.startswith("#"):
                continue
            # 长度限制:摘语句,不要长段落
            if len(line_stripped) > 200:
                continue
            m = detect_re.search(line_stripped)
            if not m:
                continue
            name = m.group(1)
            # 取该行作为样本(已限长度)
            samples[name].append({"chapter": ch_num, "sample": line_stripped})

    # 按章号分桶取样:每 100 章一桶,各取代表样本,密度比"全本均匀"更高。
    # 默认 max_samples=24,每桶平均 3 条,800 章 8 桶,体现成长曲线。
    result: dict[str, list[dict]] = {}
    bucket_size = 100
    for name, items in samples.items():
        if not items:
            continue
        if len(items) <= max_samples:
            result[name] = sorted(items, key=lambda x: x["chapter"])
            continue
        buckets: dict[int, list[dict]] = {}
        for it in items:
            b = (it["chapter"] - 1) // bucket_size
            buckets.setdefault(b, []).append(it)
        per = max(1, max_samples // max(1, len(buckets)))
        picked: list[dict] = []
        for b in sorted(buckets.keys()):
            inside = buckets[b]
            if len(inside) <= per:
                picked.extend(inside)
            else:
                step = len(inside) / per
                picked.extend(inside[int(step * i)] for i in range(per))
        # 不够 max_samples 时,从最大桶补
        if len(picked) < max_samples:
            remain = max_samples - len(picked)
            picked_set = {(p["chapter"], p["sample"]) for p in picked}
            extra: list[dict] = []
            for b in sorted(buckets.keys(), key=lambda x: -len(buckets[x])):
                for it in buckets[b]:
                    key = (it["chapter"], it["sample"])
                    if key in picked_set:
                        continue
                    extra.append(it)
                    picked_set.add(key)
                    if len(extra) >= remain:
                        break
                if len(extra) >= remain:
                    break
            picked.extend(extra)
        result[name] = sorted(picked, key=lambda x: x["chapter"])[:max_samples]
    return result


def write_voice_library(project_root: Path, voices: dict[str, list[dict]]) -> list[Path]:
    """把每个角色的样本写到 设定集/语料库/<角色>.md。"""
    lib_dir = project_root / "设定集" / "语料库"
    lib_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, items in voices.items():
        if not items:
            continue
        out = lib_dir / f"{name}.md"
        lines = [f"# {name} - 言行样本", ""]
        lines.append(f"> 自动从正文抽取,共 {len(items)} 条。每章 draft 时按需挑 3-5 条注入。")
        lines.append("")
        for item in items:
            lines.append(f"- 第{item['chapter']}章: {item['sample']}")
        out.write_text("\n".join(lines), encoding="utf-8")
        written.append(out)
    return written


def load_voice_for_prompt(project_root: Path, names: list[str], k: int = 4) -> str:
    """给 prompt builder 用:输入本章可能出现的角色名,返回拼好的样本块。"""
    lib_dir = project_root / "设定集" / "语料库"
    if not lib_dir.is_dir():
        return ""
    sections: list[str] = []
    for name in names:
        f = lib_dir / f"{name}.md"
        if not f.is_file():
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            continue
        items = [line for line in text.splitlines() if line.startswith("- 第")]
        if not items:
            continue
        # 简单挑前 k 条
        picked = items[:k]
        sections.append(f"## {name}")
        sections.extend(picked)
    return "\n".join(sections)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--project-root", required=True)
    p.add_argument("--max-samples", type=int, default=24)
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    project_root = Path(args.project_root)
    voices = extract_voice(project_root, max_samples=args.max_samples)
    written = write_voice_library(project_root, voices)
    if args.json:
        print(
            json.dumps(
                {"characters": list(voices.keys()), "files_written": [str(p) for p in written]},
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(f"角色数:{len(voices)}")
        for name, items in sorted(voices.items(), key=lambda x: -len(x[1]))[:15]:
            print(f"  {name}: {len(items)} 条")
        print(f"写入文件:{len(written)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
