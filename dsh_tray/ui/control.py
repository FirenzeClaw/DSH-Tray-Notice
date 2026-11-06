"""控制区：五态渲染与主操作。

五态（未运行 / 启动中 / 运行中·自有 / 运行中·接管 / 停止中 / 失败）之所以要区分
「自有」与「接管」，是因为两者能做的事不同：自有实例能拿到令牌、能打开带登录态的
URL；接管的实例拿不到令牌，打开后可能 401。这个差别必须写在界面上，而不是让用户
点了一次才发现。

所有危险动作（停止、重启）都复用既有 `_confirm`，默认按钮是「取消」——面板比菜单
更容易误触（它就在鼠标下面），所以确认更不能省。
"""

from __future__ import annotations

from typing import Callable

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..lifecycle import Instance, State

#: 主操作按钮的文案（按状态）。
PRIMARY_LABEL = {
    State.STOPPED: "启动 DSH",
    State.STARTING: "正在启动…",
    State.RUNNING: "打开 Web UI",
    State.STOPPING: "正在停止…",
    State.FAILED: "重试启动",
}

#: 状态圆点颜色（与设计稿一致）。
STATE_COLORS = {
    State.STOPPED: "#6b7075",
    State.STARTING: "#f7b32b",
    State.RUNNING: "#3dae5f",
    State.STOPPING: "#f7b32b",
    State.FAILED: "#da4453",
}


class ControlArea(QFrame):
    """面板顶部的控制区。"""

    #: 主操作被点击。
    primary_clicked = pyqtSignal()
    #: 重启被点击。
    restart_clicked = pyqtSignal()
    #: 停止被点击。
    stop_clicked = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        """构造。

        @param parent - 父控件
        """
        super().__init__(parent)
        self.setObjectName("control")
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 13, 14, 12)
        root.setSpacing(8)

        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        self._dot = QLabel(self)
        self._dot.setObjectName("stateDot")
        self._dot.setFixedSize(8, 8)
        status_row.addWidget(self._dot, 0, Qt.AlignmentFlag.AlignVCenter)

        self._name = QLabel("DSH 未运行", self)
        self._name.setObjectName("controlName")
        status_row.addWidget(self._name, 0)
        status_row.addStretch(1)

        self._action_open = QPushButton("打开 Web UI", self)
        self._action_open.setObjectName("btnOpen")
        self._action_open.clicked.connect(self.primary_clicked.emit)
        status_row.addWidget(self._action_open)

        root.addLayout(status_row)

        self._meta = QLabel("", self)
        self._meta.setObjectName("controlMeta")
        self._meta.setContentsMargins(16, 0, 0, 0)
        root.addWidget(self._meta)

        self._hint = QLabel("", self)
        self._hint.setObjectName("controlHint")
        self._hint.setWordWrap(True)
        self._hint.hide()
        root.addWidget(self._hint)

        action_row = QHBoxLayout()
        action_row.setSpacing(6)
        self._primary = QPushButton("启动 DSH", self)
        self._primary.setObjectName("btnPrimary")
        self._primary.clicked.connect(self.primary_clicked.emit)
        action_row.addWidget(self._primary, 1)

        self._restart = QPushButton("重启", self)
        self._restart.setObjectName("btnRestart")
        self._restart.clicked.connect(self.restart_clicked.emit)
        action_row.addWidget(self._restart)

        self._stop = QPushButton("停止", self)
        self._stop.setObjectName("btnStop")
        self._stop.clicked.connect(self.stop_clicked.emit)
        action_row.addWidget(self._stop)

        root.addLayout(action_row)

        self._state = State.STOPPED
        self._busy = False

    def render(self, state: State, instance: Instance | None, error: str, busy: bool = False) -> None:
        """按状态重画。

        @param state - 生命周期状态
        @param instance - 运行实例（未运行时 None）
        @param error - 失败原因
        @param busy - 是否有动作正在进行
        """
        self._state = state
        self._busy = busy

        self._dot.setStyleSheet(
            f"background:{STATE_COLORS.get(state, '#6b7075')};border-radius:4px;"
        )

        owned = instance is not None and instance.owned
        if state is State.RUNNING and instance is not None:
            self._name.setText("DSH 运行中")
            origin = "由托盘启动" if owned else f"外部启动 PID {instance.pid}"
            self._meta.setText(f"127.0.0.1:{instance.port} · {origin}")
        elif state is State.STARTING:
            self._name.setText("DSH 正在启动…")
            self._meta.setText("冷启动通常需要十几秒")
        elif state is State.STOPPING:
            self._name.setText("DSH 正在停止…")
            self._meta.setText("正在结束会话与子进程")
        elif state is State.FAILED:
            self._name.setText("DSH 启动失败")
            self._meta.setText(error or "未知原因")
        else:
            self._name.setText("DSH 未运行")
            self._meta.setText("")

        # 接管态：提示拿不到令牌。这条提示只在真的会影响用户时出现。
        if state is State.RUNNING and instance is not None and not owned:
            self._hint.setText(
                "这个实例不是托盘启动的，拿不到访问令牌。如果浏览器提示未授权，"
                "用「重启」换成自有实例。"
            )
            self._hint.show()
        else:
            self._hint.hide()

        transitioning = state in (State.STARTING, State.STOPPING)
        running = state is State.RUNNING and instance is not None

        self._primary.setText(PRIMARY_LABEL.get(state, "启动 DSH"))
        self._primary.setEnabled(not busy and not transitioning)
        self._action_open.setEnabled(running and not busy)
        self._restart.setEnabled(running and not busy)
        self._stop.setEnabled(running and not busy)

        # 未运行时隐藏「重启/停止」：留着只会让人以为可以点。
        self._restart.setVisible(running or transitioning)
        self._stop.setVisible(running or transitioning)
        # 运行中时主按钮是「打开」，与顶部的「打开 Web UI」重复，隐藏一个。
        self._primary.setVisible(not running)

    @property
    def state(self) -> State:
        """当前渲染的状态。"""
        return self._state
