"""通知动作按钮的开关：平台默认与用户覆盖。

为什么要有这条：`with_actions=True` 在 Plasma 上会让整条通知不渲染。默认值搞反
等于在主力平台上静默关掉通知，而失败表现是「什么都没发生」，极难察觉。
"""

from __future__ import annotations

import sys
import unittest
from unittest import mock

from dsh_tray.notify.delivery import build_gdbus_command
from dsh_tray.notify.types import SCHEMA_VERSION, TraySettings


class CommandActionsTest(unittest.TestCase):
    """命令行里的 actions 参数。"""

    def _actions_arg(self, with_actions: bool) -> str:
        entry = {"title": "标题", "body": "正文", "urgency": "normal"}
        argv = build_gdbus_command(entry, 0, with_actions=with_actions)
        # actions 是 body 之后那个位置参数：hints 的 `{}` 之前。
        return argv[argv.index("{}") - 1]

    def test_actions_present_when_enabled(self) -> None:
        self.assertIn("default", self._actions_arg(True))

    def test_actions_empty_when_disabled(self) -> None:
        self.assertEqual(self._actions_arg(False), "[]", "关闭时必须传空数组，而不是省略参数")


class PlatformDefaultTest(unittest.TestCase):
    """`auto` 的平台默认值。"""

    def _enabled(self, mode: str, platform: str) -> bool:
        from dsh_tray.ui import tray as tray_module

        settings = TraySettings(
            v=SCHEMA_VERSION,
            ts=None,  # type: ignore[arg-type] - 本用例不关心时刻
            rows_visible=5,
            banner_click="panel",
            notification_actions=mode,
        )
        fake_consumer = mock.Mock()
        fake_consumer.tray_settings = settings
        with mock.patch.object(tray_module.sys, "platform", platform):
            return tray_module.TrayApp._actions_enabled(mock.Mock(_consumer=fake_consumer))

    def test_linux_defaults_to_off(self) -> None:
        self.assertFalse(self._enabled("auto", "linux"), "Plasma 上带 actions 会整条不显示")

    def test_other_platforms_default_to_on(self) -> None:
        self.assertTrue(self._enabled("auto", "win32"))
        self.assertTrue(self._enabled("auto", "darwin"))

    def test_user_override_wins(self) -> None:
        self.assertTrue(self._enabled("on", "linux"), "用户强制开启时应生效")
        self.assertFalse(self._enabled("off", "win32"), "用户强制关闭时应生效")


if __name__ == "__main__":
    unittest.main()
