"""深链拼接测试：owned 带令牌、adopted 不带、端口正确、令牌顺序固定。

令牌只允许出现在最终 URL 里，不进日志、不进通知正文。这条测试同时充当安全断言：
断言里出现的字符串必须不含真实令牌值（用假令牌验证拼接规则）。
"""

from __future__ import annotations

import unittest
from dataclasses import dataclass

from dsh_tray.notify.deeplink import build


@dataclass
class FakeInstance:
    """与 `lifecycle.Instance` 同形的最小投影。"""

    pid: int
    port: int
    owned: bool
    url: str | None = None


@dataclass
class FakeRecord:
    """与 `locks.OwnedRecord` 同形。"""

    pid: int
    port: int
    url: str


class OwnedTest(unittest.TestCase):
    """自有实例：带令牌。"""

    def test_owned_includes_token_then_session(self) -> None:
        instance = FakeInstance(pid=1234, port=3080, owned=True)
        record = FakeRecord(pid=1234, port=3080, url="http://127.0.0.1:3080/?token=abc")
        url = build("session-1", instance, record)
        self.assertEqual(url, "http://127.0.0.1:3080/?token=abc&session=session-1")

    def test_token_before_session_is_fixed(self) -> None:
        instance = FakeInstance(pid=1234, port=3080, owned=True)
        record = FakeRecord(pid=1234, port=3080, url="http://127.0.0.1:3080/?token=abc")
        url = build("s", instance, record)
        self.assertLess(url.index("token="), url.index("session="))

    def test_pid_mismatch_drops_token(self) -> None:
        # 账本里的 pid 与当前实例不符：说明账本是旧的，令牌不该被沿用。
        instance = FakeInstance(pid=9999, port=3080, owned=True)
        record = FakeRecord(pid=1234, port=3080, url="http://127.0.0.1:3080/?token=abc")
        url = build("session-1", instance, record)
        self.assertEqual(url, "http://127.0.0.1:3080/?session=session-1")
        self.assertNotIn("token", url)


class AdoptedTest(unittest.TestCase):
    """接管实例：无令牌。"""

    def test_adopted_has_no_token(self) -> None:
        instance = FakeInstance(pid=555, port=3080, owned=False)
        url = build("session-1", instance, None)
        self.assertEqual(url, "http://127.0.0.1:3080/?session=session-1")
        self.assertNotIn("token", url)

    def test_adopted_ignores_stale_record(self) -> None:
        instance = FakeInstance(pid=555, port=3080, owned=False)
        record = FakeRecord(pid=555, port=3080, url="http://127.0.0.1:3080/?token=abc")
        self.assertNotIn("token", build("session-1", instance, record))


class PortTest(unittest.TestCase):
    """非默认端口。"""

    def test_uses_instance_port(self) -> None:
        instance = FakeInstance(pid=1, port=4123, owned=False)
        self.assertIn("127.0.0.1:4123", build("s", instance, None))


class EncodingTest(unittest.TestCase):
    """会话 id 编码。"""

    def test_session_id_is_percent_encoded(self) -> None:
        instance = FakeInstance(pid=1, port=3080, owned=False)
        url = build("a b&c", instance, None)
        self.assertIn("session=a%20b%26c", url)


if __name__ == "__main__":
    unittest.main()
