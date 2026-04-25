#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Codex 本地 LLM 写作适配器。

目标：
1. 复用现有的项目状态、章节上下文、RAG 数据层；
2. 用 OpenAI-compatible 接口生成正文或审查报告；
3. 不依赖 Claude Skill/Agent 也能直接跑。
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Optional
from urllib import error, request
from urllib.parse import urlparse

from chapter_paths import (
    default_chapter_draft_path,
    extract_chapter_num_from_filename,
    extract_chapter_title as resolve_outline_chapter_title,
    find_chapter_file,
)
from extract_chapter_context import build_chapter_context_payload, find_project_root
from runtime_compat import enable_windows_utf8_stdio
from security_utils import create_secure_directory

try:
    from data_modules.config import DataModulesConfig
except ImportError:  # pragma: no cover
    from scripts.data_modules.config import DataModulesConfig


def _chat_completions_url(base_url: str) -> str:
    root = (base_url or "").strip().rstrip("/")
    if not root:
        raise ValueError("LLM_BASE_URL 不能为空")
    if root.endswith("/chat/completions"):
        return root
    if root.endswith("/v1"):
        return f"{root}/chat/completions"
    path = urlparse(root).path.rstrip("/")
    if path.endswith(("/api/deepseek", "/api/siliconflow", "/api/volcengine")):
        return f"{root}/chat/completions"
    if path.endswith(("/api/openrouter", "/api/dashscope")):
        return f"{root}/v1/chat/completions"
    return f"{root}/v1/chat/completions"


def _is_gateway_base_url(base_url: str) -> bool:
    root = (base_url or "").strip().rstrip("/")
    if not root:
        return False
    path = urlparse(root).path.rstrip("/")
    return path.endswith(
        (
            "/api/openrouter",
            "/api/deepseek",
            "/api/siliconflow",
            "/api/volcengine",
            "/api/dashscope",
        )
    )


def _is_official_deepseek_base_url(base_url: str) -> bool:
    root = (base_url or "").strip()
    if not root:
        return False
    return urlparse(root).netloc.lower() == "api.deepseek.com"


def _is_deepseek_model(model: str) -> bool:
    return str(model or "").strip() in {"deepseek-chat", "deepseek-reasoner"}


