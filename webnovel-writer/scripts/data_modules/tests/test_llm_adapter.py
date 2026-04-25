#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import http.client
import io
import json
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest


def _ensure_scripts_on_path() -> None:
    scripts_dir = Path(__file__).resolve().parents[2]
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))


def _build_project(tmp_path: Path) -> Path:
    project_root = tmp_path / "book"
    (project_root / ".webnovel").mkdir(parents=True, exist_ok=True)
    (project_root / "正文").mkdir(parents=True, exist_ok=True)
    (project_root / "大纲").mkdir(parents=True, exist_ok=True)

    state = {
        "project_info": {},
        "progress": {"current_chapter": 0, "total_words": 0},
        "protagonist_state": {
            "power": {"realm": "炼气", "layer": 1, "bottleneck": None},
            "location": "村口",
        },
        "relationships": {},
        "world_settings": {},
        "plot_threads": {},
        "review_checkpoints": [],
        "chapter_meta": {},
    }
    (project_root / ".webnovel" / "state.json").write_text(
        json.dumps(state, ensure_ascii=False),
        encoding="utf-8",
    )
    return project_root


def _simple_context(outline: str) -> dict:
    return {
        "chapter": 1,
        "outline": outline,
        "previous_summaries": [],
        "state_summary": "当前状态",
        "writing_guidance": {"guidance_items": [], "checklist": []},
        "rag_assist": {"invoked": False, "hits": [], "reason": "test"},
    }


def test_chat_completions_url_variants():
    _ensure_scripts_on_path()

    from llm_adapter import _chat_completions_url

    assert _chat_completions_url("https://example.com") == "https://example.com/v1/chat/completions"
    assert _chat_completions_url("https://example.com/v1") == "https://example.com/v1/chat/completions"
    assert _chat_completions_url("https://example.com/v1/chat/completions") == "https://example.com/v1/chat/completions"
    assert (
        _chat_completions_url("https://api.mrxoad.uk/api/deepseek")
        == "https://api.mrxoad.uk/api/deepseek/chat/completions"
    )
    assert (
        _chat_completions_url("https://api.mrxoad.uk/api/siliconflow")
        == "https://api.mrxoad.uk/api/siliconflow/chat/completions"
    )
    assert (
        _chat_completions_url("https://api.mrxoad.uk/api/openrouter")
        == "https://api.mrxoad.uk/api/openrouter/v1/chat/completions"
    )
    assert (
        _chat_completions_url("https://api.mrxoad.uk/api/dashscope")
        == "https://api.mrxoad.uk/api/dashscope/v1/chat/completions"
    )


def test_build_llm_routes_prefers_official_deepseek_before_configured_gateway():
    _ensure_scripts_on_path()

    from llm_adapter import _build_llm_routes

    cfg = SimpleNamespace(
        llm_base_url="https://api.mrxoad.uk/api/deepseek",
        llm_api_key="generic-key",
        llm_gateway_token="gw-token",
        deepseek_official_base_url="https://api.deepseek.com",
        deepseek_official_api_key="official-key",
    )

    routes = _build_llm_routes(cfg, "deepseek-chat")
    assert [route["name"] for route in routes] == ["deepseek_official", "configured"]
    assert routes[0]["base_url"] == "https://api.deepseek.com"
    assert routes[1]["base_url"] == "https://api.mrxoad.uk/api/deepseek"


def test_build_llm_routes_skips_gateway_route_without_token():
    _ensure_scripts_on_path()

    from llm_adapter import _build_llm_routes, _env_summary

    cfg = SimpleNamespace(
        llm_provider="openai_compatible",
        llm_base_url="https://api.mrxoad.uk/api/deepseek",
        llm_chat_model="deepseekv4flash",
        llm_reasoning_model="deepseekv4flash",
        llm_api_key="",
        llm_gateway_token="",
        deepseek_official_base_url="https://api.deepseek.com",
        deepseek_official_api_key="",
        llm_timeout=180,
        deepseek_base_url="https://api.mrxoad.uk/api/deepseek",
        deepseek_model="deepseekv4flash",
    )

    assert _build_llm_routes(cfg, "deepseekv4flash") == []
    summary = _env_summary(cfg, Path("/tmp/book"))
    assert "API_GATEWAY_TOKEN" in summary["missing_fields"]


