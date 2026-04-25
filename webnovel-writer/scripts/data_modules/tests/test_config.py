#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Config tests
"""

import os

from data_modules import config as config_module
from data_modules.config import DataModulesConfig, get_config, set_project_root


def test_config_paths_and_defaults(tmp_path):
    cfg = DataModulesConfig.from_project_root(tmp_path)
    assert cfg.project_root == tmp_path
    assert cfg.webnovel_dir.name == ".webnovel"
    assert cfg.state_file.name == "state.json"
    assert cfg.index_db.name == "index.db"
    assert cfg.rag_db.name == "rag.db"
    assert cfg.vector_db.name == "vectors.db"

    cfg.ensure_dirs()
    assert cfg.webnovel_dir.exists()


def test_get_config_and_set_project_root(tmp_path):
    set_project_root(tmp_path)
    cfg = get_config()
    assert cfg.project_root == tmp_path


def test_load_dotenv(monkeypatch, tmp_path):
    # prepare .env
    env_path = tmp_path / ".env"
    env_path.write_text("EMBED_BASE_URL=https://example.com\n", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("EMBED_BASE_URL", raising=False)

    # call loader explicitly
    config_module._load_dotenv()
    assert os.environ.get("EMBED_BASE_URL") == "https://example.com"


def test_config_default_context_template_weights_dynamic_is_available(tmp_path):
    cfg = DataModulesConfig.from_project_root(tmp_path)
    dynamic = cfg.context_template_weights_dynamic

    assert isinstance(dynamic, dict)
    assert "early" in dynamic
    assert "mid" in dynamic
    assert "late" in dynamic
    assert "plot" in dynamic["early"]


def test_config_dynamic_template_weights_are_independent_instances(tmp_path):
    cfg1 = DataModulesConfig.from_project_root(tmp_path)
    cfg2 = DataModulesConfig.from_project_root(tmp_path)

    cfg1.context_template_weights_dynamic["early"]["plot"]["core"] = 0.77

    assert cfg2.context_template_weights_dynamic["early"]["plot"]["core"] != 0.77


def test_llm_settings_follow_project_workspace_global_precedence(monkeypatch, tmp_path):
    workspace_root = tmp_path / "workspace"
    book_root = workspace_root / "books" / "book-a"
    global_root = tmp_path / "codex-home"

    (workspace_root / ".codex").mkdir(parents=True, exist_ok=True)
    book_root.mkdir(parents=True, exist_ok=True)
    (global_root / "webnovel-writer").mkdir(parents=True, exist_ok=True)

    (book_root / ".env").write_text("LLM_CHAT_MODEL=project-model\n", encoding="utf-8")
    (workspace_root / ".env").write_text(
        "LLM_BASE_URL=https://workspace.example/v1\nLLM_CHAT_MODEL=workspace-model\n",
        encoding="utf-8",
    )
    (global_root / "webnovel-writer" / ".env").write_text(
        "LLM_BASE_URL=https://global.example/v1\nLLM_CHAT_MODEL=global-model\nLLM_API_KEY=global-key\nAPI_GATEWAY_TOKEN=gw-token\n",
        encoding="utf-8",
    )

    for key in (
        "LLM_PROVIDER",
        "LLM_BASE_URL",
        "LLM_CHAT_MODEL",
        "LLM_REASONING_MODEL",
        "LLM_API_KEY",
        "LLM_GATEWAY_TOKEN",
        "OPENAI_BASE_URL",
        "OPENAI_MODEL",
        "OPENAI_API_KEY",
        "DEEPSEEK_BASE_URL",
        "DEEPSEEK_MODEL",
        "DEEPSEEK_API_KEY",
        "API_GATEWAY_TOKEN",
        "GATEWAY_TOKEN",
        "CODEX_HOME",
        "WEBNOVEL_CODEX_HOME",
        "CLAUDE_HOME",
        "WEBNOVEL_CLAUDE_HOME",
    ):
        monkeypatch.delenv(key, raising=False)

    monkeypatch.setenv("WEBNOVEL_CODEX_HOME", str(global_root))
    monkeypatch.setenv("LLM_BASE_URL", "https://env.example/v1")

    cfg = DataModulesConfig.from_project_root(book_root)

    assert cfg.llm_provider == "openai_compatible"
    assert cfg.llm_base_url == "https://env.example/v1"
    assert cfg.llm_chat_model == "project-model"
    assert cfg.llm_api_key == "global-key"
    assert cfg.llm_gateway_token == "gw-token"
    assert cfg.deepseek_official_base_url == "https://api.deepseek.com"
    assert cfg.deepseek_official_api_key == "global-key"


def test_llm_settings_fallback_to_legacy_deepseek_env(monkeypatch, tmp_path):
    for key in (
        "LLM_BASE_URL",
        "LLM_CHAT_MODEL",
        "LLM_REASONING_MODEL",
        "LLM_API_KEY",
        "DEEPSEEK_BASE_URL",
        "DEEPSEEK_MODEL",
        "DEEPSEEK_REASONING_MODEL",
        "DEEPSEEK_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)

    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://legacy.example")
    monkeypatch.setenv("DEEPSEEK_MODEL", "legacy-chat")
    monkeypatch.setenv("DEEPSEEK_REASONING_MODEL", "legacy-reasoner")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "legacy-key")

    cfg = DataModulesConfig.from_project_root(tmp_path)

    assert cfg.llm_base_url == "https://legacy.example"
    assert cfg.llm_chat_model == "legacy-chat"
    assert cfg.llm_reasoning_model == "legacy-reasoner"
    assert cfg.llm_api_key == "legacy-key"
    assert cfg.deepseek_official_base_url == "https://api.deepseek.com"
    assert cfg.deepseek_official_api_key == "legacy-key"


def test_llm_settings_default_to_official_deepseek_models_when_only_key_present(monkeypatch, tmp_path):
    for key in (
        "LLM_BASE_URL",
        "LLM_CHAT_MODEL",
        "LLM_REASONING_MODEL",
        "LLM_API_KEY",
        "DEEPSEEK_BASE_URL",
        "DEEPSEEK_CHAT_MODEL",
        "DEEPSEEK_MODEL",
        "DEEPSEEK_REASONING_MODEL",
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_OFFICIAL_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)

    # 屏蔽用户级全局 .env(~/.codex/webnovel-writer/.env / ~/.claude/...)
    # 否则跑测试的开发机如果配了 LLM_CHAT_MODEL=xxx 全局兜底,本测试会拿到非默认值
    from data_modules import config as config_mod

    monkeypatch.setattr(config_mod, "_iter_user_tool_roots", lambda: iter(()))

    monkeypatch.setenv("DEEPSEEK_API_KEY", "official-key")

    cfg = DataModulesConfig.from_project_root(tmp_path)

    assert cfg.llm_chat_model == "deepseek-chat"
    assert cfg.llm_reasoning_model == "deepseek-reasoner"
    assert cfg.deepseek_official_api_key == "official-key"
