"""通知域：spool 协议、展示模型、投递与历史。

这一层**不 import Qt**：`--status`、`--selftest` 与纯逻辑测试都要能在无图形环境跑
（AGENTS.md 硬约束 2）。需要弹系统通知时才由 `dsh_tray/ui/` 与
`dsh_tray/platform/` 接手。

分工（AGENTS.md 硬约束 5）：
- 插件是唯一策略点——它决定哪些事件值得通知、文案是什么；
- 托盘是唯一投递点——它读 spool、去重、投递、存历史、处理点击。

因此本包只做「读进来、看懂、存下来」，不判断 DSH 事件该不该通知。
"""

from __future__ import annotations

__all__ = ["DEFAULT_POLL_INTERVAL_MS", "SPOOL_FILENAME"]

# 托盘 tail spool 的默认间隔。取 500 ms 的理由：人在看到通知前的容忍延迟约 1 s，
# 而 500 ms 让最坏情况仍落在 1 s 内；再快只是空转读文件（每次读 0 字节也有 syscall 成本）。
DEFAULT_POLL_INTERVAL_MS = 500

# spool 文件名，与插件侧 `plugin/src/spool.ts` 的常量必须一致（契约 C1）。
SPOOL_FILENAME = "events.jsonl"
