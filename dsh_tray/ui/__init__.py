"""托盘面板包。

本文件**刻意不 import PyQt6**：`dsh_tray/ui/__init__.py` 会被 `dsh-tray.py` 在
解析命令行参数时间接导入，而 `--status`/`--start`/`--stop`/`--selftest` 必须在
没有 DISPLAY 的机器上也能跑（AGENTS.md 硬约束 2）。真正需要 Qt 的子模块各自在
模块顶层 import，调用方按需 `from .panel import ...`。
"""

from __future__ import annotations

__all__ = ["panel", "control", "notiflist", "working", "overview"]
