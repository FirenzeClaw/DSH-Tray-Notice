"""通知列表页：未查看 / 已查看两页，按日期分组。

「已查看不删除」在界面上的体现是：点了一条，它从「未查看」移到「已查看」，
两个计数同时变；条目本身仍在历史文件里，几天后还能翻回来点进那个会话。

分组头（今天/昨天/本周/日期）由 `history.group_by_day` 提供——面板只负责渲染，
不在界面层重算日期边界，否则跨时区或跨零点会出现两处口径不一致。
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..notify import history
from ..notify.intents import to_display


class NotificationRow(QFrame):
    """一条通知。"""

    clicked = pyqtSignal(str, str)
    """(条目 id, 会话 id)"""

    mark_read_clicked = pyqtSignal(str)
    """条目 id"""

    def __init__(self, item: history.StoredNotification, parent: QWidget | None = None) -> None:
        """构造。

        @param item - 历史记录
        @param parent - 父控件
        """
        super().__init__(parent)
        self._entry = item.entry
        self.setObjectName("notifRow")
        self.setProperty("unread", not item.read)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 8, 10, 8)
        layout.setSpacing(9)

        accent = QLabel(self)
        accent.setObjectName("rowAccent")
        accent.setFixedSize(3, 28)
        accent.setStyleSheet(
            f"background:{'#da4453' if item.entry.urgency == 'critical' else '#3a3e41'};border-radius:2px;"
        )
        layout.addWidget(accent)

        text_column = QVBoxLayout()
        text_column.setSpacing(2)

        top = QHBoxLayout()
        top.setSpacing(6)
        title = QLabel(item.entry.title, self)
        title.setObjectName("rowTitle")
        top.addWidget(title, 0)
        top.addStretch(1)
        display = to_display(item.entry)
        stamp = QLabel(display.relative_time, self)
        stamp.setObjectName("rowTime")
        top.addWidget(stamp, 0)
        text_column.addLayout(top)

        body = QLabel(item.entry.body, self)
        body.setObjectName("rowBody")
        body.setWordWrap(True)
        text_column.addWidget(body)

        meta = QLabel(f"{display.category} · {item.entry.session_title}", self)
        meta.setObjectName("rowMeta")
        text_column.addWidget(meta)

        layout.addLayout(text_column, 1)

        self._mark = QPushButton("已读", self)
        self._mark.setObjectName("rowMark")
        self._mark.setFixedWidth(38)
        self._mark.clicked.connect(lambda: self.mark_read_clicked.emit(self._entry.id))
        if item.read:
            self._mark.hide()
        layout.addWidget(self._mark, 0, Qt.AlignmentFlag.AlignVCenter)

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        """点击整行：打开会话并标记已读。

        @param event - 鼠标事件
        """
        super().mousePressEvent(event)
        self.clicked.emit(self._entry.id, self._entry.session_id)


class NotificationListPage(QWidget):
    """通知列表（未查看或已查看）。

    顶部有一条工具栏（批量操作），下面是滚动区。工具栏只在对应页出现：
    「全部标为已查看」只对未查看有意义，「清空已查看」只对已查看有意义。
    """

    entry_clicked = pyqtSignal(str, str)
    """(条目 id, 会话 id)"""

    changed = pyqtSignal()
    """批量操作后通知外部刷新计数。"""

    def __init__(self, only_unread: bool, parent: QWidget | None = None) -> None:
        """构造。

        @param only_unread - True 显示未查看，False 显示已查看
        @param parent - 父控件
        """
        super().__init__(parent)
        self._only_unread = only_unread
        self.setObjectName("notifList")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(14, 6, 14, 2)
        toolbar.addStretch(1)
        self._bulk = QPushButton("全部标为已查看" if only_unread else "清空已查看", self)
        self._bulk.setObjectName("bulkAction")
        self._bulk.clicked.connect(self._on_bulk)
        toolbar.addWidget(self._bulk)
        outer.addLayout(toolbar)

        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(self._scroll, 1)

        self._container = QWidget(self._scroll)
        self._layout = QVBoxLayout(self._container)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self._scroll.setWidget(self._container)

    def refresh(
        self,
        items: list[history.StoredNotification] | None = None,
        now: datetime | None = None,
    ) -> None:
        """重建列表。

        已查看页按日期分组，未查看页不分组（未查看通常只有几条，分组反而是噪音）。

        @param items - 记录；缺省读历史
        @param now - 用于判定「今天/昨天」的时刻；缺省取真实当前时间。
            可注入是为了让分组可确定性测试——用真实时钟的测试会**跨天失败**
            （实测：11-06 写的用例在 11-07 早上把「今天」算成了「昨天」）。
        """
        records = items if items is not None else history.load()
        selected = [item for item in records if item.read != self._only_unread]

        while self._layout.count():
            child = self._layout.takeAt(0)
            widget = child.widget()
            if widget is not None:
                widget.deleteLater()

        if not selected:
            empty = QLabel("暂无通知" if self._only_unread else "还没有已查看的通知", self._container)
            empty.setObjectName("emptyHint")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._layout.addWidget(empty)
            self._layout.addStretch(1)
            return

        if self._only_unread:
            for item in sorted(selected, key=lambda record: record.entry.ts, reverse=True):
                self._add_row(item)
        else:
            for label, group in history.group_by_day(selected, now):
                header = QLabel(label, self._container)
                header.setObjectName("dayHeader")
                self._layout.addWidget(header)
                for item in group:
                    self._add_row(item)

        self._layout.addStretch(1)

    def _add_row(self, item: history.StoredNotification) -> None:
        """挂一行并接好信号。

        @param item - 记录
        """
        row = NotificationRow(item, self._container)
        row.clicked.connect(self.entry_clicked.emit)
        row.mark_read_clicked.connect(self._on_mark_read)
        self._layout.addWidget(row)

    def _on_bulk(self) -> None:
        """批量操作，二次确认后执行。

        两个操作都不可逆（清空会真的删条目、全部已读会让未读计数归零），所以都
        要确认——面板是临时浮层，误触成本比菜单更高。
        """
        from PyQt6.QtWidgets import QMessageBox

        if self._only_unread:
            question = "把全部未查看标为已查看？"
            detail = "条目仍会保留在「已查看」里，可以随时翻回。"
            confirm_label = "全部标为已查看"
        else:
            question = "清空全部已查看？"
            detail = "这会删除这些条目，未查看的不受影响。"
            confirm_label = "清空"

        box = QMessageBox(self)
        box.setWindowTitle(question)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText(question)
        box.setInformativeText(detail)
        cancel = box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        confirm = box.addButton(confirm_label, QMessageBox.ButtonRole.DestructiveRole)
        box.setDefaultButton(cancel)
        box.exec()
        if box.clickedButton() is not confirm:
            return

        if self._only_unread:
            history.mark_all_read()
        else:
            history.clear_read()
        self.refresh()
        self.changed.emit()

    def _on_mark_read(self, entry_id: str) -> None:
        """标为已读并刷新。

        @param entry_id - 条目 id
        """
        history.mark_read(entry_id)
        self.refresh()

    def row_count(self) -> int:
        """当前渲染的行数（测试用）。

        @returns 行数
        """
        return sum(
            1
            for index in range(self._layout.count())
            if isinstance(self._layout.itemAt(index).widget(), NotificationRow)
        )

    def group_labels(self) -> list[str]:
        """当前渲染的日期分组头（测试用）。

        @returns 组标题列表
        """
        return [
            widget.text()
            for index in range(self._layout.count())
            if (widget := self._layout.itemAt(index).widget()) is not None
            and widget.objectName() == "dayHeader"
        ]


def unread_count(items: list[history.StoredNotification] | None = None) -> int:
    """未查看条数（不含 test）。

    @param items - 记录；缺省读历史
    @returns 条数
    """
    records = items if items is not None else history.load()
    return sum(1 for item in records if not item.read and item.entry.kind != "test")


def read_count(items: list[history.StoredNotification] | None = None) -> int:
    """已查看条数（不含 test）。

    @param items - 记录；缺省读历史
    @returns 条数
    """
    records = items if items is not None else history.load()
    return sum(1 for item in records if item.read and item.entry.kind != "test")
