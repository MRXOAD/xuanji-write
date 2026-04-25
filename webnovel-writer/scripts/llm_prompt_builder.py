#!/usr/bin/env python3
"""LLM prompt 组装(P2-1 拆出)。

把 _build_write_messages / _build_review_messages 及其辅助函数从 llm_adapter
里抽出来,因为这是用户最常改的部分(自定义 system prompt、调约束)。

llm_adapter 里通过 import 转发,保留同名 _ 私有别名向后兼容。
"""

from __future__ import annotations

import re as _re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, Optional


def render_previous_summaries(items: Iterable[str]) -> str:
    rows = [str(item).strip() for item in items if str(item).strip()]
    return "\n\n".join(rows) if rows else "无"


def render_rag_hits(payload: Dict[str, Any]) -> str:
    rag = payload.get("rag_assist") or {}
    hits = rag.get("hits") or []
    if not rag.get("invoked") or not hits:
        reason = rag.get("reason") or "未触发"
        return f"未提供 RAG 线索（原因：{reason}）"
    rows = []
    for idx, row in enumerate(hits[:5], start=1):
        rows.append(
            f"{idx}. Ch{row.get('chapter', '?')}-S{row.get('scene_index', '?')} "
            f"[{row.get('source', 'unknown')}] score={row.get('score', 0)} "
            f"{row.get('content', '')}"
        )
    return "\n".join(rows)


def render_anti_repeat(payload: Dict[str, Any], threshold: float = 0.7) -> str:
    """RAG 反向检索:把 score >= threshold 的历史段当作"已写过,本章必须避开"。

    防止 300+ 章长篇里出现"桥段复读"——同样的酒馆打架、同样的废墟搜物、同样的雨夜对话。
    """
    rag = payload.get("rag_assist") or {}
    hits = rag.get("hits") or []
    if not rag.get("invoked") or not hits:
        return ""
    high = [h for h in hits if float(h.get("score") or 0) >= threshold]
    if not high:
        return ""
    rows = []
    for idx, row in enumerate(high[:5], start=1):
        ch = row.get("chapter", "?")
        snippet = str(row.get("content", "")).strip().replace("\n", " ")[:120]
        rows.append(f"{idx}. 第{ch}章 (score={row.get('score', 0):.2f}): {snippet}")
    return "\n".join(rows)


def render_guidance(payload: Dict[str, Any]) -> str:
    guidance = payload.get("writing_guidance") or {}
    items = guidance.get("guidance_items") or []
    checklist = guidance.get("checklist") or []
    rows: list[str] = []
    for idx, item in enumerate(items[:8], start=1):
        rows.append(f"{idx}. {item}")
    for idx, row in enumerate(checklist[:6], start=1):
        if not isinstance(row, dict):
            rows.append(f"检查 {idx}: {row}")
            continue
        label = str(row.get("label") or "未命名项").strip()
        required = "必做" if row.get("required") else "可选"
        verify_hint = str(row.get("verify_hint") or "").strip()
        if verify_hint:
            rows.append(f"检查 {idx}: [{required}] {label}；验收：{verify_hint}")
        else:
            rows.append(f"检查 {idx}: [{required}] {label}")
    return "\n".join(rows) if rows else "无"


def load_story_contract(project_root: Optional[Path]) -> str:
    """从 设定集/故事合约.md 加载全书故事合约(Story System)。

    这是一份"宪法"文件,描述全书的:
    - 核心冲突 / 题材合约
    - 主角弧 / 反派弧
    - 节奏 / 主线 / 关键转折

    缺文件 = 返回空串(向后兼容存量项目)。
    """
    if project_root is None:
        return ""
    contract_file = Path(project_root) / "设定集" / "故事合约.md"
    if not contract_file.is_file():
        return ""
    try:
        text = contract_file.read_text(encoding="utf-8")
    except Exception:
        return ""
    # 去掉文件头的顶级 # 标题行(避免和章节 prompt 的 # 撞),保留正文
    lines = text.splitlines()
    clean = [line for line in lines if not (line.startswith("# ") and not line.startswith("## "))]
    return "\n".join(clean).strip()


