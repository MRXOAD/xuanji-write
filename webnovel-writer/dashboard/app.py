"""
Webnovel Dashboard - FastAPI 主应用

默认提供只读接口，并补一组本地动作接口。
所有文件读取经过 path_guard 防穿越校验；写作动作统一转发到本地 CLI。
"""

import asyncio
import json
import shlex
import sqlite3
import subprocess
import sys
from contextlib import asynccontextmanager, closing
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from .path_guard import safe_resolve
from .watcher import FileWatcher

# ---------------------------------------------------------------------------
# 全局状态
# ---------------------------------------------------------------------------
_project_root: Path | None = None
_workspace_root: Path | None = None
_watcher = FileWatcher()

STATIC_DIR = Path(__file__).parent / "frontend" / "dist"


def _get_project_root() -> Path:
    if _project_root is None:
        raise HTTPException(status_code=500, detail="项目根目录未配置")
    return _project_root


def _get_workspace_root() -> Optional[Path]:
    return _workspace_root


def _webnovel_dir() -> Path:
    return _get_project_root() / ".webnovel"


def _infer_workspace_root(project_root: Path) -> Optional[Path]:
    for candidate in (project_root, *project_root.parents):
        if (candidate / ".codex").is_dir() or (candidate / ".claude").is_dir():
            return candidate.resolve()
    return None


def _webnovel_cli() -> Path:
    return Path(__file__).resolve().parents[1] / "scripts" / "webnovel.py"


