"""补投测试：托盘缺席期间的事件在下次启动补投。

两条边界最容易错：
- **时间窗**：超过 2 小时的事件不再弹系统通知（弹出来只会让人困惑「这是刚发生的吗」），
  但仍进历史，用户能在面板里看到。
- **偏移**：已消费区间不重复投递。这条靠 spool 的 `{inode, offset}` 保证，这里从
  消费者角度再验证一次。
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dsh_tray.notify.consumer import REPLAY_WINDOW, Consumer
from dsh_tray.notify.delivery import DeliveryResult
from dsh_tray.notify.log import Logger

NOW = datetime(2026, 11, 6, 12, 0, 0, tzinfo=timezone.utc)


def row(entry_id: str, ts: datetime) -> dict[str, object]:
    """造一条 spool 行。"""
    return {
        "v": 1,
        "type": "notification",
        "id": entry_id,
        "ts": ts.isoformat(),
        "kind": "done",
        "sessionId": "s-1",
        "sessionTitle": "通知面板设计",
        "title": "已完成",
        "body": "跑完了",
        "urgency": "normal",
        "openUrl": "http://127.0.0.1:3080/?session=s-1",
        "dedupeKey": f"done:s-1:{entry_id}",
    }


class ReplayTest(unittest.TestCase):
    """启动补投。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.spool = self.root / "events.jsonl"
        self.state = self.root / "state"
        self.state.mkdir()
        self.delivered: list[str] = []
        self.stored: list[tuple[str, bool]] = []

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write(self, *rows: dict[str, object]) -> None:
        """追加行。"""
        with self.spool.open("a", encoding="utf-8") as handle:
            for item in rows:
                handle.write(json.dumps(item, ensure_ascii=False) + "\n")

    def consumer(self) -> Consumer:
        """构造消费者。"""

        def deliverer(payload: dict[str, object]) -> DeliveryResult:
            self.delivered.append(str(payload["id"]))
            return DeliveryResult(True, 1)

        def writer(entry, *, now=None, replayed=False) -> None:
            self.stored.append((entry.id, replayed))

        return Consumer(
            spool_path=self.spool,
            state_path=self.state,
            deliverer=deliverer,
            history_writer=writer,
            logger=Logger(None, "test"),
            now=lambda: NOW,
        )

    def test_recent_entries_delivered_on_replay(self) -> None:
        self.write(row("recent", NOW - timedelta(minutes=5)))
        count = self.consumer().replay_pending()
        self.assertEqual(count, 0, "窗口内的补投不计入「错过」")
        self.assertEqual(self.delivered, ["recent"])

    def test_old_entries_stored_not_delivered(self) -> None:
        old = NOW - REPLAY_WINDOW - timedelta(minutes=1)
        self.write(row("old", old))
        count = self.consumer().replay_pending()
        self.assertEqual(count, 1, "窗口外的应计入「错过 N 条」")
        self.assertEqual(self.delivered, [], "窗口外不弹系统通知")
        self.assertEqual(self.stored, [("old", True)], "但仍入库并标记为补投")

    def test_consumed_range_not_redelivered(self) -> None:
        self.write(row("a", NOW - timedelta(minutes=5)))
        self.consumer().replay_pending()
        self.assertEqual(len(self.delivered), 1)

        # 新实例模拟托盘重启
        self.consumer().replay_pending()
        self.assertEqual(len(self.delivered), 1, "已消费区间不该再投一次")

    def test_new_entries_after_replay_are_delivered(self) -> None:
        self.write(row("a", NOW - timedelta(minutes=5)))
        self.consumer().replay_pending()

        self.write(row("b", NOW - timedelta(minutes=1)))
        self.consumer().replay_pending()
        self.assertEqual(self.delivered, ["a", "b"])

    def test_mixed_window(self) -> None:
        old = NOW - REPLAY_WINDOW - timedelta(hours=1)
        self.write(row("old", old), row("recent", NOW - timedelta(minutes=2)))
        count = self.consumer().replay_pending()
        self.assertEqual(count, 1)
        self.assertEqual(self.delivered, ["recent"])
        self.assertEqual(len(self.stored), 2, "两条都要入库")

    def test_window_is_two_hours(self) -> None:
        self.assertEqual(REPLAY_WINDOW, timedelta(hours=2))


if __name__ == "__main__":
    unittest.main()
