"""历史与消费循环的联合测试：原子写、淘汰、分组、已读。

「已查看不删除」是产品决策，不是实现细节——所以这里既断言删除行为（clear_read
只清已读），也断言保留行为（mark_read 之后条目仍在文件里）。
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from dsh_tray.notify import history
from dsh_tray.notify.types import NotificationEntry

NOW = datetime(2026, 11, 6, 12, 0, 0, tzinfo=timezone.utc)


def entry(entry_id: str, ts: datetime = NOW, kind: str = "done") -> NotificationEntry:
    """造一条通知。"""
    payload = {
        "v": 1,
        "type": "notification",
        "id": entry_id,
        "ts": ts.isoformat(),
        "kind": kind,
        "sessionId": "s-1",
        "sessionTitle": "通知面板设计",
        "title": "已完成",
        "body": "跑完了",
        "urgency": "normal",
        "openUrl": "http://127.0.0.1:3080/?session=s-1",
        "dedupeKey": f"done:s-1:{entry_id}",
    }
    parsed = NotificationEntry.from_json(payload)
    assert parsed is not None
    return parsed


class HistoryTestBase(unittest.TestCase):
    """把历史文件重定向到临时目录。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        patcher = mock.patch.object(history, "history_path", return_value=self.root / "notifications.json")
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self) -> None:
        self._tmp.cleanup()


class AppendTest(HistoryTestBase):
    """写入与读回。"""

    def test_append_then_load(self) -> None:
        history.append(entry("id-1"), now=NOW)
        items = history.load()
        self.assertEqual([item.entry.id for item in items], ["id-1"])
        self.assertFalse(items[0].read)

    def test_duplicate_id_ignored(self) -> None:
        history.append(entry("id-1"), now=NOW)
        history.append(entry("id-1"), now=NOW)
        self.assertEqual(len(history.load()), 1)

    def test_file_permissions_are_0600(self) -> None:
        history.append(entry("id-1"), now=NOW)
        mode = os.stat(self.root / "notifications.json").st_mode & 0o777
        self.assertEqual(mode, 0o600)

    def test_atomic_write_leaves_no_temp(self) -> None:
        history.append(entry("id-1"), now=NOW)
        self.assertEqual(list(self.root.glob("*.tmp")), [])

    def test_corrupt_file_reads_as_empty(self) -> None:
        (self.root / "notifications.json").write_text("{not json", encoding="utf-8")
        self.assertEqual(history.load(), [])


class PruneTest(HistoryTestBase):
    """淘汰规则。"""

    def test_cap_at_500(self) -> None:
        items = [entry(f"id-{index}", ts=NOW - timedelta(minutes=index)) for index in range(510)]
        for item in items:
            history.append(item, now=NOW)
        self.assertEqual(len(history.load()), history.MAX_ENTRIES)

    def test_old_entries_expire(self) -> None:
        old = NOW - timedelta(days=history.MAX_AGE_DAYS + 1)
        history.append(entry("id-old", ts=old), now=NOW)
        history.append(entry("id-new"), now=NOW)
        ids = [item.entry.id for item in history.load()]
        self.assertEqual(ids, ["id-new"])


class ReadStateTest(HistoryTestBase):
    """已读标记。"""

    def test_mark_read_keeps_entry(self) -> None:
        history.append(entry("id-1"), now=NOW)
        self.assertTrue(history.mark_read("id-1"))
        items = history.load()
        self.assertEqual(len(items), 1, "标记已读不该删除条目")
        self.assertTrue(items[0].read)

    def test_mark_read_unknown_returns_false(self) -> None:
        self.assertFalse(history.mark_read("nope"))

    def test_mark_all_read(self) -> None:
        history.append(entry("id-1"), now=NOW)
        history.append(entry("id-2"), now=NOW)
        self.assertEqual(history.mark_all_read(now=NOW), 2)
        self.assertEqual(history.unread_count(), 0)

    def test_clear_read_only_removes_read(self) -> None:
        history.append(entry("id-read"), now=NOW)
        history.append(entry("id-unread"), now=NOW)
        history.mark_read("id-read")

        removed = history.clear_read(now=NOW)
        self.assertEqual(removed, 1)
        ids = [item.entry.id for item in history.load()]
        self.assertEqual(ids, ["id-unread"])

    def test_test_kind_not_counted_as_unread(self) -> None:
        history.append(entry("id-test", kind="test"), now=NOW)
        self.assertEqual(history.unread_count(), 0)


class GroupingTest(HistoryTestBase):
    """日期分组。"""

    def test_groups_today_yesterday_earlier(self) -> None:
        local_now = NOW.astimezone()
        history.append(entry("id-today", ts=local_now), now=NOW)
        history.append(entry("id-yesterday", ts=local_now - timedelta(days=1)), now=NOW)
        history.append(entry("id-earlier", ts=local_now - timedelta(days=20)), now=NOW)

        groups = history.group_by_day(now=NOW)
        labels = [label for label, _ in groups]
        self.assertIn("今天", labels)
        self.assertIn("昨天", labels)
        self.assertTrue(any(label.startswith("2026-") for label in labels))

    def test_groups_sorted_newest_first(self) -> None:
        local_now = NOW.astimezone()
        history.append(entry("id-old", ts=local_now - timedelta(days=20)), now=NOW)
        history.append(entry("id-today", ts=local_now), now=NOW)
        groups = history.group_by_day(now=NOW)
        self.assertEqual(groups[0][0], "今天")


if __name__ == "__main__":
    unittest.main()
