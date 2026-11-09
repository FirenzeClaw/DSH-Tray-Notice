"""回归：面板不该在弹出瞬间的 focusOut 上自我隐藏。

为什么要有这条：面板设了 `WA_ShowWithoutActivating`，而 Wayland 下 `Qt.Tool`
常常拿不到焦点，`isActiveWindow()` 恒为假。旧实现在显示后约 120 ms 就据此隐藏，
表现为「点托盘没反应」——左键与右键菜单两条入口全部失效。
"""

from __future__ import annotations

import time
import unittest

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


class GracePeriodTest(unittest.TestCase):
    """宽限期内不隐藏，过期后才按失焦收起。"""

    def test_visible_during_grace_period(self) -> None:
        from dsh_tray.ui.panel import Panel

        app()
        panel = Panel()
        panel.show_at(10, 10)
        try:
            panel._hide_if_inactive()  # 离屏下 isActiveWindow() 恒假
            self.assertTrue(panel.isVisible(), "宽限期内不应隐藏")
        finally:
            panel.hide()

    def test_hides_after_grace_period_if_inactive(self) -> None:
        from dsh_tray.ui.panel import Panel

        app()
        panel = Panel()
        panel.show_at(10, 10)
        try:
            panel._ignore_focus_out_until = time.monotonic() - 1
            panel._hide_if_inactive()
            self.assertFalse(panel.isVisible(), "宽限期过后失焦应隐藏")
        finally:
            panel.hide()


if __name__ == "__main__":
    unittest.main()
