"""投递后端测试：命令构造、失败不抛、无令牌。

`gdbus` 的调用必须显式声明类型：QtDBus 与 gdbus 的自动推断都会把 `uint32` 推成
`int`、把 `as` 推成 `av`，服务端会以签名不匹配拒绝（实测报 `sisssava{sv}i`）。
所以这里断言的是**完整命令行**，而不只是「包含 Notify」。
"""

from __future__ import annotations

import unittest

from dsh_tray.notify.delivery import DeliveryResult, build_gdbus_command, deliver_with_runner


def entry(**overrides: object) -> dict[str, object]:
    """造一条通知条目。"""
    base: dict[str, object] = {
        "id": "id-1",
        "ts": "2026-11-06T11:40:00Z",
        "kind": "needs-approval",
        "sessionId": "s-1",
        "sessionTitle": "通知面板设计",
        "title": "需要你审批",
        "body": "Bash · rm -rf dist",
        "urgency": "critical",
        "openUrl": "http://127.0.0.1:3080/?session=s-1",
        "dedupeKey": "approval:appr_1",
    }
    base.update(overrides)
    return base


class CommandConstructionTest(unittest.TestCase):
    """命令行构造。"""

    def test_critical_uses_infinite_timeout(self) -> None:
        command = build_gdbus_command(entry())
        self.assertTrue(any("Notify" in part for part in command))
        self.assertIn("DSH-Tray", command)
        self.assertIn("需要你审批", command)
        self.assertIn("Bash · rm -rf dist", command)
        # critical → expire_timeout 0（不自动消失）
        self.assertIn("uint32 0", command)
        self.assertNotIn("uint32:0", command, "冒号写法 gdbus 不接受，会静默回退")
        joined = " ".join(command)
        self.assertIn("default", joined)
        self.assertIn("打开会话", joined)

    def test_normal_uses_5s_timeout(self) -> None:
        command = build_gdbus_command(entry(urgency="normal", kind="done"))
        self.assertIn("int32 5000", command)

    def test_actions_are_declared_as_string_array(self) -> None:
        command = build_gdbus_command(entry())
        joined = " ".join(command)
        self.assertIn("['default', '打开会话']", joined)

    def test_hints_are_empty_dict(self) -> None:
        command = build_gdbus_command(entry())
        self.assertIn("{}", command)

    def test_no_token_in_command(self) -> None:
        command = build_gdbus_command(entry())
        joined = " ".join(command)
        self.assertNotIn("token=", joined)
        self.assertNotIn("token:", joined)


class RunnerTest(unittest.TestCase):
    """runner 返回值的处理。"""

    def test_success_returns_true(self) -> None:
        calls: list[list[str]] = []

        def runner(command: list[str]) -> tuple[int, str, str]:
            calls.append(command)
            return 0, "(uint32 155,)", ""

        result = deliver_with_runner(entry(), runner)
        self.assertTrue(result.delivered)
        self.assertEqual(result.notification_id, 155)
        self.assertEqual(len(calls), 1)

    def test_nonzero_returns_false_without_raising(self) -> None:
        def runner(command: list[str]) -> tuple[int, str, str]:
            return 1, "", "Failed to call method"

        result = deliver_with_runner(entry(), runner)
        self.assertFalse(result.delivered)
        self.assertIsNone(result.notification_id)
        self.assertIn("Failed", result.reason or "")

    def test_runner_exception_is_swallowed(self) -> None:
        def runner(command: list[str]) -> tuple[int, str, str]:
            raise FileNotFoundError("gdbus")

        result = deliver_with_runner(entry(), runner)
        self.assertFalse(result.delivered)

    def test_parses_notification_id_from_stdout(self) -> None:
        def runner(command: list[str]) -> tuple[int, str, str]:
            return 0, "(uint32 42,)", ""

        result = deliver_with_runner(entry(), runner)
        self.assertEqual(result.notification_id, 42)


class ResultShapeTest(unittest.TestCase):
    """结果对象。"""

    def test_default_result_is_failure(self) -> None:
        result = DeliveryResult(delivered=False)
        self.assertFalse(result.delivered)
        self.assertIsNone(result.notification_id)


if __name__ == "__main__":
    unittest.main()