def load_character_anchors(project_root: Optional[Path]) -> list[str]:
    """从 设定集/角色约束.md 加载角色锚点。每行一条,文件不存在返回 []。"""
    if project_root is None:
        return []
    anchor_file = Path(project_root) / "设定集" / "角色约束.md"
    if not anchor_file.is_file():
        return []
    lines: list[str] = []
    try:
        for raw in anchor_file.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            line = _re.sub(r"^[-*+]\s+", "", line)
            line = _re.sub(r"^\d+[\.、]\s*", "", line)
            if line:
                lines.append(line)
    except Exception:
        return []
    return lines


# 通用规则(用户可在 设定集/角色约束.md 追加项目级规则)
BASE_WRITE_RULES = [
    "你是中文网文写手。任务只有一个:按给定大纲写出可直接落稿的章节初稿。",
    "要求:",
    "1. 严格遵守大纲、角色认知和当前状态,不得偷换设定。",
    "2. 输出只给正文 Markdown,不写解释,不写创作说明,不写额外标题页。",
    "3. 章节要有推进、有场景、有对白;不要把大纲改写成摘要。",
    "4. 新增设定必须克制,不能引入会破坏后续主线的大改动。",
    "5. 如遇信息不足,优先保守写法,不要瞎补世界规则。",
    "6. 默认使用第三人称近距写法,除非大纲明确要求,否则不要切成第一人称。",
    "7. 已给定的人名必须保持原样,不得擅自改名、换姓、写成近似名。",
    "8. 已失踪、已死亡、只存在于旧案或回忆中的人物,除非大纲明确要求其现身,否则不能直接出现在当前场景里说话行动。",
    "9. 不要擅自扩写支线,不要临时发明会抢走主线焦点的新人物、新家属、新寻亲任务;章节重心必须服从本章大纲。",
    "10. 角色回场时,优先延续旧关系、旧伤和旧账,不要为了省事给他们强加全新身世或临时职业。",
]


def _detect_chapter_characters(outline_text: str, project_root: Optional[Path]) -> list[str]:
    """从大纲文本+设定集白名单匹配本章会出现的角色。"""
    if not project_root:
        return []
    config = Path(project_root) / "设定集" / "语料库"
    if not config.is_dir():
        return []
    names = []
    for f in config.glob("*.md"):
        name = f.stem
        if not name or len(name) < 2:
            continue
        if name in outline_text:
            names.append(name)
    return names


def _load_voice_samples(project_root: Optional[Path], names: list[str], k: int = 4) -> str:
    """读 设定集/语料库/<角色>.md,每人挑 k 条样本拼成块。"""
    if not project_root or not names:
        return ""
    lib_dir = Path(project_root) / "设定集" / "语料库"
    if not lib_dir.is_dir():
        return ""
    sections: list[str] = []
    for name in names[:6]:  # 最多 6 个角色,避免 prompt 过长
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
        sections.append(f"### {name}")
        sections.extend(items[:k])
    return "\n".join(sections)


