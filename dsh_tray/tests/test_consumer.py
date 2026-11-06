"""消费循环测试：失败仍入库、间隔切换、重启不重复。

这三条是「通知可不可信」的底线：投递失败不能吞事件、DSH 停着时空转要降频、
托盘重启不能把同一批事件再弹一遍。
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dsh_tray.notify.consumer import (
    FAST_INTERVAL_MS,
    SLOW_INTERVAL_MS,
    REPLAY_WINDOW,
    Consumer,
)
from dsh_tray.notify.delivery import DeliveryResult
from dsh_tray.notify.log import Logger

FIXED = datetime(2026, 11, 6, 12, 0, 0, tzinfo=timezone.utc)


def row(entry_id: str = "id-1", **overrides: object) -> dict[str, object]:
    """造一条 spool 通知行。"""
    base: dict[str, object] = {
        "v": 1,
        "type": "notification",
        "id": entry_id,
        "ts": FIXED.isoformat(),
        "kind": "done",
        "sessionId": "s-1",
        "sessionTitle": "通知面板设计",
        "title": "已完成",
        "body": "跑完了",
        "urgency": "normal",
        "openUrl": "http://127.0.0.1:3080/?session=s-1",
        "dedupeKey": f"done:s-1:{entry_id}",
    }
    base.update(overrides)
    return base


class ConsumerTestBase(unittest.TestCase):
    """公共夹具：临时 spool + 记录型 deliverer。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.spool = self.root / "events.jsonl"
        self.state = self.root / "state"
        self.state.mkdir()
        self.delivered: list[dict[str, object]] = []
        self.stored: list[str] = []
        self.logger = Logger(None, "test")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write_rows(self, *rows: dict[str, object]) -> None:
        """追加若干行到 spool。"""
        with self.spool.open("a", encoding="utf-8") as handle:
            for item in rows:
                handle.write(json.dumps(item, ensure_ascii=False) + "\n")

    def make_consumer(self, *, fail: bool = False, now: datetime = FIXED) -> Consumer:
        """构造消费器。"""

        def deliverer(payload: dict[str, object]) -> DeliveryResult:
            self.delivered.append(payload)
            return DeliveryResult(False, reason="no notification server") if fail else DeliveryResult(True, 1)

        def writer(entry, *, now=None, replayed=False) -> None:
            self.stored.append(entry.id)

        return Consumer(
            spool_path=self.spool,
            state_path=self.state,
            deliverer=deliverer,
            history_writer=writer,
            logger=self.logger,
            now=lambda: now,
        )


class DeliveryFailureTest(ConsumerTestBase):
    """投递失败的处理。"""

    def test_failure_still_stores(self) -> None:
        self.write_rows(row())
        consumer = self.make_consumer(fail=True)
        result = consumer.poll()

        self.assertEqual(result.delivered, 0)
        self.assertEqual(result.stored, 1, "投递失败仍应入库")
        self.assertEqual(self.stored, ["id-1"])

    def test_success_counts_delivered(self) -> None:
        self.write_rows(row())
        consumer = self.make_consumer()
        result = consumer.poll()
        self.assertEqual(result.delivered, 1)
        self.assertEqual(result.stored, 1)


class IntervalTest(ConsumerTestBase):
    """轮询间隔切换。"""

    def test_interval_follows_dsh_state(self) -> None:
        consumer = self.make_consumer()
        self.assertEqual(consumer.next_interval_ms(dsh_running=True), FAST_INTERVAL_MS)
        self.assertEqual(consumer.next_interval_ms(dsh_running=False), SLOW_INTERVAL_MS)

    def test_fast_is_200_slow_is_1000(self) -> None:
        self.assertEqual(FAST_INTERVAL_MS, 200)
        self.assertEqual(SLOW_INTERVAL_MS, 1000)


class RestartTest(ConsumerTestBase):
    """重启不重复。"""

    def test_second_consumer_does_not_redeliver(self) -> None:
        self.write_rows(row())
        first = self.make_consumer()
        first.poll()
        self.assertEqual(len(self.delivered), 1)

        # 新实例模拟托盘重启：偏移已持久化，应当读不到新行
        second = self.make_consumer()
        result = second.poll()
        self.assertEqual(result.delivered, 0)
        self.assertEqual(len(self.delivered), 1)

    def test_new_row_after_restart_is_delivered(self) -> None:
        self.write_rows(row())
        self.make_consumer().poll()

        self.write_rows(row("id-2", dedupeKey="done:s-1:2"))
        second = self.make_consumer()
        result = second.poll()
        self.assertEqual(result.delivered, 1)
        self.assertEqual(self.delivered[-1]["id"], "id-2")


class DedupeTest(ConsumerTestBase):
    """去重窗口在消费器上的效果。"""

    def test_same_dedupe_key_in_one_batch_delivered_once(self) -> None:
        self.write_rows(row("id-1"), row("id-2", dedupeKey="done:s-1:id-1"))
        consumer = self.make_consumer()
        result = consumer.poll()
        self.assertEqual(result.delivered, 1)
        self.assertEqual(result.stored, 1)


class ReplayTest(ConsumerTestBase):
    """补投窗口。"""

    def test_old_entries_are_stored_not_delivered(self) -> None:
        old = (FIXED - REPLAY_WINDOW - timedelta(minutes=1)).isoformat()
        self.write_rows(row("id-old", ts=old))
        consumer = self.make_consumer()
        result = consumer.poll()

        self.assertEqual(result.delivered, 0, "超出补投窗口不该弹通知")
        self.assertEqual(result.replayed, 1)
        self.assertEqual(result.stored, 1, "仍应入库，用户能在面板里看到")

    def test_recent_entries_are_delivered(self) -> None:
        recent = (FIXED - timedelta(minutes=10)).isoformat()
        self.write_rows(row("id-recent", ts=recent))
        result = self.make_consumer().poll()
        self.assertEqual(result.delivered, 1)
        self.assertEqual(result.replayed, 0)

    def test_replay_pending_reports_count(self) -> None:
        old = (FIXED - REPLAY_WINDOW - timedelta(minutes=1)).isoformat()
        self.write_rows(row("id-old", ts=old))
        consumer = self.make_consumer()
        self.assertEqual(consumer.replay_pending(), 1)
        self.assertTrue(consumer.primed)


class SessionStateTest(ConsumerTestBase):
    """会话快照的接收。"""

    def test_last_snapshot_wins(self) -> None:
        first = {
            "v": 1,
            "type": "session-state",
            "ts": FIXED.isoformat(),
            "sessions": [{"id": "a", "title": "A", "state": "working", "turn": 1, "origin": "root"}],
        }
        second = {
            "v": 1,
            "type": "session-state",
            "ts": FIXED.isoformat(),
            "sessions": [{"id": "b", "title": "B", "state": "working", "turn": 1, "origin": "root"}],
        }
        self.write_rows(first, second)
        consumer = self.make_consumer()
        consumer.poll()
        self.assertEqual([s.id for s in consumer.session_states[0].sessions], ["b"])


if __name__ == "__main__":
    unittest.main()
