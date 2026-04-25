#!/usr/bin/env python3
"""章末硬约束验证器(防 LLM 乱跑)。

draft 完一章后调一次,扫五类问题:
1. 修仙残留词黑名单
2. 角色名白名单外出现的"姓 X" 同姓人物(可能 LLM 自造)
3. 设定崩坏(韩五尺写死、姐姐错名等)
4. 元信息漏字(章末钩子:.../下一章:...)
5. 字数明显不足或超长

通过返回 0,警告返回 1(stderr 输出问题清单),严重违规返回 2。
不阻断主流程,只警告。

用法:
  python draft_audit.py --project-root <BOOK_ROOT> --chapter 232
  python draft_audit.py --project-root <BOOK_ROOT> --chapter 232 --strict  # 严重违规 exit 2
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


# ---- 黑名单/白名单 ----

# 常见汉姓(百家姓简化版,覆盖 95%+ 中文人名)
COMMON_SURNAMES = set(
    "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜"
    "戚谢邹喻柏水窦章云苏潘葛奚范彭郎鲁韦昌马苗凤花方俞任袁柳酆鲍史唐"
    "费廉岑薛雷贺倪汤滕殷罗毕郝邬安常乐于时傅皮卞齐康伍余元卜顾孟平黄"
    "和穆萧尹姚邵湛汪祁毛禹狄米贝明臧计伏成戴谈宋茅庞熊纪舒屈项祝董梁"
    "杜阮蓝闵席季麻强贾路娄危江童颜郭梅盛林刁钟徐邱骆高夏蔡田樊胡凌霍"
    "虞万支柯昝管卢莫经房裘缪干解应宗丁宣贲邓郁单杭洪包诸左石崔吉钮龚"
    "程嵇邢滑裴陆荣翁荀羊於惠甄曲家封芮羿储靳汲邴糜松井段富巫乌焦巴弓"
    "牧隗山谷车侯宓蓬全郗班仰秋仲伊宫宁仇栾暴甘钭历戎祖武符刘景詹束龙"
    "叶幸司韶郜黎蓟薄印宿白怀蒲邰从鄂索咸籍赖卓蔺屠蒙池乔阴郁胥能苍双"
    "闻莘党翟谭贡劳逄姬申扶堵冉宰郦雍郤璩桑桂濮牛寿通边扈燕冀僮颛"
)
_SURNAME_HONORIFIC_RE = re.compile(r"([一-鿿])(?:某|大人|老爷|姑娘|公子)")

XIANXIA_BLACKLIST = [
    # 修仙体系明确词:出现即警告
    "金丹",
    "筑基",
    "元婴",
    "化神",
    "渡劫",
    "飞升",
    "灵根",
    "灵气",
    "丹田",
    "经脉",
    "真元",
    "道行",
    "修真",
    "仙人",
    "仙术",
    "符箓",
    "灵宝",
    "法宝",
    "法器",
    "灵兽",
    "妖兽",
    "灵草",
    "灵药",
]

# 修仙边缘词,密度高才警告(不单点拒)
XIANXIA_FUZZY = ["修为", "境界", "突破", "感悟", "灵识", "神识"]


# 题材过渡期豁免范围(早期章节如果是修仙→其他题材的转型期,残留词降级为 warn)
# 用 .webnovel/transition_ranges.json 配置:[[1,60]] 表示 1-60 章不算 error
def _read_transition_ranges(project_root: Path) -> list[tuple[int, int]]:
    config = project_root / ".webnovel" / "transition_ranges.json"
    if not config.is_file():
        return []
    try:
        data = json.loads(config.read_text(encoding="utf-8"))
        return [(int(a), int(b)) for a, b in data]
    except Exception:
        return []


def _in_transition(chapter: int, ranges: list[tuple[int, int]]) -> bool:
    return any(lo <= chapter <= hi for lo, hi in ranges)


META_LEAK_PATTERNS = [
    r"^\s*章末钩子[:：]",
    r"^\s*下一章[:：]",
    r"^\s*作者的话",
    r"^\s*创作说明",
    r"^\s*本章完",
    r"^\s*\(待续\)\s*$",
    r"^\s*【.*?创作.*?】",
]


def _read_anchor_names(project_root: Path) -> set[str]:
    """从 设定集/角色约束.md 提取已知角色名。"""
    anchor_file = project_root / "设定集" / "角色约束.md"
    if not anchor_file.is_file():
        return set()
    text = anchor_file.read_text(encoding="utf-8")
    # 抓 2-4 字中文名,简单粗暴:加在已知列表里
    # 不能保证完美,但够堵 LLM 自造"陈某某""王某"
    candidates = re.findall(r"[一-鿿]{2,4}", text)
    # 加点保底
    seed = {
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
        "周师爷",
        "廖庙祝",
        "周某",
        "吴三手",
    }
    return seed | set(candidates)


def _find_chapter_file(project_root: Path, chapter_num: int) -> Path | None:
    text_dir = project_root / "正文"
    pattern = f"第{chapter_num:04d}章-*.md"
    matches = list(text_dir.glob(pattern))
    return matches[0] if matches else None


def audit(project_root: Path, chapter_num: int, strict: bool = False) -> dict:
    chapter_file = _find_chapter_file(project_root, chapter_num)
    if chapter_file is None:
        return {"chapter": chapter_num, "found": False, "issues": []}

    text = chapter_file.read_text(encoding="utf-8")
    lines = text.splitlines()

    issues: list[dict] = []

    # 检查是否在题材过渡期(此区间修仙残留降级为 warn)
    transition_ranges = _read_transition_ranges(project_root)
    in_transition = _in_transition(chapter_num, transition_ranges)

    # 1. 修仙词黑名单
    for word in XIANXIA_BLACKLIST:
        if word in text:
            count = text.count(word)
            issues.append(
                {
                    "level": "warn" if in_transition else "error",
                    "type": "xianxia_blacklist_legacy" if in_transition else "xianxia_blacklist",
                    "word": word,
                    "count": count,
                    "msg": (
                        f"修仙词 {word!r} 出现 {count} 次(过渡期残留,降级)"
                        if in_transition
                        else f"修仙词 {word!r} 出现 {count} 次"
                    ),
                }
            )

    # 2. 修仙边缘词密度(全章 > 5 次才报)
    fuzzy_total = sum(text.count(w) for w in XIANXIA_FUZZY)
    if fuzzy_total > 5:
        hits = {w: text.count(w) for w in XIANXIA_FUZZY if text.count(w) > 0}
        issues.append(
            {
                "level": "warn",
                "type": "xianxia_fuzzy_density",
                "total": fuzzy_total,
                "hits": hits,
                "msg": f"修仙边缘词密度偏高({fuzzy_total} 次):{hits}",
            }
        )

    # 3. 元信息漏字
    for pattern in META_LEAK_PATTERNS:
        for i, line in enumerate(lines, 1):
            if re.search(pattern, line):
                issues.append(
                    {
                        "level": "error",
                        "type": "meta_leak",
                        "line": i,
                        "content": line.strip()[:80],
                        "msg": f"L{i}: 元信息漏到正文 — {line.strip()[:40]}",
                    }
                )

    # 4. 角色名"姓X"自造检测
    # 必须是百家姓中的姓氏 + (某|大人|老爷|姑娘|公子)才算嫌疑
    # 排除介词/动词后接"某"作泛指(从某/成某/余某/于某/到某/着某)
    anchors = _read_anchor_names(project_root)
    suspect = {}
    for m in _SURNAME_HONORIFIC_RE.finditer(text):
        s = m.group(0)
        first_char = s[0]
        if first_char not in COMMON_SURNAMES:
            continue
        # 上下文检查:s 前面 1 个字是否是动词/介词/虚词,是则跳过
        start = m.start()
        if start > 0:
            prev = text[start - 1]
            # 常见会被误识别的虚词:跟在动词/介词/连词后面 + "某"作泛指
            if prev in "的了得地着将把被是为又也还就再都很又或如若虽且":
                continue
        if s in anchors or any(a.startswith(first_char) for a in anchors):
            continue
        # 短语过滤:某只单字"某"出现在"某<量词>"组合里(某人/某事/某天/某个)
        suffix_2 = text[m.end() : m.end() + 1] if m.end() < len(text) else ""
        if s.endswith("某") and suffix_2 in "人事天个时些位件次年月日处个种类条句段":
            continue
        suspect[s] = suspect.get(s, 0) + 1
    if suspect:
        issues.append(
            {
                "level": "warn",
                "type": "unknown_surname",
                "hits": suspect,
                "msg": f"未知姓氏角色:{suspect}",
            }
        )

    # 5. 字数检查(目标 3000-5000 字,大幅偏离才警告)
    word_count = sum(1 for c in text if "一" <= c <= "鿿")
    if word_count < 1500:
        issues.append(
            {
                "level": "warn",
                "type": "too_short",
                "count": word_count,
                "msg": f"中文字数 {word_count} 偏少(< 1500)",
            }
        )
    elif word_count > 8000:
        issues.append(
            {
                "level": "warn",
                "type": "too_long",
                "count": word_count,
                "msg": f"中文字数 {word_count} 偏多(> 8000)",
            }
        )

    # 6. 韩五尺死了/暴毙类语句(本书设定他没真死)
    han_dead_pat = re.compile(r"韩五尺.{0,8}(死了|暴毙|尸首|断了气|没气了)")
    for i, line in enumerate(lines, 1):
        if han_dead_pat.search(line):
            # 排除"告示""死讯"这类描述死讯通告的句子(合法)
            if "告示" in line or "死讯" in line or "对外" in line:
                continue
            issues.append(
                {
                    "level": "error",
                    "type": "han_setting_break",
                    "line": i,
                    "content": line.strip()[:80],
                    "msg": f"L{i}: 韩五尺写死违反设定(他被州里带走未真死) — {line.strip()[:40]}",
                }
            )

    # 7. 姐姐错名
    sister_pat = re.compile(r"许晚照|许晚晴|韩三娘")
    for i, line in enumerate(lines, 1):
        if sister_pat.search(line):
            issues.append(
                {
                    "level": "error",
                    "type": "sister_name_break",
                    "line": i,
                    "content": line.strip()[:80],
                    "msg": f"L{i}: 姐姐应叫许灯娘,出现旧名 — {line.strip()[:40]}",
                }
            )

    errors = [x for x in issues if x["level"] == "error"]
    warns = [x for x in issues if x["level"] == "warn"]
    return {
        "chapter": chapter_num,
        "file": str(chapter_file),
        "found": True,
        "word_count": word_count,
        "issues": issues,
        "errors": len(errors),
        "warnings": len(warns),
        "verdict": ("FAIL" if errors else "PASS_WITH_WARN" if warns else "PASS"),
    }


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--project-root", required=True)
    p.add_argument("--chapter", type=int, required=True)
    p.add_argument("--strict", action="store_true", help="错误级别返回 exit 2")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    result = audit(Path(args.project_root), args.chapter, args.strict)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        if not result["found"]:
            print(f"[ch{args.chapter:04d}] 章节文件不存在")
            return 1
        print(
            f"[ch{args.chapter:04d}] {result['verdict']} | 字数 {result['word_count']} | {result['errors']} errors / {result['warnings']} warnings"
        )
        for issue in result["issues"]:
            mark = "✗" if issue["level"] == "error" else "⚠"
            print(f"  {mark} {issue['msg']}", file=sys.stderr)

    if args.strict and result["errors"] > 0:
        return 2
    if result["warnings"] > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
