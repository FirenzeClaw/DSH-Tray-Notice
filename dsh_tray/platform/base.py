"""平台层接口定义。

三件事按平台差异抽象：系统通知投递、面板锚点、进程采样。三者都用 `Protocol`
而非基类——实现方不需要继承，鸭子类型即可，测试里传假对象也不必先继承一层。

平台分支只允许出现在本包内（AGENTS.md 硬约束 3）；其余模块只认这三个协议。

签名以 `contracts/contracts.md` 的 C3 为准：`deliver(entry)` 接收一条条目字典，
而不是拆成 title/body 一堆参数——托盘侧本来就有完整条目，拆开只会让两处各维护
一份字段映射。
"""

from __future__ import annotations

from typing import Callable, Protocol, Sequence

# 通知紧急度。与 freedesktop 的 urgency 一一对应：0=low 1=normal 2=critical。
URGENCY_LOW = 0
URGENCY_NORMAL = 1
URGENCY_CRITICAL = 2


class NotificationBackend(Protocol):
    """系统通知后端。

    实现方负责把一条已经决定要投递的通知送到桌面。**不负责**去重、策略、历史——
    那些在 `dsh_tray/notify/`。
    """

    def is_available(self) -> bool:
        """后端是否可用（例如 D-Bus 会话总线能否连上）。

        @returns 可用为 True；不可用时投递应静默降级而不是抛错
        """

    def deliver(self, entry: dict[str, object]) -> "object":
        """投递一条通知。

        返回 `dsh_tray.notify.delivery.DeliveryResult`；用 `object` 标注是为了让本
        协议不反向依赖投递模块（`delivery` 会 import 本包的类型）。

        @param entry - 条目字典，字段名与 spool 一致
        @returns 投递结果（含是否成功与桌面分配的通知 id）
        """


class WindowAnchor(Protocol):
    """面板锚点计算。

    为什么要抽象：`QSystemTrayIcon.geometry()` 在 Plasma Wayland 上返回 0×0
    （实测），只能退化到屏幕角落；X11 下则应贴着托盘图标。
    """

    def anchor_for(self, tray_geometry: "tuple[int, int, int, int] | None", screen: object) -> tuple[int, int]:
        """计算面板左上角坐标。

        @param tray_geometry - 托盘图标矩形 (x, y, w, h)；无效时为 None
        @param screen - 有 `availableGeometry()` 的屏幕对象
        @returns (x, y) 屏幕坐标
        """


class PanelPlacement(Protocol):
    """面板精确定位。

    为什么要抽象：该合成器不接受客户端给的窗口位置——普通窗口 `move()` 不生效
    （实测面板恒落在水平居中处）。要贴右上角只能走合成器的层外壳协议，而那是
    Linux/Wayland 专有的，其它平台需要各自的实现。
    """

    def apply(self, widget: object, width: int, height: int, screen: object) -> bool:
        """把面板锚到目标位置。

        @param widget - 待定位的面板控件（需有 `windowHandle()`）
        @param width - 面板逻辑宽
        @param height - 面板逻辑高
        @param screen - 有 `geometry()` 的屏幕对象
        @returns 成功锚定返回 True；能力不可用返回 False，调用方退回既有路径
        """


class ProcessSample(Protocol):
    """一个进程的瞬时状态。"""

    @property
    def pid(self) -> int:
        """进程号。"""

    @property
    def role(self) -> str:
        """角色归类：`core` / `mcp` / `tool` / `other`。"""

    @property
    def label(self) -> str:
        """可读名，如 `dsh web`、`codegraph`、`pnpm`。"""

    @property
    def cpu_percent(self) -> float | None:
        """单核口径的 CPU 百分比；首次采样为 None。"""

    @property
    def rss_bytes(self) -> int:
        """常驻内存字节数。"""

    @property
    def age_seconds(self) -> int | None:
        """进程已存活秒数。"""


class ProcessSampler(Protocol):
    """进程采样。

    概览页必须自采，不能走插件上报——DSH 卡死时正是最需要看进程的时候
    （AGENTS.md 设计约束）。
    """

    def sample(self, root_pid: int | None) -> Sequence[ProcessSample]:
        """采一次样。

        @param root_pid - DSH 主进程号；None 时返回空序列
        @returns 本轮采样到的进程行
        """


#: 点击回执回调：(通知 id, 动作键) → None。
ActionCallback = Callable[[int, str], None]