def test_call_llm_falls_back_to_configured_route_after_official_failure(monkeypatch):
    _ensure_scripts_on_path()

    import llm_adapter as module

    cfg = SimpleNamespace(
        llm_provider="openai_compatible",
        llm_base_url="https://api.mrxoad.uk/api/deepseek",
        llm_api_key="generic-key",
        llm_gateway_token="gw-token",
        deepseek_official_base_url="https://api.deepseek.com",
        deepseek_official_api_key="official-key",
        llm_timeout=1,
        api_max_retries=1,
        api_retry_delay=0,
    )

    calls = []

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"choices":[{"message":{"content":"# \\u7b2c1\\u7ae0\\n\\u6210\\u529f"}}]}'

    def fake_urlopen(req, timeout):
        calls.append(
            {
                "url": req.full_url,
                "authorization": req.headers.get("Authorization"),
                "gateway": req.headers.get("X-gateway-token"),
            }
        )
        if len(calls) == 1:
            raise module.error.HTTPError(
                req.full_url,
                503,
                "Service Unavailable",
                hdrs=None,
                fp=io.BytesIO(b'{"error":"upstream unavailable"}'),
            )
        return _Resp()

    monkeypatch.setattr(module.request, "urlopen", fake_urlopen)

    text = module._call_llm(
        cfg,
        messages=[{"role": "user", "content": "hi"}],
        model="deepseek-chat",
        temperature=0.9,
        max_tokens=128,
    )

    assert "成功" in text
    assert calls[0]["url"] == "https://api.deepseek.com/v1/chat/completions"
    assert calls[0]["authorization"] == "Bearer official-key"
    assert calls[0]["gateway"] is None
    assert calls[1]["url"] == "https://api.mrxoad.uk/api/deepseek/chat/completions"
    assert calls[1]["authorization"] == "Bearer generic-key"
    assert calls[1]["gateway"] == "gw-token"


def test_call_llm_retries_after_incomplete_read(monkeypatch):
    _ensure_scripts_on_path()

    import llm_adapter as module

    cfg = SimpleNamespace(
        llm_provider="openai_compatible",
        llm_base_url="https://api.deepseek.com",
        llm_api_key="",
        llm_gateway_token="",
        deepseek_official_base_url="https://api.deepseek.com",
        deepseek_official_api_key="official-key",
        llm_timeout=1,
        api_max_retries=2,
        api_retry_delay=0,
    )

    calls = {"count": 0}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            calls["count"] += 1
            if calls["count"] == 1:
                raise http.client.IncompleteRead(b"partial-body")
            return b'{"choices":[{"message":{"content":"# \\u7b2c1\\u7ae0\\n\\u91cd\\u8bd5\\u6210\\u529f"}}]}'

    monkeypatch.setattr(module.request, "urlopen", lambda req, timeout: _Resp())

    text = module._call_llm(
        cfg,
        messages=[{"role": "user", "content": "hi"}],
        model="deepseek-chat",
        temperature=0.9,
        max_tokens=128,
    )

    assert "重试成功" in text
    assert calls["count"] == 2


def test_strip_code_fence():
    _ensure_scripts_on_path()

    from llm_adapter import _strip_code_fence

    fenced = "```markdown\n# 第12章\n正文\n```"
    assert _strip_code_fence(fenced) == "# 第12章\n正文"
    assert _strip_code_fence("# 第12章\n正文") == "# 第12章\n正文"


def test_write_text_file_requires_overwrite(tmp_path):
    _ensure_scripts_on_path()

    from llm_adapter import _write_text_file

    target = tmp_path / "正文" / "第0001章.md"
    _write_text_file(target, "# 第1章\n正文", overwrite=False)
    assert target.read_text(encoding="utf-8").startswith("# 第1章")

    with pytest.raises(FileExistsError):
        _write_text_file(target, "# 第1章\n新正文", overwrite=False)

    _write_text_file(target, "# 第1章\n新正文", overwrite=True)
    assert "新正文" in target.read_text(encoding="utf-8")


