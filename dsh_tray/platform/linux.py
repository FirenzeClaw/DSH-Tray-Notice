"""Linux 平台实现：通知投递、面板锚点、进程采样。

三块都依赖本机实测过的行为，注释里保留了实测结论，改动前先读理由：

- **投递**：`notify-send --action` 报 `Actions are not supported by this notifications
  server`，而 `GetCapabilities` 明确含 `actions`，`gdbus` 显式类型调用成功返回
  `uint32 155`。所以走 gdbus。
- **锚点**：`QSystemTrayIcon.geometry()` 在 Plasma Wayland 返回 0×0，只能退化到
  屏幕右上角；X11 下能拿到真实矩形。
- **采样**：只读 `/proc`，不 fork 外部命令（AGENTS.md 硬约束 4）。
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Callable, Sequence

from ..probe import child_pids, read_cmdline
from ..notify.delivery import DeliveryResult, deliver


@dataclass(frozen=True, slots=True)
class LinuxSample:
    """一个进程的瞬时状态。"""

    pid: int
    role: str
    label: str
    cpu_percent: float | None
    rss_bytes: int
    age_seconds: int | None


def _read_stat(pid: int) -> tuple[float, float] | None:
    """读 `/proc/<pid>/stat` 里的 utime+stime 与 starttime。

    @param pid - 进程号
    @returns (总 CPU 秒数, 启动时刻的 jiffies)；读不到时 None
    """
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8", errors="replace") as handle:
            raw = handle.read()
    except OSError:
        return None
    # comm 字段可能含空格与括号，从最后一个 ')' 之后切分才安全。
    tail = raw[raw.rfind(")") + 2 :].split()
    if len(tail) < 22:
        return None
    try:
        ticks = float(tail[11]) + float(tail[12])
        starttime = float(tail[19])
    except (ValueError, IndexError):
        return None
    return ticks, starttime


def _read_rss_bytes(pid: int) -> int:
    """读 VmRSS。

    @param pid - 进程号
    @returns 字节数；读不到时 0
    """
    try:
        with open(f"/proc/{pid}/status", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        return 0
    return 0


def _classify(pid: int) -> tuple[str, str]:
    """判定进程角色与可读标签。

    @param pid - 进程号
    @returns (role, label)
    """
    cmdline = read_cmdline(pid)
    joined = " ".join(cmdline)
    if "dsh" in joined and "web" in joined:
        return "core", "dsh web"
    if "mcp" in joined.lower():
        name = os.path.basename(cmdline[0]) if cmdline else "mcp"
        return "mcp", name
    if cmdline:
        return "tool", os.path.basename(cmdline[0])
    return "other", f"pid {pid}"


class LinuxNotificationBackend:
    """基于 D-Bus 的系统通知后端。"""

    def is_available(self) -> bool:
        """后端是否可用。

        @returns gdbus 或 notify-send 任一存在即视为可用
        """
        from shutil import which

        return which("gdbus") is not None or which("notify-send") is not None

    def deliver(self, entry: dict[str, object]) -> DeliveryResult:
        """投递一条通知。

        @param entry - 条目字典（字段名与 spool 一致）
        @returns 投递结果
        """
        return deliver(entry)


class LinuxWindowAnchor:
    """面板锚点。

    优先用托盘图标矩形（X11 可用），拿不到就退化到屏幕右上角。Wayland 下
    `geometry()` 返回 0×0 是常态，不是异常。
    """

    def __init__(self, margin: int = 8) -> None:
        """构造。

        @param margin - 面板与屏幕边缘的间距
        """
        self._margin = margin

    def anchor_for(self, tray_geometry: tuple[int, int, int, int] | None, screen) -> tuple[int, int]:
        """计算面板左上角坐标。

        @param tray_geometry - 托盘图标矩形；无效时传 None
        @param screen - 有 `availableGeometry()` 的对象（QRect）
        @returns (x, y)
        """
        if tray_geometry is not None:
            x, y, width, height = tray_geometry
            if width > 0 and height > 0:
                return x + width, y + height

        rect = screen.availableGeometry()
        return rect.right() - self._margin, rect.top() + self._margin


class LinuxProcessSampler:
    """基于 `/proc` 的进程采样器。"""

    def __init__(self, clock_ticks: int | None = None) -> None:
        """构造。

        @param clock_ticks - 每秒的 jiffies；缺省读 `os.sysconf`
        """
        self._ticks = clock_ticks or os.sysconf("SC_CLK_TCK")
        self._previous: dict[int, tuple[float, float]] = {}
        self._previous_at: float | None = None

    def sample(self, root_pid: int | None) -> Sequence[LinuxSample]:
        """采一次样。

        首次采样 CPU 为 None（没有上一次读数可比），这是刻意的：显示 0% 会让用户
        以为进程真的闲着。

        @param root_pid - DSH 主进程号；None 时只返回空列表
        @returns 采样结果
        """
        if root_pid is None:
            return []
        now = time.monotonic()
        elapsed = None if self._previous_at is None else now - self._previous_at

        samples: list[LinuxSample] = []
        for pid in [root_pid, *child_pids(root_pid)]:
            stat = _read_stat(pid)
            if stat is None:
                continue
            ticks, starttime = stat
            previous = self._previous.get(pid)
            cpu: float | None = None
            if previous is not None and elapsed is not None and elapsed > 0:
                delta = ticks - previous[0]
                cpu = max(0.0, delta / self._ticks / elapsed * 100.0)
            age = None
            try:
                uptime = float(open("/proc/uptime", encoding="utf-8").read().split()[0])
                age = int(uptime - starttime / self._ticks)
            except (OSError, ValueError, IndexError):
                age = None
            role, label = _classify(pid)
            samples.append(
                LinuxSample(
                    pid=pid,
                    role=role,
                    label=label,
                    cpu_percent=cpu,
                    rss_bytes=_read_rss_bytes(pid),
                    age_seconds=age,
                )
            )

        self._previous = {
            sample.pid: _read_stat(sample.pid) or (0.0, 0.0) for sample in samples
        }
        self._previous_at = now
        return samples

class LinuxActionListener:
    """订阅桌面通知的点击回执。

    实测结论（本机 Plasma 6.6.6 / Wayland）：
    - QtDBus 的**自动类型推断对 `Notify` 不可用**（把 `uint32` 推成 `int`、`as` 推成
      `av`），所以投递走 `gdbus`；
    - 但 `QDBusConnection.connect(..., "ActionInvoked", slot)` 是可行的，前提是 slot
      必须是 `@pyqtSlot("uint", "QString")` 修饰的 QObject 方法——不加装饰器时
      Qt 会把它当普通 Python 方法，签名匹配不上，回调永远不触发。

    本类因此只负责**接收**，不负责投递。
    """

    #: 动作键白名单：`default` 是点通知本体，`open` 是历史版本里的别名。
    ACCEPTED_KEYS = frozenset({"default", "open"})

    def __init__(
        self,
        on_action: Callable[[int, str], None],
        service_filter: str = "org.freedesktop.Notifications",
    ) -> None:
        """构造。

        @param on_action - 回调：(通知 id, 动作键)
        @param service_filter - 只接收来自该服务的信号；空串表示不限发送方。
            生产环境必须是通知守护进程的名字——否则任何进程都能伪造点击；
            测试时传空串，才能用 `gdbus emit` 从另一条连接模拟信号。
        """
        self._callback = on_action
        self._service_filter = service_filter
        self._connected = False
        self._receiver: QObject | None = None

    def start(self) -> bool:
        """建立订阅。

        需要 QApplication 已创建；在无图形环境调用会返回 False 而不是抛错。

        @returns 是否订阅成功
        """
        try:
            from PyQt6.QtCore import QObject, pyqtSlot
            from PyQt6.QtDBus import QDBusConnection
        except ImportError:
            return False

        callback = self._callback
        accepted = self.ACCEPTED_KEYS

        class _Receiver(QObject):
            """必须继承 QObject 才能暴露 D-Bus 槽。"""

            @pyqtSlot("uint", "QString")
            def on_action(self, notification_id: int, action_key: str) -> None:
                """D-Bus 回调入口。

                @param notification_id - 桌面分配的通知 id
                @param action_key - 动作键
                """
                if action_key in accepted:
                    callback(int(notification_id), action_key)

        receiver = _Receiver()
        bus = QDBusConnection.sessionBus()
        if not bus.isConnected():
            return False
        # PyQt6 的 connect 是 5 参数形式：直接传绑定方法（PyQt 会读取
        # @pyqtSlot 的签名）。PyQt5 那种 (receiver, "method") 六参数写法在这里
        # 会报 "too many arguments"。
        connected = bus.connect(
            self._service_filter,
            "/org/freedesktop/Notifications",
            "org.freedesktop.Notifications",
            "ActionInvoked",
            receiver.on_action,
        )
        if connected:
            self._receiver = receiver
            self._connected = True
        return connected

    def stop(self) -> None:
        """断开订阅。"""
        if self._receiver is None:
            return
        try:
            from PyQt6.QtDBus import QDBusConnection

            QDBusConnection.sessionBus().disconnect(
                self._service_filter,
                "/org/freedesktop/Notifications",
                "org.freedesktop.Notifications",
                "ActionInvoked",
                self._receiver.on_action,
            )
        except Exception:  # noqa: BLE001 - 断开失败不该影响退出
            pass
        self._receiver = None
        self._connected = False

    @property
    def connected(self) -> bool:
        """是否已订阅。"""
        return self._connected
