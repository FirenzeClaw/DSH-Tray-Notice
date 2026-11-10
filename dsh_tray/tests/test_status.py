"""状态文案测试：标题行与底栏的分工。

覆盖 FR-015~FR-019 与 SC-004。这些是纯函数，不需要 QApplication——刻意保持
如此，让「文案对不对」的验证不依赖界面能否起来。
"""

from __future__ import annotations

import unittest

from dsh_tray.lifecycle import Instance, State
from dsh_tray.ui.status import detail_text, status_text


def make_instance(
    pid: int = 4512,
    port: int = 3080,
    owned: bool = True,
    has_token: bool = True,
) -> Instance:
    """造一个实例，只填本测试关心的字段。

    `has_token` 是 `Instance` 的派生属性（`url is not None`），不是构造参数——
    所以要给令牌就造一个 url。
    """
    url = f"http://127.0.0.1:{port}/?token=test" if has_token else None
    return Instance(pid=pid, port=port, owned=owned, url=url)


class StatusTextTest(unittest.TestCase):
    """标题行：只放状态，不放数字。"""

    def test_all_states_have_text(self) -> None:
        for state in (State.STOPPED, State.STARTING, State.RUNNING, State.STOPPING, State.FAILED):
            self.assertTrue(status_text(state), f"{state} 没有文案")

    def test_contains_no_digits(self) -> None:
        """FR-015：标题行不显示 PID、端口等细节。"""
        for state in (State.STOPPED, State.STARTING, State.RUNNING, State.STOPPING, State.FAILED):
            text = status_text(state)
            self.assertFalse(
                any(ch.isdigit() for ch in text),
                f"{state} 的标题行含数字：{text}",
            )

    def test_no_url_in_title(self) -> None:
        """标题行不出现地址。"""
        for state in (State.STOPPED, State.RUNNING):
            self.assertNotIn("127.0.0.1", status_text(state))
            self.assertNotIn(":", status_text(state))

    def test_distinct_per_state(self) -> None:
        """五种状态必须能区分开。"""
        texts = [status_text(s) for s in (State.STOPPED, State.STARTING, State.RUNNING, State.STOPPING, State.FAILED)]
        self.assertEqual(len(set(texts)), len(texts), f"文案重复：{texts}")


class DetailTextTest(unittest.TestCase):
    """底栏：四项细节齐全。"""

    def test_running_owned_has_all_four(self) -> None:
        """SC-004：PID、端口、启动方式、令牌四项齐全。"""
        text = detail_text(State.RUNNING, make_instance(owned=True, has_token=True), "", 3080)
        self.assertIn("PID 4512", text)
        self.assertIn("端口 3080", text)
        self.assertIn("由托盘启动", text)
        self.assertIn("带令牌", text)

    def test_running_adopted_marks_external(self) -> None:
        """FR-018：接管态的令牌失权要能一眼看出。"""
        text = detail_text(State.RUNNING, make_instance(owned=False, has_token=False), "", 3080)
        self.assertIn("外部启动", text)
        self.assertIn("无令牌", text)
        self.assertNotIn("带令牌", text)

    def test_owned_and_adopted_differ(self) -> None:
        """两种运行态的底栏文本必须不同，否则用户分不出自己处在哪种。"""
        owned = detail_text(State.RUNNING, make_instance(owned=True, has_token=True), "", 3080)
        adopted = detail_text(State.RUNNING, make_instance(owned=False, has_token=False), "", 3080)
        self.assertNotEqual(owned, adopted)

    def test_stopped_has_no_pid(self) -> None:
        """FR-017：未运行时不显示 PID。"""
        text = detail_text(State.STOPPED, None, "", 3080)
        self.assertNotIn("PID", text)
        self.assertIn("3080", text)

    def test_failed_shows_reason(self) -> None:
        text = detail_text(State.FAILED, None, "端口被占用", 3080)
        self.assertIn("端口被占用", text)
        self.assertIn("3080", text)

    def test_failed_without_reason_is_not_empty(self) -> None:
        """没有错误原因时也要给出可读文案，不能是空白。"""
        self.assertTrue(detail_text(State.FAILED, None, "", 3080))

    def test_starting_and_stopping_differ(self) -> None:
        starting = detail_text(State.STARTING, None, "", 3080)
        stopping = detail_text(State.STOPPING, None, "", 3080)
        self.assertNotEqual(starting, stopping)

    def test_never_empty(self) -> None:
        """底栏任何状态下都不该是空串——空行会让面板看起来缺了一块。"""
        for state in (State.STOPPED, State.STARTING, State.RUNNING, State.STOPPING, State.FAILED):
            self.assertTrue(detail_text(state, None, "", 3080), f"{state} 的底栏为空")

    def test_uses_instance_port_not_argument(self) -> None:
        """运行中时端口取实例自己的，避免显示与实际服务不一致。"""
        text = detail_text(State.RUNNING, make_instance(port=3999), "", 3080)
        self.assertIn("3999", text)
        self.assertNotIn("3080", text)


if __name__ == "__main__":
    unittest.main()