def test_default_review_path(tmp_path):
    _ensure_scripts_on_path()

    from llm_adapter import _default_review_path

    path = _default_review_path(tmp_path, 12)
    assert path == tmp_path / ".webnovel" / "reviews" / "ch0012.llm-review.md"


def test_extract_summary_prefers_explicit_section_and_outline_title(tmp_path):
    _ensure_scripts_on_path()

    from llm_adapter import _extract_chapter_title, _extract_summary_text

    chapter_path = tmp_path / "正文" / "第0001章.md"
    chapter_path.parent.mkdir(parents=True, exist_ok=True)
    chapter_path.write_text("# 第1章\n正文", encoding="utf-8")

    text = "# 第1章\n\n## 本章摘要\n这里是明确摘要。\n\n正文第一段。"
    outline = "### 第1章：起势\n- 主角进城\n- 发现异样"

    assert _extract_summary_text(text, outline_text=outline) == "这里是明确摘要。"
    # 正文存在 → 优先用正文(P1-D 修:防止批量摘要全是大纲模板)
    assert _extract_summary_text("# 第1章\n正文第一段。", outline_text=outline) == "正文第一段。"
    # 正文空 → 才回退用大纲
    assert _extract_summary_text("", outline_text=outline) == "主角进城 发现异样"
    assert (
        _extract_chapter_title(
            "正文没有标题",
            1,
            chapter_path,
            outline_text=outline,
        )
        == "起势"
    )


def test_parse_review_metrics_accepts_chinese_sections_and_points(tmp_path):
    _ensure_scripts_on_path()

    from llm_adapter import _parse_review_metrics

    report_path = tmp_path / "report.md"
    metrics = _parse_review_metrics(
        "## 综合评分\n82分\n\n"
        "## 严重问题\n设定冲突导致战力失真\n\n"
        "## 主要问题\n1. 节奏偏慢\n2. 结尾钩子不够\n\n"
        "## 次要问题\n个别对白重复\n",
        chapter_num=3,
        report_path=report_path,
    )

    assert metrics["overall_score"] == 82.0
    assert metrics["severity_counts"] == {"critical": 1, "high": 2, "medium": 1, "low": 0}
    assert metrics["critical_issues"] == ["设定冲突导致战力失真"]

    metrics = _parse_review_metrics(
        "## 总评\n**7.5/10**\n\n## Critical\n- 战力失真\n",
        chapter_num=3,
        report_path=report_path,
    )
    assert metrics["overall_score"] == 75.0

    metrics = _parse_review_metrics(
        "总分 7.5/10\n\n## Major\n- 节奏偏慢\n",
        chapter_num=3,
        report_path=report_path,
    )
    assert metrics["overall_score"] == 75.0

    metrics = _parse_review_metrics(
        "## 总评\n8/10\n\n## Critical 问题\n- 设定冲突\n\n## Major 问题\n- 节奏偏慢\n",
        chapter_num=3,
        report_path=report_path,
    )
    assert metrics["severity_counts"]["critical"] == 1
    assert metrics["severity_counts"]["high"] == 1

    metrics = _parse_review_metrics(
        "## Overall Score\n8/10\n\n## Critical Issues\n- 设定冲突\n\n## Major Issues\n- 节奏偏慢\n\n## Minor Issues\n- 描写重复\n",
        chapter_num=3,
        report_path=report_path,
    )
    assert metrics["severity_counts"] == {"critical": 1, "high": 1, "medium": 1, "low": 0}

    metrics = _parse_review_metrics(
        "# 网文审稿报告 - 第1章\n\n## 1. 总评 (8/10)\n本章完成度很高。\n",
        chapter_num=3,
        report_path=report_path,
    )
    assert metrics["overall_score"] == 80.0


