"""安全复查的自动断言：权限与令牌边界。

这三条都是「看起来没事、出事才发现」的类型：
- 目录权限宽了，同机其他用户能读到通知历史（可能含命令与路径）。
- 令牌进了日志，日志一转发就泄露。
- 令牌进了通知正文，桌面通知在锁屏界面上可见。
"""

from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from dsh_tray.notify import history, log as notify_log
from dsh_tray.notify.spool import save_offset
from dsh_tray.notify.types import NotificationEntry
from dsh_tray import locks

NOW_TEXT = "2026-11-06T12:00:00+00:00"


def entry(entry_id: str = "id-1") -> NotificationEntry:
    """造一条通知。"""
    parsed = NotificationEntry.from_json(
        {
            "v": 1,
            "type": "notification",
            "id": entry_id,
            "ts": NOW_TEXT,
            "kind": "needs-approval",
            "sessionId": "s-1",
            "sessionTitle": "通知面板设计",
            "title": "需要你审批",
            "body": "Bash",
            "urgency": "critical",
            "openUrl": "http://127.0.0.1:3080/?session=s-1",
            "dedupeKey": "approval:appr_1",
        }
    )
    assert parsed is not None
    return parsed


class PermissionTest(unittest.TestCase):
    """目录 0700 / 文件 0600。"""

    def test_state_dir_is_0700(self) -> None:
        mode = stat.S_IMODE(os.stat(locks.state_dir()).st_mode)
        self.assertEqual(mode, 0o700, f"实际 {oct(mode)}")

    def test_owned_record_is_0600(self) -> None:
        record = locks.OwnedRecord(pid=os.getpid(), port=3998, url="http://127.0.0.1:3998/?token=x")
        locks.write_owned_record(record)
        try:
            mode = stat.S_IMODE(os.stat(locks._owned_path(3998)).st_mode)
            self.assertEqual(mode, 0o600, f"实际 {oct(mode)}")
        finally:
            locks.clear_owned_record(3998)

    def test_offset_file_is_0600(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            spool = root / "events.jsonl"
            spool.write_text("{}\n", encoding="utf-8")
            state = root / "state"
            save_offset(state, spool, 3)
            mode = stat.S_IMODE(os.stat(state / "spool-offset.json").st_mode)
            self.assertEqual(mode, 0o600, f"实际 {oct(mode)}")


class HistoryPermissionTest(unittest.TestCase):
    """历史文件 0600。"""

    def test_history_file_is_0600(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "notifications.json"
            with mock.patch.object(history, "history_path", return_value=path):
                history.append(entry(), now=None)
            mode = stat.S_IMODE(os.stat(path).st_mode)
            self.assertEqual(mode, 0o600, f"实际 {oct(mode)}")


class TokenBoundaryTest(unittest.TestCase):
    """令牌不进日志。"""

    def test_logger_redacts_token(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "tray.log"
            logger = notify_log.Logger(path, "test")
            logger.info("打开 http://127.0.0.1:3080/?token=SECRET123&session=s-1")
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("SECRET123", text)
            self.assertIn("token=***", text)

    def test_redact_covers_common_forms(self) -> None:
        for raw in (
            "?token=abc",
            '"token":"abc"',
            "token=abc",
            "apiKey: abc",
            "password=abc",
        ):
            redacted = notify_log.redact(raw)
            self.assertNotIn("abc", redacted, f"{raw} 未脱敏：{redacted}")

    def test_open_url_has_no_token(self) -> None:
        # 契约要求插件只写裸链接；这里从类型层再确认一次。
        self.assertNotIn("token", entry().open_url)


if __name__ == "__main__":
    unittest.main()
