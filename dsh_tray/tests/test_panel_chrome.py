"""面板外框测试：关闭按钮与底栏。

覆盖 FR-008~FR-011（关闭按钮）与 FR-013~FR-015（底栏）。

全部离屏断言。`QT_QPA_PLATFORM=offscreen` 下 widget 可实例化且布局会真实计算，
所以「按钮在左半边还是右半边」这种几何断言是可信的。
"""

from __future__ import annotations

import time
import unittest

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from dsh_tray.lifecycle import Instance, State
from dsh_tray.ui.panel import PANEL_WIDTH, Panel


def setUpModule() -> None:
    """整模块共用一个 QApplication。"""
    global _app
    _app = QApplication.instance() or QApplication([])


class CloseButtonTest(unittest.TestCase):
    """FR-008~FR-011。"""

    def setUp(self) -> None:
        self.panel = Panel()
        self.panel.resize(PANEL_WIDTH, 400)

    def tearDown(self) -> None:
        self.panel.deleteLater()

    def test_has_close_button(self) -> None:
        self.assertIsNotNone(self.panel.close_button)

    def test_close_button_visible(self) -> None:
        self.panel.show()
        self.assertTrue(self.panel.close_button.isVisible())

    def test_has_pointing_hand_cursor(self) -> None:
        """无边框窗口没有这个提示，用户不会知道这里可点。"""
        self.assertEqual(
            self.panel.close_button.cursor().shape(),
            Qt.CursorShape.PointingHandCursor,
        )

    def test_close_button_on_right_half(self) -> None:
        """FR-008：位于标题栏右侧。"""
        self.panel.show()
        QApplication.processEvents()
        button = self.panel.close_button
        center_x = button.mapTo(self.panel, button.rect().center()).x()
        self.assertGreater(center_x, self.panel.width() / 2)

    def test_click_hides_panel(self) -> None:
        """FR-009：点击收起面板。"""
        self.panel.show()
        QApplication.processEvents()
        self.assertTrue(self.panel.isVisible())
        self.panel.close_button.click()
        QApplication.processEvents()
        self.assertFalse(self.panel.isVisible())

    def test_click_hides_within_200ms(self) -> None:
        """SC-003：200 毫秒内不可见。"""
        self.panel.show()
        QApplication.processEvents()
        start = time.monotonic()
        self.panel.close_button.click()
        QApplication.processEvents()
        elapsed = time.monotonic() - start
        self.assertFalse(self.panel.isVisible())
        self.assertLess(elapsed, 0.2, f"关闭耗时 {elapsed:.3f}s")

    def test_click_does_not_quit_application(self) -> None:
        """FR-010：关闭按钮只收面板，不退出应用。

        原来断言 `assertIsNotNone(QApplication.instance())`——测试进程里它永远
        非 None，是恒真断言。改为监视 `aboutToQuit` 信号是否被触发。
        """
        fired: list[bool] = []
        app = QApplication.instance()
        app.aboutToQuit.connect(lambda: fired.append(True))
        try:
            self.panel.show()
            QApplication.processEvents()
            self.panel.close_button.click()
            QApplication.processEvents()
            self.assertFalse(self.panel.isVisible())
            self.assertTrue(self.panel.isHidden(), "应为隐藏而非销毁")
            self.assertEqual(fired, [], "关闭按钮不应触发应用退出")
        finally:
            try:
                app.aboutToQuit.disconnect()
            except TypeError:
                pass


class FooterTest(unittest.TestCase):
    """FR-013~FR-015。"""

    def setUp(self) -> None:
        self.panel = Panel()
        self.panel.resize(PANEL_WIDTH, 400)

    def tearDown(self) -> None:
        self.panel.deleteLater()

    def test_has_footer(self) -> None:
        self.assertIsNotNone(self.panel.footer)

    def test_running_shows_four_items(self) -> None:
        """SC-004：PID、端口、启动方式、令牌四项齐全。"""
        instance = Instance(pid=4512, port=3080, owned=True, url="http://127.0.0.1:3080/?token=x")
        self.panel.set_status(State.RUNNING, instance, "", 3080)
        text = self.panel.footer.text()
        self.assertIn("PID 4512", text)
        self.assertIn("端口 3080", text)
        self.assertIn("由托盘启动", text)
        self.assertIn("带令牌", text)

    def test_stopped_has_no_pid(self) -> None:
        """FR-014。"""
        self.panel.set_status(State.STOPPED, None, "", 3080)
        self.assertNotIn("PID", self.panel.footer.text())

    def test_adopted_is_distinguishable(self) -> None:
        """FR-015。"""
        instance = Instance(pid=8801, port=3080, owned=False, url=None)
        self.panel.set_status(State.RUNNING, instance, "", 3080)
        text = self.panel.footer.text()
        self.assertIn("外部启动", text)
        self.assertIn("无令牌", text)

    def test_title_shows_status_not_fixed_text(self) -> None:
        """FR-012：标题行显示运行状态。"""
        self.panel.set_status(State.RUNNING, None, "", 3080)
        self.assertIn("运行中", self.panel.title_text)

    def test_title_has_no_pid(self) -> None:
        """FR-012：标题行不显示 PID。"""
        instance = Instance(pid=4512, port=3080, owned=True, url=None)
        self.panel.set_status(State.RUNNING, instance, "", 3080)
        self.assertNotIn("4512", self.panel.title_text)

    def test_title_and_footer_agree(self) -> None:
        """FR-016：两处不出现矛盾结论（都在说运行中）。"""
        instance = Instance(pid=4512, port=3080, owned=True, url=None)
        self.panel.set_status(State.RUNNING, instance, "", 3080)
        self.assertIn("运行中", self.panel.title_text)
        self.assertIn("PID 4512", self.panel.footer.text())

    def test_footer_height_affects_panel_height(self) -> None:
        """底栏要计入总高度，否则列表最后一条会被截掉。

        必须用 `assertGreater` 并断言差值：原来写 `assertGreaterEqual` 时，
        把 `_footer_height()` 改成恒返回 0 测试依然通过——底栏完全不计入高度
        也测不出来。
        """
        self.panel.set_rows_visible(5)
        height_with = self.panel.height()
        footer_height = self.panel._footer_height()
        self.assertGreater(footer_height, 0, "底栏高度应为正")

        self.panel.footer.hide()
        self.panel.apply_height()
        height_without = self.panel.height()

        self.assertGreater(height_with, height_without, "有底栏时必须更高")
        self.assertEqual(height_with - height_without, footer_height)


if __name__ == "__main__":
    unittest.main()