def test_cmd_draft_reuses_existing_chapter_and_syncs_outputs(tmp_path, monkeypatch):
    _ensure_scripts_on_path()

    import llm_adapter as module
    from data_modules.config import DataModulesConfig
    from data_modules.index_manager import IndexManager

    project_root = _build_project(tmp_path)
    existing = project_root / "正文" / "第1卷" / "第001章-旧名.md"
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_text("旧稿", encoding="utf-8")

    monkeypatch.setattr(
        module, "build_chapter_context_payload", lambda *_args, **_kwargs: _simple_context("### 第1章：起势")
    )
    monkeypatch.setattr(
        module,
        "_call_llm",
        lambda *_args, **_kwargs: "# 第1章 旧名\n正文第一段。\n\n正文第二段。\n",
    )

    args = argparse.Namespace(
        project_root=str(project_root),
        chapter=1,
        output=None,
        model=None,
        target_words=2200,
        temperature=None,
        max_tokens=None,
        overwrite=True,
        stdout_only=False,
        use_volume_layout=False,
    )

    assert module.cmd_draft(args) == 0

    assert "正文第一段" in existing.read_text(encoding="utf-8")
    assert not (project_root / "正文" / "第0001章.md").exists()

    summary_path = project_root / ".webnovel" / "summaries" / "ch0001.md"
    assert summary_path.exists()
    assert "## 剧情摘要" in summary_path.read_text(encoding="utf-8")

    state = json.loads((project_root / ".webnovel" / "state.json").read_text(encoding="utf-8"))
    assert state["progress"]["current_chapter"] == 1
    assert state["progress"]["total_words"] > 0

    manager = IndexManager(DataModulesConfig.from_project_root(project_root))
    chapter = manager.get_chapter(1)
    assert chapter is not None
    assert chapter["summary"]
    assert chapter["word_count"] > 0
    assert chapter["title"] == "旧名"


def test_cmd_write_errors_when_outline_missing(tmp_path, monkeypatch):
    _ensure_scripts_on_path()

    import llm_adapter as module

    project_root = _build_project(tmp_path)
    monkeypatch.setattr(
        module,
        "build_chapter_context_payload",
        lambda *_args, **_kwargs: _simple_context("⚠️ 大纲文件不存在：第 2 章"),
    )
    monkeypatch.setattr(module, "_call_llm", lambda *_args, **_kwargs: pytest.fail("不该继续调用模型"))

    args = argparse.Namespace(
        project_root=str(project_root),
        chapter=2,
        output=None,
        model=None,
        target_words=2200,
        temperature=None,
        max_tokens=None,
        overwrite=True,
        stdout_only=False,
        use_volume_layout=False,
    )

    with pytest.raises(ValueError, match="缺少可用大纲"):
        module.cmd_draft(args)


def test_cmd_review_saves_metrics_and_keeps_review_checkpoint(tmp_path, monkeypatch):
    _ensure_scripts_on_path()

    import llm_adapter as module
    from data_modules.config import DataModulesConfig
    from data_modules.index_manager import IndexManager

    project_root = _build_project(tmp_path)
    chapter_file = project_root / "正文" / "第0001章.md"
    chapter_file.write_text("# 第1章\n这里是正文。", encoding="utf-8")

    monkeypatch.setattr(
        module, "build_chapter_context_payload", lambda *_args, **_kwargs: _simple_context("### 第1章：审稿")
    )
    monkeypatch.setattr(
        module,
        "_call_llm",
        lambda *_args, **_kwargs: (
            "## 总评\n7.5/10\n\n"
            "## Critical\n- 设定冲突\n\n"
            "## Major\n- 节奏偏慢\n- 冲突抬升不够\n\n"
            "## Minor\n- 个别对白重复\n"
        ),
    )

    args = argparse.Namespace(
        project_root=str(project_root),
        chapter=1,
        chapter_file=None,
        output=None,
        model=None,
        temperature=None,
        max_tokens=None,
        overwrite=True,
        stdout_only=False,
        skip_state_record=False,
    )

    assert module.cmd_review(args) == 0

    state = json.loads((project_root / ".webnovel" / "state.json").read_text(encoding="utf-8"))
    checkpoints = state.get("review_checkpoints") or []
    assert len(checkpoints) == 1
    assert checkpoints[0]["chapters"] == "1"

    manager = IndexManager(DataModulesConfig.from_project_root(project_root))
    records = manager.get_recent_review_metrics(limit=1)
    assert len(records) == 1
    record = records[0]
    assert record["overall_score"] == 75.0
    assert record["severity_counts"]["critical"] == 1
    assert record["severity_counts"]["high"] == 2
    assert record["severity_counts"]["medium"] == 1
    assert record["critical_issues"] == ["设定冲突"]
    assert record["report_file"] == ".webnovel/reviews/ch0001.llm-review.md"


