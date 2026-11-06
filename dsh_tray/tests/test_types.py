"""契约解析测试：正常行、缺字段、版本不符、坏快照。

这几条是跨进程边界上唯一能自动验证的东西——spool 里出现坏行是**正常工况**
（插件升级、写入被打断），托盘必须跳过它继续工作。
"""

from __future__ import annotations

import unittest

from dsh_tray.notify.types import (
    NotificationEntry,
    SessionRow,
    SessionState,
    parse_row,
    parse_ts,
)

FULL_ROW = {
    "v": 1,
    "type": "notification",
    "id": "7c0e",
    "ts": "2026-11-06T11:40:00.512Z",
    "kind": "needs-approval",
    "sessionId": "session-1dc80bc4",
    "sessionTitle": "通知面板设计",
    "workspace": "DSH-Tray&Notice",
    "title": "需要你审批",
    "body": "Bash · rm -rf dist && pnpm build",
    "urgency": "critical",
    "openUrl": "http://127.0.0.1:3080/?session=session-1dc80bc4",
    "dedupeKey": "approval:appr_01",
}


class NotificationEntryTest(unittest.TestCase):
    """通知行的解析。"""

    def test_full_row_roundtrip(self) -> None:
        entry = NotificationEntry.from_json(FULL_ROW)
        self.assertIsNotNone(entry)
        assert entry is not None
        self.assertEqual(entry.session_id, "session-1dc80bc4")
        self.assertEqual(entry.open_url, "http://127.0.0.1:3080/?session=session-1dc80bc4")
        self.assertEqual(entry.dedupe_key, "approval:appr_01")
        self.assertTrue(entry.is_critical)
        self.assertEqual(entry.ts.year, 2026)
        self.assertEqual(entry.ts.tzinfo is None, False)

    def test_missing_body_is_rejected(self) -> None:
        row = dict(FULL_ROW)
        del row["body"]
        self.assertIsNone(NotificationEntry.from_json(row))

    def test_version_mismatch_is_rejected(self) -> None:
        row = dict(FULL_ROW)
        row["v"] = 2
        self.assertIsNone(NotificationEntry.from_json(row))

    def test_workspace_is_optional(self) -> None:
        row = dict(FULL_ROW)
        del row["workspace"]
        entry = NotificationEntry.from_json(row)
        self.assertIsNotNone(entry)
        assert entry is not None
        self.assertIsNone(entry.workspace)

    def test_bad_timestamp_is_rejected(self) -> None:
        row = dict(FULL_ROW)
        row["ts"] = "not-a-time"
        self.assertIsNone(NotificationEntry.from_json(row))


class SessionStateTest(unittest.TestCase):
    """会话快照的解析。"""

    def test_snapshot_parses_rows(self) -> None:
        row = {
            "v": 1,
            "type": "session-state",
            "ts": "2026-11-06T11:40:05Z",
            "sessions": [
                {
                    "id": "session-1dc80bc4",
                    "title": "通知面板设计",
                    "state": "working",
                    "turn": 4,
                    "turnStartedAt": "2026-11-06T11:36:48Z",
                    "currentTool": "Bash · pnpm build",
                    "origin": "root",
                }
            ],
        }
        state = SessionState.from_json(row)
        self.assertIsNotNone(state)
        assert state is not None
        self.assertEqual(len(state.sessions), 1)
        session = state.sessions[0]
        self.assertTrue(session.is_working)
        self.assertEqual(session.current_tool, "Bash · pnpm build")
        self.assertIsNotNone(session.turn_started_at)

    def test_bad_session_row_is_skipped_not_fatal(self) -> None:
        row = {
            "v": 1,
            "type": "session-state",
            "ts": "2026-11-06T11:40:05Z",
            "sessions": [
                {"id": "ok", "title": "t", "state": "idle", "turn": 1, "origin": "root"},
                {"id": "broken"},
            ],
        }
        state = SessionState.from_json(row)
        self.assertIsNotNone(state)
        assert state is not None
        self.assertEqual([session.id for session in state.sessions], ["ok"])

    def test_session_turn_must_be_int(self) -> None:
        row = {"id": "x", "title": "t", "state": "idle", "turn": "1", "origin": "root"}
        self.assertIsNone(SessionRow.from_json(row))


class ParseRowTest(unittest.TestCase):
    """行级分派。"""

    def test_unknown_type_returns_none(self) -> None:
        self.assertIsNone(parse_row({"v": 1, "type": "mystery"}))

    def test_non_mapping_returns_none(self) -> None:
        self.assertIsNone(parse_row(["not", "a", "dict"]))

    def test_dispatches_notification(self) -> None:
        parsed = parse_row(FULL_ROW)
        self.assertIsInstance(parsed, NotificationEntry)


class ParseTimestampTest(unittest.TestCase):
    """时间解析的边界。"""

    def test_z_suffix_is_utc(self) -> None:
        parsed = parse_ts("2026-11-06T11:40:05Z")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.utcoffset().total_seconds(), 0)

    def test_naive_time_is_assumed_utc(self) -> None:
        parsed = parse_ts("2026-11-06T11:40:05")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.utcoffset().total_seconds(), 0)

    def test_empty_is_none(self) -> None:
        self.assertIsNone(parse_ts(""))
        self.assertIsNone(parse_ts(None))


if __name__ == "__main__":
    unittest.main()
