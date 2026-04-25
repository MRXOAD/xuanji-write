#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
preflight.py — 写章前预检

跑 `webnovel.py llm draft --chapter N` 之前先验:
- 大纲文件存在(或 *阶段支架*.md 表格里有该段)
- 角色约束.md 存在
- state.json 当前卷号和 N 在同一卷
- LLM API key 已配
- monitoring API 已配则报 ✓,缺则报 INFO(不是 error,fallback 到 writing 也能跑)
- 大纲里出现的"主要人名"在 角色约束.md 里有定义(避免主角名跑偏)

用法:
    python preflight.py --project-root <BOOK> --chapter 232
    python preflight.py --project-root <BOOK> --chapter 232 --strict   # warning 当 error

cmd_draft / cmd_batch_draft 自动调,加 --no-preflight 可关。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# 确保导入 sibling 模块
sys.path.insert(0, str(Path(__file__).resolve().parent))


def _read_state(project_root: Path) -> dict:
    state_path = project_root / ".webnovel" / "state.json"
    if not state_path.exists():
        return {}
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _read_outline(project_root: Path, chapter_num: int) -> tuple[str, str]:
    """返回 (大纲文本, 来源描述)。来源 = "细纲" / "阶段支架降级" / "缺失"。"""
    try:
        from chapter_outline_loader import load_chapter_outline
    except Exception:
        return "", "缺失"
    outline = load_chapter_outline(project_root, chapter_num)
    if not outline or outline.startswith("⚠️"):
        return "", "缺失"
    if outline.startswith("[阶段支架降级大纲"):
        return outline, "阶段支架降级"
    return outline, "细纲"


def _read_role_anchors(project_root: Path) -> tuple[str, Path]:
    """读 角色约束.md 全文,作为已知角色 corpus(用全文匹配,不强行抽名字)。"""
    anchor_path = project_root / "设定集" / "角色约束.md"
    if not anchor_path.is_file():
        return "", anchor_path
    return anchor_path.read_text(encoding="utf-8"), anchor_path


def _extract_chinese_names_from_outline(outline: str) -> set[str]:
    """从大纲抽中文 2-3 字人名候选(用 jieba 词性 + 启发式过滤)。

    没装 jieba 就降级到粗 regex,目的是给作者一个软提示,误报可忽略。
    """
    # jieba 通用 stop:跟人名形似但实际是结构 / 时间词
    jieba_stop = {
        "章末",
        "章首",
        "本章",
        "下章",
        "上章",
        "段尾",
        "段首",
        "线索",
        "主线",
        "副线",
        "回收",
        "推进",
        "兑现",
    }

    # 先试 jieba(更准:nr 词性 = 人名)
    try:
        import jieba.posseg as pseg

        names: set[str] = set()
        for word, flag in pseg.cut(outline):
            if str(flag).startswith("nr") and 2 <= len(word) <= 4:
                if word not in jieba_stop:
                    names.add(word)
        return names
    except Exception:
        pass

    # 降级:`名:` 后跟冒号才算候选
    candidates: set[str] = set()
    for m in re.finditer(r"([一-鿿]{2,4})(?=[::])", outline):
        candidates.add(m.group(1))
    stop_suffix = ("失手", "打开", "出场", "登场", "结尾", "开场", "回来", "现身", "复出")
    stop = {
        "主角",
        "配角",
        "反派",
        "本章",
        "今天",
        "突然",
        "于是",
        "随后",
        "接着",
        "时候",
        "不过",
        "线索",
        "主线",
        "副线",
    }
    return {n for n in candidates if n not in stop and not any(n.endswith(s) for s in stop_suffix)}


def _llm_config_ok(project_root: Path) -> tuple[bool, dict]:
    try:
        from data_modules.config import DataModulesConfig
    except Exception as exc:
        return False, {"error": f"无法导入 config: {exc}"}
    try:
        cfg = DataModulesConfig.from_project_root(project_root)
    except Exception as exc:
        return False, {"error": f"读取 config 失败: {exc}"}

    info = {
        "llm_chat_model": cfg.llm_chat_model,
        "llm_base_url": cfg.llm_base_url,
        "llm_api_key_present": bool(str(cfg.llm_api_key or "").strip()),
        "llm_gateway_token_present": bool(str(getattr(cfg, "llm_gateway_token", "") or "").strip()),
        "deepseek_official_api_key_present": bool(str(getattr(cfg, "deepseek_official_api_key", "") or "").strip()),
        "monitoring_dedicated": False,
    }
    # 监控
    if hasattr(cfg, "role_view"):
        view = cfg.role_view("monitoring")
        info["monitoring_dedicated"] = view.has_dedicated_config(cfg)
        info["monitoring_chat_model"] = view.chat_model
        info["monitoring_base_url"] = view.base_url
    return True, info


def _volume_for_chapter(state: dict, chapter_num: int) -> int | None:
    progress = state.get("progress") or {}
    for vol in progress.get("volumes_planned") or []:
        rng = str(vol.get("chapters_range") or "")
        m = re.match(r"^\s*(\d+)\s*[-–]\s*(\d+)\s*$", rng)
        if m and int(m.group(1)) <= chapter_num <= int(m.group(2)):
            try:
                return int(vol.get("volume"))
            except (TypeError, ValueError):
                continue
    return None