def test_cmd_write_updates_total_words_for_output_outside_project_root(tmp_path, monkeypatch):
    _ensure_scripts_on_path()

    import llm_adapter as module

    project_root = _build_project(tmp_path)
    state_path = project_root / ".webnovel" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["progress"] = {"current_chapter": 2, "total_words": 120}
    state_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")

    monkeypatch.setattr(
        module,
        "build_chapter_context_payload",
        lambda *_args, **_kwargs: _simple_context("### 第3章：外置成稿\n- 主角离开村子"),
    )
    monkeypatch.setattr(
        module,
        "_call_llm",
        lambda *_args, **_kwargs: "# 第3章\n外置目录正文。\n",
    )

    output_path = tmp_path / "external-output" / "第0003章.md"
    args = argparse.Namespace(
        project_root=str(project_root),
        chapter=3,
        output=str(output_path),
        model=None,
        target_words=2200,
        temperature=None,
        max_tokens=None,
        overwrite=True,
        stdout_only=False,
        use_volume_layout=False,
    )

    assert module.cmd_draft(args) == 0

    updated = json.loads(state_path.read_text(encoding="utf-8"))
    assert updated["progress"]["current_chapter"] == 3
    assert updated["progress"]["total_words"] > 120
    registry = json.loads((project_root / ".webnovel" / "external_chapters.json").read_text(encoding="utf-8"))
    assert registry["0003"] == str(output_path.resolve())


def test_scan_chapter_progress_uses_registry_key_for_external_path(tmp_path):
    _ensure_scripts_on_path()

    from llm_adapter import _scan_chapter_progress

    project_root = _build_project(tmp_path)
    external_path = tmp_path / "external-output" / "终稿.md"
    external_path.parent.mkdir(parents=True, exist_ok=True)
    external_path.write_text("# 第三章\n外置目录正文。\n", encoding="utf-8")

    registry_path = project_root / ".webnovel" / "external_chapters.json"
    registry_path.write_text(
        json.dumps({"0003": str(external_path.resolve())}, ensure_ascii=False),
        encoding="utf-8",
    )

    current_chapter, total_words = _scan_chapter_progress(project_root)
    assert current_chapter == 3
    assert total_words > 0


def test_scan_chapter_progress_uses_registry_for_internal_custom_output_path(tmp_path):
    _ensure_scripts_on_path()

    from llm_adapter import _register_external_chapter_path, _scan_chapter_progress

    project_root = _build_project(tmp_path)
    custom_path = project_root / "导出" / "终稿.md"
    custom_path.parent.mkdir(parents=True, exist_ok=True)
    custom_path.write_text("# 第三章\n项目内自定义输出。\n", encoding="utf-8")

    _register_external_chapter_path(project_root, 3, custom_path)
    registry = json.loads((project_root / ".webnovel" / "external_chapters.json").read_text(encoding="utf-8"))
    assert registry["0003"] == str(custom_path.resolve())

    current_chapter, total_words = _scan_chapter_progress(project_root)
    assert current_chapter == 3
    assert total_words > 0


def test_load_chapter_text_uses_registry_for_custom_output_path(tmp_path):
    _ensure_scripts_on_path()

    from llm_adapter import _load_chapter_text, _register_external_chapter_path

    project_root = _build_project(tmp_path)
    custom_path = project_root / "导出" / "终稿.md"
    custom_path.parent.mkdir(parents=True, exist_ok=True)
    custom_path.write_text("# 第三章\n项目内自定义输出。\n", encoding="utf-8")

    _register_external_chapter_path(project_root, 3, custom_path)
    loaded_path, chapter_text = _load_chapter_text(project_root, 3, None)
    assert loaded_path == custom_path.resolve()
    assert "项目内自定义输出" in chapter_text


