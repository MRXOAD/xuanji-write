#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


def _ensure_scripts_on_path() -> None:
    scripts_dir = Path(__file__).resolve().parents[2]
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))


def _load_webnovel_module():
    _ensure_scripts_on_path()
    import data_modules.webnovel as webnovel_module

    return webnovel_module


def test_init_does_not_resolve_existing_project_root(monkeypatch):
    module = _load_webnovel_module()

    called = {}

    def _fake_run_script(script_name, argv):
        called["script_name"] = script_name
        called["argv"] = list(argv)
        return 0

    def _fail_resolve(_explicit_project_root=None):
        raise AssertionError("init 子命令不应触发 project_root 解析")

    monkeypatch.setenv("WEBNOVEL_PROJECT_ROOT", r"D:\invalid\root")
    monkeypatch.setattr(module, "_run_script", _fake_run_script)
    monkeypatch.setattr(module, "_resolve_root", _fail_resolve)
    monkeypatch.setattr(sys, "argv", ["webnovel", "init", "proj-dir", "测试书", "修仙"])

    with pytest.raises(SystemExit) as exc:
        module.main()

    assert int(exc.value.code or 0) == 0
    assert called["script_name"] == "init_project.py"
    assert called["argv"] == ["proj-dir", "测试书", "修仙"]


def test_helpers_cover_project_root_parsing_and_missing_script(monkeypatch, tmp_path, capsys):
    module = _load_webnovel_module()

    monkeypatch.setattr(module, "resolve_project_root", lambda raw=None: Path("/tmp/book"))
    assert module._resolve_root(None) == Path("/tmp/book")
    assert module._strip_project_root_args(["--project-root", "/a", "index", "--project-root=/b", "stats"]) == [
        "index",
        "stats",
    ]

    missing_dir = tmp_path / "missing"
    monkeypatch.setattr(module, "_scripts_dir", lambda: missing_dir)
    with pytest.raises(FileNotFoundError):
        module._run_script("nope.py", [])

    monkeypatch.setattr(module, "_resolve_root", lambda explicit_project_root=None: Path("/tmp/book"))
    monkeypatch.setattr(sys, "argv", ["webnovel", "where"])

    with pytest.raises(SystemExit) as exc:
        module.main()

    assert int(exc.value.code or 0) == 0
    assert "/tmp/book" in capsys.readouterr().out


def test_extract_context_forwards_with_resolved_project_root(monkeypatch, tmp_path):
    module = _load_webnovel_module()

    book_root = (tmp_path / "book").resolve()
    called = {}

    def _fake_resolve(explicit_project_root=None):
        return book_root

    def _fake_run_script(script_name, argv):
        called["script_name"] = script_name
        called["argv"] = list(argv)
        return 0

    monkeypatch.setattr(module, "_resolve_root", _fake_resolve)
    monkeypatch.setattr(module, "_run_script", _fake_run_script)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "webnovel",
            "--project-root",
            str(tmp_path),
            "extract-context",
            "--chapter",
            "12",
            "--format",
            "json",
        ],
    )

    with pytest.raises(SystemExit) as exc:
        module.main()

    assert int(exc.value.code or 0) == 0
    assert called["script_name"] == "extract_chapter_context.py"
    assert called["argv"] == [
        "--project-root",
        str(book_root),
        "--chapter",
        "12",
        "--format",
        "json",
    ]