def run_preflight(project_root: Path, chapter_num: int) -> dict:
    """跑预检,返回 {errors:[], warnings:[], infos:[], ok: bool}。"""
    errors: list[str] = []
    warnings: list[str] = []
    infos: list[str] = []

    # 1. 大纲
    outline, source = _read_outline(project_root, chapter_num)
    if source == "缺失":
        errors.append(f"第 {chapter_num} 章大纲缺失,请在 大纲/ 下放 `第{chapter_num}章-XXX.md`")
    elif source == "阶段支架降级":
        warnings.append(f"第 {chapter_num} 章只有阶段支架降级大纲,建议补一份逐章细纲")
    else:
        infos.append(f"大纲: {source}")

    # 2. 角色约束
    role_corpus, anchor_path = _read_role_anchors(project_root)
    if not anchor_path.is_file():
        errors.append(f"角色约束文件缺失: {anchor_path} (写一份每行一条角色定义)")
    elif not role_corpus.strip():
        warnings.append(f"角色约束 {anchor_path.name} 是空文件")
    else:
        infos.append(f"角色约束 {anchor_path.name} ({len(role_corpus)} 字)")

    # 3. 大纲提到的人名,如果在角色约束 corpus 里没出现 = 警告
    if outline and role_corpus:
        outline_names = _extract_chinese_names_from_outline(outline)
        unknown = {n for n in outline_names if n not in role_corpus}
        if unknown:
            warnings.append(
                f"大纲提到但角色约束.md 未提及的人名: {', '.join(sorted(unknown))} "
                f"(如果是配角/路人可忽略;主线角色应补到 角色约束.md)"
            )

    # 4. state 卷号和当前章一致
    state = _read_state(project_root)
    if state:
        progress = state.get("progress") or {}
        current_vol = progress.get("current_volume")
        expected_vol = _volume_for_chapter(state, chapter_num)
        if expected_vol is not None and current_vol is not None and int(current_vol) != int(expected_vol):
            warnings.append(
                f"state.current_volume={current_vol} 但第 {chapter_num} 章按 volumes_planned 在第 {expected_vol} 卷 "
                f"(跑 update_state.py --audit-volumes 校准)"
            )

    # 5. LLM 配置
    ok, llm_info = _llm_config_ok(project_root)
    if not ok:
        errors.append(f"LLM 配置错误: {llm_info.get('error')}")
    else:
        if not llm_info.get("llm_chat_model"):
            errors.append("缺 LLM_CHAT_MODEL,在 .env 配 LLM_CHAT_MODEL=deepseek-chat 之类")
        has_auth = (
            llm_info.get("llm_api_key_present")
            or llm_info.get("deepseek_official_api_key_present")
            or llm_info.get("llm_gateway_token_present")
        )
        if not has_auth:
            errors.append("缺 LLM_API_KEY / DEEPSEEK_API_KEY / LLM_GATEWAY_TOKEN(网关用)中的任一个")
        if llm_info.get("monitoring_dedicated"):
            infos.append(
                f"监控走独立 API: {llm_info.get('monitoring_chat_model', '?')} "
                f"@ {llm_info.get('monitoring_base_url', '?')}"
            )
        else:
            infos.append("监控未独立配置, fallback 到 writing API (可在 .env 配 MONITORING_*)")

    return {
        "chapter": chapter_num,
        "errors": errors,
        "warnings": warnings,
        "infos": infos,
        "ok": len(errors) == 0,
    }


def _print_report(report: dict, *, strict: bool) -> int:
    chapter = report["chapter"]
    print(f"=== 预检 第 {chapter} 章 ===")
    for msg in report["infos"]:
        print(f"  ℹ️  {msg}")
    for msg in report["warnings"]:
        print(f"  ⚠️  {msg}")
    for msg in report["errors"]:
        print(f"  ❌ {msg}")
    if report["ok"]:
        if strict and report["warnings"]:
            print("strict 模式下有 warning, 退出码 1")
            return 1
        print(f"✓ 第 {chapter} 章预检通过 ({len(report['warnings'])} warn / 0 error)")
        return 0
    print(f"❌ 第 {chapter} 章预检失败 ({len(report['errors'])} error)")
    return 2


def main() -> int:
    parser = argparse.ArgumentParser(description="写章前预检")
    parser.add_argument("--project-root", required=True, help="书项目根目录")
    parser.add_argument("--chapter", type=int, required=True, help="章号")
    parser.add_argument("--strict", action="store_true", help="把 warning 当 error")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()

    project_root = Path(args.project_root).expanduser().resolve()
    report = run_preflight(project_root, args.chapter)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if not report["ok"]:
            return 2
        if args.strict and report["warnings"]:
            return 1
        return 0
    return _print_report(report, strict=args.strict)


if __name__ == "__main__":
    sys.exit(main())
