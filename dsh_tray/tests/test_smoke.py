"""骨架 smoke 测试：证明包结构可导入，且关键常量没被改动。

为什么要有这条：`dsh_tray.notify` 与 `dsh_tray.platform` 都被设计成「不 import Qt」，
而这条约束只能靠「在没有 DISPLAY 的环境里导入成功」来证明。CI 与本地
`--selftest` 之外，这是最便宜的一条回归线。
"""

from __future__ import annotations

import unittest


class PackageImportTest(unittest.TestCase):
    """包结构与常量。"""

    def test_default_port_is_3080(self) -> None:
        from dsh_tray.lifecycle import DEFAULT_PORT

        self.assertEqual(DEFAULT_PORT, 3080)

    def test_notify_package_imports_without_qt(self) -> None:
        import dsh_tray.notify as notify

        self.assertEqual(notify.SPOOL_FILENAME, "events.jsonl")
        self.assertEqual(notify.DEFAULT_POLL_INTERVAL_MS, 500)

    def test_platform_package_imports_without_qt(self) -> None:
        import dsh_tray.platform as platform

        self.assertIn(platform.current_platform(), {"linux", "windows", "darwin"})

    def test_ui_package_imports_without_qt(self) -> None:
        import dsh_tray.ui as ui

        self.assertIn("panel", ui.__all__)


if __name__ == "__main__":
    unittest.main()