def test_preflight_succeeds_for_valid_project_root(monkeypatch, tmp_path, capsys):
    module = _load_webnovel_module()

    project_root = tmp_path / "book"
    (project_root / ".webnovel").mkdir(parents=True, exist_ok=True)
    (project_root / ".webnovel" / "state.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(sys, "argv", ["webnovel", "--project-root", str(project_root), "preflight"])

    with pytest.raises(SystemExit) as exc:
        module.main()

    captured = capsys.readouterr()
    assert int(exc.value.code or 0) == 0
    assert "OK project_root" in captured.out
    assert str(project_root.resolve()) in captured.out


def test_preflight_fails_when_required_scripts_are_missing(monkeypatch, tmp_path, capsys):
    module = _load_webnovel_module()

    project_root = tmp_path / "book"
    (project_root / ".webnovel").mkdir(parents=True, exist_ok=True)
    (project_root / ".webnovel" / "state.json").write_text("{}", encoding="utf-8")

    fake_scripts_dir = tmp_path / "fake-scripts"
    fake_scripts_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(module, "_scripts_dir", lambda: fake_scripts_dir)
    monkeypatch.setattr(sys, "argv", ["webnovel", "--project-root", str(project_root), "preflight", "--format", "json"])

    with pytest.raises(SystemExit) as exc:
        module.main()

    captured = capsys.readouterr()
    assert int(exc.value.code or 0) == 1
    assert '"ok": false' in captured.out
    assert '"name": "entry_script"' in captured.out


def test_use_command_updates_pointer_and_registry(monkeypatch, tmp_path, capsys):
    module = _load_webnovel_module()

    workspace_root = (tmp_path / "workspace").resolve()
    project_root = (workspace_root / "book").resolve()
    registry_path = (tmp_path / "home" / "workspaces.json").resolve()
    expected_pointer = workspace_root / ".codex" / ".webnovel-current-project"
    called = {}

    (project_root / ".webnovel").mkdir(parents=True, exist_ok=True)
    (project_root / ".webnovel" / "state.json").write_text("{}", encoding="utf-8")

    def _fake_write_pointer(project_root_arg, workspace_root=None):
        called["pointer"] = (project_root_arg, workspace_root)
        return expected_pointer

    def _fake_update_registry(workspace_root=None, project_root=None):
        called["registry"] = (workspace_root, project_root)
        return registry_path

    monkeypatch.setattr(module, "write_current_project_pointer", _fake_write_pointer)
    monkeypatch.setattr(module, "update_global_registry_current_project", _fake_update_registry)
    monkeypatch.setattr(
        sys,
        "argv",
        ["webnovel", "use", str(project_root), "--workspace-root", str(workspace_root)],
    )

    with pytest.raises(SystemExit) as exc:
        module.main()

    captured = capsys.readouterr()
    assert int(exc.value.code or 0) == 0
    assert called["pointer"][0] == project_root
    assert called["pointer"][1] == workspace_root
    assert called["registry"][0] == workspace_root
    assert called["registry"][1] == project_root
    assert f"workspace pointer: {expected_pointer}" in captured.out
    assert f"global registry: {registry_path}" in captured.out


def test_use_command_handles_skipped_pointer_and_registry(monkeypatch, tmp_path, capsys):
    module = _load_webnovel_module()

    workspace_root = (tmp_path / "workspace").resolve()
    project_root = (workspace_root / "book").resolve()

    (project_root / ".webnovel").mkdir(parents=True, exist_ok=True)
    (project_root / ".webnovel" / "state.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(module, "write_current_project_pointer", lambda *args, **kwargs: None)
    monkeypatch.setattr(module, "update_global_registry_current_project", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        sys,
        "argv",
        ["webnovel", "use", str(project_root), "--workspace-root", str(workspace_root)],
    )

    with pytest.raises(SystemExit) as exc:
        module.main()

    captured = capsys.readouterr()
    assert int(exc.value.code or 0) == 0
    assert "workspace pointer: (skipped)" in captured.out
    assert "global registry: (skipped)" in captured.out


def test_llm_command_forwards_with_resolved_project_root(monkeypatch, tmp_path):
    module = _load_webnovel_module()

    book_root = (tmp_path / "book").resolve()
    called = {}

    def _fake_resolve(explicit_project_root=None):
        return book_root

    def _fake_run_script(script_name, argv):
        called["script_name"] = script_name
        called["argv"] = list(argv)
        return 0

    monkeypatch.setattr(module, "_resolve_root", _fake_resolve)
    monkeypatch.setattr(module, "_run_script", _fake_run_script)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "webnovel",
            "--project-root",
            str(tmp_path),
            "llm",
            "env-check",
            "--format",
            "json",
        ],
    )

    with pytest.raises(SystemExit) as exc:
        module.main()

    assert int(exc.value.code or 0) == 0
    assert called["script_name"] == "llm_adapter.py"
    assert called["argv"] == [
        "--project-root",
        str(book_root),
        "env-check",
        "--format",
        "json",
    ]


def test_deepseek_alias_still_forwards_with_resolved_project_root(monkeypatch, tmp_path):
    module = _load_webnovel_module()

    book_root = (tmp_path / "book").resolve()
    called = {}

    monkeypatch.setattr(module, "_resolve_root", lambda explicit_project_root=None: book_root)
    monkeypatch.setattr(
        module,
        "_run_script",
        lambda script_name, argv: called.update({"script_name": script_name, "argv": list(argv)}) or 0,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "webnovel",
            "--project-root",
            str(tmp_path),
            "deepseek",
            "env-check",
        ],
    )

    with pytest.raises(SystemExit) as exc:
        module.main()

    assert int(exc.value.code or 0) == 0
    assert called["script_name"] == "deepseek_adapter.py"
    assert called["argv"] == [
        "--project-root",
        str(book_root),
        "env-check",
    ]


def test_run_data_module_handles_missing_main_and_system_exit(monkeypatch):
    module = _load_webnovel_module()

    monkeypatch.setattr(module.importlib, "import_module", lambda name: SimpleNamespace())
    with pytest.raises(RuntimeError):
        module._run_data_module("missing", [])

    fake_module = SimpleNamespace(main=lambda: (_ for _ in ()).throw(SystemExit(7)))
    monkeypatch.setattr(module.importlib, "import_module", lambda name: fake_module)
    assert module._run_data_module("with_exit", ["arg"]) == 7


def test_quality_trend_report_writes_to_book_root_when_input_is_workspace_root(tmp_path, monkeypatch):
    _ensure_scripts_on_path()
    import quality_trend_report as quality_trend_report_module

    workspace_root = (tmp_path / "workspace").resolve()
    book_root = (workspace_root / "凡人资本论").resolve()

    (workspace_root / ".claude").mkdir(parents=True, exist_ok=True)
    (workspace_root / ".claude" / ".webnovel-current-project").write_text(str(book_root), encoding="utf-8")

    (book_root / ".webnovel").mkdir(parents=True, exist_ok=True)
    (book_root / ".webnovel" / "state.json").write_text("{}", encoding="utf-8")

    output_path = workspace_root / "report.md"

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "quality_trend_report",
            "--project-root",
            str(workspace_root),
            "--limit",
            "1",
            "--output",
            str(output_path),
        ],
    )

    quality_trend_report_module.main()

    assert output_path.is_file()
    assert (book_root / ".webnovel" / "index.db").is_file()
    assert not (workspace_root / ".webnovel" / "index.db").exists()
