"""展示模型测试：去重窗口、紧急度映射、test 类别。

去重是「同一条事件被插件重发」与「用户真的想再看一次」之间的唯一分辨手段；
10 秒窗口是权衡：短了挡不住重复，长了会把连续两次真实事件合并掉。
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from dsh_tray.notify.intents import (
    DEDUPE_WINDOW_SECONDS,
    DisplayModel,
    to_display,
)
from dsh_tray.notify.types import NotificationEntry


def make_entry(**overrides: object) -> NotificationEntry:
    """造一条通知条目。"""
    base = {
        "v": 1,
        "type": "notification",
        "id": "id-1",
        "ts": "2026-11-06T11:40:00Z",
        "kind": "needs-approval",
        "sessionId": "s-1",
        "sessionTitle": "通知面板设计",
        "title": "需要你审批",
        "body": "Bash",
        "urgency": "critical",
        "openUrl": "http://127.0.0.1:3080/?session=s-1",
        "dedupeKey": "approval:appr_1",
    }
    base.update(overrides)
    return NotificationEntry.from_json(base)  # type: ignore[return-value]


class DedupeTest(unittest.TestCase):
    """去重窗口。"""

    def test_first_entry_accepted(self) -> None:
        model = DisplayModel()
        self.assertTrue(model.accept(make_entry()))

    def test_same_key_within_window_dropped(self) -> None:
        model = DisplayModel()
        first = make_entry()
        self.assertTrue(model.accept(first))

        second = make_entry(id="id-2")
        self.assertFalse(model.accept(second, now=first.ts + timedelta(seconds=5)))

    def test_same_key_after_window_accepted(self) -> None:
        model = DisplayModel()
        first = make_entry()
        model.accept(first)

        second = make_entry(id="id-2")
        self.assertTrue(model.accept(second, now=first.ts + timedelta(seconds=DEDUPE_WINDOW_SECONDS + 1)))

    def test_different_key_accepted_immediately(self) -> None:
        model = DisplayModel()
        model.accept(make_entry())
        other = make_entry(id="id-2", dedupeKey="approval:appr_2")
        self.assertTrue(model.accept(other))

    def test_window_is_ten_seconds(self) -> None:
        self.assertEqual(DEDUPE_WINDOW_SECONDS, 10)


class UrgencyTest(unittest.TestCase):
    """紧急度映射。"""

    def test_critical_maps_to_zero_timeout(self) -> None:
        display = to_display(make_entry())
        self.assertTrue(display.critical)
        self.assertEqual(display.expire_timeout_ms, 0)

    def test_normal_uses_system_default(self) -> None:
        display = to_display(make_entry(urgency="normal", kind="done"))
        self.assertFalse(display.critical)
        self.assertGreater(display.expire_timeout_ms, 0)


class DisplayFieldsTest(unittest.TestCase):
    """展示字段。"""

    def test_relative_time_minutes(self) -> None:
        entry = make_entry()
        later = entry.ts + timedelta(minutes=3)
        display = to_display(entry, now=later)
        self.assertEqual(display.relative_time, "3 分钟前")

    def test_relative_time_just_now(self) -> None:
        entry = make_entry()
        display = to_display(entry, now=entry.ts + timedelta(seconds=20))
        self.assertEqual(display.relative_time, "刚刚")

    def test_relative_time_hours_and_days(self) -> None:
        entry = make_entry()
        self.assertEqual(to_display(entry, now=entry.ts + timedelta(hours=2)).relative_time, "2 小时前")
        self.assertEqual(to_display(entry, now=entry.ts + timedelta(days=2)).relative_time, "2 天前")

    def test_category_label_mapping(self) -> None:
        self.assertEqual(to_display(make_entry(kind="needs-approval")).category, "需要你")
        self.assertEqual(to_display(make_entry(kind="needs-answer")).category, "需要你")
        self.assertEqual(to_display(make_entry(kind="done")).category, "完成")
        self.assertEqual(to_display(make_entry(kind="error")).category, "出错")
        self.assertEqual(to_display(make_entry(kind="notice")).category, "提示")
        self.assertEqual(to_display(make_entry(kind="job")).category, "其它")

    def test_test_kind_is_marked_and_not_counted(self) -> None:
        display = to_display(make_entry(kind="test"))
        self.assertTrue(display.is_test)
        self.assertFalse(display.counts_toward_unread)


class TestKindTest(unittest.TestCase):
    """`kind:"test"` 的统计语义。"""

    def test_test_entry_not_counted_in_unread(self) -> None:
        model = DisplayModel()
        model.accept(make_entry(kind="test"))
        self.assertEqual(model.unread_count, 0)

    def test_normal_entry_counted(self) -> None:
        model = DisplayModel()
        model.accept(make_entry())
        self.assertEqual(model.unread_count, 1)


if __name__ == "__main__":
    unittest.main()
