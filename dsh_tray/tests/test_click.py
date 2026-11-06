"""点击处理的测试：顺序、失败路径、不记令牌。

顺序断言用「记录调用序列」的方式做：`mark_read` 与 opener 都换成记录器，
断言 mark_read 先发生。这条顺序错了不会让任何功能报错，只会让面板的未读数
在打开浏览器的瞬间看起来「没反应」。
"""

from __future__ import annotations

import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest import mock

from dsh_tray.notify import click, history
from dsh_tray.notify.log import Logger
from dsh_tray.notify.types import NotificationEntry


@dataclass
class FakeInstance:
    """实例投影。"""

    pid: int
    port: int
    owned: bool


def make_entry(entry_id: str = "id-1") -> NotificationEntry:
    """造一条通知。"""
    payload = {
        "v": 1,
        "type": "notification",
        "id": entry_id,
        "ts": "2026-11-06T11:40:00Z",
        "kind": "needs-approval",
        "sessionId": "session-1",
        "sessionTitle": "通知面板设计",
        "title": "需要你审批",
        "body": "Bash",
        "urgency": "critical",
        "openUrl": "http://127.0.0.1:3080/?session=session-1",
        "dedupeKey": "approval:appr_1",
    }
    parsed = NotificationEntry.from_json(payload)
    assert parsed is not None
    return parsed


class ClickTestBase(unittest.TestCase):
    """把历史文件重定向到临时目录。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        patcher = mock.patch.object(history, "history_path", return_value=self.root / "notifications.json")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.logger = Logger(None, "test")
        self.calls: list[str] = []

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def opener(self, ok: bool = True):
        """记录打开调用的 opener。"""

        def open_url(url: str) -> bool:
            self.calls.append(f"open:{url}")
            return ok

        return open_url


class OrderTest(ClickTestBase):
    """调用顺序。"""

    def test_mark_read_before_open(self) -> None:
        entry = make_entry()
        history.append(entry)

        real_mark = history.mark_read
        sequence: list[str] = []

        def tracking_mark(entry_id: str) -> bool:
            sequence.append("mark_read")
            return real_mark(entry_id)

        def tracking_open(url: str) -> bool:
            sequence.append("open")
            return True

        with mock.patch.object(history, "mark_read", side_effect=tracking_mark):
            click.handle_click(entry.id, entry.session_id, FakeInstance(1, 3080, False), self.logger, tracking_open)

        self.assertEqual(sequence, ["mark_read", "open"])

    def test_entry_is_read_after_click(self) -> None:
        entry = make_entry()
        history.append(entry)
        click.handle_click(entry.id, entry.session_id, FakeInstance(1, 3080, False), self.logger, self.opener())
        items = history.load()
        self.assertTrue(items[0].read)


class FailureTest(ClickTestBase):
    """失败路径。"""

    def test_opener_failure_returns_false_but_marks_read(self) -> None:
        entry = make_entry()
        history.append(entry)
        ok = click.handle_click(
            entry.id, entry.session_id, FakeInstance(1, 3080, False), self.logger, self.opener(ok=False)
        )
        self.assertFalse(ok)
        self.assertTrue(history.load()[0].read)

    def test_opener_exception_is_swallowed(self) -> None:
        entry = make_entry()
        history.append(entry)

        def boom(url: str) -> bool:
            raise RuntimeError("no browser")

        self.assertFalse(
            click.handle_click(entry.id, entry.session_id, FakeInstance(1, 3080, False), self.logger, boom)
        )

    def test_no_instance_only_marks_read(self) -> None:
        entry = make_entry()
        history.append(entry)
        ok = click.handle_click(entry.id, entry.session_id, None, self.logger, self.opener())
        self.assertFalse(ok)
        self.assertEqual(self.calls, [])
        self.assertTrue(history.load()[0].read)


class UrlTest(ClickTestBase):
    """拼出的 URL。"""

    def test_adopted_url_has_session_only(self) -> None:
        entry = make_entry()
        history.append(entry)
        click.handle_click(entry.id, entry.session_id, FakeInstance(1, 3080, False), self.logger, self.opener())
        self.assertEqual(self.calls, ["open:http://127.0.0.1:3080/?session=session-1"])


if __name__ == "__main__":
    unittest.main()
