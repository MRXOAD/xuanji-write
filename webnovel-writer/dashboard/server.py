"""
Dashboard 启动脚本

用法：
    python -m dashboard.server --project-root /path/to/novel-project
    python -m dashboard.server                   # 自动从 .codex/.claude 指针读取
"""

import argparse
import os
import sys
import webbrowser
from pathlib import Path


def _pointer_candidates(cwd: Path) -> list[Path]:
    return [
        cwd / ".codex" / ".webnovel-current-project",
        cwd / ".claude" / ".webnovel-current-project",
    ]


def _resolve_pointer_target(base: Path) -> Path | None:
    for pointer in _pointer_candidates(base):
        if not pointer.is_file():
            continue
        target = pointer.read_text(encoding="utf-8").strip()
        if not target:
            continue
        p = Path(target)
        if p.is_dir() and (p / ".webnovel" / "state.json").is_file():
            return p.resolve()
    return None


def _resolve_project_root(cli_root: str | None) -> Path:
    """按优先级解析 PROJECT_ROOT：CLI > 环境变量 > .codex/.claude 指针 > CWD。"""
    if cli_root:
        candidate = Path(cli_root).resolve()
        if (candidate / ".webnovel" / "state.json").is_file():
            return candidate
        pointed = _resolve_pointer_target(candidate)
        if pointed is not None:
            return pointed
        print("ERROR: --project-root 既不是书项目根，也没有可用工作区指针", file=sys.stderr)
        sys.exit(1)

    env = os.environ.get("WEBNOVEL_PROJECT_ROOT")
    if env:
        candidate = Path(env).resolve()
        if (candidate / ".webnovel" / "state.json").is_file():
            return candidate
        pointed = _resolve_pointer_target(candidate)
        if pointed is not None:
            return pointed
        print("ERROR: WEBNOVEL_PROJECT_ROOT 既不是书项目根，也没有可用工作区指针", file=sys.stderr)
        sys.exit(1)

    # 尝试从工作区指针读取
    cwd = Path.cwd()
    pointed = _resolve_pointer_target(cwd)
    if pointed is not None:
        return pointed

    # 最终兜底：当前目录
    if (cwd / ".webnovel" / "state.json").is_file():
        return cwd.resolve()

    print("ERROR: 无法定位 PROJECT_ROOT（需要包含 .webnovel/state.json 的目录）", file=sys.stderr)
    sys.exit(1)


def _resolve_workspace_root(cli_root: str | None, project_root: Path) -> Path | None:
    if cli_root:
        return Path(cli_root).resolve()

    env = os.environ.get("WEBNOVEL_WORKSPACE_ROOT")
    if env:
        return Path(env).resolve()

    for candidate in (project_root, *project_root.parents):
        if (candidate / ".codex").is_dir() or (candidate / ".claude").is_dir():
            return candidate.resolve()
    return None


def main():
    parser = argparse.ArgumentParser(description="Webnovel Dashboard Server")
    parser.add_argument("--project-root", type=str, default=None, help="小说项目根目录")
    parser.add_argument("--workspace-root", type=str, default=None, help="工作区根目录")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址")
    parser.add_argument("--port", type=int, default=8765, help="监听端口")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    args = parser.parse_args()

    project_root = _resolve_project_root(args.project_root)
    workspace_root = _resolve_workspace_root(args.workspace_root, project_root)
    print(f"项目路径: {project_root}")
    if workspace_root is not None:
        print(f"工作区路径: {workspace_root}")

    # 延迟导入，以便先处理路径
    import uvicorn
    from .app import create_app

    app = create_app(project_root, workspace_root=workspace_root)

    url = f"http://{args.host}:{args.port}"
    print(f"Dashboard 启动: {url}")
    print(f"API 文档: {url}/docs")

    if not args.no_browser:
        webbrowser.open(url)

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