def test_load_chapter_text_prefers_registry_over_standard_path(tmp_path):
    _ensure_scripts_on_path()

    from llm_adapter import _load_chapter_text, _register_external_chapter_path

    project_root = _build_project(tmp_path)
    standard_path = project_root / "正文" / "第0003章.md"
    standard_path.write_text("# 第三章\n旧稿。\n", encoding="utf-8")

    custom_path = project_root / "导出" / "终稿.md"
    custom_path.parent.mkdir(parents=True, exist_ok=True)
    custom_path.write_text("# 第三章\n终稿正文更长一些。\n", encoding="utf-8")

    _register_external_chapter_path(project_root, 3, custom_path)
    loaded_path, chapter_text = _load_chapter_text(project_root, 3, None)
    assert loaded_path == custom_path.resolve()
    assert "终稿正文更长一些" in chapter_text


def test_scan_chapter_progress_prefers_registry_over_standard_path(tmp_path):
    _ensure_scripts_on_path()

    from llm_adapter import _register_external_chapter_path, _scan_chapter_progress

    project_root = _build_project(tmp_path)
    standard_path = project_root / "正文" / "第0003章.md"
    standard_path.write_text("# 第三章\n旧稿。\n", encoding="utf-8")

    custom_path = project_root / "导出" / "终稿.md"
    custom_path.parent.mkdir(parents=True, exist_ok=True)
    custom_path.write_text("# 第三章\n终稿正文更长一些。\n", encoding="utf-8")

    _register_external_chapter_path(project_root, 3, custom_path)
    current_chapter, total_words = _scan_chapter_progress(project_root)
    assert current_chapter == 3
    assert total_words == len("终稿正文更长一些。")


def test_load_chapter_text_supports_relative_registry_path(tmp_path):
    _ensure_scripts_on_path()

    from llm_adapter import _load_chapter_text

    project_root = _build_project(tmp_path)
    standard_path = project_root / "正文" / "第0003章.md"
    standard_path.write_text("# 第三章\n旧稿。\n", encoding="utf-8")

    custom_path = project_root / "导出" / "终稿.md"
    custom_path.parent.mkdir(parents=True, exist_ok=True)
    custom_path.write_text("# 第三章\n终稿正文更长一些。\n", encoding="utf-8")

    registry_path = project_root / ".webnovel" / "external_chapters.json"
    registry_path.write_text(
        json.dumps({"0003": "导出/终稿.md"}, ensure_ascii=False),
        encoding="utf-8",
    )

    loaded_path, chapter_text = _load_chapter_text(project_root, 3, None)
    assert loaded_path == custom_path.resolve()
    assert "终稿正文更长一些" in chapter_text


def test_scan_chapter_progress_supports_relative_registry_path(tmp_path):
    _ensure_scripts_on_path()

    from llm_adapter import _scan_chapter_progress

    project_root = _build_project(tmp_path)
    standard_path = project_root / "正文" / "第0003章.md"
    standard_path.write_text("# 第三章\n旧稿。\n", encoding="utf-8")

    custom_path = project_root / "导出" / "终稿.md"
    custom_path.parent.mkdir(parents=True, exist_ok=True)
    custom_path.write_text("# 第三章\n终稿正文更长一些。\n", encoding="utf-8")

    registry_path = project_root / ".webnovel" / "external_chapters.json"
    registry_path.write_text(
        json.dumps({"0003": "导出/终稿.md"}, ensure_ascii=False),
        encoding="utf-8",
    )

    current_chapter, total_words = _scan_chapter_progress(project_root)
    assert current_chapter == 3
    assert total_words == len("终稿正文更长一些。")


