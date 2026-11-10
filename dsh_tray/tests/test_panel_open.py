"""回归：托盘左键必须能打开面板。

为什么要有这条：`QSystemTrayIcon` 在 PyQt6 中没有 `screen()`，曾直接写成
`self._tray.screen()`，导致左键与右键菜单「打开面板」两条路径都抛
AttributeError——面板完全打不开，而当时没有任何测试覆盖这一行。
这里断言 `toggle_panel()` 端到端不抛异常且面板可见。
"""

from __future__ import annotations

import unittest

from PyQt6.QtCore import QRect
from PyQt6.QtWidgets import QApplication

_APP: QApplication | None = None


def app() -> QApplication:
    """取（或创建）QApplication。

    @returns 应用实例
    """
    global _APP
    if _APP is None:
        _APP = QApplication.instance() or QApplication([])
    return _APP


class ResolveScreenTest(unittest.TestCase):
    """按几何反查屏幕。"""

    def test_returns_screen_for_zero_geometry(self) -> None:
        from dsh_tray.ui.tray import resolve_screen

        app()
        self.assertIsNotNone(resolve_screen(QRect(0, 0, 0, 0)), "几何为 0×0 时也必须给出屏幕")

    def test_returns_screen_for_normal_geometry(self) -> None:
        from dsh_tray.ui.tray import resolve_screen

        app()
        self.assertIsNotNone(resolve_screen(QRect(100, 100, 24, 24)))


class TogglePanelTest(unittest.TestCase):
    """端到端：调 toggle_panel 必须不抛异常，且面板可见。"""

    def test_toggle_panel_opens_without_error(self) -> None:
        from dsh_tray.ui.tray import TrayApp

        app()
        lifecycle = _StubLifecycle()
        tray = TrayApp(lifecycle, lambda: None)
        try:
            tray.toggle_panel()  # 旧实现会在这里抛 AttributeError
            app().processEvents()
            self.assertIsNotNone(tray._panel, "面板应已创建")
            self.assertTrue(tray._panel.isVisible(), "面板应可见")
        finally:
            if tray._panel is not None:
                tray._panel.hide()


class _StubLifecycle:
    """最小生命周期替身：托盘只需要 poll() 与两个属性。"""

    from dsh_tray.lifecycle import State as _State

    state = _State.STOPPED
    instance = None
    last_error = ""
    port = 3080

    def poll(self):
        return self.state, self.instance

    def start(self, *args, **kwargs):
        raise AssertionError("测试不应触发启动")

    def stop(self):
        raise AssertionError("测试不应触发停止")


if __name__ == "__main__":
    unittest.main()
