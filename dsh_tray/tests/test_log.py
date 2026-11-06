"""日志工具测试：脱敏规则与轮转。

脱敏是安全红线的一部分（AGENTS.md：令牌不得进日志），所以它值得一条断言而不是
「看起来对」。
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dsh_tray.notify.log import LOG_MAX_BYTES, Logger, redact


class RedactTest(unittest.TestCase):
    """令牌脱敏。"""

    def test_query_string_token(self) -> None:
        raw = "打开 http://127.0.0.1:3080/?token=abc&session=x"
        self.assertEqual(redact(raw), "打开 http://127.0.0.1:3080/?token=***&session=x")

    def test_json_token(self) -> None:
        self.assertEqual(redact('{"token":"abc"}'), '{"token":"***"}')

    def test_assignment_token(self) -> None:
        self.assertEqual(redact("apiKey: sk-123"), "apiKey: ***")

    def test_already_redacted_is_stable(self) -> None:
        self.assertEqual(redact("token=***"), "token=***")

    def test_plain_word_untouched(self) -> None:
        self.assertEqual(redact("token 已过期"), "token 已过期")


class LoggerTest(unittest.TestCase):
    """写盘与轮转。"""

    def test_writes_line_with_component(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            path = Path(raw_dir) / "tray.log"
            Logger(path, "consumer").info("收到 3 条")
            text = path.read_text(encoding="utf-8")
            self.assertIn("info consumer 收到 3 条", text)
            self.assertTrue(text.endswith("\n"))

    def test_rotates_when_oversized(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            path = Path(raw_dir) / "tray.log"
            path.write_text("x" * (LOG_MAX_BYTES + 1), encoding="utf-8")
            Logger(path, "consumer").info("新一行")
            self.assertTrue(Path(str(path) + ".1").exists())
            self.assertNotIn("x" * 100, path.read_text(encoding="utf-8"))

    def test_missing_directory_is_created(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            path = Path(raw_dir) / "nested" / "deep" / "tray.log"
            Logger(path, "consumer").warn("hi")
            self.assertTrue(path.exists())

    def test_none_path_is_noop(self) -> None:
        Logger(None, "consumer").info("丢弃")  # 不抛即通过


if __name__ == "__main__":
    unittest.main()