def _resolve_action_project_root(payload: dict | None = None) -> Path:
    raw = str((payload or {}).get("project_root") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return _get_project_root()


def _parse_action_artifacts(stdout: str) -> dict[str, str]:
    artifacts: dict[str, str] = {}
    for raw_line in str(stdout or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()
            if key and value:
                artifacts[key] = value
            continue
        if line.startswith("/"):
            artifacts.setdefault("output_path", line)
    return artifacts


def _run_webnovel_cli(
    *,
    args: list[str],
    project_root: Optional[Path] = None,
    timeout: int = 1800,
) -> dict:
    command = [sys.executable, str(_webnovel_cli())]
    if project_root is not None:
        command.extend(["--project-root", str(project_root)])
    command.extend(args)
    proc = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    stdout = proc.stdout or ""
    stderr = proc.stderr or ""
    return {
        "ok": proc.returncode == 0,
        "exit_code": int(proc.returncode),
        "command": " ".join(shlex.quote(part) for part in command),
        "stdout": stdout,
        "stderr": stderr,
        "artifacts": _parse_action_artifacts(stdout),
    }


def _safe_state_title(project_root: Path) -> str:
    state_path = project_root / ".webnovel" / "state.json"
    if not state_path.is_file():
        return project_root.name
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return project_root.name
    project_info = payload.get("project_info") if isinstance(payload, dict) else {}
    if isinstance(project_info, dict):
        title = str(project_info.get("title") or "").strip()
        if title:
            return title
    return project_root.name


def _list_workspace_books(workspace_root: Optional[Path]) -> list[dict]:
    if workspace_root is None:
        return []
    books_dir = workspace_root / "books"
    if not books_dir.is_dir():
        return []
    items: list[dict] = []
    for child in sorted(books_dir.iterdir()):
        if not child.is_dir():
            continue
        items.append(
            {
                "slug": child.name,
                "path": str(child.resolve()),
                "title": _safe_state_title(child),
                "initialized": (child / ".webnovel" / "state.json").is_file(),
            }
        )
    return items


def _workspace_info_payload() -> dict:
    project_root = _get_project_root()
    workspace_root = _get_workspace_root()
    llm_info = _run_webnovel_cli(
        project_root=project_root,
        args=["llm", "env-check", "--format", "json"],
        timeout=60,
    )
    llm_payload = None
    try:
        llm_payload = json.loads(llm_info["stdout"]) if llm_info["stdout"].strip() else None
    except json.JSONDecodeError:
        llm_payload = None
    return {
        "project_root": str(project_root),
        "workspace_root": str(workspace_root) if workspace_root is not None else "",
        "current_title": _safe_state_title(project_root),
        "books": _list_workspace_books(workspace_root),
        "llm": llm_payload,
    }


# ---------------------------------------------------------------------------
# 应用工厂
# ---------------------------------------------------------------------------


def create_app(project_root: str | Path | None = None, workspace_root: str | Path | None = None) -> FastAPI:
    global _project_root, _workspace_root

    if project_root:
        _project_root = Path(project_root).resolve()
    if workspace_root:
        _workspace_root = Path(workspace_root).resolve()
    elif _project_root is not None:
        _workspace_root = _infer_workspace_root(_project_root)

    @asynccontextmanager
    async def _lifespan(_: FastAPI):
        webnovel = _webnovel_dir()
        if webnovel.is_dir():
            _watcher.start(webnovel, asyncio.get_running_loop())
        try:
            yield
        finally:
            _watcher.stop()

    app = FastAPI(title="Webnovel Dashboard", version="0.1.0", lifespan=_lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    # ===========================================================
    # API：项目元信息
    # ===========================================================

    @app.get("/api/project/info")
    def project_info():
        """返回 state.json 完整内容（只读）。"""
        state_path = _webnovel_dir() / "state.json"
        if not state_path.is_file():
            raise HTTPException(404, "state.json 不存在")
        return json.loads(state_path.read_text(encoding="utf-8"))

    @app.get("/api/workspace/info")
    def workspace_info():
        return _workspace_info_payload()

    @app.post("/api/actions/use-book")
    async def action_use_book(payload: dict | None = Body(default=None)):
        global _project_root, _workspace_root
        payload = payload or {}

        project_root = _resolve_action_project_root(payload)
        workspace_root = _get_workspace_root() or _infer_workspace_root(project_root)
        result = _run_webnovel_cli(
            args=[
                "use",
                str(project_root),
                *(["--workspace-root", str(workspace_root)] if workspace_root is not None else []),
            ],
            timeout=60,
        )
        if not result["ok"]:
            raise HTTPException(status_code=400, detail=result)

        _project_root = project_root
        _workspace_root = workspace_root or _infer_workspace_root(project_root)
        _watcher.stop()
        if _webnovel_dir().is_dir():
            _watcher.start(_webnovel_dir(), asyncio.get_running_loop())

        return {
            **result,
            "workspace": _workspace_info_payload(),
        }

    @app.post("/api/actions/env-check")
    def action_env_check(payload: dict | None = Body(default=None)):
        payload = payload or {}
        project_root = _resolve_action_project_root(payload)
        result = _run_webnovel_cli(
            project_root=project_root,
            args=["llm", "env-check", "--format", "json"],
            timeout=60,
        )
        try:
            result["payload"] = json.loads(result["stdout"]) if result["stdout"].strip() else None
        except json.JSONDecodeError:
            result["payload"] = None
        return result

    @app.post("/api/actions/prompt")
    def action_prompt(payload: dict | None = Body(default=None)):
        payload = payload or {}
        project_root = _resolve_action_project_root(payload)
        chapter = int(payload.get("chapter") or 1)
        task = str(payload.get("task") or "draft").strip() or "draft"
        args = ["llm", "prompt", "--chapter", str(chapter), "--task", task]
        chapter_file = str(payload.get("chapter_file") or "").strip()
        if chapter_file:
            args.extend(["--chapter-file", chapter_file])
        target_words = payload.get("target_words")
        if target_words is not None:
            args.extend(["--target-words", str(int(target_words))])
        return _run_webnovel_cli(project_root=project_root, args=args, timeout=120)

    @app.post("/api/actions/draft")
    def action_draft(payload: dict | None = Body(default=None)):
        payload = payload or {}
        project_root = _resolve_action_project_root(payload)
        chapter = int(payload.get("chapter") or 1)
        args = ["llm", "draft", "--chapter", str(chapter)]
        if payload.get("target_words") is not None:
            args.extend(["--target-words", str(int(payload["target_words"]))])
        if payload.get("output"):
            args.extend(["--output", str(payload["output"])])
        if payload.get("model"):
            args.extend(["--model", str(payload["model"])])
        if payload.get("temperature") is not None:
            args.extend(["--temperature", str(payload["temperature"])])
        if payload.get("max_tokens") is not None:
            args.extend(["--max-tokens", str(int(payload["max_tokens"]))])
        if payload.get("use_volume_layout"):
            args.append("--use-volume-layout")
        args.append("--overwrite")
        return _run_webnovel_cli(project_root=project_root, args=args)

    @app.post("/api/actions/review")
    def action_review(payload: dict | None = Body(default=None)):
        payload = payload or {}
        project_root = _resolve_action_project_root(payload)
        chapter = int(payload.get("chapter") or 1)
        args = ["llm", "review", "--chapter", str(chapter), "--overwrite"]
        if payload.get("chapter_file"):
            args.extend(["--chapter-file", str(payload["chapter_file"])])
        if payload.get("output"):
            args.extend(["--output", str(payload["output"])])
        if payload.get("model"):
            args.extend(["--model", str(payload["model"])])
        if payload.get("temperature") is not None:
            args.extend(["--temperature", str(payload["temperature"])])
        if payload.get("max_tokens") is not None:
            args.extend(["--max-tokens", str(int(payload["max_tokens"]))])
        return _run_webnovel_cli(project_root=project_root, args=args)

    # ===========================================================
    # API：实体数据库（index.db 只读查询）
    # ===========================================================

    def _get_db() -> sqlite3.Connection:
        db_path = _webnovel_dir() / "index.db"
        if not db_path.is_file():
            raise HTTPException(404, "index.db 不存在")
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _fetchall_safe(conn: sqlite3.Connection, query: str, params: tuple = ()) -> list[dict]:
        """执行只读查询；若目标表不存在（旧库），返回空列表。"""
        try:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).lower():
                return []
            raise HTTPException(status_code=500, detail=f"数据库查询失败: {exc}") from exc

    @app.get("/api/entities")
    def list_entities(
        entity_type: Optional[str] = Query(None, alias="type"),
        include_archived: bool = False,
    ):
        """列出所有实体（可按类型过滤）。"""
        with closing(_get_db()) as conn:
            q = "SELECT * FROM entities"
            params: list = []
            clauses: list[str] = []
            if entity_type:
                clauses.append("type = ?")
                params.append(entity_type)
            if not include_archived:
                clauses.append("is_archived = 0")
            if clauses:
                q += " WHERE " + " AND ".join(clauses)
            q += " ORDER BY last_appearance DESC"
            rows = conn.execute(q, params).fetchall()
            return [dict(r) for r in rows]

    @app.get("/api/entities/{entity_id}")
    def get_entity(entity_id: str):
        with closing(_get_db()) as conn:
            row = conn.execute("SELECT * FROM entities WHERE id = ?", (entity_id,)).fetchone()
            if not row:
                raise HTTPException(404, "实体不存在")
            return dict(row)

    @app.get("/api/relationships")
    def list_relationships(entity: Optional[str] = None, limit: int = 200):
        with closing(_get_db()) as conn:
            if entity:
                rows = conn.execute(
                    "SELECT * FROM relationships WHERE from_entity = ? OR to_entity = ? ORDER BY chapter DESC LIMIT ?",
                    (entity, entity, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM relationships ORDER BY chapter DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]

    @app.get("/api/relationship-events")
    def list_relationship_events(
        entity: Optional[str] = None,
        from_chapter: Optional[int] = None,
        to_chapter: Optional[int] = None,
        limit: int = 200,
    ):
        with closing(_get_db()) as conn:
            q = "SELECT * FROM relationship_events"
            params: list = []
            clauses: list[str] = []
            if entity:
                clauses.append("(from_entity = ? OR to_entity = ?)")
                params.extend([entity, entity])
            if from_chapter is not None:
                clauses.append("chapter >= ?")
                params.append(from_chapter)
            if to_chapter is not None:
                clauses.append("chapter <= ?")
                params.append(to_chapter)
            if clauses:
                q += " WHERE " + " AND ".join(clauses)
            q += " ORDER BY chapter DESC, id DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(q, params).fetchall()
            return [dict(r) for r in rows]

    @app.get("/api/chapters")
    def list_chapters():
        with closing(_get_db()) as conn:
            rows = conn.execute("SELECT * FROM chapters ORDER BY chapter ASC").fetchall()
            return [dict(r) for r in rows]

    @app.get("/api/scenes")
    def list_scenes(chapter: Optional[int] = None, limit: int = 500):
        with closing(_get_db()) as conn:
            if chapter is not None:
                rows = conn.execute(
                    "SELECT * FROM scenes WHERE chapter = ? ORDER BY scene_index ASC", (chapter,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM scenes ORDER BY chapter ASC, scene_index ASC LIMIT ?", (limit,)
                ).fetchall()
            return [dict(r) for r in rows]

    @app.get("/api/reading-power")
    def list_reading_power(limit: int = 50):
        with closing(_get_db()) as conn:
            rows = conn.execute(
                "SELECT * FROM chapter_reading_power ORDER BY chapter DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]

    @app.get("/api/review-metrics")
    def list_review_metrics(limit: int = 20):
        with closing(_get_db()) as conn:
            rows = conn.execute("SELECT * FROM review_metrics ORDER BY end_chapter DESC LIMIT ?", (limit,)).fetchall()
            return [dict(r) for r in rows]

    @app.get("/api/state-changes")
    def list_state_changes(entity: Optional[str] = None, limit: int = 100):
        with closing(_get_db()) as conn:
            if entity:
                rows = conn.execute(
                    "SELECT * FROM state_changes WHERE entity_id = ? ORDER BY chapter DESC LIMIT ?",
                    (entity, limit),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM state_changes ORDER BY chapter DESC LIMIT ?", (limit,)).fetchall()
            return [dict(r) for r in rows]

    @app.get("/api/aliases")
    def list_aliases(entity: Optional[str] = None):
        with closing(_get_db()) as conn:
            if entity:
                rows = conn.execute("SELECT * FROM aliases WHERE entity_id = ?", (entity,)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM aliases").fetchall()
            return [dict(r) for r in rows]

    # ===========================================================
    # API：扩展表（v5.3+ / v5.4+）
    # ===========================================================

    @app.get("/api/overrides")
    def list_overrides(status: Optional[str] = None, limit: int = 100):
        with closing(_get_db()) as conn:
            if status:
                return _fetchall_safe(
                    conn,
                    "SELECT * FROM override_contracts WHERE status = ? ORDER BY chapter DESC LIMIT ?",
                    (status, limit),
                )
            return _fetchall_safe(
                conn,
                "SELECT * FROM override_contracts ORDER BY chapter DESC LIMIT ?",
                (limit,),
            )

    @app.get("/api/debts")
    def list_debts(status: Optional[str] = None, limit: int = 100):
        with closing(_get_db()) as conn:
            if status:
                return _fetchall_safe(
                    conn,
                    "SELECT * FROM chase_debt WHERE status = ? ORDER BY updated_at DESC LIMIT ?",
                    (status, limit),
                )
            return _fetchall_safe(
                conn,
                "SELECT * FROM chase_debt ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            )

    @app.get("/api/debt-events")
    def list_debt_events(debt_id: Optional[int] = None, limit: int = 200):
        with closing(_get_db()) as conn:
            if debt_id is not None:
                return _fetchall_safe(
                    conn,
                    "SELECT * FROM debt_events WHERE debt_id = ? ORDER BY chapter DESC, id DESC LIMIT ?",
                    (debt_id, limit),
                )
            return _fetchall_safe(
                conn,
                "SELECT * FROM debt_events ORDER BY chapter DESC, id DESC LIMIT ?",
                (limit,),
            )

    @app.get("/api/invalid-facts")
    def list_invalid_facts(status: Optional[str] = None, limit: int = 100):
        with closing(_get_db()) as conn:
            if status:
                return _fetchall_safe(
                    conn,
                    "SELECT * FROM invalid_facts WHERE status = ? ORDER BY marked_at DESC LIMIT ?",
                    (status, limit),
                )
            return _fetchall_safe(
                conn,
                "SELECT * FROM invalid_facts ORDER BY marked_at DESC LIMIT ?",
                (limit,),
            )

    @app.get("/api/rag-queries")
    def list_rag_queries(query_type: Optional[str] = None, limit: int = 100):
        with closing(_get_db()) as conn:
            if query_type:
                return _fetchall_safe(
                    conn,
                    "SELECT * FROM rag_query_log WHERE query_type = ? ORDER BY created_at DESC LIMIT ?",
                    (query_type, limit),
                )
            return _fetchall_safe(
                conn,
                "SELECT * FROM rag_query_log ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )

    @app.get("/api/tool-stats")
    def list_tool_stats(tool_name: Optional[str] = None, limit: int = 200):
        with closing(_get_db()) as conn:
            if tool_name:
                return _fetchall_safe(
                    conn,
                    "SELECT * FROM tool_call_stats WHERE tool_name = ? ORDER BY created_at DESC LIMIT ?",
                    (tool_name, limit),
                )
            return _fetchall_safe(
                conn,
                "SELECT * FROM tool_call_stats ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )

    @app.get("/api/checklist-scores")
    def list_checklist_scores(limit: int = 100):
        with closing(_get_db()) as conn:
            return _fetchall_safe(
                conn,
                "SELECT * FROM writing_checklist_scores ORDER BY chapter DESC LIMIT ?",
                (limit,),
            )

    # ===========================================================
    # API：章末硬约束验证（draft_audit）
    # ===========================================================

    @app.get("/api/audit/{chapter}")
    def audit_chapter(chapter: int):
        """对指定章节跑 draft_audit,返回 JSON。"""
        root = _get_project_root()
        try:
            scripts_dir = Path(__file__).resolve().parent.parent / "scripts"
            if str(scripts_dir) not in sys.path:
                sys.path.insert(0, str(scripts_dir))
            from draft_audit import audit as _audit_call
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"draft_audit 加载失败: {exc}")
        result = _audit_call(root, chapter)
        return result

    @app.get("/api/audit")
    def audit_all(from_chapter: int = 1, to_chapter: int = 0):
        """扫所有(或指定范围)章节,返回每章 audit 结果列表。

        默认扫到 state.json 的 current_chapter。
        """
        root = _get_project_root()
        try:
            scripts_dir = Path(__file__).resolve().parent.parent / "scripts"
            if str(scripts_dir) not in sys.path:
                sys.path.insert(0, str(scripts_dir))
            from draft_audit import audit as _audit_call
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"draft_audit 加载失败: {exc}")

        end_chapter = to_chapter
        if end_chapter <= 0:
            state_path = root / ".webnovel" / "state.json"
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
                end_chapter = int(state.get("progress", {}).get("current_chapter") or 0)
            except Exception:
                end_chapter = 0
        if end_chapter <= 0:
            return {"results": [], "summary": {"total": 0}}

        results: list[dict] = []
        pass_n = warn_n = fail_n = 0
        for ch in range(max(1, from_chapter), end_chapter + 1):
            r = _audit_call(root, ch)
            if not r.get("found"):
                continue
            r_min = {
                "chapter": r["chapter"],
                "verdict": r["verdict"],
                "errors": r["errors"],
                "warnings": r["warnings"],
                "word_count": r["word_count"],
            }
            results.append(r_min)
            if r["verdict"] == "PASS":
                pass_n += 1
            elif r["verdict"] == "PASS_WITH_WARN":
                warn_n += 1
            else:
                fail_n += 1
        return {
            "results": results,
            "summary": {"total": len(results), "pass": pass_n, "warn": warn_n, "fail": fail_n},
        }

    # ===========================================================
    # API：文档浏览（正文/大纲/设定集 —— 只读）
    # ===========================================================

    @app.get("/api/files/tree")
    def file_tree():
        """列出 正文/、大纲/、设定集/ 三个目录的树结构。"""
        root = _get_project_root()
        result = {}
        for folder_name in ("正文", "大纲", "设定集"):
            folder = root / folder_name
            if not folder.is_dir():
                result[folder_name] = []
                continue
            result[folder_name] = _walk_tree(folder, root)
        return result

    @app.get("/api/files/read")
    def file_read(path: str):
        """只读读取一个文件内容（限 正文/大纲/设定集 目录）。"""
        root = _get_project_root()
        resolved = safe_resolve(root, path)

        # 二次限制：只允许三大目录
        allowed_parents = [root / n for n in ("正文", "大纲", "设定集")]
        if not any(_is_child(resolved, p) for p in allowed_parents):
            raise HTTPException(403, "仅允许读取 正文/大纲/设定集 目录下的文件")

        if not resolved.is_file():
            raise HTTPException(404, "文件不存在")

        # 文本文件直接读；其他情况返回占位信息
        try:
            content = resolved.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = "[二进制文件，无法预览]"

        return {"path": path, "content": content}

    # ===========================================================
    # SSE：实时变更推送
    # ===========================================================

    @app.get("/api/events")
    async def sse():
        """Server-Sent Events 端点，推送 .webnovel/ 下的文件变更。"""
        q = _watcher.subscribe()

        async def _gen():
            try:
                while True:
                    msg = await q.get()
                    yield f"data: {msg}\n\n"
            except asyncio.CancelledError:
                pass
            finally:
                _watcher.unsubscribe(q)

        return StreamingResponse(_gen(), media_type="text/event-stream")

    # ===========================================================
    # 前端静态文件托管
    # ===========================================================

    if STATIC_DIR.is_dir():
        app.mount("/assets", StaticFiles(directory=str(STATIC_DIR / "assets")), name="assets")

        @app.get("/{full_path:path}")
        def serve_spa(full_path: str):
            """SPA fallback：任何非 /api 路径都返回 index.html。"""
            index = STATIC_DIR / "index.html"
            if index.is_file():
                return FileResponse(str(index))
            raise HTTPException(404, "前端尚未构建")
    else:

        @app.get("/")
        def no_frontend():
            return HTMLResponse(
                "<h2>Webnovel Dashboard API is running</h2>"
                "<p>前端尚未构建。请先在 <code>dashboard/frontend</code> 目录执行 <code>npm run build</code>。</p>"
                '<p>API 文档：<a href="/docs">/docs</a></p>'
            )

    return app


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def _walk_tree(folder: Path, root: Path) -> list[dict]:
    items = []
    for child in sorted(folder.iterdir()):
        rel = str(child.relative_to(root)).replace("\\", "/")
        if child.is_dir():
            items.append({"name": child.name, "type": "dir", "path": rel, "children": _walk_tree(child, root)})
        else:
            items.append({"name": child.name, "type": "file", "path": rel, "size": child.stat().st_size})
    return items


def _is_child(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False
