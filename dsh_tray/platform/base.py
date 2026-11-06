"""平台层接口定义。

三件事按平台差异抽象：系统通知投递、面板锚点、进程采样。三者都用 `Protocol`
而非基类——实现方不需要继承，鸭子类型即可，测试里传假对象也不必先继承一层。

平台分支只允许出现在本包内（AGENTS.md 硬约束 3）；其余模块只认这三个协议。
"""

from __future__ import annotations

from typing import Protocol, Sequence

# 通知紧急度。与 freedesktop 的 urgency 一一对应：0=low 1=normal 2=critical。
URGENCY_LOW = 0
URGENCY_NORMAL = 1
URGENCY_CRITICAL = 2


class NotificationBackend(Protocol):
    """系统通知后端。

    实现方负责把一条已经决定要投递的通知送到桌面，并回报它的身份，供点击回执
    与撤回使用。**不负责**去重、策略、历史——那些在 `dsh_tray/notify/`。
    """

    def is_available(self) -> bool:
        """后端是否可用（例如 D-Bus 会话总线能否连上）。

        @returns 可用为 True；不可用时投递应静默降级而不是抛错
        """

    def send(
        self,
        *,
        title: str,
        body: str,
        urgency: int,
        action_label: str | None,
        action_key: str | None,
        replace_id: int | None,
    ) -> int | None:
        """投递一条通知。

        @param title - 标题（已由策略层截断）
        @param body - 正文（已由策略层截断）
        @param urgency - `URGENCY_*` 之一
        @param action_label - 按钮文案；None 表示不带按钮
        @param action_key - 按钮回执键，点击时原样回到 `on_action`
        @param replace_id - 要替换的通知 id（同会话合并用）；None 表示新建
        @returns 桌面分配的通知 id；投递失败返回 None（不得抛错）
        """

    def close(self, notification_id: int) -> None:
        """撤回一条通知（用户已从面板处理掉时调用）。

        @param notification_id - `send` 返回的 id
        """


class WindowAnchor(Protocol):
    """面板锚点计算。

    为什么要抽象：`QSystemTrayIcon.geometry()` 在 Plasma Wayland 上返回 0×0
    （实测），只能退化到屏幕角落；X11 下则应贴着托盘图标。两种行为都由实现方
    决定，面板本身只问「我该摆在哪」。
    """

    def anchor_rect(self) -> tuple[int, int, int, int]:
        """返回锚点矩形（屏幕坐标，x, y, w, h）。

        @returns 锚点；无法定位时返回空矩形 (0, 0, 0, 0)，调用方自行退化
        """


class ProcessSampler(Protocol):
    """进程采样。

    概览页必须自采，不能走插件上报——DSH 卡死时正是最需要看进程的时候
    （AGENTS.md 设计约束）。
    """

    def sample(self) -> Sequence["ProcessSample"]:
        """采一次样。

        @returns 本轮采样到的进程行；采不到时返回空序列而不是抛错
        """


class ProcessSample(Protocol):
    """一个进程的瞬时状态。

    字段刻意保持最少：概览页只显示「谁在跑、占多少」。
    """

    @property
    def pid(self) -> int:
        """进程号。"""

    @property
    def role(self) -> str:
        """角色归类（例如 `dsh-web` / `child` / `other`），由实现方判定。"""

    @property
    def cpu_percent(self) -> float:
        """瞬时 CPU 占用百分比。"""

    @property
    def rss_bytes(self) -> int:
        """常驻内存字节数。"""
