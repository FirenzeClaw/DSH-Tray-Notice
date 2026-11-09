"""投递层：把条目变成系统通知。

为什么不用 `notify-send`：它不支持动作按钮（实测报 `Actions are not supported by
this notifications server`），而「点通知回到会话」是本规格的 P1 需求。改用
`gdbus` 直接调 `org.freedesktop.Notifications.Notify`，显式声明每个参数的类型——
自动推断会把 `uint32` 推成 `int`、把 `as` 推成 `av`，服务端以签名不符拒绝。

回退策略：没有 `gdbus` 时退到 `notify-send`（无按钮，但至少能弹出）；两者都没有
就返回失败，由调用方在 tooltip 里说明「通知不可用」。
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Callable, Mapping, Sequence

# 应用名；与 .desktop 的 StartupWMClass 无关，只影响通知中心的归组。
APP_NAME = "DSH-Tray"

# 动作键与按钮文案。`default` 是 freedesktop 约定的「点通知本体」键。
ACTION_KEY = "default"
ACTION_LABEL = "打开会话"

# 通知超时（毫秒）——仅作为条目没带 `timeoutMs` 时的兜底。
#
# critical 的兜底值是 5 分钟而不是 0（不自动消失）：实测「不消失」的横幅会占住
# Plasma 的通知弹窗位，用户不点掉它，**后续所有通知都排队不显示**，看起来就像
# 通知功能坏了。真正的时限由插件按设置下发（见 types.py 的 `banner_timeout_ms`）。
TIMEOUT_CRITICAL_MS = 300_000
TIMEOUT_NORMAL_MS = 5000

# 一次调用的超时；D-Bus 卡住时不该拖住消费循环。
CALL_TIMEOUT_SECONDS = 3.0

# runner 签名：(命令) → (返回码, stdout, stderr)
Runner = Callable[[Sequence[str]], "tuple[int, str, str]"]


@dataclass(frozen=True, slots=True)
class DeliveryResult:
    """一次投递的结果。"""

    delivered: bool
    notification_id: int | None = None
    reason: str | None = None
    """失败原因（已脱敏）；成功时为 None。"""


def timeout_for(entry: Mapping[str, object]) -> int:
    """取本条通知的横幅停留毫秒数。

    优先用条目自带的 `timeoutMs`（插件按用户设置下发），缺省才按紧急度兜底。

    @param entry - 通知条目
    @returns 毫秒数
    """
    raw = entry.get("timeoutMs")
    if isinstance(raw, (int, float)) and not isinstance(raw, bool) and raw > 0:
        return int(raw)
    return TIMEOUT_CRITICAL_MS if entry.get("urgency") == "critical" else TIMEOUT_NORMAL_MS


@dataclass(slots=True)
class PopupRegistry:
    """会话 → 该会话最近一条桌面弹窗的 id。

    为什么要它：同一会话反复弹通知时，新的一条用 `replaces_id` **顶替**旧横幅，
    而不是排队。排队会让用户看到一串过期的「需要你审批」，且最旧的那条一直占着
    弹窗位。

    只在投递成功且拿到 id 时登记；只保留最近 `limit` 个会话，避免长跑进程里
    会话表无限增长。
    """

    limit: int = 200
    _ids: dict[str, int] = field(default_factory=dict)

    def get(self, session_id: str) -> int:
        """取该会话最近的弹窗 id。

        @param session_id - 会话 id
        @returns id；没有则 0（0 = 让通知服务新建）
        """
        return self._ids.get(session_id, 0)

    def remember(self, session_id: str, notification_id: int) -> None:
        """登记一次成功投递。

        @param session_id - 会话 id
        @param notification_id - 通知服务分配的 id
        """
        if not session_id or notification_id <= 0:
            return
        # 重新插入以刷新顺序：dict 保序，最早插入的排在最前。
        self._ids.pop(session_id, None)
        self._ids[session_id] = notification_id
        while len(self._ids) > self.limit:
            self._ids.pop(next(iter(self._ids)))


def build_gdbus_command(
    entry: Mapping[str, object],
    replaces_id: int = 0,
    *,
    with_actions: bool = True,
) -> list[str]:
    """构造 `gdbus call` 命令。

    每个参数都带显式类型前缀，这是能调通的关键：
    - `replaces_id` 必须是 `uint32`（0 = 新建）
    - `actions` 必须是 `as`（字符串数组），不是 `av`
    - `hints` 是 `a{sv}`，空字典写作 `{}`
    - `expire_timeout` 是 `int32`

    格式是 **`uint32 0`（空格）而不是 `uint32:0`（冒号）**：gdbus 用 GVariant 文本
    格式，冒号写法会报「解析 u 类型的第 2 个参数时发生错误」。这个错很隐蔽——
    投递会静默回退到 `notify-send`，通知照样弹出，只是没有动作按钮。

    @param entry - 通知条目（dict 形态，字段名与 spool 一致）
    @param replaces_id - 顶替哪条弹窗；0 = 新建
    @param with_actions - 是否声明 `default` 动作。
        **Plasma 6.6.6 上必须传 False**：实测 actions 非空时通知被接受但不渲染在
        任何位置（横幅、通知中心、全屏 OCR 都没有，见
        research/linux-notification-actions.md 第五节）。代价是「点通知」不再触发，
        交互只能走托盘。
    @returns 完整 argv
    """
    title = str(entry.get("title", ""))
    body = str(entry.get("body", ""))
    return [
        "gdbus",
        "call",
        "--session",
        "--dest",
        "org.freedesktop.Notifications",
        "--object-path",
        "/org/freedesktop/Notifications",
        "--method",
        "org.freedesktop.Notifications.Notify",
        APP_NAME,
        f"uint32 {replaces_id:d}",
        "",
        title,
        body,
        f"['{ACTION_KEY}', '{ACTION_LABEL}']" if with_actions else "[]",
        "{}",
        f"int32 {timeout_for(entry)}",
    ]


def build_notify_send_command(entry: Mapping[str, object]) -> list[str]:
    """构造 `notify-send` 回退命令（无动作按钮）。

    @param entry - 通知条目
    @returns 完整 argv
    """
    urgency = "critical" if entry.get("urgency") == "critical" else "normal"
    return [
        "notify-send",
        "--app-name",
        APP_NAME,
        "--urgency",
        urgency,
        str(entry.get("title", "")),
        str(entry.get("body", "")),
    ]


def _default_runner(command: Sequence[str]) -> "tuple[int, str, str]":
    """默认 runner：真的跑子进程。

    @param command - argv
    @returns (返回码, stdout, stderr)；启动失败按返回码 127 处理
    """
    try:
        completed = subprocess.run(
            list(command),
            capture_output=True,
            text=True,
            timeout=CALL_TIMEOUT_SECONDS,
            check=False,
        )
        return completed.returncode, completed.stdout, completed.stderr
    except (OSError, subprocess.SubprocessError) as error:
        return 127, "", str(error)


def _parse_notification_id(stdout: str) -> int | None:
    """从 `(uint32 155,)` 里取出 id。

    必须跳过类型名本身：`uint32` 里就带一个 32，逐字符取数字会把它当 id（实测踩过）。

    @param stdout - gdbus 输出
    @returns id；解析不出时 None
    """
    match = re.search(r"uint32\s+(\d+)", stdout)
    return int(match.group(1)) if match is not None else None


def deliver_with_runner(
    entry: Mapping[str, object],
    runner: Runner | None = None,
    *,
    has_gdbus: bool | None = None,
    has_notify_send: bool | None = None,
    replaces_id: int = 0,
    with_actions: bool = True,
) -> DeliveryResult:
    """投递一条通知。

    优先 `gdbus`（支持动作），其次 `notify-send`，都没有则失败。任何异常都转成
    失败结果，绝不向上抛——投递失败不该中断消费循环。

    @param entry - 通知条目
    @param runner - 命令执行器；测试注入
    @param has_gdbus - 是否可用；None 时探测 PATH
    @param has_notify_send - 同上
    @param replaces_id - 顶替哪条弹窗；0 = 新建。回退到 notify-send 时不生效
        （libnotify 不支持顶替），届时会多出一条横幅而不是替换
    @param with_actions - 是否声明动作按钮；KDE 上必须 False，否则整条通知不显示
    @returns 投递结果
    """
    run = runner or _default_runner
    gdbus_available = shutil.which("gdbus") is not None if has_gdbus is None else has_gdbus
    notify_available = shutil.which("notify-send") is not None if has_notify_send is None else has_notify_send

    if gdbus_available:
        try:
            code, stdout, stderr = run(
                build_gdbus_command(entry, replaces_id, with_actions=with_actions)
            )
        except Exception as error:  # noqa: BLE001 - 投递失败不得中断调用方
            return DeliveryResult(False, reason=f"gdbus 调用异常：{error}")
        if code == 0:
            return DeliveryResult(True, notification_id=_parse_notification_id(stdout))
        # gdbus 失败后再试 notify-send：可能是通知服务重启中。
        if not notify_available:
            return DeliveryResult(False, reason=stderr.strip() or f"gdbus 返回 {code}")

    if notify_available:
        try:
            code, _stdout, stderr = run(build_notify_send_command(entry))
        except Exception as error:  # noqa: BLE001
            return DeliveryResult(False, reason=f"notify-send 调用异常：{error}")
        if code == 0:
            return DeliveryResult(True)
        return DeliveryResult(False, reason=stderr.strip() or f"notify-send 返回 {code}")

    return DeliveryResult(False, reason="系统既无 gdbus 也无 notify-send")


def deliver(
    entry: Mapping[str, object],
    replaces_id: int = 0,
    *,
    with_actions: bool = True,
) -> DeliveryResult:
    """投递一条通知（使用默认真实 runner）。

    @param entry - 通知条目
    @param replaces_id - 顶替哪条弹窗；0 = 新建
    @param with_actions - 是否声明动作按钮；KDE 上必须 False
    @returns 投递结果
    """
    return deliver_with_runner(entry, replaces_id=replaces_id, with_actions=with_actions)
