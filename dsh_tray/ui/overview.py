"""概览页：DSH 及其子进程的开销。

两条设计约束：

1. **只在可见时采样**。2 秒一次的 `/proc` 扫描在面板关闭时毫无意义，还会让
   「托盘空闲时也在耗 CPU」变成可观测的问题。
2. **首次显示「待采样」而不是 0%**。CPU 是差值，没有基准就没有值；显示 0 会
   让人误判「进程闲着」。

页脚要写明口径（单核百分比、ΣRSS 含共享页），否则「内存 800 MB」会被当成真实
独占内存——多个进程共享的页会被重复计入。
"""

from __future__ import annotations

from typing import Callable

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..notify.sampling import ProcessRow, SampleSummary

#: 采样间隔。
SAMPLE_INTERVAL_MS = 2000

#: 角色 → 中文标签。
ROLE_LABELS = {
    "core": "DSH 本体",
    "mcp": "MCP 服务",
    "tool": "工具进程",
    "other": "其它",
}


def format_bytes(size: int) -> str:
    """把字节数写成人类可读。

    @param size - 字节数
    @returns 形如 `128 MB`
    """
    megabytes = size / (1024 * 1024)
    if megabytes < 1:
        return f"{size / 1024:.0f} KB"
    if megabytes < 1024:
        return f"{megabytes:.0f} MB"
    return f"{megabytes / 1024:.1f} GB"


def format_cpu(percent: float | None) -> str:
    """把 CPU 百分比写成展示文本。

    @param percent - 百分比；None 表示还没有基准
    @returns 形如 `12.3%` 或 `待采样`
    """
    return "待采样" if percent is None else f"{percent:.1f}%"


class OverviewPage(QWidget):
    """概览页。"""

    def __init__(
        self,
        sampler: Callable[[], list[ProcessRow]],
        parent: QWidget | None = None,
    ) -> None:
        """构造。

        @param sampler - 采样函数，返回进程行
        @param parent - 父控件
        """
        super().__init__(parent)
        self._sampler = sampler
        self.setObjectName("overview")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._summary = QLabel("合计 —", self)
        self._summary.setObjectName("overviewSummary")
        self._summary.setContentsMargins(14, 8, 14, 4)
        outer.addWidget(self._summary)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll, 1)

        self._container = QWidget(scroll)
        self._layout = QVBoxLayout(self._container)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        scroll.setWidget(self._container)

        footer = QLabel("单核百分比 · ΣRSS 含共享页", self)
        footer.setObjectName("overviewFooter")
        footer.setContentsMargins(14, 4, 14, 8)
        outer.addWidget(footer)

        self._timer = QTimer(self)
        self._timer.setInterval(SAMPLE_INTERVAL_MS)
        self._timer.timeout.connect(self.refresh)

        self._rows: list[ProcessRow] = []

    def refresh(self) -> None:
        """采一次样并重建行。

        采样失败（DSH 未运行、/proc 读不到）时显示空态而不是保留旧数据：留着旧
        数据会让人以为进程还在。
        """
        try:
            rows = self._sampler()
        except Exception:  # noqa: BLE001 - 采样失败不该拖垮面板
            rows = []
        self._rows = rows
        self._render(rows)

    def _render(self, rows: list[ProcessRow]) -> None:
        """按采样行重建界面。

        @param rows - 采样行
        """
        while self._layout.count():
            child = self._layout.takeAt(0)
            widget = child.widget()
            if widget is not None:
                widget.deleteLater()

        if not rows:
            empty = QLabel("DSH 未运行", self._container)
            empty.setObjectName("emptyHint")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._layout.addWidget(empty)
            self._layout.addStretch(1)
            self._summary.setText("合计 —")
            return

        summary = SampleSummary.from_rows(rows)
        self._summary.setText(
            f"合计 CPU {summary.cpu_percent:.1f}% · 内存 {format_bytes(summary.rss_bytes)} · {summary.process_count} 个进程"
        )

        grouped: dict[str, list[ProcessRow]] = {}
        for row in rows:
            grouped.setdefault(row.role, []).append(row)

        for role in ("core", "mcp", "tool", "other"):
            entries = grouped.get(role)
            if not entries:
                continue
            header = QLabel(ROLE_LABELS.get(role, role), self._container)
            header.setObjectName("overviewGroup")
            self._layout.addWidget(header)
            for row in sorted(entries, key=lambda item: item.rss_bytes, reverse=True):
                self._layout.addWidget(self._row_widget(row))

        self._layout.addStretch(1)

    def _row_widget(self, row: ProcessRow) -> QWidget:
        """一行进程。

        @param row - 采样行
        @returns 控件
        """
        widget = QWidget(self._container)
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(14, 5, 14, 5)
        layout.setSpacing(8)

        name = QLabel(f"{row.label}", widget)
        name.setObjectName("procLabel")
        layout.addWidget(name, 1)

        age = QLabel("" if row.age_seconds is None else f"{row.age_seconds // 60} 分", widget)
        age.setObjectName("procAge")
        layout.addWidget(age, 0)

        cpu = QLabel(format_cpu(row.cpu_percent), widget)
        cpu.setObjectName("procCpu")
        cpu.setMinimumWidth(56)
        cpu.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(cpu, 0)

        memory = QLabel(format_bytes(row.rss_bytes), widget)
        memory.setObjectName("procRss")
        memory.setMinimumWidth(64)
        memory.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(memory, 0)

        return widget

    def showEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        """显示时开始采样并立刻采一次。

        @param event - 显示事件
        """
        super().showEvent(event)
        self.refresh()
        if not self._timer.isActive():
            self._timer.start()

    def hideEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        """隐藏时停止采样。

        @param event - 隐藏事件
        """
        super().hideEvent(event)
        if self._timer.isActive():
            self._timer.stop()

    @property
    def timer_active(self) -> bool:
        """采样定时器是否在跑（测试用）。"""
        return self._timer.isActive()

    @property
    def rows(self) -> list[ProcessRow]:
        """最近一次采样（测试用）。"""
        return self._rows

    def summary_text(self) -> str:
        """合计文本（测试用）。

        @returns 文本
        """
        return self._summary.text()
