"""会话状态表测试：全量替换、子会话过滤、等待标记、时长。

快照是**全量替换**而非增量（data-model.md 不变量 4）：新快照里没有的会话就是已经
结束的，托盘不做合并逻辑。这条语义错了会让「工作中」页留着早已结束的会话。
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from dsh_tray.notify.sessionstate import SessionTable
from dsh_tray.notify.types import SessionState

NOW = datetime(2026, 11, 6, 12, 0, 0, tzinfo=timezone.utc)


def snapshot(*rows: dict[str, object], ts: datetime = NOW) -> SessionState:
    """造一个会话快照。"""
    parsed = SessionState.from_json(
        {"v": 1, "type": "session-state", "ts": ts.isoformat(), "sessions": list(rows)}
    )
    assert parsed is not None
    return parsed


def row(session_id: str = "s-1", **overrides: object) -> dict[str, object]:
    """造一行会话。"""
    base: dict[str, object] = {
        "id": session_id,
        "title": "通知面板设计",
        "state": "working",
        "turn": 3,
        "turnStartedAt": (NOW - timedelta(seconds=90)).isoformat(),
        "currentTool": "Bash · pnpm build",
        "origin": "root",
    }
    base.update(overrides)
    return base


class ReplacementTest(unittest.TestCase):
    """全量替换语义。"""

    def test_snapshot_replaces_previous(self) -> None:
        table = SessionTable()
        table.apply(snapshot(row("a"), row("b")))
        self.assertEqual(len(table.active()), 2)

        table.apply(snapshot(row("b")))
        self.assertEqual([entry.id for entry in table.active()], ["b"], "缺少的会话应被移除")

    def test_empty_snapshot_clears(self) -> None:
        table = SessionTable()
        table.apply(snapshot(row("a")))
        table.apply(snapshot())
        self.assertEqual(table.active(), ())


class FilterTest(unittest.TestCase):
    """子会话过滤。"""

    def test_subagent_filtered_by_default(self) -> None:
        table = SessionTable()
        table.apply(snapshot(row("root"), row("child", origin="subagent")))
        self.assertEqual([entry.id for entry in table.active()], ["root"])

    def test_subagent_included_when_enabled(self) -> None:
        table = SessionTable(show_subagents=True)
        table.apply(snapshot(row("root"), row("child", origin="subagent")))
        self.assertEqual(len(table.active()), 2)


class WaitingTest(unittest.TestCase):
    """等待标记。"""

    def test_waiting_user_is_flagged(self) -> None:
        table = SessionTable()
        table.apply(snapshot(row("a", state="waiting-user")))
        entry = table.active()[0]
        self.assertTrue(entry.waiting_for_user)

    def test_working_is_not_flagged(self) -> None:
        table = SessionTable()
        table.apply(snapshot(row("a", state="working")))
        self.assertFalse(table.active()[0].waiting_for_user)


class ElapsedTest(unittest.TestCase):
    """时长计算。"""

    def test_elapsed_uses_local_clock(self) -> None:
        table = SessionTable()
        table.apply(snapshot(row("a")))
        seconds = table.elapsed("a", now=NOW)
        self.assertEqual(seconds, 90)

    def test_elapsed_unknown_session_is_none(self) -> None:
        table = SessionTable()
        self.assertIsNone(table.elapsed("nope", now=NOW))

    def test_elapsed_without_start_is_none(self) -> None:
        table = SessionTable()
        payload = row("a")
        del payload["turnStartedAt"]
        table.apply(snapshot(payload))
        self.assertIsNone(table.elapsed("a", now=NOW))

    def test_elapsed_never_negative(self) -> None:
        table = SessionTable()
        table.apply(snapshot(row("a", turnStartedAt=(NOW + timedelta(minutes=5)).isoformat())))
        self.assertEqual(table.elapsed("a", now=NOW), 0)

    def test_elapsed_monotonic_across_snapshots(self) -> None:
        table = SessionTable()
        table.apply(snapshot(row("a")))
        first = table.elapsed("a", now=NOW)
        # 新快照带来更晚的起始时刻：不该让时长倒退到负
        table.apply(snapshot(row("a", turnStartedAt=(NOW - timedelta(seconds=30)).isoformat())))
        second = table.elapsed("a", now=NOW)
        self.assertGreaterEqual(second, 0)
        self.assertLessEqual(second, first)


class FormatTest(unittest.TestCase):
    """时长格式化。"""

    def test_formats_seconds(self) -> None:
        self.assertEqual(SessionTable.format_elapsed(45), "45 秒")

    def test_formats_minutes(self) -> None:
        self.assertEqual(SessionTable.format_elapsed(125), "2 分 5 秒")

    def test_formats_hours(self) -> None:
        self.assertEqual(SessionTable.format_elapsed(3725), "1 时 2 分")

    def test_formats_none(self) -> None:
        self.assertEqual(SessionTable.format_elapsed(None), "—")


if __name__ == "__main__":
    unittest.main()