def _build_llm_routes(config: DataModulesConfig, model: str) -> list[dict[str, str]]:
    routes: list[dict[str, str]] = []

    official_api_key = str(getattr(config, "deepseek_official_api_key", "") or "").strip()
    official_base_url = (
        str(getattr(config, "deepseek_official_base_url", "") or "").strip() or "https://api.deepseek.com"
    )
    if _is_deepseek_model(model) and official_api_key:
        routes.append(
            {
                "name": "deepseek_official",
                "base_url": official_base_url,
                "api_key": official_api_key,
                "gateway_token": "",
            }
        )

    configured_base_url = str(config.llm_base_url or "").strip()
    if configured_base_url:
        configured_api_key = str(config.llm_api_key or "").strip()
        configured_gateway_token = str(getattr(config, "llm_gateway_token", "") or "").strip()
        if _is_official_deepseek_base_url(configured_base_url) and not configured_api_key:
            configured_api_key = official_api_key
        if not (_is_gateway_base_url(configured_base_url) and not configured_gateway_token):
            routes.append(
                {
                    "name": "configured",
                    "base_url": configured_base_url,
                    "api_key": configured_api_key,
                    "gateway_token": configured_gateway_token,
                }
            )

    unique_routes: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for route in routes:
        key = (
            str(route.get("base_url") or "").rstrip("/"),
            str(route.get("api_key") or ""),
            str(route.get("gateway_token") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        unique_routes.append(route)
    return unique_routes


def _strip_code_fence(text: str) -> str:
    stripped = str(text or "").strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if not lines:
        return stripped
    if lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


# P2-1:prompt 组装抽到 llm_prompt_builder.py。这里保留同名 _ 私有别名给现有调用者用。
from llm_prompt_builder import (
    build_review_messages as _build_review_messages,
    build_write_messages as _build_write_messages,
)


def _call_llm_once(
    config: DataModulesConfig,
    *,
    route: dict[str, str],
    messages: list[dict[str, str]],
    model: str,
    temperature: float,
    max_tokens: int,
) -> str:
    url = _chat_completions_url(str(route.get("base_url") or ""))
    api_key = str(route.get("api_key") or "").strip()
    gateway_token = str(route.get("gateway_token") or "").strip()
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    retryable_statuses = {429, 500, 502, 503, 504}
    max_retries = max(int(getattr(config, "api_max_retries", 3) or 3), 1)
    base_delay = float(getattr(config, "api_retry_delay", 1.0) or 1.0)
    last_error = "未知错误"

    for attempt in range(1, max_retries + 1):
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "webnovel-codex/llm-adapter",
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        if gateway_token:
            headers["X-Gateway-Token"] = gateway_token
        req = request.Request(
            url,
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=config.llm_timeout) as resp:
                response_body = resp.read().decode("utf-8")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            last_error = f"HTTP {exc.code}: {detail[:400]}"
            if exc.code in retryable_statuses and attempt < max_retries:
                time.sleep(base_delay * (2 ** (attempt - 1)))
                continue
            raise RuntimeError(last_error) from exc
        except error.URLError as exc:
            last_error = f"网络错误: {exc.reason}"
            if attempt < max_retries:
                time.sleep(base_delay * (2 ** (attempt - 1)))
                continue
            raise RuntimeError(last_error) from exc
        except http.client.IncompleteRead as exc:
            partial = getattr(exc, "partial", b"") or b""
            detail = partial.decode("utf-8", errors="replace")[:200] if isinstance(partial, (bytes, bytearray)) else ""
            last_error = "响应读取不完整"
            if detail:
                last_error = f"{last_error}: {detail}"
            if attempt < max_retries:
                time.sleep(base_delay * (2 ** (attempt - 1)))
                continue
            raise RuntimeError(last_error) from exc
        except http.client.RemoteDisconnected as exc:
            last_error = "远端断开连接"
            if attempt < max_retries:
                time.sleep(base_delay * (2 ** (attempt - 1)))
                continue
            raise RuntimeError(last_error) from exc
        except TimeoutError as exc:
            last_error = "请求超时"
            if attempt < max_retries:
                time.sleep(base_delay * (2 ** (attempt - 1)))
                continue
            raise RuntimeError(last_error) from exc

        try:
            data = json.loads(response_body)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"LLM 返回了无法解析的 JSON: {response_body[:400]}") from exc

        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError(f"LLM 返回缺少 choices: {response_body[:400]}")
        message = choices[0].get("message") or {}
        content = message.get("content")
        if isinstance(content, list):
            content = "\n".join(
                str(item.get("text") or "").strip() for item in content if isinstance(item, dict)
            ).strip()
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError(f"LLM 返回空内容: {response_body[:400]}")
        usage = data.get("usage") or {}
        # 把 usage 暂存在 thread-local,_call_llm 的调用方能取到
        _set_last_usage(
            {
                "prompt_tokens": int(usage.get("prompt_tokens") or 0),
                "completion_tokens": int(usage.get("completion_tokens") or 0),
                "total_tokens": int(usage.get("total_tokens") or 0),
                "model": model,
                "route": str(route.get("base_url") or ""),
            }
        )
        return _strip_code_fence(content)

    raise RuntimeError(last_error)


# 线程局部存储的最后一次 LLM 调用 usage(用于 _append_llm_call_log 取数)
import threading as _threading

_LAST_USAGE_TLS = _threading.local()


def _set_last_usage(usage: dict) -> None:
    _LAST_USAGE_TLS.value = usage


def _get_last_usage() -> dict:
    return getattr(_LAST_USAGE_TLS, "value", {}) or {}


def _call_llm(
    config: DataModulesConfig,
    *,
    messages: list[dict[str, str]],
    model: str,
    temperature: float,
    max_tokens: int,
) -> str:
    provider = str(config.llm_provider or "").strip() or "openai_compatible"
    if provider != "openai_compatible":
        raise RuntimeError(f"暂不支持的 LLM_PROVIDER: {provider}")
    if not str(model or "").strip():
        raise RuntimeError("缺少可用模型名，请配置 LLM_CHAT_MODEL 或 LLM_REASONING_MODEL")
    routes = _build_llm_routes(config, model)
    if not routes:
        if _is_deepseek_model(model):
            raise RuntimeError("缺少可用 DeepSeek 路由，请配置 DEEPSEEK_API_KEY，或补齐 LLM_BASE_URL 与对应鉴权")
        raise RuntimeError("缺少可用 LLM 路由，请补齐 LLM_BASE_URL 与对应鉴权")

    errors: list[str] = []
    for route in routes:
        try:
            return _call_llm_once(
                config,
                route=route,
                messages=messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except RuntimeError as exc:
            errors.append(f"{route['name']}({route['base_url']}): {exc}")
    raise RuntimeError("LLM 请求失败: " + " | ".join(errors))


def _write_text_file(path: Path, content: str, *, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(f"文件已存在，若要覆盖请加 --overwrite: {path}")
    create_secure_directory(str(path.parent))
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def _chapter_output_path(
    project_root: Path,
    chapter_num: int,
    *,
    output: Optional[str],
    use_volume_layout: bool = False,
) -> Path:
    if output:
        return Path(output).expanduser().resolve()
    existing = find_chapter_file(project_root, chapter_num)
    if existing is not None:
        return existing
    return default_chapter_draft_path(
        project_root,
        chapter_num,
        use_volume_layout=use_volume_layout,
    )


def _default_review_path(project_root: Path, chapter_num: int) -> Path:
    """审查报告优先写到用户可见的 审查报告/ 目录,fallback 到 .webnovel/reviews/。

    规则:
    - 项目有 审查报告/ 目录 → 写 审查报告/ch{NNNN}.llm-review.md
    - 否则 → 写 .webnovel/reviews/ch{NNNN}.llm-review.md(老路径)
    这样用户手工 verifier 产物和系统自动 review 都在同一目录,状态同步更简单。
    """
    visible_dir = project_root / "审查报告"
    if visible_dir.is_dir():
        return visible_dir / f"ch{chapter_num:04d}.llm-review.md"
    return project_root / ".webnovel" / "reviews" / f"ch{chapter_num:04d}.llm-review.md"


def _load_chapter_text(project_root: Path, chapter_num: int, chapter_file: Optional[str]) -> tuple[Path, str]:
    if chapter_file:
        path = Path(chapter_file).expanduser().resolve()
    else:
        path = _resolve_registered_chapter_paths(project_root).get(int(chapter_num))
        if path is None:
            path = find_chapter_file(project_root, chapter_num)
        if path is None:
            path = default_chapter_draft_path(project_root, chapter_num)
    if not path.exists():
        raise FileNotFoundError(f"章节文件不存在: {path}")
    return path, path.read_text(encoding="utf-8")


def _ensure_write_outline(payload: Dict[str, Any], chapter_num: int) -> None:
    outline = str(payload.get("outline") or "").strip()
    if not outline or outline.startswith("⚠️"):
        detail = outline or "大纲为空"
        raise ValueError(f"第 {chapter_num} 章缺少可用大纲，已停止生成: {detail}")
    # 阶段支架降级大纲允许通过,但留个 stderr 警告让用户知道
    if outline.startswith("[阶段支架降级大纲"):
        import sys as _sys

        print(f"⚠️ 第 {chapter_num} 章使用阶段支架降级大纲,建议补一份逐章细纲", file=_sys.stderr)


def _strip_markdown_for_stats(text: str) -> str:
    cleaned = re.sub(r"```[\s\S]*?```", "", text)
    cleaned = re.sub(r"^#+\s+.+$", "", cleaned, flags=re.MULTILINE)
    cleaned = cleaned.replace("---", "")
    return cleaned.strip()


def _chapter_word_count(text: str) -> int:
    return len(_strip_markdown_for_stats(text))


def _clip_text(text: str, max_chars: int) -> str:
    compact = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 3].rstrip() + "..."


def _clean_outline_text(outline_text: str) -> str:
    rows: list[str] = []
    title_fallback = ""
    for raw_line in str(outline_text or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("⚠️"):
            continue
        if line.startswith("#"):
            heading = re.sub(r"^#+\s*", "", line).strip()
            heading = re.sub(r"^第\s*\d+\s*章(?:[：:\-—\s]+)?", "", heading).strip()
            if heading and not title_fallback:
                title_fallback = heading
            continue
        line = re.sub(r"^第\s*\d+\s*章(?:[：:\-—\s]+)?", "", line).strip()
        if not line:
            continue
        line = re.sub(r"^(?:[-*+]|(?:\d+|[一二三四五六七八九十]+)[\.\)、])\s*", "", line).strip()
        if line:
            rows.append(line)
    if not rows and title_fallback:
        rows.append(title_fallback)
    return " ".join(rows).strip()


def _extract_outline_title(outline_text: str, chapter_num: int) -> str:
    patterns = (
        rf"^\s*#+\s*第\s*{chapter_num}\s*章(?:[：:\-—\s]+(.+?))?\s*$",
        rf"^\s*第\s*{chapter_num}\s*章(?:[：:\-—\s]+(.+?))?\s*$",
    )
    for pattern in patterns:
        match = re.search(pattern, str(outline_text or ""), re.MULTILINE)
        if not match:
            continue
        title = (match.group(1) or "").strip()
        if title:
            return title
    return ""


def _extract_chapter_title(
    text: str,
    chapter_num: int,
    chapter_path: Path,
    *,
    project_root: Optional[Path] = None,
    outline_text: str = "",
) -> str:
    match = re.search(rf"^\s*#\s*第\s*{chapter_num}\s*章(?:[：:\-—\s]+(.+?))?\s*$", text, re.MULTILINE)
    if match:
        title = (match.group(1) or "").strip()
        if title:
            return title

    outline_title = _extract_outline_title(outline_text, chapter_num)
    if outline_title:
        return outline_title

    if project_root is not None:
        outline_title = resolve_outline_chapter_title(project_root, chapter_num)
        if outline_title:
            return outline_title

    stem = chapter_path.stem
    stem = re.sub(rf"^第0*{chapter_num}章[-—_ ]*", "", stem).strip()
    return stem


def _extract_summary_text(text: str, *, outline_text: str = "", max_chars: int = 220) -> str:
    """提章节摘要。优先级:显式 ## 摘要 > 正文首段 > 大纲(降级)。

    P1-D 修:原来 outline 排在正文前导致批量生成的摘要全是大纲模板,长程上下文失效。
    现在改成正文首段优先,只有正文为空才用大纲。
    """
    explicit_summary = re.search(r"##\s*(?:本章摘要|剧情摘要)\s*\r?\n(.+?)(?=\r?\n##|$)", text, re.DOTALL)
    if explicit_summary:
        first_paragraph = re.split(r"\r?\n\s*\r?\n", explicit_summary.group(1).strip(), maxsplit=1)[0]
        return _clip_text(first_paragraph, max_chars)

    body = _strip_markdown_for_stats(text)
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    if lines:
        parts: list[str] = []
        total = 0
        for line in lines:
            parts.append(line)
            total += len(line)
            if total >= max_chars:
                break
        summary = _clip_text(" ".join(parts), max_chars)
        if summary:
            return summary

    # 正文为空或太短才回退到大纲
    outline_anchor = _clip_text(_clean_outline_text(outline_text), max_chars)
    return outline_anchor


def _summary_path(project_root: Path, chapter_num: int) -> Path:
    return project_root / ".webnovel" / "summaries" / f"ch{chapter_num:04d}.md"


def _external_chapter_registry_path(project_root: Path) -> Path:
    return project_root / ".webnovel" / "external_chapters.json"


def _load_external_chapter_registry(project_root: Path) -> dict[str, str]:
    registry_path = _external_chapter_registry_path(project_root)
    if not registry_path.exists():
        return {}
    try:
        payload = json.loads(registry_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    registry: dict[str, str] = {}
    for key, value in payload.items():
        if isinstance(key, str) and isinstance(value, str) and value.strip():
            registry[key] = value.strip()
    return registry


def _resolve_registered_chapter_paths(project_root: Path) -> dict[int, Path]:
    resolved: dict[int, Path] = {}
    for key, raw_path in _load_external_chapter_registry(project_root).items():
        try:
            chapter_num = int(str(key))
        except (TypeError, ValueError):
            continue
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = (project_root / path).resolve()
        if path.exists():
            resolved[chapter_num] = path.resolve()
    return resolved


def _save_external_chapter_registry(project_root: Path, registry: dict[str, str]) -> None:
    registry_path = _external_chapter_registry_path(project_root)
    _write_text_file(
        registry_path,
        json.dumps(registry, ensure_ascii=False, indent=2),
        overwrite=True,
    )


def _path_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _uses_filename_chapter_identity(chapter_path: Path, chapter_num: int) -> bool:
    return extract_chapter_num_from_filename(chapter_path.name) == int(chapter_num)


def _register_external_chapter_path(project_root: Path, chapter_num: int, chapter_path: Path) -> None:
    registry = _load_external_chapter_registry(project_root)
    key = f"{int(chapter_num):04d}"
    if _path_within(chapter_path, project_root) and _uses_filename_chapter_identity(chapter_path, chapter_num):
        registry.pop(key, None)
    else:
        registry[key] = str(chapter_path.resolve())
    _save_external_chapter_registry(project_root, registry)


def _write_summary_file(
    project_root: Path,
    chapter_num: int,
    summary_text: str,
    *,
    title: str = "",
    outline_anchor: str = "",
) -> Path:
    summary_path = _summary_path(project_root, chapter_num)
    heading = f"# 第{chapter_num}章摘要"
    if title:
        heading = f"{heading} - {title}"
    parts = [heading, "", "## 剧情摘要", summary_text or "（待补充）"]
    if outline_anchor and outline_anchor != summary_text:
        parts.extend(["", "## 大纲锚点", outline_anchor])
    payload = "\n".join(parts) + "\n"
    _write_text_file(summary_path, payload, overwrite=True)
    return summary_path


def _scan_chapter_progress(project_root: Path) -> tuple[int, int]:
    current_chapter = 0
    total_words = 0
    for chapter_num, path in _collect_chapter_files(project_root):
        current_chapter = max(current_chapter, chapter_num)
        try:
            total_words += _chapter_word_count(path.read_text(encoding="utf-8"))
        except OSError:
            continue
    return current_chapter, total_words


def _collect_chapter_files(project_root: Path) -> list[tuple[int, Path]]:
    collected: dict[int, Path] = {}
    scanned: set[Path] = set()
    registered_paths = _resolve_registered_chapter_paths(project_root)

    chapters_dir = project_root / "正文"
    if chapters_dir.exists():
        for path in sorted(chapters_dir.rglob("*.md")):
            chapter_num = extract_chapter_num_from_filename(path.name)
            if not chapter_num:
                continue
            resolved = path.resolve()
            if registered_paths.get(chapter_num) not in (None, resolved):
                continue
            scanned.add(resolved)
            collected[chapter_num] = resolved

    for path in sorted(project_root.rglob("*.md")):
        resolved = path.resolve()
        if resolved in scanned:
            continue
        if ".webnovel" in path.parts or "大纲" in path.parts:
            continue
        chapter_num = extract_chapter_num_from_filename(path.name)
        if not chapter_num:
            continue
        if registered_paths.get(chapter_num) not in (None, resolved):
            continue
        scanned.add(resolved)
        collected[chapter_num] = resolved

    for chapter_num, resolved in registered_paths.items():
        if resolved in scanned:
            continue
        if resolved.exists():
            scanned.add(resolved)
            collected[chapter_num] = resolved

    return sorted(collected.items())


def _load_state_progress(project_root: Path) -> tuple[int, int]:
    state_path = project_root / ".webnovel" / "state.json"
    if not state_path.exists():
        return 0, 0
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return 0, 0
    progress = state.get("progress") if isinstance(state, dict) else {}
    if not isinstance(progress, dict):
        return 0, 0
    try:
        current_chapter = int(progress.get("current_chapter", 0) or 0)
    except (TypeError, ValueError):
        current_chapter = 0
    try:
        total_words = int(progress.get("total_words", 0) or 0)
    except (TypeError, ValueError):
        total_words = 0
    return current_chapter, total_words


def _record_progress(project_root: Path, current_chapter: int, total_words: int) -> None:
    script = Path(__file__).resolve().parent / "update_state.py"
    cmd = [
        sys.executable,
        str(script),
        "--project-root",
        str(project_root),
        "--progress",
        str(current_chapter),
        str(total_words),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        stderr = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"写入进度失败: {stderr}")


def _relative_project_path(project_root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(project_root.resolve()))
    except ValueError:
        return str(path)


_NAME_SPLIT_RE = re.compile(r"[、,，/|；;]+")
_TRACKING_RANGE_RE = re.compile(r"第\s*(\d+)(?:\s*[-—~至到]+\s*(\d+))?\s*章")
_SUMMARY_FIELD_RE = re.compile(r"(场景|推进|兑现|章末钩子|失认节点)：")


def _load_runtime_state(project_root: Path) -> dict[str, Any]:
    state_path = project_root / ".webnovel" / "state.json"
    if not state_path.exists():
        return {}
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    try:
        from data_modules.state_validator import normalize_state_runtime_sections
    except ImportError:  # pragma: no cover
        from scripts.data_modules.state_validator import normalize_state_runtime_sections
    return normalize_state_runtime_sections(payload)


def _save_runtime_state(project_root: Path, state: dict[str, Any]) -> None:
    state_path = project_root / ".webnovel" / "state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _split_names(raw_value: Any) -> list[str]:
    if raw_value is None:
        return []
    if isinstance(raw_value, list):
        values = raw_value
    else:
        values = _NAME_SPLIT_RE.split(str(raw_value))
    names: list[str] = []
    seen: set[str] = set()
    for item in values:
        name = str(item or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        names.append(name)
    return names


def _parse_markdown_table(text: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if not cells or not any(cells):
            continue
        if all(set(cell) <= {"-"} for cell in cells if cell):
            continue
        rows.append(cells)
    return rows


def _load_known_character_roles(project_root: Path, state: dict[str, Any]) -> dict[str, dict[str, str]]:
    project_info = state.get("project_info", {}) if isinstance(state.get("project_info"), dict) else {}
    protagonist_name = str(state.get("protagonist_state", {}).get("name") or "").strip()
    roles: dict[str, dict[str, str]] = {}

    def _set_role(name: str, *, tier: str, affinity: str, relation: str, desc: str = "") -> None:
        if not name:
            return
        roles[name] = {
            "tier": tier,
            "affinity": affinity,
            "relation": relation,
            "desc": desc,
        }

    if protagonist_name:
        _set_role(protagonist_name, tier="核心", affinity="self", relation="自我", desc="主视角")

    for name in _split_names(project_info.get("heroine_names")):
        _set_role(
            name, tier="核心", affinity="ally", relation="官配同盟", desc=str(project_info.get("heroine_role") or "")
        )
    for name in _split_names(project_info.get("co_protagonists")):
        _set_role(
            name,
            tier="重要",
            affinity="ally",
            relation="同伴",
            desc=str(project_info.get("co_protagonist_roles") or ""),
        )
    for name in _split_names(project_info.get("antagonist_tiers")):
        _set_role(name, tier="重要", affinity="enemy", relation="敌对", desc="反派层级")

    cast_path = project_root / "设定集" / "主角组.md"
    if cast_path.exists():
        for row in _parse_markdown_table(cast_path.read_text(encoding="utf-8")):
            if len(row) < 2 or row[0] in {"名称", "------"}:
                continue
            name = row[0].strip()
            desc = row[1].strip()
            relation = "同伴"
            affinity = "ally"
            tier = "重要"
            if "官配" in desc:
                relation = "官配同盟"
                tier = "核心"
            elif "师父" in desc:
                relation = "师徒"
            elif "红颜" in desc:
                relation = "复杂同盟"
            elif "体制线" in desc:
                relation = "体制盟友"
            elif "副线行动位" in desc:
                relation = "行动同伴"
            if name == protagonist_name:
                affinity = "self"
                relation = "自我"
                tier = "核心"
            existing = roles.get(name, {})
            if existing.get("affinity") == "enemy" and affinity != "self":
                affinity = "enemy"
                relation = existing.get("relation") or "敌对"
                tier = existing.get("tier") or tier
            roles[name] = {
                "tier": tier,
                "affinity": affinity,
                "relation": relation,
                "desc": desc,
            }
    return roles


def _infer_tracking_location(title: str, text: str, summary_text: str, outline_text: str) -> str:
    corpus = "\n".join(part for part in [title, summary_text, outline_text, text[-800:]] if part)
    candidates = [
        ("香行街", "香行街"),
        ("州城南库", "州城南库"),
        ("南库", "州城南库"),
        ("州城北码头", "州城北码头"),
        ("北码头", "州城北码头"),
        ("州城", "州城"),
        ("义渡", "义渡"),
        ("水驿", "州城水驿"),
        ("夜船", "夜船"),
        ("义庄", "义庄"),
        ("城隍庙", "城隍庙"),
        ("抬棺铺", "抬棺铺"),
        ("渡口", "渡口"),
    ]
    for keyword, location in candidates:
        if keyword in corpus:
            return location
    return ""


def _parse_summary_signals(summary_text: str) -> dict[str, str]:
    text = str(summary_text or "").strip()
    if not text:
        return {}
    matches = list(_SUMMARY_FIELD_RE.finditer(text))
    if not matches:
        return {}
    result: dict[str, str] = {}
    for idx, match in enumerate(matches):
        label = match.group(1)
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        value = text[start:end].strip(" ：:\n")
        if value:
            result[label] = value.strip()
    return result


def _read_existing_summary(project_root: Path, chapter_num: int) -> tuple[str, dict[str, str]]:
    summary_path = _summary_path(project_root, chapter_num)
    if not summary_path.exists():
        return "", {}
    raw = summary_path.read_text(encoding="utf-8").strip()
    if not raw:
        return "", {}
    lines = raw.splitlines()
    if lines and lines[0].startswith("#"):
        lines = lines[1:]
        while lines and not lines[0].strip():
            lines = lines[1:]
    body = "\n".join(lines).strip()
    return body, _parse_summary_signals(body)


def _extract_milestone_chapters(cell_text: str) -> list[int]:
    chapters: list[int] = []
    for start, _end in _TRACKING_RANGE_RE.findall(str(cell_text or "")):
        try:
            chapter = int(start)
        except ValueError:
            continue
        if chapter > 0:
            chapters.append(chapter)
    return chapters


def _infer_foreshadowing_tier(content: str, fallback: str = "支线") -> str:
    text = str(content or "")
    if any(
        keyword in text
        for keyword in (
            "许三更这个名字",
            "姐姐许灯娘",
            "开国正名大祭",
            "三重见证",
            "道级总册",
            "天下总账",
            "流域分账",
        )
    ):
        return "核心"
    if any(keyword in text for keyword in ("空白香签", "老鲁头", "沈见秋", "何晚舟", "程雁书", "边军")):
        return "支线"
    return fallback or "支线"


def _build_dynamic_foreshadowing(
    project_root: Path, state: dict[str, Any], current_chapter: int
) -> list[dict[str, Any]]:
    clue_path = project_root / "大纲" / "线索回收表.md"
    existing_items = state.get("plot_threads", {}).get("foreshadowing", [])
    existing_map = {
        str(item.get("content") or "").strip(): item
        for item in existing_items
        if isinstance(item, dict) and str(item.get("content") or "").strip()
    }
    if not clue_path.exists():
        return existing_items if isinstance(existing_items, list) else []

    rows = _parse_markdown_table(clue_path.read_text(encoding="utf-8"))
    foreshadowing: list[dict[str, Any]] = []
    for row in rows:
        if len(row) < 6 or row[0] == "线索":
            continue
        content = row[0].strip()
        if not content:
            continue
        planted_candidates = _extract_milestone_chapters(row[1])
        planted_chapter = planted_candidates[0] if planted_candidates else None
        milestones: list[int] = []
        for cell in row[2:6]:
            milestones.extend(_extract_milestone_chapters(cell))
        milestones = sorted({chapter for chapter in milestones if chapter and chapter > 0})
        existing = existing_map.get(content, {})
        target_chapter = None
        for chapter in milestones:
            if chapter > current_chapter:
                target_chapter = chapter
                break
        if target_chapter is None:
            target_chapter = milestones[-1] if milestones else planted_chapter

        foreshadowing.append(
            {
                "content": content,
                "status": str(existing.get("status") or "未回收"),
                "added_at": str(existing.get("added_at") or time.strftime("%Y-%m-%d")),
                "planted_chapter": planted_chapter,
                "target_chapter": target_chapter,
                "tier": _infer_foreshadowing_tier(content, str(existing.get("tier") or "支线")),
                "milestones": milestones,
            }
        )
    return foreshadowing


def _infer_dominant_strand(
    title: str,
    text: str,
    summary_text: str,
    outline_text: str,
    mentioned_characters: list[str],
) -> str:
    corpus = "\n".join(part for part in [title, summary_text, outline_text, text] if part)
    scores = {"quest": 0, "fire": 0, "constellation": 0}

    quest_keywords = (
        ("追", 1),
        ("找", 1),
        ("查", 1),
        ("翻账", 2),
        ("对账", 2),
        ("证据", 2),
        ("破", 1),
        ("救", 1),
        ("抢", 2),
        ("截", 1),
        ("脱身", 2),
        ("夜船", 2),
        ("义庄", 1),
        ("水路", 1),
    )
    constellation_keywords = (
        ("州里", 2),
        ("州城", 2),
        ("州祭", 2),
        ("分账", 3),
        ("总账", 3),
        ("祭局", 3),
        ("香火局", 3),
        ("香行", 2),
        ("名册", 2),
        ("州册", 3),
        ("地方册", 3),
        ("库房", 2),
        ("收名", 3),
        ("空名", 2),
        ("补签", 2),
        ("规矩", 1),
        ("旧礼", 2),
        ("势力", 2),
        ("案库", 3),
        ("巡香使", 2),
    )
    fire_keywords = (
        ("试探", 2),
        ("分歧", 3),
        ("硬顶", 3),
        ("校正", 2),
        ("互相", 2),
        ("牵引", 2),
        ("看穿", 2),
        ("裂", 2),
        ("救命", 2),
        ("争", 1),
        ("护", 1),
        ("陪", 1),
        ("站主角这边", 3),
        ("一起", 1),
    )
    for keyword, weight in quest_keywords:
        if keyword in corpus:
            scores["quest"] += weight
    for keyword, weight in constellation_keywords:
        if keyword in corpus:
            scores["constellation"] += weight
    for keyword, weight in fire_keywords:
        if keyword in corpus:
            scores["fire"] += weight
    for name in mentioned_characters:
        if name in {"沈见秋", "何晚舟", "程雁书"}:
            scores["fire"] += 2
    if any(word in title for word in ("追", "查", "抢", "脱身", "救")):
        scores["quest"] += 2
    if any(word in title for word in ("州", "名", "账", "册", "香", "祭", "库")):
        scores["constellation"] += 2
    if any(word in title for word in ("错认", "试探", "分歧", "夜谈", "回铺")):
        scores["fire"] += 2
    if scores["fire"] > scores["quest"] and scores["fire"] >= scores["constellation"]:
        return "fire"
    if scores["constellation"] > scores["quest"]:
        return "constellation"
    return "quest"


def _infer_hook_type(hook_text: str) -> str:
    text = str(hook_text or "").strip()
    if not text:
        return "悬念钩"
    if any(token in text for token in ("谁", "为什么", "哪", "会不会", "是不是", "究竟", "？", "?")):
        return "悬念钩"
    if any(token in text for token in ("要", "得", "必须", "准备", "去", "上船", "进州", "回州")):
        return "行动钩"
    if any(token in text for token in ("名字", "香票", "香火局", "名册", "旧账", "总账", "签押")):
        return "信息钩"
    return "情绪钩"


def _infer_hook_strength(hook_text: str, hook_type: str) -> str:
    text = str(hook_text or "").strip()
    if not text:
        return "weak"
    if hook_type == "悬念钩" and any(token in text for token in ("谁", "为什么", "会不会", "香火局", "总账", "名字")):
        return "strong"
    if len(text) >= 18:
        return "medium"
    return "weak"


def _infer_coolpoint_patterns(text: str, summary_text: str, outline_text: str) -> list[str]:
    corpus = "\n".join(part for part in [summary_text, outline_text, text] if part)
    rules = [
        ("查错破局", ("看出", "认出", "查出", "追", "摸清", "找出", "对账")),
        ("夺证翻账", ("账册", "存根", "香票", "名册", "证据", "搜出", "抄下")),
        ("借规矩反咬", ("规矩", "反咬", "反杀", "压住", "借相", "设局", "反扑")),
        ("水路追凶", ("夜船", "义渡", "水路", "黑篷船", "水驿", "码头")),
        ("失认惊险", ("失认", "认错", "错认", "名字被改", "残名")),
        ("关系对撞", ("沈见秋", "何晚舟", "程雁书", "分歧", "试探", "硬顶")),
        ("黑幕加深", ("香火局", "河祭司", "州里收名", "分账", "总账", "旧礼")),
    ]
    patterns: list[str] = []
    for label, keywords in rules:
        if any(keyword in corpus for keyword in keywords):
            patterns.append(label)
    return patterns[:4]


def _collect_micropayoffs(summary_text: str) -> list[str]:
    signals = _parse_summary_signals(summary_text)
    payoff = str(signals.get("兑现") or "").strip()
    return [payoff] if payoff else []


def _build_tracking_payload(
    project_root: Path,
    state: dict[str, Any],
    chapter_num: int,
    title: str,
    chapter_text: str,
    summary_text: str,
    outline_text: str,
) -> dict[str, Any]:
    protagonist_name = str(state.get("protagonist_state", {}).get("name") or "").strip()
    role_registry = _load_known_character_roles(project_root, state)
    combined_text = "\n".join(part for part in [title, summary_text, outline_text, chapter_text] if part)
    mentioned = [name for name in role_registry if name and name in combined_text]
    if protagonist_name and protagonist_name not in mentioned:
        mentioned.insert(0, protagonist_name)

    location = _infer_tracking_location(title, chapter_text, summary_text, outline_text)
    summary_signals = _parse_summary_signals(summary_text)
    hook_text = str(summary_signals.get("章末钩子") or "").strip()
    if not hook_text:
        paragraphs = [line.strip() for line in chapter_text.splitlines() if line.strip()]
        hook_text = paragraphs[-1] if paragraphs else ""
    dominant = _infer_dominant_strand(title, chapter_text, summary_text, outline_text, mentioned)
    coolpoint_patterns = _infer_coolpoint_patterns(chapter_text, summary_text, outline_text)
    micropayoffs = _collect_micropayoffs(summary_text)
    hook_type = _infer_hook_type(hook_text)
    hook_strength = _infer_hook_strength(hook_text, hook_type)

    return {
        "mentioned_characters": mentioned,
        "location": location,
        "dominant": dominant,
        "hook": hook_text,
        "hook_type": hook_type,
        "hook_strength": hook_strength,
        "coolpoint_patterns": coolpoint_patterns,
        "micropayoffs": micropayoffs,
        "summary_signals": summary_signals,
        "roles": role_registry,
        "chapter_meta": {
            "title": title,
            "hook": hook_text,
            "hook_type": hook_type,
            "hook_strength": hook_strength,
            "coolpoint_patterns": coolpoint_patterns,
            "micropayoffs": micropayoffs,
            "dominant": dominant,
            "location": location,
            "characters": mentioned,
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "source": "llm_adapter.sync",
        },
    }


def _sync_state_tracking(
    project_root: Path,
    chapter_num: int,
    *,
    current_chapter: int,
    tracking: dict[str, Any],
) -> None:
    state = _load_runtime_state(project_root)
    if not state:
        return

    chapter_meta = state.setdefault("chapter_meta", {})
    chapter_key = f"{chapter_num:04d}"
    chapter_meta[chapter_key] = tracking["chapter_meta"]

    strand_tracker = state.setdefault(
        "strand_tracker",
        {
            "last_quest_chapter": 0,
            "last_fire_chapter": 0,
            "last_constellation_chapter": 0,
            "current_dominant": None,
            "chapters_since_switch": 0,
            "history": [],
        },
    )
    history_rows = [row for row in strand_tracker.get("history", []) if isinstance(row, dict)]
    history_map = {
        int(str(row.get("chapter") or 0)): row for row in history_rows if str(row.get("chapter") or "").isdigit()
    }
    history_map[chapter_num] = {
        "chapter": chapter_num,
        "dominant": tracking["dominant"],
        "strand": tracking["dominant"],
    }
    ordered_history = [history_map[key] for key in sorted(history_map)]
    if len(ordered_history) > 200:
        ordered_history = ordered_history[-200:]
    strand_tracker["history"] = ordered_history
    strand_tracker[f"last_{tracking['dominant']}_chapter"] = chapter_num
    strand_tracker["current_dominant"] = ordered_history[-1]["dominant"] if ordered_history else tracking["dominant"]
    since_switch = 0
    for row in reversed(ordered_history):
        if row.get("dominant") != strand_tracker["current_dominant"]:
            break
        since_switch += 1
    strand_tracker["chapters_since_switch"] = since_switch

    plot_threads = state.setdefault("plot_threads", {})
    plot_threads["foreshadowing"] = _build_dynamic_foreshadowing(project_root, state, current_chapter)
    state["foreshadowing"] = plot_threads["foreshadowing"]
    pending_items = [
        item
        for item in plot_threads.get("foreshadowing", [])
        if isinstance(item, dict) and str(item.get("status") or "未回收") != "已回收"
    ]
    pending_items.sort(key=lambda item: int(item.get("target_chapter") or 10**9))
    plot_threads["active_threads"] = [
        str(item.get("content") or "").strip() for item in pending_items[:3] if item.get("content")
    ]

    protagonist_state = state.setdefault("protagonist_state", {})
    if tracking["location"]:
        protagonist_state["location"] = {
            "current": tracking["location"],
            "last_chapter": chapter_num,
        }

    relationships = state.get("relationships")
    if not isinstance(relationships, dict):
        relationships = {}
        state["relationships"] = relationships
    allies_map = {
        item.get("name"): dict(item)
        for item in relationships.get("allies", [])
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    }
    enemies_map = {
        item.get("name"): dict(item)
        for item in relationships.get("enemies", [])
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    }
    protagonist_name = str(protagonist_state.get("name") or "").strip()
    for name in tracking["mentioned_characters"]:
        if not name or name == protagonist_name:
            continue
        role_info = tracking["roles"].get(name, {})
        record = {
            "name": name,
            "relation": role_info.get("relation") or "同伴",
            "last_chapter": chapter_num,
        }
        if role_info.get("affinity") == "enemy":
            enemies_map[name] = record
        else:
            allies_map[name] = record
    relationships["allies"] = sorted(
        allies_map.values(), key=lambda item: (int(item.get("last_chapter", 0)), item.get("name", "")), reverse=True
    )
    relationships["enemies"] = sorted(
        enemies_map.values(), key=lambda item: (int(item.get("last_chapter", 0)), item.get("name", "")), reverse=True
    )

    _save_runtime_state(project_root, state)


def _sync_index_tracking(
    project_root: Path,
    chapter_num: int,
    *,
    tracking: dict[str, Any],
) -> None:
    try:
        from data_modules.index_manager import (
            ChapterReadingPowerMeta,
            EntityMeta,
            IndexManager,
            RelationshipEventMeta,
            RelationshipMeta,
        )
    except ImportError:  # pragma: no cover
        from scripts.data_modules.index_manager import (
            ChapterReadingPowerMeta,
            EntityMeta,
            IndexManager,
            RelationshipEventMeta,
            RelationshipMeta,
        )

    protagonist_name = str(_load_runtime_state(project_root).get("protagonist_state", {}).get("name") or "").strip()
    config = DataModulesConfig.from_project_root(project_root)
    manager = IndexManager(config)

    manager.save_chapter_reading_power(
        ChapterReadingPowerMeta(
            chapter=chapter_num,
            hook_type=tracking["hook_type"],
            hook_strength=tracking["hook_strength"],
            coolpoint_patterns=tracking["coolpoint_patterns"],
            micropayoffs=tracking["micropayoffs"],
            soft_suggestions=[f"dominant={tracking['dominant']}"] if tracking.get("dominant") else [],
            is_transition=tracking["dominant"] == "constellation" and not tracking["coolpoint_patterns"],
        )
    )

    for name in tracking["mentioned_characters"]:
        role_info = tracking["roles"].get(name, {})
        entity_id = f"char:{name}"
        existing = manager.get_entity(entity_id)
        manager.upsert_entity(
            EntityMeta(
                id=entity_id,
                type="角色",
                canonical_name=name,
                tier=role_info.get("tier") or ("核心" if name == protagonist_name else "重要"),
                desc=role_info.get("desc") or role_info.get("relation") or "",
                current={"location": tracking["location"]} if tracking["location"] and name == protagonist_name else {},
                first_appearance=chapter_num if not existing else int(existing.get("first_appearance") or chapter_num),
                last_appearance=chapter_num,
                is_protagonist=name == protagonist_name,
            ),
            update_metadata=True,
        )

    protagonist_id = f"char:{protagonist_name}" if protagonist_name else ""
    for name in tracking["mentioned_characters"]:
        if not protagonist_id or name == protagonist_name:
            continue
        role_info = tracking["roles"].get(name, {})
        relation_type = role_info.get("relation") or ("敌对" if role_info.get("affinity") == "enemy" else "同伴")
        other_id = f"char:{name}"
        existing_rel = manager.get_relationship_between(protagonist_id, other_id)
        manager.upsert_relationship(
            RelationshipMeta(
                from_entity=protagonist_id,
                to_entity=other_id,
                type=relation_type,
                description=f"第{chapter_num}章同步为{relation_type}",
                chapter=chapter_num,
            )
        )
        manager.record_relationship_event(
            RelationshipEventMeta(
                from_entity=protagonist_id,
                to_entity=other_id,
                type=relation_type,
                chapter=chapter_num,
                action="create" if not existing_rel else "update",
                polarity=-1 if role_info.get("affinity") == "enemy" else 1,
                strength=0.8 if role_info.get("affinity") == "enemy" else 0.65,
                description=f"第{chapter_num}章继续推进 {relation_type}",
                evidence=tracking["hook"] or relation_type,
            )
        )


def _snapshot_state_for_rollback(project_root: Path) -> dict[str, bytes | None]:
    """P1-4 事务化:抓 sync 涉及的关键文件快照,失败时可回滚。"""
    files = [
        project_root / ".webnovel" / "state.json",
        project_root / ".webnovel" / "external_chapters.json",
    ]
    snap: dict[str, bytes | None] = {}
    for p in files:
        try:
            snap[str(p)] = p.read_bytes() if p.is_file() else None
        except Exception:
            snap[str(p)] = None
    return snap


def _restore_state_from_snapshot(snap: dict[str, bytes | None]) -> None:
    """从快照回滚关键文件(state.json / external_chapters.json)。"""
    for path_str, data in snap.items():
        p = Path(path_str)
        try:
            if data is None:
                if p.is_file():
                    p.unlink()
            else:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(data)
        except Exception as exc:
            print(f"⚠️ 回滚 {p} 失败: {exc}", file=sys.stderr)


def _sync_written_chapter(
    project_root: Path,
    chapter_num: int,
    chapter_path: Path,
    chapter_text: str,
    *,
    outline_text: str = "",
    previous_text: str = "",
    summary_override: str = "",
    rewrite_summary: bool = True,
) -> dict[str, Any]:
    # P1-4:事务化 — 先快照,失败回滚
    snapshot = _snapshot_state_for_rollback(project_root)
    sync_stage = "init"
    try:
        sync_stage = "register_external"
        _register_external_chapter_path(project_root, chapter_num, chapter_path)
        return _sync_written_chapter_impl(
            project_root,
            chapter_num,
            chapter_path,
            chapter_text,
            outline_text=outline_text,
            previous_text=previous_text,
            summary_override=summary_override,
            rewrite_summary=rewrite_summary,
        )
    except Exception as exc:
        print(
            f"⚠️ ch{chapter_num:04d} _sync_written_chapter 失败 stage={sync_stage}: {exc};正在回滚 state",
            file=sys.stderr,
        )
        _restore_state_from_snapshot(snapshot)
        raise


def _sync_written_chapter_impl(
    project_root: Path,
    chapter_num: int,
    chapter_path: Path,
    chapter_text: str,
    *,
    outline_text: str = "",
    previous_text: str = "",
    summary_override: str = "",
    rewrite_summary: bool = True,
) -> dict[str, Any]:
    title = _extract_chapter_title(
        chapter_text,
        chapter_num,
        chapter_path,
        project_root=project_root,
        outline_text=outline_text,
    )
    outline_anchor = _clip_text(_clean_outline_text(outline_text), 160)
    summary_text = str(summary_override or "").strip() or _extract_summary_text(chapter_text, outline_text=outline_text)
    summary_path = _summary_path(project_root, chapter_num)
    if rewrite_summary or not summary_path.exists():
        summary_path = _write_summary_file(
            project_root,
            chapter_num,
            summary_text,
            title=title,
            outline_anchor=outline_anchor,
        )

    try:
        from data_modules.index_manager import ChapterMeta, IndexManager
    except ImportError:  # pragma: no cover
        from scripts.data_modules.index_manager import ChapterMeta, IndexManager

    config = DataModulesConfig.from_project_root(project_root)
    manager = IndexManager(config)
    manager.add_chapter(
        ChapterMeta(
            chapter=chapter_num,
            title=title,
            location="",
            word_count=_chapter_word_count(chapter_text),
            characters=[],
            summary=summary_text,
        )
    )

    scanned_chapter, scanned_words = _scan_chapter_progress(project_root)
    state_chapter, state_words = _load_state_progress(project_root)
    current_chapter = max(scanned_chapter, state_chapter, chapter_num)
    total_words = max(
        scanned_words,
        state_words - _chapter_word_count(previous_text) + _chapter_word_count(chapter_text),
    )
    if total_words <= 0:
        total_words = _chapter_word_count(chapter_text)
    _record_progress(project_root, current_chapter, total_words)
    state = _load_runtime_state(project_root)
    tracking = _build_tracking_payload(
        project_root,
        state,
        chapter_num,
        title,
        chapter_text,
        summary_text,
        outline_text,
    )
    _sync_state_tracking(project_root, chapter_num, current_chapter=current_chapter, tracking=tracking)
    _sync_index_tracking(project_root, chapter_num, tracking=tracking)

    # 章末硬约束验证(防 LLM 乱跑) — 只警告,不阻断
    audit_result = None
    try:
        try:
            from draft_audit import audit as _draft_audit
        except ImportError:
            from scripts.draft_audit import audit as _draft_audit  # pragma: no cover
        audit_result = _draft_audit(project_root, chapter_num)
        if audit_result.get("errors"):
            print(
                f"⚠️ ch{chapter_num:04d} draft_audit FAIL: "
                f"{audit_result['errors']} errors / {audit_result.get('warnings', 0)} warnings",
                file=sys.stderr,
            )
            for issue in audit_result.get("issues", []):
                if issue.get("level") == "error":
                    print(f"   ✗ {issue.get('msg', '')}", file=sys.stderr)
        elif audit_result.get("warnings"):
            print(
                f"⚠️ ch{chapter_num:04d} draft_audit warns: {audit_result['warnings']}",
                file=sys.stderr,
            )
    except Exception as exc:
        # audit 失败不影响主流程
        print(f"⚠️ draft_audit 调用失败: {exc}", file=sys.stderr)

    # P1-B 伏笔自动追踪:每章写完自动跑一次提取(后台,失败静默)
    # 通过环境变量 WEBNOVEL_FORESHADOWING_AUTO=0 可关闭
    if os.environ.get("WEBNOVEL_FORESHADOWING_AUTO", "1") != "0":
        try:
            try:
                from foreshadowing_tracker import extract_via_llm, update_state_with_foreshadowing
            except ImportError:
                from scripts.foreshadowing_tracker import extract_via_llm, update_state_with_foreshadowing
            payload_fs = extract_via_llm(project_root, chapter_num)
            if payload_fs:
                added = update_state_with_foreshadowing(project_root, chapter_num, payload_fs)
                if added:
                    print(f"📌 ch{chapter_num:04d} 新增伏笔 {added} 条", file=sys.stderr)
        except Exception as exc:
            print(f"⚠️ foreshadowing 自动追踪失败(已忽略): {exc}", file=sys.stderr)

    return {
        "summary_path": summary_path,
        "current_chapter": current_chapter,
        "total_words": total_words,
        "audit": audit_result,
    }


def _record_review_checkpoint(project_root: Path, chapter_num: int, report_path: Path) -> None:
    script = Path(__file__).resolve().parent / "update_state.py"
    cmd = [
        sys.executable,
        str(script),
        "--project-root",
        str(project_root),
        "--add-review",
        str(chapter_num),
        str(report_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        stderr = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"写入 review_checkpoints 失败: {stderr}")


_REVIEW_SECTION_LABELS = {
    "critical": ("Critical", "严重", "严重问题", "关键问题", "致命问题"),
    "major": ("Major", "主要", "主要问题", "重大问题"),
    "minor": ("Minor", "次要", "次要问题", "轻微", "轻微问题", "一般问题"),
}
_REVIEW_STOP_LABELS = (
    "总评",
    "总分",
    "评分",
    "综合评分",
    "Overall Score",
    "Score",
    "可直接修改建议",
    "修改建议",
    "是否建议重写本章",
    "是否建议重写",
    "建议重写",
    *_REVIEW_SECTION_LABELS["critical"],
    *_REVIEW_SECTION_LABELS["major"],
    *_REVIEW_SECTION_LABELS["minor"],
)


def _build_label_pattern(labels: Iterable[str]) -> str:
    return "|".join(sorted((re.escape(label) for label in labels), key=len, reverse=True))


def _extract_review_section(text: str, labels: Iterable[str]) -> str:
    heading_pat = _build_label_pattern(labels)
    stop_pat = _build_label_pattern(_REVIEW_STOP_LABELS)
    pattern = (
        rf"(?ims)^\s*(?:#+\s*)?(?:{heading_pat})(?:\s*(?:问题|Issues?))?\s*(?:[:：]|$)\s*(.*?)"
        rf"(?=^\s*(?:#+\s*)?(?:{stop_pat})(?:\s*(?:问题|Issues?))?\s*(?:[:：]|$)|\Z)"
    )
    match = re.search(pattern, text)
    return match.group(1).strip() if match else ""


def _normalize_review_text(review_text: str) -> str:
    return re.sub(r"[*_`]+", "", str(review_text or ""))


def _count_review_items(section_text: str) -> int:
    count = 0
    for line in section_text.splitlines():
        stripped = line.strip()
        if re.match(r"^(?:[-*+]|(?:\d+|[一二三四五六七八九十]+)[\.\)、])\s+", stripped):
            count += 1
    if count == 0 and section_text.strip():
        return 1
    return count


def _extract_bullets(section_text: str) -> list[str]:
    items: list[str] = []
    for line in section_text.splitlines():
        stripped = line.strip()
        stripped = re.sub(r"^(?:[-*+]|(?:\d+|[一二三四五六七八九十]+)[\.\)、])\s+", "", stripped).strip()
        if stripped:
            items.append(stripped)
    if not items and section_text.strip():
        return [_clip_text(section_text, 160)]
    return items


def _extract_overall_score(review_text: str) -> float:
    label_pat = _build_label_pattern(("总评", "总分", "评分", "综合评分", "Overall Score", "Score"))
    lines = [line.strip() for line in str(review_text or "").splitlines()]
    for idx, line in enumerate(lines):
        if not re.search(label_pat, line, re.IGNORECASE):
            continue
        next_line = lines[idx + 1] if idx + 1 < len(lines) else ""
        probe = " ".join(part for part in (line, next_line) if part)
        for pattern in (
            r"(\d+(?:\.\d+)?)\s*/\s*(10|100)",
            r"(\d+(?:\.\d+)?)\s*分",
            r"(?:[:：]\s*|\s+)(\d+(?:\.\d+)?)\s*$",
        ):
            match = re.search(pattern, probe, re.IGNORECASE)
            if not match:
                continue
            score = float(match.group(1))
            scale = match.group(2) if len(match.groups()) > 1 else None
            if scale == "10" or (scale is None and score <= 10):
                return round(score * 10, 2)
            return round(score, 2)
    return 0.0


def _extract_dimension_scores(review_text: str) -> dict[str, float]:
    scores: dict[str, float] = {}
    skip_labels = {
        "总评",
        "总分",
        "评分",
        "综合评分",
        "overall score",
        "score",
        *(label.lower() for label in _REVIEW_SECTION_LABELS["critical"]),
        *(label.lower() for label in _REVIEW_SECTION_LABELS["major"]),
        *(label.lower() for label in _REVIEW_SECTION_LABELS["minor"]),
    }
    for raw_line in review_text.splitlines():
        line = raw_line.strip()
        for pattern in (
            r"^(?:[-*+]\s*)?([^:：]{1,20})[:：]\s*(\d+(?:\.\d+)?)\s*/\s*(10|100)\s*$",
            r"^(?:[-*+]\s*)?([^:：]{1,20})[:：]\s*(\d+(?:\.\d+)?)\s*分\s*$",
        ):
            match = re.match(pattern, line)
            if not match:
                continue
            label = match.group(1).strip()
            if label.lower() in skip_labels:
                break
            score = float(match.group(2))
            scale = float(match.group(3)) if len(match.groups()) > 2 and match.group(3) else 100.0
            if scale == 10:
                score *= 10.0
            scores[label] = round(score, 2)
            break
    return scores


def _parse_review_metrics(review_text: str, *, chapter_num: int, report_path: Path) -> dict[str, Any]:
    normalized_review_text = _normalize_review_text(review_text)
    critical_section = _extract_review_section(normalized_review_text, _REVIEW_SECTION_LABELS["critical"])
    major_section = _extract_review_section(normalized_review_text, _REVIEW_SECTION_LABELS["major"])
    minor_section = _extract_review_section(normalized_review_text, _REVIEW_SECTION_LABELS["minor"])
    return {
        "start_chapter": chapter_num,
        "end_chapter": chapter_num,
        "overall_score": _extract_overall_score(normalized_review_text),
        "dimension_scores": _extract_dimension_scores(normalized_review_text),
        "severity_counts": {
            "critical": _count_review_items(critical_section),
            "high": _count_review_items(major_section),
            "medium": _count_review_items(minor_section),
            "low": 0,
        },
        "critical_issues": _extract_bullets(critical_section)[:5],
        "report_file": str(report_path),
        "notes": "source=llm_adapter",
    }


def _save_review_metrics(
    project_root: Path, review_text: str, *, chapter_num: int, report_path: Path
) -> dict[str, Any]:
    try:
        from data_modules.index_manager import IndexManager, ReviewMetrics
    except ImportError:  # pragma: no cover
        from scripts.data_modules.index_manager import IndexManager, ReviewMetrics

    metrics_payload = _parse_review_metrics(
        review_text,
        chapter_num=chapter_num,
        report_path=Path(_relative_project_path(project_root, report_path)),
    )
    config = DataModulesConfig.from_project_root(project_root)
    manager = IndexManager(config)
    manager.save_review_metrics(ReviewMetrics(**metrics_payload))
    return metrics_payload


def _llm_call_log_path(project_root: Path) -> Path:
    return project_root / ".webnovel" / "logs" / "llm_calls.jsonl"


def _append_llm_call_log(
    project_root: Path,
    *,
    task: str,
    chapter: int,
    provider: str,
    model: str,
    latency_ms: int,
    success: bool,
    output_path: Optional[Path] = None,
    error_message: str = "",
) -> None:
    payload = {
        "ts": int(time.time()),
        "task": task,
        "chapter": int(chapter),
        "provider": provider,
        "model": model,
        "latency_ms": int(latency_ms),
        "success": bool(success),
        "error": str(error_message or "").strip(),
    }
    if output_path is not None:
        payload["output_path"] = _relative_project_path(project_root, output_path)

    # P1-5:取最近一次 LLM 调用的 usage 写入(token 数 + 估算成本)
    last_usage = _get_last_usage()
    if last_usage:
        payload["usage"] = {
            "prompt_tokens": int(last_usage.get("prompt_tokens") or 0),
            "completion_tokens": int(last_usage.get("completion_tokens") or 0),
            "total_tokens": int(last_usage.get("total_tokens") or 0),
        }
        # deepseek 价格(每百万 token,USD):chat $0.14/$0.28,reasoner $0.55/$2.19
        # 这里给个粗略估算,不准也行,够看趋势就行
        m = str(model or "").lower()
        if "reason" in m:
            cost = (payload["usage"]["prompt_tokens"] * 0.55 + payload["usage"]["completion_tokens"] * 2.19) / 1_000_000
        else:
            cost = (payload["usage"]["prompt_tokens"] * 0.14 + payload["usage"]["completion_tokens"] * 0.28) / 1_000_000
        payload["estimated_cost_usd"] = round(cost, 6)

    log_path = _llm_call_log_path(project_root)
    create_secure_directory(str(log_path.parent))
    # P3-3:简易 rotation,> 5MB 时归档为 llm_calls.jsonl.<ts>,从空文件重开
    try:
        if log_path.is_file() and log_path.stat().st_size > 5 * 1024 * 1024:
            archived = log_path.with_suffix(f".jsonl.{int(time.time())}")
            log_path.rename(archived)
    except Exception:
        pass
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _env_summary(config: DataModulesConfig, project_root: Path) -> dict[str, Any]:
    missing_fields = []
    if not str(config.llm_chat_model or "").strip():
        missing_fields.append("LLM_CHAT_MODEL")
    routes = _build_llm_routes(config, config.llm_chat_model)
    if not routes:
        if _is_deepseek_model(config.llm_chat_model):
            if not str(getattr(config, "deepseek_official_api_key", "") or "").strip():
                missing_fields.append("DEEPSEEK_API_KEY")
            if str(config.llm_base_url or "").strip():
                gateway_mode = _is_gateway_base_url(config.llm_base_url)
                if gateway_mode and not str(getattr(config, "llm_gateway_token", "") or "").strip():
                    missing_fields.append("API_GATEWAY_TOKEN")
                elif not gateway_mode and not (
                    str(config.llm_api_key or "").strip()
                    or (
                        _is_official_deepseek_base_url(config.llm_base_url)
                        and str(getattr(config, "deepseek_official_api_key", "") or "").strip()
                    )
                ):
                    missing_fields.append("LLM_API_KEY")
        else:
            if not str(config.llm_base_url or "").strip():
                missing_fields.append("LLM_BASE_URL")
            elif (
                _is_gateway_base_url(config.llm_base_url)
                and not str(getattr(config, "llm_gateway_token", "") or "").strip()
            ):
                missing_fields.append("API_GATEWAY_TOKEN")
            elif not _is_gateway_base_url(config.llm_base_url) and not str(config.llm_api_key or "").strip():
                missing_fields.append("LLM_API_KEY")
    return {
        "project_root": str(project_root),
        "llm_provider": config.llm_provider,
        "llm_base_url": config.llm_base_url,
        "llm_chat_model": config.llm_chat_model,
        "llm_reasoning_model": config.llm_reasoning_model,
        "llm_timeout": config.llm_timeout,
        "llm_api_key_present": bool(str(config.llm_api_key or "").strip()),
        "llm_gateway_token_present": bool(str(getattr(config, "llm_gateway_token", "") or "").strip()),
        "deepseek_official_base_url": str(getattr(config, "deepseek_official_base_url", "") or "").strip(),
        "deepseek_official_api_key_present": bool(str(getattr(config, "deepseek_official_api_key", "") or "").strip()),
        "llm_route_order": [f"{route['name']}:{route['base_url']}" for route in routes],
        "missing_fields": missing_fields,
        "legacy_deepseek_env_present": bool(
            str(config.deepseek_base_url or "").strip()
            or str(config.deepseek_model or "").strip()
            or str(config.deepseek_api_key or "").strip()
        ),
    }


def cmd_env_check(args: argparse.Namespace) -> int:
    project_root = find_project_root(Path(args.project_root)) if args.project_root else find_project_root()
    config = DataModulesConfig.from_project_root(project_root)
    payload = _env_summary(config, project_root)
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for key, value in payload.items():
            print(f"{key}: {value}")
        if payload["missing_fields"]:
            print("提示: 在书项目 .env、工作区 .env 或 ~/.codex/webnovel-writer/.env 里补齐上面的 LLM_*")
    return 0 if not payload["missing_fields"] else 1


def cmd_prompt(args: argparse.Namespace) -> int:
    project_root = find_project_root(Path(args.project_root)) if args.project_root else find_project_root()
    payload = build_chapter_context_payload(project_root, args.chapter)
    task = "draft" if args.task == "write" else args.task
    if task == "draft":
        _ensure_write_outline(payload, args.chapter)
        messages = _build_write_messages(
            payload,
            chapter_num=args.chapter,
            target_words=args.target_words,
            project_root=project_root,
        )
    else:
        chapter_path, chapter_text = _load_chapter_text(project_root, args.chapter, args.chapter_file)
        messages = _build_review_messages(payload, chapter_num=args.chapter, chapter_text=chapter_text)
        payload["chapter_file"] = str(chapter_path)

    out = {
        "project_root": str(project_root),
        "chapter": args.chapter,
        "task": task,
        "messages": messages,
        "context": payload,
    }
    if args.format == "json":
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        for idx, row in enumerate(messages, start=1):
            print(f"## Message {idx} [{row['role']}]")
            print(row["content"])
            print("")
    return 0


def cmd_draft(args: argparse.Namespace) -> int:
    project_root = find_project_root(Path(args.project_root)) if args.project_root else find_project_root()
    config = DataModulesConfig.from_project_root(project_root)
    payload = build_chapter_context_payload(project_root, args.chapter)
    _ensure_write_outline(payload, args.chapter)
    messages = _build_write_messages(
        payload,
        chapter_num=args.chapter,
        target_words=args.target_words,
        project_root=project_root,
    )
    model = args.model or config.llm_chat_model
    output_path: Optional[Path] = None
    started_at = time.time()
    success = False
    error_message = ""
    try:
        text = _call_llm(
            config,
            messages=messages,
            model=model,
            temperature=args.temperature if args.temperature is not None else config.llm_temperature,
            max_tokens=args.max_tokens if args.max_tokens is not None else config.llm_max_tokens,
        )

        if args.stdout_only:
            success = True
            print(text)
            return 0

        output_path = _chapter_output_path(
            project_root,
            args.chapter,
            output=args.output,
            use_volume_layout=bool(args.use_volume_layout),
        )
        previous_text = output_path.read_text(encoding="utf-8") if output_path.exists() else ""
        _write_text_file(output_path, text, overwrite=bool(args.overwrite))
        sync_info = _sync_written_chapter(
            project_root,
            args.chapter,
            output_path,
            text,
            outline_text=str(payload.get("outline") or ""),
            previous_text=previous_text,
        )

        # audit 失败自动 retry 一次(防 LLM 乱跑)
        audit_info = sync_info.get("audit") if isinstance(sync_info, dict) else None
        no_retry = bool(getattr(args, "no_audit_retry", False))
        if audit_info and audit_info.get("errors") and not no_retry:
            error_msgs = [
                f"- {issue.get('msg', '')}" for issue in audit_info.get("issues", []) if issue.get("level") == "error"
            ]
            print(
                f"⚠️ ch{args.chapter:04d} audit FAIL,自动 retry 一次。问题:\n" + "\n".join(error_msgs),
                file=sys.stderr,
            )
            retry_messages = list(messages)
            retry_messages.append(
                {
                    "role": "user",
                    "content": (
                        "上一版生成命中以下硬约束错误,请基于同样大纲重写本章,严格避开这些问题:\n"
                        + "\n".join(error_msgs)
                        + "\n\n直接输出修正后的正文,不要解释。"
                    ),
                }
            )
            retry_text = _call_llm(
                config,
                messages=retry_messages,
                model=model,
                temperature=(args.temperature if args.temperature is not None else config.llm_temperature),
                max_tokens=args.max_tokens if args.max_tokens is not None else config.llm_max_tokens,
            )
            _write_text_file(output_path, retry_text, overwrite=True)
            sync_info = _sync_written_chapter(
                project_root,
                args.chapter,
                output_path,
                retry_text,
                outline_text=str(payload.get("outline") or ""),
                previous_text=text,
            )
            audit_info_2 = sync_info.get("audit") if isinstance(sync_info, dict) else None
            if audit_info_2 and audit_info_2.get("errors"):
                print(
                    f"⚠️ ch{args.chapter:04d} retry 后仍有 {audit_info_2['errors']} 个 errors,需手工检查",
                    file=sys.stderr,
                )
            else:
                print(f"✓ ch{args.chapter:04d} retry 成功", file=sys.stderr)

        success = True
        print(output_path)
        print(f"summary_file: {sync_info['summary_path']}")
        print(f"progress: ch={sync_info['current_chapter']} words={sync_info['total_words']}")
        return 0
    except Exception as exc:
        error_message = str(exc)
        raise
    finally:
        _append_llm_call_log(
            project_root,
            task="draft",
            chapter=args.chapter,
            provider=config.llm_provider,
            model=model,
            latency_ms=int((time.time() - started_at) * 1000),
            success=success,
            output_path=output_path,
            error_message=error_message,
        )


def _chapter_numbers_from_args(args: argparse.Namespace) -> list[int]:
    start = int(getattr(args, "from_chapter", 0) or 0)
    end = int(getattr(args, "to_chapter", 0) or 0)
    if not start or not end or end < start:
        raise ValueError("--from-chapter 和 --to-chapter 必须组成有效区间")
    return list(range(start, end + 1))


def _preflight_batch_outputs(
    project_root: Path,
    chapter_numbers: list[int],
    *,
    overwrite: bool,
    use_volume_layout: bool,
) -> dict[int, Path]:
    output_paths: dict[int, Path] = {}
    conflicts: list[str] = []
    for chapter_num in chapter_numbers:
        output_path = _chapter_output_path(
            project_root,
            chapter_num,
            output=None,
            use_volume_layout=use_volume_layout,
        )
        if output_path.exists() and not overwrite:
            conflicts.append(str(output_path))
        output_paths[chapter_num] = output_path
    if conflicts:
        joined = "\n".join(conflicts)
        raise FileExistsError(f"批量写作发现已存在正文文件，请加 --overwrite 或先处理：\n{joined}")
    return output_paths


def cmd_batch_draft(args: argparse.Namespace) -> int:
    project_root = find_project_root(Path(args.project_root)) if args.project_root else find_project_root()
    config = DataModulesConfig.from_project_root(project_root)
    model = args.model or config.llm_chat_model
    temperature = args.temperature if args.temperature is not None else config.llm_temperature
    max_tokens = args.max_tokens if args.max_tokens is not None else config.llm_max_tokens
    chapter_numbers = _chapter_numbers_from_args(args)

    summary = _env_summary(config, project_root)
    missing_fields = summary.get("missing_fields") or []
    if missing_fields:
        raise RuntimeError("LLM 配置缺失，批量写作未启动: " + ", ".join(missing_fields))

    output_paths = _preflight_batch_outputs(
        project_root,
        chapter_numbers,
        overwrite=bool(args.overwrite),
        use_volume_layout=bool(args.use_volume_layout),
    )

    payloads: dict[int, dict[str, Any]] = {}
    messages_by_chapter: dict[int, list[dict[str, str]]] = {}
    for chapter_num in chapter_numbers:
        payload = build_chapter_context_payload(project_root, chapter_num)
        _ensure_write_outline(payload, chapter_num)
        payloads[chapter_num] = payload
        messages_by_chapter[chapter_num] = _build_write_messages(
            payload,
            chapter_num=chapter_num,
            target_words=args.target_words,
            project_root=project_root,
        )

    if args.resume_dir:
        temp_dir = Path(args.resume_dir).expanduser().resolve()
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        temp_dir = (
            project_root / ".webnovel" / "tmp" / f"batch_draft_{chapter_numbers[0]}_{chapter_numbers[-1]}_{timestamp}"
        )
    create_secure_directory(str(temp_dir))

    # P1-6:并发跑 draft,默认 1(串行),用户可 --parallel N 提速
    parallel = max(1, int(getattr(args, "parallel", 1) or 1))
    skip_on_error = bool(getattr(args, "skip_on_error", False))
    generated: dict[int, Path] = {}
    failed: dict[int, str] = {}
    pending: list[int] = []
    for chapter_num in chapter_numbers:
        temp_path = temp_dir / f"ch{chapter_num:04d}.md"
        if temp_path.exists() and temp_path.read_text(encoding="utf-8").strip():
            generated[chapter_num] = temp_path
            print(f"reuse: ch={chapter_num} temp={temp_path}", flush=True)
        else:
            pending.append(chapter_num)

    def _draft_one(ch: int) -> tuple[int, Path | None, str]:
        temp_path = temp_dir / f"ch{ch:04d}.md"
        output_path = output_paths[ch]
        started_at = time.time()
        success = False
        error_message = ""
        try:
            text = _call_llm(
                config,
                messages=messages_by_chapter[ch],
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            _write_text_file(temp_path, text, overwrite=True)
            success = True
            return ch, temp_path, ""
        except Exception as exc:
            error_message = str(exc)
            return ch, None, error_message
        finally:
            _append_llm_call_log(
                project_root,
                task="batch-draft",
                chapter=ch,
                provider=config.llm_provider,
                model=model,
                latency_ms=int((time.time() - started_at) * 1000),
                success=success,
                output_path=output_path,
                error_message=error_message,
            )

    if parallel > 1 and pending:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        print(f"batch parallel={parallel} pending={len(pending)}", flush=True)
        with ThreadPoolExecutor(max_workers=parallel) as pool:
            futures = {pool.submit(_draft_one, ch): ch for ch in pending}
            for fut in as_completed(futures):
                ch, temp_path, err = fut.result()
                if err:
                    failed[ch] = err
                    print(f"FAILED: ch={ch} err={err[:120]}", flush=True)
                    if not skip_on_error:
                        # 取消未完成,然后抛
                        for f in futures:
                            f.cancel()
                        raise RuntimeError(f"batch-draft ch={ch} 失败:{err}")
                else:
                    generated[ch] = temp_path
                    print(f"drafted: ch={ch} temp={temp_path}", flush=True)
    else:
        for ch in pending:
            ch_, temp_path, err = _draft_one(ch)
            if err:
                failed[ch_] = err
                print(f"FAILED: ch={ch_} err={err[:120]}", flush=True)
                if not skip_on_error:
                    raise RuntimeError(f"batch-draft ch={ch_} 失败:{err}")
            else:
                generated[ch_] = temp_path
                print(f"drafted: ch={ch_} temp={temp_path}", flush=True)

    # commit + sync 都只对 generated 里的章节做(失败章跳过)
    for chapter_num in chapter_numbers:
        if chapter_num not in generated:
            continue
        output_path = output_paths[chapter_num]
        text = generated[chapter_num].read_text(encoding="utf-8")
        _write_text_file(output_path, text, overwrite=True)
        print(f"committed: ch={chapter_num} file={output_path}", flush=True)

    if args.no_sync:
        if failed:
            print(f"⚠️ batch 完成,失败 {len(failed)} 章: {sorted(failed.keys())}", file=sys.stderr)
        return 0

    for chapter_num in chapter_numbers:
        if chapter_num not in generated:
            continue
        output_path = output_paths[chapter_num]
        chapter_text = output_path.read_text(encoding="utf-8")
        try:
            outline_text = load_chapter_outline(project_root, chapter_num, max_chars=None)
        except Exception:
            outline_text = ""
        sync_info = _sync_written_chapter(
            project_root,
            chapter_num,
            output_path,
            chapter_text,
            outline_text=outline_text,
            previous_text=chapter_text,
            rewrite_summary=True,
        )
        print(
            f"synced: ch={chapter_num} summary={sync_info['summary_path']} "
            f"progress={sync_info['current_chapter']}/{sync_info['total_words']}",
            flush=True,
        )

    if failed:
        print(f"⚠️ batch 完成,失败 {len(failed)} 章: {sorted(failed.keys())}", file=sys.stderr)

    if args.health_report:
        status_script = Path(__file__).resolve().parent / "status_reporter.py"
        subprocess.run(
            [
                sys.executable,
                str(status_script),
                "--project-root",
                str(project_root),
                "--output",
                ".webnovel/health_report.md",
            ],
            check=True,
        )

    return 0


def cmd_review(args: argparse.Namespace) -> int:
    project_root = find_project_root(Path(args.project_root)) if args.project_root else find_project_root()
    config = DataModulesConfig.from_project_root(project_root)
    payload = build_chapter_context_payload(project_root, args.chapter)
    chapter_path, chapter_text = _load_chapter_text(project_root, args.chapter, args.chapter_file)
    messages = _build_review_messages(payload, chapter_num=args.chapter, chapter_text=chapter_text)
    model = args.model or config.llm_reasoning_model or config.llm_chat_model
    output_path: Optional[Path] = None
    started_at = time.time()
    success = False
    error_message = ""
    try:
        text = _call_llm(
            config,
            messages=messages,
            model=model,
            temperature=args.temperature if args.temperature is not None else config.llm_review_temperature,
            max_tokens=args.max_tokens if args.max_tokens is not None else config.llm_max_tokens,
        )

        if args.stdout_only:
            success = True
            print(text)
            return 0

        output_path = (
            Path(args.output).expanduser().resolve()
            if args.output
            else _default_review_path(project_root, args.chapter)
        )
        _write_text_file(output_path, text, overwrite=bool(args.overwrite))
        metrics = _save_review_metrics(project_root, text, chapter_num=args.chapter, report_path=output_path)
        if not args.skip_state_record:
            _record_review_checkpoint(project_root, args.chapter, output_path)
        success = True
        print(output_path)
        print(f"chapter_file: {chapter_path}")
        print(f"review_score: {metrics['overall_score']}")
        return 0
    except Exception as exc:
        error_message = str(exc)
        raise
    finally:
        _append_llm_call_log(
            project_root,
            task="review",
            chapter=args.chapter,
            provider=config.llm_provider,
            model=model,
            latency_ms=int((time.time() - started_at) * 1000),
            success=success,
            output_path=output_path,
            error_message=error_message,
        )


def cmd_sync(args: argparse.Namespace) -> int:
    project_root = find_project_root(Path(args.project_root)) if args.project_root else find_project_root()
    collected = _collect_chapter_files(project_root)
    chapter_map = {chapter: path for chapter, path in collected}

    if args.chapter is not None:
        chapter_numbers = [args.chapter]
    else:
        start = args.from_chapter or (collected[0][0] if collected else 0)
        end = args.to_chapter or (collected[-1][0] if collected else 0)
        chapter_numbers = list(range(start, end + 1)) if start and end and end >= start else []

    if not chapter_numbers:
        raise RuntimeError("未找到可同步的章节文件")

    _record_progress(project_root, 0, 0)
    synced = 0
    for chapter_num in chapter_numbers:
        chapter_path = chapter_map.get(chapter_num)
        if chapter_path is None or not chapter_path.exists():
            if args.skip_missing:
                print(f"skip_missing: ch={chapter_num}")
                continue
            raise FileNotFoundError(f"未找到第 {chapter_num} 章正文文件")
        chapter_text = chapter_path.read_text(encoding="utf-8")
        outline_text = ""
        try:
            outline_text = load_chapter_outline(project_root, chapter_num, max_chars=None)
        except Exception:
            outline_text = ""
        summary_path = _summary_path(project_root, chapter_num)
        summary_override = summary_path.read_text(encoding="utf-8") if summary_path.exists() else ""
        sync_info = _sync_written_chapter(
            project_root,
            chapter_num,
            chapter_path,
            chapter_text,
            outline_text=outline_text,
            previous_text=chapter_text,
            summary_override=summary_override,
            rewrite_summary=bool(args.rewrite_summary),
        )
        synced += 1
        print(
            f"sync: ch={chapter_num} file={chapter_path} "
            f"summary={sync_info['summary_path']} progress={sync_info['current_chapter']}/{sync_info['total_words']}"
        )

    return 0 if synced else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Codex LLM adapter for webnovel-writer")
    parser.add_argument("--project-root", type=str, help="项目根目录")

    sub = parser.add_subparsers(dest="command", required=True)

    p_env = sub.add_parser("env-check", help="检查 LLM 配置")
    p_env.add_argument("--format", choices=["text", "json"], default="text")
    p_env.set_defaults(func=cmd_env_check)

    p_prompt = sub.add_parser("prompt", help="打印发给 LLM 的 prompt")
    p_prompt.add_argument("--chapter", type=int, required=True, help="章节号")
    p_prompt.add_argument("--task", choices=["draft", "review", "write"], default="draft")
    p_prompt.add_argument("--chapter-file", type=str, help="审稿时显式指定章节文件")
    p_prompt.add_argument("--target-words", type=int, default=2200, help="写作目标字数")
    p_prompt.add_argument("--format", choices=["text", "json"], default="text")
    p_prompt.set_defaults(func=cmd_prompt)

    p_draft = sub.add_parser("draft", help="调用 LLM 生成章节初稿")
    p_draft.add_argument("--chapter", type=int, required=True, help="章节号")
    p_draft.add_argument("--output", type=str, help="输出文件路径")
    p_draft.add_argument("--model", type=str, help="覆盖 LLM_CHAT_MODEL")
    p_draft.add_argument("--target-words", type=int, default=2200, help="写作目标字数")
    p_draft.add_argument("--temperature", type=float, help="覆盖 LLM_TEMPERATURE")
    p_draft.add_argument("--max-tokens", type=int, help="覆盖 LLM_MAX_TOKENS")
    p_draft.add_argument("--overwrite", action="store_true", help="允许覆盖现有文件")
    p_draft.add_argument("--stdout-only", action="store_true", help="只打印，不落文件")
    p_draft.add_argument("--use-volume-layout", action="store_true", help="输出到 正文/第N卷/第NNN章*.md")
    p_draft.add_argument("--no-audit-retry", action="store_true", help="audit 失败时不自动 retry")
    p_draft.set_defaults(func=cmd_draft)

    p_write = sub.add_parser("write", help="兼容旧命令，等同于 draft")
    p_write.add_argument("--chapter", type=int, required=True, help="章节号")
    p_write.add_argument("--output", type=str, help="输出文件路径")
    p_write.add_argument("--model", type=str, help="覆盖 LLM_CHAT_MODEL")
    p_write.add_argument("--target-words", type=int, default=2200, help="写作目标字数")
    p_write.add_argument("--temperature", type=float, help="覆盖 LLM_TEMPERATURE")
    p_write.add_argument("--max-tokens", type=int, help="覆盖 LLM_MAX_TOKENS")
    p_write.add_argument("--overwrite", action="store_true", help="允许覆盖现有文件")
    p_write.add_argument("--stdout-only", action="store_true", help="只打印，不落文件")
    p_write.add_argument("--use-volume-layout", action="store_true", help="输出到 正文/第N卷/第NNN章*.md")
    p_write.set_defaults(func=cmd_draft)

    p_batch = sub.add_parser("batch-draft", help="批量调用 LLM 生成章节，全部成功后再写入正稿")
    p_batch.add_argument("--from-chapter", type=int, required=True, help="起始章节号")
    p_batch.add_argument("--to-chapter", type=int, required=True, help="结束章节号")
    p_batch.add_argument("--model", type=str, help="覆盖 LLM_CHAT_MODEL")
    p_batch.add_argument("--target-words", type=int, default=4500, help="单章目标字数")
    p_batch.add_argument("--temperature", type=float, help="覆盖 LLM_TEMPERATURE")
    p_batch.add_argument("--max-tokens", type=int, help="覆盖 LLM_MAX_TOKENS")
    p_batch.add_argument("--overwrite", action="store_true", help="允许覆盖现有正文")
    p_batch.add_argument("--use-volume-layout", action="store_true", help="输出到 正文/第N卷/第NNN章*.md")
    p_batch.add_argument("--resume-dir", type=str, help="复用已有 batch_draft 临时目录")
    p_batch.add_argument("--no-sync", action="store_true", help="只写正文，不同步摘要和状态")
    p_batch.add_argument("--health-report", action="store_true", help="批量同步后刷新健康报告")
    p_batch.add_argument("--parallel", type=int, default=1, help="并发数,默认 1(串行);建议 2-4 兼顾速度和限速")
    p_batch.add_argument("--skip-on-error", action="store_true", help="单章失败不中断,跳过继续")
    p_batch.set_defaults(func=cmd_batch_draft)

    p_review = sub.add_parser("review", help="调用 LLM 生成章节审查报告")
    p_review.add_argument("--chapter", type=int, required=True, help="章节号")
    p_review.add_argument("--chapter-file", type=str, help="显式指定章节文件")
    p_review.add_argument("--output", type=str, help="输出文件路径")
    p_review.add_argument("--model", type=str, help="覆盖 LLM_REASONING_MODEL")
    p_review.add_argument("--temperature", type=float, help="覆盖 LLM_REVIEW_TEMPERATURE")
    p_review.add_argument("--max-tokens", type=int, help="覆盖 LLM_MAX_TOKENS")
    p_review.add_argument("--overwrite", action="store_true", help="允许覆盖现有文件")
    p_review.add_argument("--stdout-only", action="store_true", help="只打印，不落文件")
    p_review.add_argument("--skip-state-record", action="store_true", help="只生成报告，不写 review_checkpoints")
    p_review.set_defaults(func=cmd_review)

    p_sync = sub.add_parser("sync", help="重算现有章节的状态追踪和索引")
    p_sync.add_argument("--chapter", type=int, help="只同步单章")
    p_sync.add_argument("--from-chapter", type=int, help="起始章节")
    p_sync.add_argument("--to-chapter", type=int, help="结束章节")
    p_sync.add_argument("--rewrite-summary", action="store_true", help="按当前正文重写摘要文件")
    p_sync.add_argument("--skip-missing", action="store_true", help="范围内缺章时跳过")
    p_sync.set_defaults(func=cmd_sync)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    code = int(args.func(args) or 0)
    raise SystemExit(code)


if __name__ == "__main__":
    enable_windows_utf8_stdio(skip_in_pytest=True)
    main()
