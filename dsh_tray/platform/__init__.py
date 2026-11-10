"""平台层入口：按 `sys.platform` 分派到具体实现。

**本包是唯一允许出现平台分支的地方**（AGENTS.md 硬约束 3）。其余模块只从这里取
工厂函数，不写 `if sys.platform`。

设计取舍：分派写成「惰性取实现」而不是在导入期就 `import` 平台模块。理由有两个：
一是 Linux 实现在导入期会碰 D-Bus 与 `/proc`，而 `--status` 这类命令不该因此失败；
二是测试要能注入假后端，导入期定死实现会让这件事变难。
"""

from __future__ import annotations

import sys

from .base import (
    URGENCY_CRITICAL,
    URGENCY_LOW,
    URGENCY_NORMAL,
    NotificationBackend,
    PanelPlacement,
    ProcessSample,
    ProcessSampler,
    WindowAnchor,
)

__all__ = [
    "URGENCY_CRITICAL",
    "URGENCY_LOW",
    "URGENCY_NORMAL",
    "NotificationBackend",
    "PanelPlacement",
    "ProcessSample",
    "ProcessSampler",
    "WindowAnchor",
    "create_action_listener",
    "create_backend",
    "create_anchor",
    "create_placement",
    "create_sampler",
    "current_platform",
]


def current_platform() -> str:
    """归一化后的平台名：`linux` / `windows` / `darwin`。

    @returns 平台标识；未知平台原样返回 `sys.platform`
    """
    if sys.platform.startswith("linux"):
        return "linux"
    if sys.platform in {"win32", "cygwin"}:
        return "windows"
    if sys.platform == "darwin":
        return "darwin"
    return sys.platform


def _unsupported(what: str) -> NotImplementedError:
    """构造「本平台尚未实现」的错误。

    macOS 只留接口不实现（用户已确认的范围）；Windows 在 S3 多平台规格里落地。
    错误信息要给出下一步，而不是只说失败（AGENTS.md 错误处理约定）。
    """
    return NotImplementedError(
        f"{current_platform()} 上的{what}尚未实现：多平台规格交付（S3）。"
        "Linux 已可用；Windows/macOS 的实现与验证步骤见 docs/design.md。"
    )


def create_backend() -> NotificationBackend:
    """创建当前平台的系统通知后端。

    @returns 通知后端实例
    @throws NotImplementedError - 当前平台未实现时
    """
    platform = current_platform()
    if platform == "linux":
        from .linux import LinuxNotificationBackend

        return LinuxNotificationBackend()
    raise _unsupported("通知投递")


def create_anchor() -> WindowAnchor:
    """创建当前平台的面板锚点计算器。

    @returns 锚点实例
    @throws NotImplementedError - 当前平台未实现时
    """
    platform = current_platform()
    if platform == "linux":
        from .linux import LinuxWindowAnchor

        return LinuxWindowAnchor()
    raise _unsupported("面板锚点")


def create_sampler() -> ProcessSampler:
    """创建当前平台的进程采样器。

    @returns 采样器实例
    @throws NotImplementedError - 当前平台未实现时
    """
    platform = current_platform()
    if platform == "linux":
        from .linux import LinuxProcessSampler

        return LinuxProcessSampler()
    raise _unsupported("进程采样")


def create_placement() -> PanelPlacement:
    """创建当前平台的面板定位器。

    @returns 定位器实例
    @throws NotImplementedError - 当前平台未实现时
    """
    platform = current_platform()
    if platform == "linux":
        from .linux import LinuxPanelPlacement

        return LinuxPanelPlacement()
    raise _unsupported("面板定位")


def create_action_listener(on_action: object) -> object:
    """创建当前平台的通知点击监听器。

    @param on_action - 回调：(通知 id, 动作键)
    @returns 监听器实例
    @throws NotImplementedError - 当前平台未实现时
    """
    platform = current_platform()
    if platform == "linux":
        from .linux import LinuxActionListener

        return LinuxActionListener(on_action)  # type: ignore[arg-type]
    raise _unsupported("通知点击监听")