def test_build_dynamic_foreshadowing_advances_to_next_milestone(tmp_path):
    _ensure_scripts_on_path()

    from llm_adapter import _build_dynamic_foreshadowing

    project_root = _build_project(tmp_path)
    clue_table = """# 线索回收表

| 线索 | 首次埋设 | 早期提醒 | 中段推进 | 后段推进 | 终局回收 |
|---|---|---|---|---|---|
| 姐姐许灯娘留下半张香票 | 第 3 章 | 第 36 章州边义庄；第 58 章水路线 | 第 118 章旧名页侧证 | 第 356 章道城案库 | 第 735-760 章 |
"""
    (project_root / "大纲" / "线索回收表.md").write_text(clue_table, encoding="utf-8")

    state = json.loads((project_root / ".webnovel" / "state.json").read_text(encoding="utf-8"))
    state["plot_threads"] = {"foreshadowing": []}
    (project_root / ".webnovel" / "state.json").write_text(
        json.dumps(state, ensure_ascii=False),
        encoding="utf-8",
    )

    records = _build_dynamic_foreshadowing(project_root, state, current_chapter=60)
    assert len(records) == 1
    assert records[0]["content"] == "姐姐许灯娘留下半张香票"
    assert records[0]["planted_chapter"] == 3
    assert records[0]["target_chapter"] == 118
    assert records[0]["milestones"] == [36, 58, 118, 356, 735]


def test_sync_written_chapter_populates_tracking_state_and_index(tmp_path, monkeypatch):
    _ensure_scripts_on_path()

    import llm_adapter as module
    from data_modules.config import DataModulesConfig
    from data_modules.index_manager import IndexManager

    project_root = _build_project(tmp_path)
    (project_root / "设定集").mkdir(parents=True, exist_ok=True)

    state_path = project_root / ".webnovel" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["project_info"] = {
        "heroine_names": "沈见秋",
        "co_protagonists": "季七",
        "antagonist_tiers": "韩五尺",
    }
    state["protagonist_state"]["name"] = "许三更"
    state["plot_threads"] = {"foreshadowing": []}
    state["strand_tracker"] = {
        "last_quest_chapter": 0,
        "last_fire_chapter": 0,
        "last_constellation_chapter": 0,
        "current_dominant": None,
        "chapters_since_switch": 0,
        "history": [],
    }
    state_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")

    (project_root / "设定集" / "主角组.md").write_text(
        """# 主线角色群像

| 名称 | 定位 | 主线贡献 | 关键缺陷 | 关键能力 |
|------|------|----------|----------|----------|
| 许三更 | 主视角 | 查错名 | 多疑 | 闻灰辨名 |
| 沈见秋 | 官配女主 / 后期双核心 | 香行知识 | 冷 | 听香辨祟 |
| 韩五尺 | 地方压账人 | 压账 | 狠 | 改签 |
""",
        encoding="utf-8",
    )
    (project_root / "大纲" / "线索回收表.md").write_text(
        """# 线索回收表

| 线索 | 首次埋设 | 早期提醒 | 中段推进 | 后段推进 | 终局回收 |
|---|---|---|---|---|---|
| 许三更这个名字像临时名字 | 第 1 章 | 第 35 章夜祭残名 | 第 112 章旧名页 | 第 540 章旧朝残礼 | 第 760-790 章 |
""",
        encoding="utf-8",
    )

    def fake_record_progress(root, current_chapter, total_words):
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        payload.setdefault("progress", {})
        payload["progress"]["current_chapter"] = current_chapter
        payload["progress"]["total_words"] = total_words
        state_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    monkeypatch.setattr(module, "_record_progress", fake_record_progress)

    chapter_path = project_root / "正文" / "第0001章-夜船问香.md"
    chapter_text = (
        "# 第1章\n\n许三更和沈见秋追查夜船账册，发现香火局留下的空白香签。\n\n两人翻到账册后反咬韩五尺，决定继续追船。"
    )
    summary_override = (
        "场景：香行后屋翻账 推进：许三更和沈见秋并查夜船。 "
        "兑现：主角拿到第一份账册证据。 章末钩子：香火局为什么提前留下空白香签？"
    )

    result = module._sync_written_chapter(
        project_root,
        1,
        chapter_path,
        chapter_text,
        outline_text="### 第1章：夜船问香\n- 查账\n- 追船",
        summary_override=summary_override,
        rewrite_summary=False,
    )

    assert result["current_chapter"] == 1

    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["chapter_meta"]["0001"]["hook_type"] == "悬念钩"
    assert "查错破局" in state["chapter_meta"]["0001"]["coolpoint_patterns"]
    assert state["strand_tracker"]["history"][-1]["chapter"] == 1
    assert state["plot_threads"]["foreshadowing"][0]["target_chapter"] == 35
    assert state["foreshadowing"][0]["target_chapter"] == 35
    assert state["relationships"]["allies"][0]["name"] == "沈见秋"

    idx = IndexManager(DataModulesConfig.from_project_root(project_root))
    reading_power = idx.get_chapter_reading_power(1)
    assert reading_power["hook_type"] == "悬念钩"
    assert idx.get_entity("char:许三更") is not None
    assert idx.get_relationship_between("char:许三更", "char:沈见秋")


