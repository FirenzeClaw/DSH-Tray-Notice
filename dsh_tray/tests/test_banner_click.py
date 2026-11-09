"""点击横幅的分流：去面板还是直接进会话。

为什么要测：两条路径都会写历史、都涉及浏览器，走错一边的表现是「点了没反应」
或「跳错地方」，而这两种都不会报错。
"""

from __future__ import annotations

import unittest
from unittest import mock

from dsh_tray.notify.types import SCHEMA_VERSION, TraySettings


def settings_with(mode: str) -> TraySettings:
    """构造只有 banner_click 有意义的一份设置。

    @param mode - `panel` 或 `session`
    @returns 设置对象
    """
    return TraySettings(v=SCHEMA_VERSION, ts=None, rows_visible=5, banner_click=mode)  # type: ignore[arg-type]


class BannerClickTest(unittest.TestCase):
    """两种模式的分流。"""

    def _run(self, mode: str):
        from dsh_tray.ui import tray as tray_module

        fake = mock.Mock()
        fake._notified = {7: "session-1"}
        fake._notified_entry = {7: "entry-1"}
        fake._consumer.tray_settings = settings_with(mode)
        fake.toggle_panel = mock.Mock()

        with mock.patch.object(tray_module, "history") as fake_history, \
                mock.patch.object(tray_module, "handle_click") as fake_click:
            tray_module.TrayApp._on_notification_action(fake, 7, "default")
        return fake, fake_history, fake_click

    def test_panel_mode_marks_read_and_opens_panel(self) -> None:
        fake, fake_history, fake_click = self._run("panel")
        fake_history.mark_read.assert_called_once_with("entry-1")
        fake.toggle_panel.assert_called_once()
        fake_click.assert_not_called()

    def test_session_mode_goes_straight_to_session(self) -> None:
        fake, fake_history, fake_click = self._run("session")
        fake_click.assert_called_once()
        fake.toggle_panel.assert_not_called()

    def test_unknown_notification_is_ignored(self) -> None:
        from dsh_tray.ui import tray as tray_module

        fake = mock.Mock()
        fake._notified = {}
        fake._notified_entry = {}
        fake._consumer.tray_settings = settings_with("panel")
        with mock.patch.object(tray_module, "handle_click") as fake_click:
            tray_module.TrayApp._on_notification_action(fake, 99, "default")
        fake_click.assert_not_called()


if __name__ == "__main__":
    unittest.main()
