"""工作中页：谁在跑、跑了多久。

时长每秒自增，但**只更新文本、不重建整页**——整页重建会让滚动位置与鼠标悬停
状态每秒重置一次，看起来像在闪。因此这里保留行控件引用，定时器只调
`setText`。

面板关闭即停定时器：一个隐藏的页面还在每秒跑回调是纯粹的浪费，而且会让
「关闭面板后 CPU 占用」这个可观测指标变差。
"""

from __future__ import annotations

from datetime import datetime, timezone

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..notify.sessionstate import ActiveSession, SessionTable

#: 时长刷新间隔。
TICK_MS = 1000


class WorkingRow(QFrame):
    """一个正在跑的会话。"""

    clicked = pyqtSignal(str)

    def __init__(self, session: ActiveSession, parent: QWidget | None = None) -> None:
        """构造。

        @param session - 会话行
        @param parent - 父控件
        """
        super().__init__(parent)
        self.session_id = session.id
        self.setObjectName("workingRow")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 9, 14, 9)
        layout.setSpacing(9)

        self._dot = QLabel(self)
        self._dot.setFixedSize(6, 6)
        self._dot.setStyleSheet(
            "background:#f7b32b;border-radius:3px;" if session.waiting_for_user else "background:#3dae5f;border-radius:3px;"
        )
        layout.addWidget(self._dot, 0, Qt.AlignmentFlag.AlignTop)

        column = QVBoxLayout()
        column.setSpacing(2)
        title = QLabel(session.title, self)
        title.setObjectName("workingTitle")
        column.addWidget(title)

        detail = session.current_tool or ("等你回答" if session.waiting_for_user else "思考中")
        self._detail = QLabel(f"第 {session.turn} 轮 · {detail}", self)
        self._detail.setObjectName("workingDetail")
        column.addWidget(self._detail)
        layout.addLayout(column, 1)

        self._elapsed = QLabel("—", self)
        self._elapsed.setObjectName("workingElapsed")
        layout.addWidget(self._elapsed, 0, Qt.AlignmentFlag.AlignVCenter)

    def set_elapsed(self, text: str) -> None:
        """更新时长文本。

        @param text - 已格式化的时长
        """
        self._elapsed.setText(text)

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        """点击行：打开该会话。

        @param event - 鼠标事件
        """
        super().mousePressEvent(event)
        self.clicked.emit(self.session_id)


class WorkingPage(QScrollArea):
    """「工作中」页。"""

    session_clicked = pyqtSignal(str)

    def __init__(self, table: SessionTable, parent: QWidget | None = None) -> None:
        """构造。

        @param table - 会话状态表
        @param parent - 父控件
        """
        super().__init__(parent)
        self._table = table
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setObjectName("workingList")

        self._container = QWidget(self)
        self._layout = QVBoxLayout(self._container)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self.setWidget(self._container)

        self._rows: list[WorkingRow] = []
        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._tick)

    def refresh(self) -> None:
        """按会话表重建行。

        只在会话集合变化时调用；时长由 `_tick` 单独更新。
        """
        while self._layout.count():
            child = self._layout.takeAt(0)
            widget = child.widget()
            if widget is not None:
                widget.deleteLater()
        self._rows = []

        sessions = self._table.active()
        if not sessions:
            empty = QLabel("当前没有会话在跑", self._container)
            empty.setObjectName("emptyHint")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._layout.addWidget(empty)
            self._layout.addStretch(1)
            self._stop_timer()
            return

        for session in sessions:
            row = WorkingRow(session, self._container)
            row.clicked.connect(self.session_clicked.emit)
            self._layout.addWidget(row)
            self._rows.append(row)
        self._layout.addStretch(1)
        self._tick()
        self._start_timer()

    def _tick(self) -> None:
        """只更新时长文本。"""
        now = datetime.now(timezone.utc)
        for row in self._rows:
            seconds = self._table.elapsed(row.session_id, now=now)
            row.set_elapsed(SessionTable.format_elapsed(seconds))

    def _start_timer(self) -> None:
        """启动计时器（幂等）。"""
        if not self._timer.isActive():
            self._timer.start()

    def _stop_timer(self) -> None:
        """停止计时器。"""
        if self._timer.isActive():
            self._timer.stop()

    def showEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        """页面显示时恢复计时。

        @param event - 显示事件
        """
        super().showEvent(event)
        if self._rows:
            self._start_timer()

    def hideEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        """页面隐藏时停止计时。

        @param event - 隐藏事件
        """
        super().hideEvent(event)
        self._stop_timer()

    @property
    def timer_active(self) -> bool:
        """计时器是否在跑（测试用）。"""
        return self._timer.isActive()

    def row_count(self) -> int:
        """行数（测试用）。

        @returns 行数
        """
        return len(self._rows)

    def elapsed_texts(self) -> list[str]:
        """各行时长文本（测试用）。

        @returns 文本列表
        """
        return [row._elapsed.text() for row in self._rows]
