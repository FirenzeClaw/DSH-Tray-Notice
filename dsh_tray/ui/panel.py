"""面板容器：四标签 + 控制区 + 三个页面。

窗口类型是 `Qt.Tool | FramelessWindowHint`，不是 `Qt.Popup`——后者在 Wayland 上
创建失败（实测：`Failed to create grabbing popup … has no transientParent`），窗口
根本不可见。`Qt.Tool` 的代价是会抢焦点（即使设了 `WA_ShowWithoutActivating`），
这一点由 `focusOut` 自动隐藏来补偿：用户点到别处，面板就收起，不会挡住桌面。

四个标签等宽（`flex: 1 1 0` 的 Qt 等价写法是 stretch 全给 1），文字始终居中；
计数与活动点用绝对定位覆盖在标签上，不参与布局——否则数字一变，文字就会左右跳。
"""

from __future__ import annotations

import time
from typing import Callable

from PyQt6.QtCore import QPoint, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

#: 面板宽度，与设计稿一致（378 px 是在 1366 宽屏上能贴住托盘又不遮内容的折中）。
PANEL_WIDTH = 378

#: 弹出后的焦点宽限期（秒）。期间收到 focusOut 不隐藏。
SHOW_GRACE_SECONDS = 0.6

#: 标签名。
TAB_LABELS = ("未查看", "已查看", "工作中", "概览")

#: 标签索引。
TAB_UNREAD = 0
TAB_READ = 1
TAB_WORKING = 2
TAB_OVERVIEW = 3


