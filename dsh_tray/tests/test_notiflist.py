"""通知列表与工作中页的离屏测试。

两条最容易回归的行为：点未查看条目后它要出现在已查看页且仍在历史文件里；
时长每秒自增但**不重建整页**（重建会丢滚动位置）。
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from PyQt6.QtWidgets import QApplication

from dsh_tray.notify import history
from dsh_tray.notify.sessionstate import SessionTable
from dsh_tray.notify.types import NotificationEntry, SessionState
from dsh_tray.ui.notiflist import NotificationListPage, read_count, unread_count
from dsh_tray.ui.working import WorkingPage

NOW = datetime(2026, 11, 6, 12, 0, 0, tzinfo=timezone.utc)

_APP: QApplication | None = None


def app() -> QApplication:
    """取（或创建）QApplication。"""
    global _APP
    if _APP is None:
        _APP = QApplication.instance() or QApplication([])
    return _APP


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


class HistoryRedirect(unittest.TestCase):
    """把历史文件重定向到临时目录。"""

    def setUp(self) -> None:
        app()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        patcher = mock.patch.object(history, "history_path", return_value=self.root / "notifications.json")
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self) -> None:
        self._tmp.cleanup()


class NotificationListTest(HistoryRedirect):
    """通知列表页。"""

    def test_unread_page_shows_unread_only(self) -> None:
        history.append(entry("a"), now=NOW)
        history.append(entry("b"), now=NOW)
        history.mark_read("a")

        page = NotificationListPage(only_unread=True)
        page.refresh()
        self.assertEqual(page.row_count(), 1)

    def test_read_page_shows_read_only(self) -> None:
        history.append(entry("a"), now=NOW)
        history.append(entry("b"), now=NOW)
        history.mark_read("a")

        page = NotificationListPage(only_unread=False)
        page.refresh()
        self.assertEqual(page.row_count(), 1)

    def test_mark_read_moves_entry_and_keeps_it(self) -> None:
        history.append(entry("a"), now=NOW)
        unread = NotificationListPage(only_unread=True)
        unread.refresh()
        self.assertEqual(unread.row_count(), 1)
        self.assertEqual(unread_count(), 1)

        unread._on_mark_read("a")

        self.assertEqual(unread.row_count(), 0, "已读后应从「未查看」消失")
        self.assertEqual(unread_count(), 0)
        self.assertEqual(len(history.load()), 1, "条目仍应存在于历史文件")

        read = NotificationListPage(only_unread=False)
        read.refresh()
        self.assertEqual(read.row_count(), 1, "应出现在「已查看」")

    def test_empty_page_shows_hint(self) -> None:
        page = NotificationListPage(only_unread=True)
        page.refresh()
        self.assertEqual(page.row_count(), 0)

    def test_read_page_groups_by_day(self) -> None:
        local_now = NOW.astimezone()
        for entry_id, delta in (("today", timedelta()), ("yesterday", timedelta(days=1)), ("old", timedelta(days=20))):
            history.append(entry(entry_id, ts=local_now - delta), now=NOW)
            history.mark_read(entry_id)

        page = NotificationListPage(only_unread=False)
        page.refresh()
        labels = page.group_labels()
        self.assertIn("今天", labels)
        self.assertIn("昨天", labels)
        self.assertEqual(page.row_count(), 3)

    def test_test_kind_excluded_from_counts(self) -> None:
        history.append(entry("t", kind="test"), now=NOW)
        self.assertEqual(unread_count(), 0)
        self.assertEqual(read_count(), 0)


def snapshot(*rows: dict[str, object]) -> SessionState:
    """造会话快照。"""
    parsed = SessionState.from_json(
        {"v": 1, "type": "session-state", "ts": NOW.isoformat(), "sessions": list(rows)}
    )
    assert parsed is not None
    return parsed


class WorkingPageTest(unittest.TestCase):
    """工作中页。"""

    def setUp(self) -> None:
        app()
        self.table = SessionTable()
        self.page = WorkingPage(self.table)
        self.page.show()
        app().processEvents()

    def tearDown(self) -> None:
        self.page.close()
        self.page.deleteLater()
        app().processEvents()

    def test_renders_rows(self) -> None:
        self.table.apply(
            snapshot(
                {"id": "a", "title": "会话 A", "state": "working", "turn": 2, "origin": "root",
                 "turnStartedAt": (NOW - timedelta(seconds=30)).isoformat()},
                {"id": "b", "title": "会话 B", "state": "working", "turn": 1, "origin": "root",
                 "turnStartedAt": (NOW - timedelta(seconds=90)).isoformat()},
            )
        )
        self.page.refresh()
        self.assertEqual(self.page.row_count(), 2)

    def test_timer_runs_with_rows(self) -> None:
        self.table.apply(
            snapshot({"id": "a", "title": "A", "state": "working", "turn": 1, "origin": "root",
                      "turnStartedAt": (NOW - timedelta(seconds=5)).isoformat()})
        )
        self.page.refresh()
        self.assertTrue(self.page.timer_active)

    def test_timer_stops_when_empty(self) -> None:
        self.table.apply(snapshot())
        self.page.refresh()
        self.assertFalse(self.page.timer_active)

    def test_hide_stops_timer(self) -> None:
        self.table.apply(
            snapshot({"id": "a", "title": "A", "state": "working", "turn": 1, "origin": "root",
                      "turnStartedAt": (NOW - timedelta(seconds=5)).isoformat()})
        )
        self.page.refresh()
        self.assertTrue(self.page.timer_active)
        self.page.hide()
        app().processEvents()
        self.assertFalse(self.page.timer_active, "隐藏后不该继续每秒回调")

    def test_elapsed_text_updates_without_rebuild(self) -> None:
        self.table.apply(
            snapshot({"id": "a", "title": "A", "state": "working", "turn": 1, "origin": "root",
                      "turnStartedAt": (NOW - timedelta(seconds=10)).isoformat()})
        )
        self.page.refresh()
        first_rows = list(self.page._rows)
        first_text = self.page.elapsed_texts()

        self.page._tick()
        self.assertEqual(self.page._rows, first_rows, "tick 不该重建行控件")
        self.assertEqual(len(self.page.elapsed_texts()), len(first_text))

    def test_waiting_session_marked(self) -> None:
        self.table.apply(
            snapshot({"id": "a", "title": "A", "state": "waiting-user", "turn": 1, "origin": "root",
                      "turnStartedAt": (NOW - timedelta(seconds=5)).isoformat()})
        )
        self.page.refresh()
        self.assertEqual(self.page.row_count(), 1)


if __name__ == "__main__":
    unittest.main()