def build_write_messages(
    payload: Dict[str, Any],
    *,
    chapter_num: int,
    target_words: int,
    project_root: Optional[Path] = None,
) -> list[dict[str, str]]:
    anchors = load_character_anchors(project_root)
    if anchors:
        rules = list(BASE_WRITE_RULES) + ["", "角色锚点(来自本项目 设定集/角色约束.md):"]
        start_idx = len(BASE_WRITE_RULES) - 1
        for offset, anchor in enumerate(anchors, start=1):
            rules.append(f"{start_idx + offset}. {anchor}")
    else:
        rules = list(BASE_WRITE_RULES)
    base_system = "\n".join(rules)

    # Story System 主合约层(可选, 缺文件不影响)
    story_contract = load_story_contract(project_root)
    if story_contract:
        system_prompt = (
            base_system
            + "\n\n"
            + "=== 故事合约(Story System,全书宪法,优先于一切单章细节)===\n"
            + story_contract
            + "\n=== 故事合约结束 ==="
        )
    else:
        system_prompt = base_system

    # P1-A 角色言行风格库:从本章大纲匹配出场角色,各挑 4 条历史样本
    outline_text = str(payload.get("outline") or "")
    chapter_chars = _detect_chapter_characters(outline_text, project_root)
    voice_block = _load_voice_samples(project_root, chapter_chars, k=4)
    voice_section = f"\n【角色言行样本(模仿语气,不要照抄)】\n{voice_block}\n" if voice_block else ""

    # P1-B 伏笔追踪:注入超 20 章未推进的悬念
    foreshadow_section = ""
    if project_root:
        try:
            sys_path_save = list(sys.path) if hasattr(__builtins__, "__import__") else None
            import sys as _sys
            from pathlib import Path as _Path

            scripts_dir = str(_Path(__file__).resolve().parent)
            if scripts_dir not in _sys.path:
                _sys.path.insert(0, scripts_dir)
            from foreshadowing_tracker import render_open_for_prompt

            block = render_open_for_prompt(project_root, current_chapter=chapter_num, top_k=5)
            if block:
                foreshadow_section = f"\n【未回收伏笔提醒】\n{block}\n"
        except Exception:
            foreshadow_section = ""

    # 反向检索:防桥段复读
    anti_repeat_block = render_anti_repeat(payload, threshold=0.7)
    anti_repeat_section = ""
    if anti_repeat_block:
        anti_repeat_section = (
            "\n【⚠️ 桥段复读警报(避免重写以下已存在场景)】\n"
            "下面这几段是 RAG 检索到的高度相似历史段。本章场景结构、桥段铺陈、"
            "对白模式都要明显不同,不要复用同样的解决路径。\n\n"
            f"{anti_repeat_block}\n"
        )

    # 卷头 transition 章特别注入
    transition_section = ""
    vt = payload.get("volume_transition") or {}
    if vt.get("is_volume_head"):
        vol_num = vt.get("volume_num")
        vol_title = vt.get("volume_title") or ""
        scaffold = vt.get("new_volume_scaffold") or ""
        prev_tail = vt.get("prev_volume_tail_chapter")
        block_lines = [
            f"⚠️ 本章是第 {vol_num} 卷《{vol_title}》卷头章,需做章节情绪和节奏的转折承接:",
            f"- 上一卷已收束在第 {prev_tail} 章,先用 1-2 段微回顾让读者过渡",
            "- 然后正式打开新卷主题(场景 / 视角 / 时间 / 反派阵营换),不要继续上卷的小冲突",
            "- 卷头钩子比常规章更强,留一个能拉动整卷主线的悬念",
        ]
        if scaffold:
            block_lines.append("\n新卷阶段支架(参考结构,不要照抄):")
            block_lines.append(scaffold)
        transition_section = "\n【卷头 transition 注入】\n" + "\n".join(block_lines) + "\n"

    user_prompt = (
        f"请写第 {chapter_num} 章，目标篇幅约 {target_words} 字。\n\n"
        f"【本章大纲】\n{payload.get('outline', '')}\n\n"
        f"【前文摘要】\n{render_previous_summaries(payload.get('previous_summaries', []))}\n\n"
        f"【当前状态】\n{payload.get('state_summary', '')}\n\n"
        f"【写作提示】\n{render_guidance(payload)}\n\n"
        f"【RAG 线索】\n{render_rag_hits(payload)}\n"
        f"{voice_section}"
        f"{foreshadow_section}"
        f"{anti_repeat_section}"
        f"{transition_section}\n"
        "输出格式：\n"
        f"# 第{chapter_num}章\n"
        "接着直接写正文。不要附加“本章完”“作者的话”“创作说明”。"
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def build_review_messages(
    payload: Dict[str, Any],
    *,
    chapter_num: int,
    chapter_text: str,
) -> list[dict[str, str]]:
    system_prompt = (
        "你是网文审稿人。请检查章节是否违反大纲、设定、人物认知和连载节奏。\n"
        "输出必须是 Markdown，结构固定：\n"
        "1. 总评（1-10）\n"
        "2. Critical / Major / Minor 问题\n"
        "3. 可直接修改建议\n"
        "4. 是否建议重写本章（是/否）\n"
        "不要复述大段正文。"
    )
    user_prompt = (
        f"请审第 {chapter_num} 章。\n\n"
        f"【本章大纲】\n{payload.get('outline', '')}\n\n"
        f"【前文摘要】\n{render_previous_summaries(payload.get('previous_summaries', []))}\n\n"
        f"【当前状态】\n{payload.get('state_summary', '')}\n\n"
        f"【正文】\n{chapter_text}\n"
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
