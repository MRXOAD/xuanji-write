#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import sys
from pathlib import Path


def _ensure_scripts_on_path() -> None:
    scripts_dir = Path(__file__).resolve().parents[2]
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))


def test_resolve_project_root_prefers_cwd_project(tmp_path):
    _ensure_scripts_on_path()

    from project_locator import resolve_project_root

    project_root = tmp_path / "workspace"
    (project_root / ".webnovel").mkdir(parents=True, exist_ok=True)
    (project_root / ".webnovel" / "state.json").write_text("{}", encoding="utf-8")

    resolved = resolve_project_root(cwd=project_root)
    assert resolved == project_root.resolve()


def test_resolve_project_root_stops_at_git_root(tmp_path):
    _ensure_scripts_on_path()

    from project_locator import resolve_project_root

    repo_root = tmp_path / "repo"
    (repo_root / ".git").mkdir(parents=True, exist_ok=True)

    nested = repo_root / "sub" / "dir"
    nested.mkdir(parents=True, exist_ok=True)

    outside_project = tmp_path / "outside_project"
    (outside_project / ".webnovel").mkdir(parents=True, exist_ok=True)
    (outside_project / ".webnovel" / "state.json").write_text("{}", encoding="utf-8")

    try:
        resolve_project_root(cwd=nested)
        assert False, "Expected FileNotFoundError when only parent outside git root has project"
    except FileNotFoundError:
        pass


def test_resolve_project_root_finds_default_subdir_within_git_root(tmp_path):
    _ensure_scripts_on_path()

    from project_locator import resolve_project_root

    repo_root = tmp_path / "repo"
    (repo_root / ".git").mkdir(parents=True, exist_ok=True)

    default_project = repo_root / "webnovel-project"
    (default_project / ".webnovel").mkdir(parents=True, exist_ok=True)
    (default_project / ".webnovel" / "state.json").write_text("{}", encoding="utf-8")

    nested = repo_root / "sub" / "dir"
    nested.mkdir(parents=True, exist_ok=True)

    resolved = resolve_project_root(cwd=nested)
    assert resolved == default_project.resolve()


def test_resolve_project_root_uses_workspace_pointer(tmp_path, monkeypatch):
    _ensure_scripts_on_path()

    from project_locator import resolve_project_root, write_current_project_pointer

    monkeypatch.setenv("WEBNOVEL_CODEX_HOME", str(tmp_path / "home" / ".codex"))
    monkeypatch.setenv("WEBNOVEL_CLAUDE_HOME", str(tmp_path / "home" / ".claude"))

    workspace = tmp_path / "workspace"
    (workspace / ".claude").mkdir(parents=True, exist_ok=True)

    project_root = workspace / "凡人资本论"
    (project_root / ".webnovel").mkdir(parents=True, exist_ok=True)
    (project_root / ".webnovel" / "state.json").write_text("{}", encoding="utf-8")

    pointer_file = write_current_project_pointer(project_root, workspace_root=workspace)
    assert pointer_file is not None
    assert pointer_file.is_file()

    resolved = resolve_project_root(cwd=workspace)
    assert resolved == project_root.resolve()


def test_resolve_project_root_uses_codex_workspace_pointer(tmp_path, monkeypatch):
    _ensure_scripts_on_path()

    from project_locator import resolve_project_root, write_current_project_pointer

    monkeypatch.setenv("WEBNOVEL_CODEX_HOME", str(tmp_path / "home" / ".codex"))
    monkeypatch.setenv("WEBNOVEL_CLAUDE_HOME", str(tmp_path / "home" / ".claude"))

    workspace = tmp_path / "workspace"
    (workspace / ".codex").mkdir(parents=True, exist_ok=True)

    project_root = workspace / "星海长夜"
    (project_root / ".webnovel").mkdir(parents=True, exist_ok=True)
    (project_root / ".webnovel" / "state.json").write_text("{}", encoding="utf-8")

    pointer_file = write_current_project_pointer(project_root, workspace_root=workspace)
    assert pointer_file is not None
    assert pointer_file == workspace / ".codex" / ".webnovel-current-project"
    assert pointer_file.is_file()

    resolved = resolve_project_root(cwd=workspace)
    assert resolved == project_root.resolve()


