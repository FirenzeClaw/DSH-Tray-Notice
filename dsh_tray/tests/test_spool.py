"""spool 增量读的测试：增量、轮转、坏行、半行。

这四条是 spool 协议最容易出错的地方——每条都曾让「事件静默消失」发生：
offset 不带 inode 会跳过轮转后的新文件；半行推进会永久丢掉正在写的那条；
坏行若抛错会让整批停摆。
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from dsh_tray.notify.spool import (
    SpoolBatch,
    load_offset,
    read_new,
    resolve_dsh_home,
    save_offset,
    spool_path_for,
)

ROW = {
    "v": 1,
    "type": "notification",
    "id": "id-1",
    "ts": "2026-11-06T11:40:00.000Z",
    "kind": "done",
    "sessionId": "s-1",
    "sessionTitle": "标题",
    "title": "已完成",
    "body": "正文",
    "urgency": "normal",
    "openUrl": "http://127.0.0.1:3080/?session=s-1",
    "dedupeKey": "done:s-1:1",
}

STATE = {
    "v": 1,
    "type": "session-state",
    "ts": "2026-11-06T11:40:05.000Z",
    "sessions": [{"id": "s-1", "title": "标题", "state": "working", "turn": 2, "origin": "root"}],
}


def line(payload: dict) -> str:
    """序列化成一行（含换行）。"""
    return json.dumps(payload, ensure_ascii=False) + "\n"


class SpoolReadTest(unittest.TestCase):
    """增量读。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.state_dir = self.root / "state"
        self.spool = self.root / "events.jsonl"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_reads_incrementally(self) -> None:
        self.spool.write_text(line(ROW), encoding="utf-8")
        first = read_new(self.spool, self.state_dir)
        self.assertEqual(len(first.notifications), 1)
        self.assertEqual(first.skipped, 0)

        second = read_new(self.spool, self.state_dir)
        self.assertTrue(second.is_empty)

        with self.spool.open("a", encoding="utf-8") as handle:
            handle.write(line({**ROW, "id": "id-2"}))
        third = read_new(self.spool, self.state_dir)
        self.assertEqual([entry.id for entry in third.notifications], ["id-2"])

    def test_rotation_resets_offset(self) -> None:
        self.spool.write_text(line(ROW), encoding="utf-8")
        read_new(self.spool, self.state_dir)
        # 模拟轮转：删掉重建（inode 变化）
        self.spool.unlink()
        self.spool.write_text(line({**ROW, "id": "id-new"}), encoding="utf-8")

        batch = read_new(self.spool, self.state_dir)
        self.assertEqual([entry.id for entry in batch.notifications], ["id-new"])

    def test_bad_lines_are_skipped_and_counted(self) -> None:
        self.spool.write_text(
            "not json\n" + line({**ROW, "v": 2}) + line(ROW) + "\n", encoding="utf-8"
        )
        batch = read_new(self.spool, self.state_dir)
        self.assertEqual(len(batch.notifications), 1)
        self.assertEqual(batch.skipped, 2)

    def test_partial_line_is_not_consumed(self) -> None:
        complete = line(ROW)
        pending = line({**ROW, "id": "id-2"})
        # 只写前半行，模拟写入方还没写完
        self.spool.write_text(complete + pending[: len(pending) // 2], encoding="utf-8")

        first = read_new(self.spool, self.state_dir)
        self.assertEqual([entry.id for entry in first.notifications], ["id-1"])

        # 补完后半行：半行没有被消费掉，所以现在应当读到 id-2
        with self.spool.open("a", encoding="utf-8") as handle:
            handle.write(pending[len(pending) // 2 :])
        second = read_new(self.spool, self.state_dir)
        self.assertEqual([entry.id for entry in second.notifications], ["id-2"])

    def test_session_state_is_separated(self) -> None:
        self.spool.write_text(line(ROW) + line(STATE), encoding="utf-8")
        batch = read_new(self.spool, self.state_dir)
        self.assertEqual(len(batch.notifications), 1)
        self.assertEqual(len(batch.session_states), 1)
        self.assertEqual(batch.session_states[0].sessions[0].state, "working")

    def test_missing_file_is_empty_batch(self) -> None:
        batch = read_new(self.root / "nope.jsonl", self.state_dir)
        self.assertIsInstance(batch, SpoolBatch)
        self.assertTrue(batch.is_empty)

    def test_truncated_file_rereads_from_zero(self) -> None:
        self.spool.write_text(line(ROW) + line({**ROW, "id": "id-2"}), encoding="utf-8")
        read_new(self.spool, self.state_dir)
        self.spool.write_text(line({**ROW, "id": "id-9"}), encoding="utf-8")
        batch = read_new(self.spool, self.state_dir)
        self.assertEqual([entry.id for entry in batch.notifications], ["id-9"])


class OffsetTest(unittest.TestCase):
    """偏移文件的容错。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.spool = self.root / "events.jsonl"
        self.spool.write_text(line(ROW), encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_corrupt_offset_file_reads_from_zero(self) -> None:
        self.root.joinpath("spool-offset.json").write_text("{not json", encoding="utf-8")
        self.assertEqual(load_offset(self.root, self.spool), 0)

    def test_roundtrip(self) -> None:
        save_offset(self.root, self.spool, 42)
        self.assertEqual(load_offset(self.root, self.spool), 42)

    def test_stale_inode_reads_from_zero(self) -> None:
        save_offset(self.root, self.spool, 42)
        self.spool.unlink()
        self.spool.write_text(line(ROW), encoding="utf-8")
        self.assertEqual(load_offset(self.root, self.spool), 0)


class PathTest(unittest.TestCase):
    """路径解析。"""

    def test_spool_path_layout(self) -> None:
        self.assertEqual(
            spool_path_for(Path("/home/u/.dsh")),
            Path("/home/u/.dsh/run/tray-notify/events.jsonl"),
        )

    def test_dsh_home_honours_env(self) -> None:
        import os

        previous = os.environ.get("DSH_HOME")
        os.environ["DSH_HOME"] = "/tmp/custom-dsh"
        try:
            self.assertEqual(resolve_dsh_home(), Path("/tmp/custom-dsh"))
        finally:
            if previous is None:
                del os.environ["DSH_HOME"]
            else:
                os.environ["DSH_HOME"] = previous

    def test_blank_env_falls_back(self) -> None:
        import os

        previous = os.environ.get("DSH_HOME")
        os.environ["DSH_HOME"] = "   "
        try:
            self.assertEqual(resolve_dsh_home(), Path(os.path.expanduser("~/.dsh")))
        finally:
            if previous is None:
                del os.environ["DSH_HOME"]
            else:
                os.environ["DSH_HOME"] = previous


if __name__ == "__main__":
    unittest.main()