def test_cmd_sync_rebuilds_progress_and_tracking(tmp_path, monkeypatch):
    _ensure_scripts_on_path()

    import llm_adapter as module

    project_root = _build_project(tmp_path)
    (project_root / "设定集").mkdir(parents=True, exist_ok=True)
    state_path = project_root / ".webnovel" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["protagonist_state"]["name"] = "许三更"
    state["project_info"] = {
        "heroine_names": "沈见秋",
        "co_protagonists": "",
        "antagonist_tiers": "韩五尺",
    }
    state["plot_threads"] = {"foreshadowing": []}
    state_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")

    (project_root / "设定集" / "主角组.md").write_text(
        """# 主线角色群像

| 名称 | 定位 | 主线贡献 | 关键缺陷 | 关键能力 |
|------|------|----------|----------|----------|
| 许三更 | 主视角 | 查错名 | 多疑 | 闻灰辨名 |
| 沈见秋 | 官配女主 | 香行知识 | 冷 | 听香辨祟 |
| 韩五尺 | 地方压账人 | 压账 | 狠 | 改签 |
""",
        encoding="utf-8",
    )
    (project_root / "大纲" / "线索回收表.md").write_text(
        """# 线索回收表

| 线索 | 首次埋设 | 早期提醒 | 中段推进 | 后段推进 | 终局回收 |
|---|---|---|---|---|---|
| 半张旧香票 | 第 2 章 | 第 18 章 | 第 60 章 | 第 280 章 | 第 760 章 |
""",
        encoding="utf-8",
    )
    (project_root / "大纲" / "第1章-起头.md").write_text(
        "### 第1章：起头\n- 夜船查账\n- 空白香签",
        encoding="utf-8",
    )
    (project_root / "正文" / "第0001章-起头.md").write_text(
        "# 第1章\n\n许三更和沈见秋夜里翻到账册，查出一张空白香签，决定继续追查。",
        encoding="utf-8",
    )
    (project_root / "大纲" / "第2章-追灰.md").write_text(
        "### 第2章：追灰\n- 顺水追查\n- 韩五尺露头",
        encoding="utf-8",
    )
    second_text = "# 第2章\n\n许三更顺着灰路追到河埠，韩五尺的人也跟了上来。"
    (project_root / "正文" / "第0002章-追灰.md").write_text(
        second_text,
        encoding="utf-8",
    )

    def fake_record_progress(root, current_chapter, total_words):
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        payload.setdefault("progress", {})
        payload["progress"]["current_chapter"] = current_chapter
        payload["progress"]["total_words"] = total_words
        payload["current_chapter"] = current_chapter
        payload["total_words"] = total_words
        state_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    monkeypatch.setattr(module, "_record_progress", fake_record_progress)

    args = argparse.Namespace(
        project_root=str(project_root),
        chapter=None,
        from_chapter=1,
        to_chapter=2,
        rewrite_summary=False,
        skip_missing=False,
    )
    assert module.cmd_sync(args) == 0

    updated = json.loads(state_path.read_text(encoding="utf-8"))
    assert updated["progress"]["current_chapter"] == 2
    assert updated["current_chapter"] == 2
    assert updated["progress"]["total_words"] > 0
    assert updated["total_words"] == updated["progress"]["total_words"]
    scanned_chapter, scanned_words = module._scan_chapter_progress(project_root)
    assert scanned_chapter == 2
    assert updated["progress"]["total_words"] == scanned_words
    assert updated["chapter_meta"]["0001"]["hook_type"] in {"悬念钩", "行动钩", "信息钩", "情绪钩"}
    assert updated["foreshadowing"]
