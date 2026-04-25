#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient


def _ensure_dashboard_on_path() -> None:
    package_root = Path(__file__).resolve().parents[3]
    if str(package_root) not in sys.path:
        sys.path.insert(0, str(package_root))


def _build_book(path: Path, *, title: str) -> Path:
    (path / ".webnovel").mkdir(parents=True, exist_ok=True)
    (path / ".webnovel" / "state.json").write_text(
        json.dumps({"project_info": {"title": title}}, ensure_ascii=False),
        encoding="utf-8",
    )
    (path / ".webnovel" / "index.db").write_text("", encoding="utf-8")
    return path


def test_workspace_info_lists_books_and_llm_summary(monkeypatch, tmp_path):
    _ensure_dashboard_on_path()
    from dashboard import app as app_module

    workspace_root = tmp_path / "workspace"
    (workspace_root / ".codex").mkdir(parents=True, exist_ok=True)
    book_a = _build_book(workspace_root / "books" / "book-a", title="甲书")
    _build_book(workspace_root / "books" / "book-b", title="乙书")

    monkeypatch.setattr(
        app_module,
        "_run_webnovel_cli",
        lambda **kwargs: {
            "ok": True,
            "exit_code": 0,
            "command": "fake env-check",
            "stdout": json.dumps(
                {
                    "llm_provider": "openai_compatible",
                    "llm_base_url": "https://api.example/v1",
                    "llm_chat_model": "test-model",
                    "llm_reasoning_model": "reason-model",
                    "llm_timeout": 120,
                    "llm_api_key_present": True,
                    "missing_fields": [],
                },
                ensure_ascii=False,
            ),
            "stderr": "",
            "artifacts": {},
        },
    )
    monkeypatch.setattr(app_module._watcher, "start", lambda *args, **kwargs: None)
    monkeypatch.setattr(app_module._watcher, "stop", lambda *args, **kwargs: None)

    client = TestClient(app_module.create_app(book_a, workspace_root=workspace_root))
    payload = client.get("/api/workspace/info").json()

    assert payload["project_root"] == str(book_a.resolve())
    assert payload["workspace_root"] == str(workspace_root.resolve())
    assert [book["slug"] for book in payload["books"]] == ["book-a", "book-b"]
    assert payload["llm"]["llm_chat_model"] == "test-model"


def test_draft_action_forwards_expected_llm_args(monkeypatch, tmp_path):
    _ensure_dashboard_on_path()
    from dashboard import app as app_module

    workspace_root = tmp_path / "workspace"
    (workspace_root / ".codex").mkdir(parents=True, exist_ok=True)
    book_a = _build_book(workspace_root / "books" / "book-a", title="甲书")
    called = {}

    def _fake_run_webnovel_cli(**kwargs):
        called.update(kwargs)
        return {
            "ok": True,
            "exit_code": 0,
            "command": "fake draft",
            "stdout": str(book_a / "正文" / "第0005章.md"),
            "stderr": "",
            "artifacts": {"output_path": str(book_a / "正文" / "第0005章.md")},
        }

    monkeypatch.setattr(app_module, "_run_webnovel_cli", _fake_run_webnovel_cli)
    monkeypatch.setattr(app_module._watcher, "start", lambda *args, **kwargs: None)
    monkeypatch.setattr(app_module._watcher, "stop", lambda *args, **kwargs: None)

    client = TestClient(app_module.create_app(book_a, workspace_root=workspace_root))
    payload = client.post(
        "/api/actions/draft",
        json={"chapter": 5, "target_words": 2500, "project_root": str(book_a)},
    ).json()

    assert payload["ok"] is True
    assert called["project_root"] == book_a.resolve()
    assert called["args"] == [
        "llm",
        "draft",
        "--chapter",
        "5",
        "--target-words",
        "2500",
        "--overwrite",
    ]