class TabBar(QWidget):
    """四个等宽标签，文字居中，计数绝对定位。

    为什么不用 QTabBar：Qt 的标签宽度由文字长度决定，四个标签会宽窄不一，而设计稿
    要求均分（每栏 87 px）。自绘一个条更直接，也让「计数不影响居中」容易实现。
    """

    changed = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        """构造。

        @param parent - 父控件
        """
        super().__init__(parent)
        self._current = TAB_UNREAD
        self._counts: dict[int, int] = {}
        self._live: dict[int, bool] = {}

        self.setObjectName("tabbar")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._buttons: list[QPushButton] = []
        for index, label in enumerate(TAB_LABELS):
            button = QPushButton(label, self)
            button.setObjectName(f"tab{index}")
            button.setCheckable(True)
            button.setFlat(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked, position=index: self.set_current(position))
            # 四个标签各拿一份 stretch，宽度自然相等。
            layout.addWidget(button, 1)
            self._buttons.append(button)

        # 计数与活动点：绝对定位在对应按钮右上/左侧，不参与布局。
        self._badges: list[QLabel] = []
        self._dots: list[QLabel] = []
        for index in range(len(TAB_LABELS)):
            badge = QLabel("", self)
            badge.setObjectName(f"badge{index}")
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge.hide()
            self._badges.append(badge)

            dot = QLabel("", self)
            dot.setObjectName(f"dot{index}")
            dot.setFixedSize(5, 5)
            dot.hide()
            self._dots.append(dot)

        self._apply_selection()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        """尺寸变化时重新摆放角标。

        @param event - 尺寸事件
        """
        super().resizeEvent(event)
        self._reposition_badges()

    def _reposition_badges(self) -> None:
        """把计数与活动点摆到各自标签上。

        抽成独立方法而不是手动调 `resizeEvent`：`resizeEvent` 只接受 `QResizeEvent`，
        传 `QEvent(Resize)` 会抛 TypeError（实测）。
        """
        width = max(1, self.width() // len(TAB_LABELS))
        for index, badge in enumerate(self._badges):
            badge.adjustSize()
            badge.move(index * width + width - badge.width() - 4, 4)
            self._dots[index].move(index * width + 4, self.height() // 2 - 2)

    def set_current(self, index: int) -> None:
        """切换当前标签。

        @param index - 标签索引
        """
        if index == self._current:
            return
        self._current = index
        self._apply_selection()
        self.changed.emit(index)

    @property
    def current(self) -> int:
        """当前标签索引。"""
        return self._current

    def set_count(self, index: int, count: int) -> None:
        """设置某标签的计数角标。

        @param index - 标签索引
        @param count - 数量；0 时隐藏
        """
        self._counts[index] = count
        badge = self._badges[index]
        badge.setText(str(count) if count > 0 else "")
        badge.setVisible(count > 0)
        badge.adjustSize()
        self._reposition_badges()

    def set_live(self, index: int, live: bool) -> None:
        """设置某标签的活动点（「工作中」有会话在跑时亮）。

        @param index - 标签索引
        @param live - 是否亮
        """
        self._live[index] = live
        self._dots[index].setVisible(live)

    def _apply_selection(self) -> None:
        """把选中态同步到按钮样式。"""
        for index, button in enumerate(self._buttons):
            selected = index == self._current
            button.setChecked(selected)
            weight = QFont.Weight.DemiBold if selected else QFont.Weight.Normal
            font = button.font()
            font.setWeight(weight)
            button.setFont(font)
            button.setProperty("selected", selected)
            button.style().unpolish(button)
            button.style().polish(button)


class Panel(QFrame):
    """托盘面板。

    内容由三部分组成：顶部标题行、控制区（外部注入）、标签条 + 页面栈。
    """

    closed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        """构造。

        @param parent - 父控件
        """
        super().__init__(parent)
        # Qt.Tool：不进任务栏、不抢主窗口焦点；FramelessWindowHint：无边框。
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("panel")
        self.setFixedWidth(PANEL_WIDTH)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        #: 早于此刻的失焦一律忽略，见 show_at / _hide_if_inactive。
        self._ignore_focus_out_until = 0.0

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QWidget(self)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(14, 12, 14, 8)
        self._title = QLabel("DSH 通知", header)
        self._title.setObjectName("panelTitle")
        header_layout.addWidget(self._title)
        header_layout.addStretch(1)
        self._missed = QLabel("", header)
        self._missed.setObjectName("missedHint")
        self._missed.hide()
        header_layout.addWidget(self._missed)
        root.addWidget(header)

        self._control: QWidget | None = None

        self.tabs = TabBar(self)
        root.addWidget(self.tabs)

        self.stack = QStackedWidget(self)
        # 四个占位页：页面由外部按需替换，但索引必须从构造时就有效——否则
        # `set_current(2)` 在页面还没挂上时会把 stack 置成 -1。
        for _ in range(len(TAB_LABELS)):
            self.stack.addWidget(QWidget(self))
        root.addWidget(self.stack, 1)

        self.tabs.changed.connect(self.stack.setCurrentIndex)

    def set_control(self, control: QWidget) -> None:
        """挂入控制区。

        @param control - 控制区控件
        """
        if self._control is not None:
            self.layout().removeWidget(self._control)
            self._control.deleteLater()
        self._control = control
        self.layout().insertWidget(1, control)

    def add_page(self, index: int, page: QWidget) -> None:
        """按索引挂入页面。

        @param index - 标签索引
        @param page - 页面控件
        """
        while self.stack.count() <= index:
            self.stack.addWidget(QWidget(self))
        existing = self.stack.widget(index)
        if existing is not None:
            self.stack.removeWidget(existing)
            existing.deleteLater()
        self.stack.insertWidget(index, page)
        self.stack.setCurrentIndex(self.tabs.current)

    def set_counts(self, unread: int, read: int, working: int) -> None:
        """更新三个标签的计数。

        @param unread - 未查看数
        @param read - 已查看数
        @param working - 工作中的会话数
        """
        self.tabs.set_count(TAB_UNREAD, unread)
        self.tabs.set_count(TAB_READ, read)
        self.tabs.set_count(TAB_WORKING, working)
        self.tabs.set_live(TAB_WORKING, working > 0)

    def set_missed(self, count: int) -> None:
        """显示「错过 N 条」提示。

        @param count - 补投条数；0 时隐藏
        """
        self._missed.setText(f"错过 {count} 条" if count > 0 else "")
        self._missed.setVisible(count > 0)

    def show_at(self, x: int, y: int) -> None:
        """在指定坐标显示。

        @param x - 左上角 x
        @param y - 左上角 y
        """
        self.move(QPoint(x, y))
        self.show()
        self.raise_()
        # 宽限期：刚弹出时 Wayland 常会先给一次 focusOut（窗口还没拿到焦点），
        # 这段时间内一律不据此隐藏，否则面板闪一下就没了。
        self._ignore_focus_out_until = time.monotonic() + SHOW_GRACE_SECONDS

    def focusOutEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        """失去焦点即隐藏：面板是临时浮层，不该常驻。

        @param event - 焦点事件
        """
        super().focusOutEvent(event)
        # 稍等再隐藏：点面板内部的按钮也会触发 focusOut，立刻隐藏会让点击落空。
        QTimer.singleShot(120, self._hide_if_inactive)

    def _hide_if_inactive(self) -> None:
        """若仍无焦点则隐藏。

        Wayland 下 `Qt.Tool` 常常拿不到焦点，`isActiveWindow()` 恒为假。若无条件
        据此隐藏，面板会在显示后约 120 ms 自己消失（表现为「点托盘没反应」）。
        因此只在宽限期已过时才按失焦收起。
        """
        if time.monotonic() < self._ignore_focus_out_until:
            return
        if not self.isVisible() or self.isActiveWindow():
            return
        self.hide()
        self.closed.emit()
