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

from PyQt6.QtCore import QPoint, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QPainter, QPainterPath, QPen
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

#: 圆角半径与围绕卡片的透明留白。二者一起决定窗口外观；留白不可省，
#: 否则圆角外侧会直接顶到窗口边，描边被裁掉一半。
CORNER_RADIUS = 12
PANEL_MARGIN = 1

#: 通知单行实测高度（字体、换行、内边距共同决定，改样式时要同步回归）。
ROW_HEIGHT = 74

#: 列表自身的固定开销：工具行 + 内边距。用于把「露出 N 条」换算成面板高度。
LIST_CHROME_HEIGHT = 46

#: 未查看列表默认露出几条。设置项可调，范围见下面两个常量。
#: 取 5 是因为一屏能看清「最近发生了什么」，再长就要滚动、再短就频繁翻页。
DEFAULT_ROWS_VISIBLE = 5
ROWS_VISIBLE_MIN = 3
ROWS_VISIBLE_MAX = 12

#: 面板高度上下限。下限保证控制区与标签都在；上限避免在 768 高的屏上超出。
PANEL_MIN_HEIGHT = 340
PANEL_MAX_HEIGHT = 820

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

    高度不再写死：按「未查看列表里能看到 N 条」反推（`rows_visible`，设置项），
    再夹在最小/最大之间。这样 1 条通知时不会留一大片空白，20 条时也不会把面板
    撑到屏幕外——两种极端都在真实使用里出现过。
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
        #: 圆角靠透明背景 + 圆角矩形自绘实现；不设 WA_TranslucentBackground 时
        #: FramelessWindowHint 的窗口四角仍是直角，圆角会被背景填掉。
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        #: 早于此刻的失焦一律忽略，见 show_at / _hide_if_inactive。
        self._ignore_focus_out_until = 0.0
        #: 拖拽起点（相对窗口），None 表示没在拖。
        self._drag_offset: QPoint | None = None
        #: 未查看列表要露出几条；由设置项驱动，见 set_rows_visible。
        self._rows_visible = DEFAULT_ROWS_VISIBLE

        root = QVBoxLayout(self)
        root.setContentsMargins(PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN)
        root.setSpacing(0)

        # 圆角容器：所有内容挂在它里面，它在 paintEvent 里被画成圆角卡片。
        self._surface = QWidget(self)
        self._surface.setObjectName("panelSurface")
        self._surface.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        root.addWidget(self._surface)

        surface_layout = QVBoxLayout(self._surface)
        surface_layout.setContentsMargins(0, 0, 0, 0)
        surface_layout.setSpacing(0)
        self._surface_layout = surface_layout

        header = QWidget(self._surface)
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
        surface_layout.addWidget(header)

        self._control: QWidget | None = None

        self.tabs = TabBar(self._surface)
        surface_layout.addWidget(self.tabs)

        self.stack = QStackedWidget(self._surface)
        # 四个占位页：页面由外部按需替换，但索引必须从构造时就有效——否则
        # `set_current(2)` 在页面还没挂上时会把 stack 置成 -1。
        for _ in range(len(TAB_LABELS)):
            self.stack.addWidget(QWidget(self._surface))
        surface_layout.addWidget(self.stack, 1)

        self.tabs.changed.connect(self.stack.setCurrentIndex)
        self.apply_height()

    def set_control(self, control: QWidget) -> None:
        """挂入控制区。

        @param control - 控制区控件
        """
        if self._control is not None:
            self._surface_layout.removeWidget(self._control)
            self._control.deleteLater()
        self._control = control
        self._surface_layout.insertWidget(1, control)
        self.apply_height()

    def set_rows_visible(self, rows: int) -> None:
        """设置未查看列表要露出几条，并立即重算高度。

        @param rows - 条数；会被夹到 `ROWS_VISIBLE_MIN`–`ROWS_VISIBLE_MAX`
        """
        clamped = max(ROWS_VISIBLE_MIN, min(ROWS_VISIBLE_MAX, int(rows)))
        if clamped == self._rows_visible:
            self.apply_height()
            return
        self._rows_visible = clamped
        self.apply_height()

    def apply_height(self) -> None:
        """按「露出 N 条通知」重算并固定面板高度。

        高度 = 标题行 + 控制区 + 标签条 + N × 行高 + 边距，再夹到上下限。
        用实测行高而不是估算：`NotificationRow` 的高度由字体度量与换行决定，
        写死 74 会在不同字号/DPI 下露出半条。
        这里只固定高度、不固定宽度——宽度始终是 `PANEL_WIDTH`。
        """
        chrome = 0
        if self._control is not None:
            chrome += self._control.sizeHint().height()
        chrome += self.tabs.sizeHint().height()
        chrome += self._header_height()
        chrome += 2 * PANEL_MARGIN

        target = chrome + self._rows_visible * ROW_HEIGHT + LIST_CHROME_HEIGHT
        self.setFixedHeight(max(PANEL_MIN_HEIGHT, min(PANEL_MAX_HEIGHT, target)))

    def _header_height(self) -> int:
        """标题行高度。

        @returns 像素高度
        """
        title = getattr(self, "_title", None)
        if title is None or title.parentWidget() is None:
            return 56
        return title.parentWidget().sizeHint().height()

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

    # ------------------------------------------------------------- 圆角与拖拽

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        """把窗口背景画成圆角卡片。

        窗口本身是矩形的（Wayland 下没法直接给窗口加圆角），所以整块背景由这里
        自绘：外圈全透明，内圈是圆角矩形。子控件都挂在 `_surface` 里，几何上
        正好落在圆角矩形内，因此不需要给每个控件单独裁切。

        @param event - 绘制事件
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        # 先铺透明：不铺的话上一帧的残留会留在圆角外侧。
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.fillRect(self.rect(), Qt.GlobalColor.transparent)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

        rect = QRectF(self.rect()).adjusted(
            PANEL_MARGIN, PANEL_MARGIN, -PANEL_MARGIN, -PANEL_MARGIN
        )
        path = QPainterPath()
        path.addRoundedRect(rect, CORNER_RADIUS, CORNER_RADIUS)
        painter.fillPath(path, self.palette().window())
        painter.setPen(QPen(self.palette().mid().color(), 1))
        painter.drawPath(path)
        painter.end()

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        """记录拖拽起点。

        @param event - 鼠标事件
        """
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        """按住拖动窗口。

        @param event - 鼠标事件
        """
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        """结束拖拽。

        @param event - 鼠标事件
        """
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def focusOutEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        """失去焦点即隐藏：面板是临时浮层，不该常驻。

        @param event - 焦点事件
        """
        super().focusOutEvent(event)
        # 正在拖拽时不收起：拖窗口的过程中必然短暂失焦。
        if self._drag_offset is not None:
            return
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
