"""托盘外观设置：经 spool 下发、解析、应用到面板。

为什么单独测：这三项设置走一条新加的 spool 行类型（`tray-settings`），
而托盘侧此前只认两种行。回归点在于「未知字段/越界值不能让 set_rows_visible
拿到非法值」，否则面板高度会算成负数。
"""

from __future__ import annotations

import unittest

from dsh_tray.notify.types import SCHEMA_VERSION, TraySettings, parse_row


class TraySettingsParseTest(unittest.TestCase):
    """解析与钳制。"""

    def test_parses_full_row(self) -> None:
        row = parse_row(
            {
                "v": SCHEMA_VERSION,
                "type": "tray-settings",
                "ts": "2026-11-09T10:00:00Z",
                "rowsVisible": 7,
                "bannerClick": "session",
                "notificationActions": "off",
            }
        )
        self.assertIsInstance(row, TraySettings)
        assert isinstance(row, TraySettings)
        self.assertEqual(row.rows_visible, 7)
        self.assertEqual(row.banner_click, "session")
        self.assertEqual(row.notification_actions, "off")

    def test_clamps_rows_visible(self) -> None:
        def rows(value):
            parsed = parse_row(
                {"v": SCHEMA_VERSION, "type": "tray-settings", "ts": "2026-11-09T10:00:00Z", "rowsVisible": value}
            )
            assert isinstance(parsed, TraySettings)
            return parsed.rows_visible

        self.assertEqual(rows(99), 12, "上限 12")
        self.assertEqual(rows(1), 3, "下限 3")
        self.assertEqual(rows("5"), 5, "非整数退回默认")

    def test_unknown_enum_falls_back(self) -> None:
        row = parse_row(
            {
                "v": SCHEMA_VERSION,
                "type": "tray-settings",
                "ts": "2026-11-09T10:00:00Z",
                "bannerClick": "nonsense",
                "notificationActions": "nonsense",
            }
        )
        assert isinstance(row, TraySettings)
        self.assertEqual(row.banner_click, "panel")
        self.assertEqual(row.notification_actions, "auto")

    def test_rejects_wrong_version(self) -> None:
        self.assertIsNone(
            parse_row({"v": SCHEMA_VERSION + 1, "type": "tray-settings", "ts": "2026-11-09T10:00:00Z"})
        )

    def test_rejects_missing_ts(self) -> None:
        self.assertIsNone(parse_row({"v": SCHEMA_VERSION, "type": "tray-settings"}))


_APP = None


def app():
    """取（或创建）QApplication。

    @returns 应用实例
    """
    global _APP
    from PyQt6.QtWidgets import QApplication

    if _APP is None:
        _APP = QApplication.instance() or QApplication([])
    return _APP


class PanelRowsVisibleTest(unittest.TestCase):
    """面板高度随「露出几条」变化。"""

    def test_height_grows_with_rows(self) -> None:
        from dsh_tray.ui.panel import Panel

        app()
        panel = Panel()
        panel.show()
        try:
            heights = []
            for rows in (3, 5, 8):
                panel.set_rows_visible(rows)
                heights.append(panel.height())
            self.assertEqual(heights, sorted(heights), "条数越多面板越高")
            self.assertLess(heights[0], heights[-1])
        finally:
            panel.hide()


if __name__ == "__main__":
    unittest.main()
