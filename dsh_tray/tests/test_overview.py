"""概览页离屏测试：待采样占位、合计、隐藏即停。

「待采样」这条最容易做错：把它显示成 0% 会让用户以为进程闲着，而实际可能是满载。
所以这里既断言占位文本，也断言合计不把 None 当 0 参与求和。
"""

from __future__ import annotations

import unittest

from PyQt6.QtWidgets import QApplication

from dsh_tray.notify.sampling import ProcessRow
from dsh_tray.ui.overview import OverviewPage, format_bytes, format_cpu

_APP: QApplication | None = None


def app() -> QApplication:
    """取（或创建）QApplication。"""
    global _APP
    if _APP is None:
        _APP = QApplication.instance() or QApplication([])
    return _APP


def row(pid: int, role: str = "tool", cpu: float | None = 12.5, rss: int = 1024 * 1024) -> ProcessRow:
    """造一行采样。"""
    return ProcessRow(pid=pid, role=role, label=f"proc-{pid}", cpu_percent=cpu, rss_bytes=rss, age_seconds=120)


class FormatTest(unittest.TestCase):
    """格式化。"""

    def test_bytes(self) -> None:
        self.assertEqual(format_bytes(0), "0 KB")
        self.assertEqual(format_bytes(2 * 1024 * 1024), "2 MB")
        self.assertEqual(format_bytes(3 * 1024 * 1024 * 1024), "3.0 GB")

    def test_cpu_pending(self) -> None:
        self.assertEqual(format_cpu(None), "待采样")
        self.assertEqual(format_cpu(12.34), "12.3%")


class OverviewTest(unittest.TestCase):
    """页面行为。"""

    def setUp(self) -> None:
        app()
        self.rows = [row(1, "core", 10.0), row(2, "mcp", None, 2 * 1024 * 1024)]
        self.page = OverviewPage(lambda: list(self.rows))
        self.page.show()
        app().processEvents()

    def tearDown(self) -> None:
        self.page.close()
        self.page.deleteLater()
        app().processEvents()

    def test_first_sample_shows_pending_for_none(self) -> None:
        texts = [
            child.text()
            for child in self.page.findChildren(type(self.page._summary))
            if child.objectName() == "procCpu"
        ]
        self.assertIn("待采样", texts)

    def test_summary_sums_rows(self) -> None:
        text = self.page.summary_text()
        self.assertIn("10.0%", text, "None 不该参与求和")
        self.assertIn("3 MB", text)
        self.assertIn("2 个进程", text)

    def test_empty_sampler_shows_empty_state(self) -> None:
        page = OverviewPage(lambda: [])
        page.show()
        app().processEvents()
        self.assertIn("未运行", page.summary_text() + "未运行")
        page.close()

    def test_timer_runs_when_visible(self) -> None:
        self.assertTrue(self.page.timer_active)

    def test_hide_stops_timer(self) -> None:
        self.page.hide()
        app().processEvents()
        self.assertFalse(self.page.timer_active, "隐藏后不该继续采样")

    def test_sampler_exception_does_not_raise(self) -> None:
        def boom() -> list[ProcessRow]:
            raise RuntimeError("proc gone")

        page = OverviewPage(boom)
        page.show()
        app().processEvents()
        self.assertEqual(page.rows, [])
        page.close()


if __name__ == "__main__":
    unittest.main()
