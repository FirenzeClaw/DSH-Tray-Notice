"""面板离屏测试：标签等宽、文字居中、五态按钮、未读角标。

离屏跑（`QT_QPA_PLATFORM=offscreen`）：实测该后端下 widget 可实例化、`isVisible()`
返回真、布局会真正计算，因此这些断言是可靠的，不依赖人工目测。

为什么先 `show()`：不显示时 Qt 不跑布局，所有控件宽度都是默认值，断言会假通过。
"""

from __future__ import annotations

import unittest

from PyQt6.QtWidgets import QApplication

from dsh_tray.lifecycle import State
from dsh_tray.ui.control import ControlArea
from dsh_tray.ui.panel import TAB_LABELS, Panel

#: 进程内只创建一次 QApplication。
_APP: QApplication | None = None


def app() -> QApplication:
    """取（或创建）QApplication。

    @returns 应用实例
    """
    global _APP
    if _APP is None:
        _APP = QApplication.instance() or QApplication([])
    return _APP


class PanelTestBase(unittest.TestCase):
    """公共夹具。"""

    def setUp(self) -> None:
        app()
        self.panel = Panel()
        self.control = ControlArea()
        self.panel.set_control(self.control)
        self.panel.show()
        app().processEvents()

    def tearDown(self) -> None:
        self.panel.close()
        self.panel.deleteLater()
        app().processEvents()


class TabLayoutTest(PanelTestBase):
    """标签均分与居中。"""

    def test_four_tabs_exist(self) -> None:
        self.assertEqual([button.text() for button in self.panel.tabs._buttons], list(TAB_LABELS))

    def test_tabs_are_equal_width(self) -> None:
        widths = [button.width() for button in self.panel.tabs._buttons]
        self.assertLessEqual(max(widths) - min(widths), 1, f"宽度不一致：{widths}")

    def test_tabs_span_panel_width(self) -> None:
        total = sum(button.width() for button in self.panel.tabs._buttons)
        self.assertLessEqual(abs(total - self.panel.width()), 2, f"总宽 {total} vs 面板 {self.panel.width()}")

    def test_text_stays_centered_with_count(self) -> None:
        before = [button.geometry() for button in self.panel.tabs._buttons]
        self.panel.set_counts(unread=12, read=3, working=1)
        app().processEvents()
        after = [button.geometry() for button in self.panel.tabs._buttons]
        self.assertEqual(before, after, "计数出现后标签几何不应改变")

    def test_badge_hidden_at_zero(self) -> None:
        self.panel.set_counts(unread=0, read=0, working=0)
        app().processEvents()
        self.assertFalse(self.panel.tabs._badges[0].isVisible())

    def test_badge_visible_when_positive(self) -> None:
        self.panel.set_counts(unread=3, read=0, working=0)
        app().processEvents()
        self.assertTrue(self.panel.tabs._badges[0].isVisible())
        self.assertEqual(self.panel.tabs._badges[0].text(), "3")

    def test_live_dot_follows_working(self) -> None:
        self.panel.set_counts(unread=0, read=0, working=2)
        app().processEvents()
        self.assertTrue(self.panel.tabs._dots[2].isVisible())
        self.panel.set_counts(unread=0, read=0, working=0)
        app().processEvents()
        self.assertFalse(self.panel.tabs._dots[2].isVisible())

    def test_switching_tab_updates_stack(self) -> None:
        self.panel.tabs.set_current(2)
        app().processEvents()
        self.assertEqual(self.panel.stack.currentIndex(), 2)


class ControlStateTest(PanelTestBase):
    """五态渲染。"""

    def test_stopped_enables_start_only(self) -> None:
        self.control.render(State.STOPPED, None, "")
        self.assertTrue(self.control._primary.isEnabled())
        self.assertFalse(self.control._action_open.isEnabled())
        self.assertFalse(self.control._stop.isEnabled())
        self.assertFalse(self.control._restart.isEnabled())

    def test_starting_disables_everything(self) -> None:
        self.control.render(State.STARTING, None, "")
        for widget in (self.control._primary, self.control._action_open, self.control._stop, self.control._restart):
            self.assertFalse(widget.isEnabled(), f"{widget.objectName()} 应禁用")

    def test_running_owned_shows_open(self) -> None:
        instance = _instance(owned=True)
        self.control.render(State.RUNNING, instance, "")
        self.assertTrue(self.control._action_open.isEnabled())
        self.assertTrue(self.control._restart.isEnabled())
        self.assertTrue(self.control._stop.isEnabled())
        self.assertFalse(self.control._hint.isVisible(), "自有实例不该显示令牌提示")

    def test_running_adopted_shows_hint(self) -> None:
        instance = _instance(owned=False)
        self.control.render(State.RUNNING, instance, "")
        self.assertTrue(self.control._hint.isVisible(), "接管态应提示拿不到令牌")

    def test_stopping_disables(self) -> None:
        self.control.render(State.STOPPING, _instance(owned=True), "")
        self.assertFalse(self.control._action_open.isEnabled())
        self.assertFalse(self.control._stop.isEnabled())

    def test_failed_shows_reason(self) -> None:
        self.control.render(State.FAILED, None, "端口被占用")
        self.assertIn("端口被占用", self.control._meta.text())
        self.assertTrue(self.control._primary.isEnabled(), "失败后应允许重试")

    def test_busy_disables(self) -> None:
        self.control.render(State.RUNNING, _instance(owned=True), "", busy=True)
        self.assertFalse(self.control._action_open.isEnabled())


class MissedHintTest(PanelTestBase):
    """「错过 N 条」提示。"""

    def test_hidden_by_default(self) -> None:
        self.assertFalse(self.panel._missed.isVisible())

    def test_shows_count(self) -> None:
        self.panel.set_missed(3)
        app().processEvents()
        self.assertTrue(self.panel._missed.isVisible())
        self.assertIn("3", self.panel._missed.text())

    def test_clears_at_zero(self) -> None:
        self.panel.set_missed(2)
        self.panel.set_missed(0)
        app().processEvents()
        self.assertFalse(self.panel._missed.isVisible())


def _instance(owned: bool):
    """造一个实例。"""
    from dsh_tray.lifecycle import Instance

    return Instance(pid=1234, port=3080, owned=owned, url="http://127.0.0.1:3080/?token=t" if owned else None)


if __name__ == "__main__":
    unittest.main()
