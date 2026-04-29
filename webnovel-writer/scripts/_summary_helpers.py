"""
_summary_helpers.py — 摘要 / 改稿 pipeline 的公共工具

把 build_segment_summaries / build_volume_summaries / build_book_main /
revise_chapter 里反复出现的小工具抽到这里。新代码统一从这里导入,
旧代码逐步迁移。

不要把"领域逻辑"放这里(段摘要怎么挑章/卷摘要怎么排版),只放和领
域无关的工具函数。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


# 6 个脚本都要 sys.path.insert(0, scripts_dir),抽这里
def ensure_scripts_path() -> None:
    """确保 scripts/ 在 sys.path 里,这样 from llm_adapter 等导入能成功。

    替代各文件顶部的:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
    """
    scripts_dir = str(Path(__file__).resolve().parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)


def strip_code_fence(text: str) -> str:
    """剥掉 LLM 输出里包裹的 markdown code fence。

    LLM 偶尔会把 JSON / 章节正文用 ```json ... ``` 或 ``` ... ``` 包起来,
    要剥掉才能解析。

    替代各文件里反复出现的:
        if text.startswith("```"):
            lines = text.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()
    """
    text = (text or "").strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


_CN_RE = re.compile(r"[一-鿿]")


def cn_char_count(text: str) -> int:
    """汉字字数(基本+扩展 A 区,不含标点和换行)。

    revise_chapter.py 里的 _cn_chars,大多数地方需要它。
    """
    if not text:
        return 0
    return len(_CN_RE.findall(text))


def parse_chapter_num(filename: str) -> int | None:
    """从 `第NNNN章...` 文件名抽章号。返回 None 表示不匹配。"""
    m = re.match(r"第(\d+)章", filename)
    return int(m.group(1)) if m else None


__all__ = [
    "ensure_scripts_path",
    "strip_code_fence",
    "cn_char_count",
    "parse_chapter_num",
]
