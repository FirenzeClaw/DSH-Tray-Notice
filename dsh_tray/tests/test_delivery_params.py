"""投递参数的行为：顶替、超时来源、弹窗登记。

这三条都是为了修一个实测缺陷：**「永不消失」的横幅会占住 Plasma 的通知弹窗位**，
用户不点掉它，后续通知全部排队不显示——看起来就像通知功能坏了。修法有两层：
同会话的新通知顶替旧横幅（`replaces_id`），且 critical 也有有限时限。
"""

from __future__ import annotations

import unittest

from dsh_tray.notify.delivery import (
    TIMEOUT_CRITICAL_MS,
    TIMEOUT_NORMAL_MS,
    DeliveryResult,
    PopupRegistry,
    build_gdbus_command,
    deliver_with_runner,
    timeout_for,
)


def entry(**overrides: object) -> dict[str, object]:
    """造一条 spool 条目。"""
    row: dict[str, object] = {
        "title": "需要你审批",
        "body": "Bash",
        "urgency": "critical",
    }
    row.update(overrides)
    return row


class TimeoutTest(unittest.TestCase):
    """超时来源：条目优先，缺省按紧急度兜底。"""

    def test_entry_timeout_wins(self) -> None:
        self.assertEqual(timeout_for(entry(timeoutMs=120_000)), 120_000)

    def test_critical_fallback_is_finite(self) -> None:
        value = timeout_for(entry())
        self.assertEqual(value, TIMEOUT_CRITICAL_MS)
        self.assertGreater(value, 0, "critical 兜底值不能是「永不消失」")

    def test_normal_fallback(self) -> None:
        self.assertEqual(timeout_for(entry(urgency="normal")), TIMEOUT_NORMAL_MS)

    def test_zero_or_negative_ignored(self) -> None:
        for bad in (0, -1):
            self.assertEqual(timeout_for(entry(timeoutMs=bad)), TIMEOUT_CRITICAL_MS)

    def test_non_numeric_ignored(self) -> None:
        for bad in ("60000", None, True):
            self.assertEqual(timeout_for(entry(timeoutMs=bad)), TIMEOUT_CRITICAL_MS)

    def test_command_carries_entry_timeout(self) -> None:
        command = build_gdbus_command(entry(timeoutMs=90_000))
        self.assertEqual(command[-1], "int32 90000")


class ReplacesIdTest(unittest.TestCase):
    """顶替语义。"""

    def test_default_is_new(self) -> None:
        command = build_gdbus_command(entry())
        self.assertEqual(command[command.index("DSH-Tray") + 1], "uint32 0")

    def test_replaces_id_in_command(self) -> None:
        command = build_gdbus_command(entry(), replaces_id=42)
        self.assertEqual(command[command.index("DSH-Tray") + 1], "uint32 42")

    def test_deliver_passes_replaces_id(self) -> None:
        seen: list[list[str]] = []

        def runner(command: list[str]) -> tuple[int, str, str]:
            seen.append(list(command))
            return 0, "(uint32 7,)", ""

        result = deliver_with_runner(entry(), runner, has_gdbus=True, has_notify_send=False, replaces_id=42)
        self.assertTrue(result.delivered)
        self.assertEqual(seen[0][seen[0].index("DSH-Tray") + 1], "uint32 42")


class PopupRegistryTest(unittest.TestCase):
    """会话 → 弹窗 id。"""

    def test_unknown_session_is_zero(self) -> None:
        self.assertEqual(PopupRegistry().get("s-1"), 0)

    def test_remember_then_get(self) -> None:
        registry = PopupRegistry()
        registry.remember("s-1", 10)
        self.assertEqual(registry.get("s-1"), 10)

    def test_latest_wins(self) -> None:
        registry = PopupRegistry()
        registry.remember("s-1", 10)
        registry.remember("s-1", 11)
        self.assertEqual(registry.get("s-1"), 11)

    def test_sessions_are_independent(self) -> None:
        registry = PopupRegistry()
        registry.remember("s-1", 10)
        registry.remember("s-2", 20)
        self.assertEqual((registry.get("s-1"), registry.get("s-2")), (10, 20))

    def test_oldest_evicted_at_limit(self) -> None:
        registry = PopupRegistry(limit=2)
        for name, notification_id in (("a", 1), ("b", 2), ("c", 3)):
            registry.remember(name, notification_id)
        self.assertEqual(registry.get("a"), 0, "最早登记的应被淘汰")
        self.assertEqual(registry.get("c"), 3)

    def test_invalid_inputs_ignored(self) -> None:
        registry = PopupRegistry()
        registry.remember("", 5)
        registry.remember("s-1", 0)
        registry.remember("s-1", -3)
        self.assertEqual(registry.get("s-1"), 0)
        self.assertEqual(registry.get(""), 0)

    def test_result_id_reused_for_same_session(self) -> None:
        """端到端语义：同一会话第二次投递会带上第一次的 id。"""
        registry = PopupRegistry()
        commands: list[list[str]] = []

        def runner(command: list[str]) -> tuple[int, str, str]:
            commands.append(list(command))
            return 0, f"(uint32 {100 + len(commands)},)", ""

        for _ in range(2):
            session = "s-1"
            result = deliver_with_runner(
                entry(),
                runner,
                has_gdbus=True,
                has_notify_send=False,
                replaces_id=registry.get(session),
            )
            if result.delivered and result.notification_id is not None:
                registry.remember(session, result.notification_id)

        first, second = commands
        self.assertEqual(first[first.index("DSH-Tray") + 1], "uint32 0")
        self.assertEqual(second[second.index("DSH-Tray") + 1], "uint32 101", "第二次应顶替第一次")


class FailureTest(unittest.TestCase):
    """失败仍返回结果、不抛。"""

    def test_both_missing(self) -> None:
        result = deliver_with_runner(entry(), lambda c: (1, "", "x"), has_gdbus=False, has_notify_send=False)
        self.assertFalse(result.delivered)
        self.assertIsInstance(result, DeliveryResult)


if __name__ == "__main__":
    unittest.main()
