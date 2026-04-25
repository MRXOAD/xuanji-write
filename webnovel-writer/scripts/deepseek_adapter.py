#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
兼容入口。

旧命令 `webnovel.py deepseek ...` 继续可用，实际转发到通用 `llm_adapter.py`。
"""

from __future__ import annotations

from llm_adapter import *  # noqa: F401,F403
from llm_adapter import main


if __name__ == "__main__":
    main()