def test_resolve_project_root_ignores_stale_pointer_and_fallbacks(tmp_path):
    _ensure_scripts_on_path()

    from project_locator import resolve_project_root

    workspace = tmp_path / "workspace"
    (workspace / ".claude").mkdir(parents=True, exist_ok=True)
    # stale pointer
    (workspace / ".claude" / ".webnovel-current-project").write_text(
        str(workspace / "missing-project"), encoding="utf-8"
    )

    default_project = workspace / "webnovel-project"
    (default_project / ".webnovel").mkdir(parents=True, exist_ok=True)
    (default_project / ".webnovel" / "state.json").write_text("{}", encoding="utf-8")

    resolved = resolve_project_root(cwd=workspace)
    assert resolved == default_project.resolve()


def test_resolve_project_root_rejects_explicit_book_root_without_state_file(tmp_path):
    _ensure_scripts_on_path()

    from project_locator import resolve_project_root

    project_root = tmp_path / "book"
    (project_root / ".webnovel").mkdir(parents=True, exist_ok=True)

    try:
        resolve_project_root(str(project_root))
        assert False, "Expected FileNotFoundError for explicit path without state.json"
    except FileNotFoundError:
        pass


def test_resolve_project_root_rejects_explicit_workspace_without_state_file(tmp_path):
    _ensure_scripts_on_path()

    from project_locator import resolve_project_root

    workspace = tmp_path / "workspace"
    (workspace / ".webnovel").mkdir(parents=True, exist_ok=True)
    (workspace / ".codex").mkdir(parents=True, exist_ok=True)

    try:
        resolve_project_root(str(workspace))
        assert False, "Expected FileNotFoundError for workspace without state.json"
    except FileNotFoundError:
        pass


def test_resolve_explicit_cli_project_root_allows_explicit_book_root_without_state_file(tmp_path):
    _ensure_scripts_on_path()

    from project_locator import resolve_explicit_cli_project_root

    project_root = tmp_path / "book"
    (project_root / ".webnovel").mkdir(parents=True, exist_ok=True)

    resolved = resolve_explicit_cli_project_root(str(project_root))
    assert resolved == project_root.resolve()


def test_resolve_explicit_cli_project_root_rejects_missing_metadata_dir(tmp_path):
    _ensure_scripts_on_path()

    from project_locator import resolve_explicit_cli_project_root

    project_root = tmp_path / "book"

    try:
        resolve_explicit_cli_project_root(str(project_root))
        assert False, "Expected FileNotFoundError for path without .webnovel metadata dir"
    except FileNotFoundError:
        pass


def test_resolve_project_root_rejects_invalid_env_workspace_root(tmp_path, monkeypatch):
    _ensure_scripts_on_path()

    from project_locator import resolve_project_root

    workspace = tmp_path / "workspace"
    (workspace / ".webnovel").mkdir(parents=True, exist_ok=True)
    (workspace / ".claude").mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("WEBNOVEL_PROJECT_ROOT", str(workspace))
    try:
        resolve_project_root(cwd=tmp_path)
        assert False, "Expected FileNotFoundError for env root without state.json"
    except FileNotFoundError:
        pass


def test_resolve_project_root_registry_prefix_match_works_on_posix(tmp_path, monkeypatch):
    _ensure_scripts_on_path()

    from project_locator import resolve_project_root

    codex_home = tmp_path / "home" / ".codex"
    claude_home = tmp_path / "home" / ".claude"
    monkeypatch.setenv("WEBNOVEL_CODEX_HOME", str(codex_home))
    monkeypatch.setenv("WEBNOVEL_CLAUDE_HOME", str(claude_home))

    workspace = tmp_path / "workspace"
    nested = workspace / "sub" / "dir"
    nested.mkdir(parents=True, exist_ok=True)

    project_root = workspace / "青冥志"
    (project_root / ".webnovel").mkdir(parents=True, exist_ok=True)
    (project_root / ".webnovel" / "state.json").write_text("{}", encoding="utf-8")

    registry_path = codex_home / "webnovel-writer" / "workspaces.json"
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "workspaces": {
                    str(workspace.resolve()): {
                        "current_project_root": str(project_root.resolve()),
                    }
                },
                "last_used_project_root": "",
                "updated_at": "2026-04-22T00:00:00",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    resolved = resolve_project_root(cwd=nested)
    assert resolved == project_root.resolve()
