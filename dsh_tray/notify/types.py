"""托盘侧的契约类型：spool 行的两种形态。

与 `plugin/src/types.ts` 一一对应。刻意不共享代码：双语言仓库里，共享 schema 的
成本（生成、版本、调试）高于各写一份、靠契约文档与测试对齐。

解析策略：**宽进严出**。`from_json` 对缺字段、错类型、版本不匹配一律返回 None，
由调用方计数跳过——spool 里出现半行坏数据不该让托盘崩，也不该让整批停摆
（contracts C1「跳过 + 计数」）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

# 协议版本。与 plugin/src/types.ts 的 SCHEMA_VERSION 必须一致。
SCHEMA_VERSION = 1

# 已知通知类别。未知值不算错——插件可能先于托盘升级——但托盘按「其它」处理。
KNOWN_KINDS = frozenset(
    {
        "needs-approval",
        "needs-answer",
        "done",
        "error",
        "blocked",
        "max-tokens",
        "job",
        "goal",
        "subagent",
        "tool-failure",
        "notice",
        "test",
    }
)

# 会话运行态与来源。
RUN_STATES = frozenset({"working", "waiting-user", "idle"})
ORIGINS = frozenset({"root", "subagent"})


def parse_ts(raw: Any) -> datetime | None:
    """把 ISO-8601 字符串解析成带时区的 datetime。

    为什么容忍 `Z` 后缀：JS 的 `toISOString()` 产出的就是 `…Z`，而
    `datetime.fromisoformat` 直到 3.11 才接受它——本机是 3.14，但仍显式替换，
    免得代码被复制到旧解释器上时静默失败。

    @param raw - 待解析值
    @returns UTC datetime；无法解析时 None
    """
    if not isinstance(raw, str) or raw == "":
        return None
    text = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _text(raw: Any) -> str | None:
    """取必填字符串字段；类型不对或为空返回 None。"""
    return raw if isinstance(raw, str) else None


def _optional_text(raw: Any) -> str | None:
    """取可选字符串字段；缺失或类型不对返回 None（不视为错误）。"""
    return raw if isinstance(raw, str) else None


class _BadRow(Exception):
    """必填字段缺失或类型不对。

    用异常而非逐字段 `if … is None: return None`：九个必填字段各写一次判断会让
    构造过程淹没在守卫里，而这里唯一需要的语义就是「任一不合格即整行作废」。
    """


def _need(raw: Mapping[str, Any], key: str) -> str:
    """取必填字符串字段，不合格即抛 `_BadRow`。

    @param raw - 原始字典
    @param key - 字段名
    @returns 字段值
    @throws _BadRow - 缺失或不是字符串时
    """
    value = _text(raw.get(key))
    if value is None:
        raise _BadRow(key)
    return value


@dataclass(frozen=True, slots=True)
class NotificationEntry:
    """一条通知。托盘侧主键是 `id`（幂等消费）。"""

    v: int
    id: str
    ts: datetime
    kind: str
    session_id: str
    session_title: str
    title: str
    body: str
    urgency: str
    open_url: str
    dedupe_key: str
    workspace: str | None = None

    @property
    def is_critical(self) -> bool:
        """是否「需要你」级别——决定是否抢焦点与用 critical urgency。"""
        return self.urgency == "critical"

    @classmethod
    def from_json(cls, raw: Mapping[str, Any]) -> "NotificationEntry | None":
        """从 spool 行构造。

        @param raw - 已 `json.loads` 的字典
        @returns 条目；版本不符、缺必填字段或类型错误时 None
        """
        if raw.get("v") != SCHEMA_VERSION:
            return None
        if raw.get("type") != "notification":
            return None
        ts = parse_ts(raw.get("ts"))
        if ts is None:
            return None
        try:
            return cls(
                v=SCHEMA_VERSION,
                id=_need(raw, "id"),
                ts=ts,
                kind=_need(raw, "kind"),
                session_id=_need(raw, "sessionId"),
                session_title=_need(raw, "sessionTitle"),
                title=_need(raw, "title"),
                body=_need(raw, "body"),
                urgency=_need(raw, "urgency"),
                open_url=_need(raw, "openUrl"),
                dedupe_key=_need(raw, "dedupeKey"),
                workspace=_optional_text(raw.get("workspace")),
            )
        except _BadRow:
            return None


@dataclass(frozen=True, slots=True)
class SessionRow:
    """一个会话的当前状态。"""

    id: str
    title: str
    state: str
    turn: int
    origin: str
    turn_started_at: datetime | None = None
    current_tool: str | None = None

    @property
    def is_working(self) -> bool:
        """是否正在跑——「工作中」页与概览的计数口径。"""
        return self.state == "working"

    @classmethod
    def from_json(cls, raw: Mapping[str, Any]) -> "SessionRow | None":
        """从快照里的单个会话对象构造。

        @param raw - 字典
        @returns 行；缺必填字段或类型错误时 None
        """
        session_id = _text(raw.get("id"))
        title = _text(raw.get("title"))
        state = _text(raw.get("state"))
        origin = _text(raw.get("origin"))
        turn = raw.get("turn")
        if session_id is None or title is None or state is None or origin is None:
            return None
        if not isinstance(turn, int) or isinstance(turn, bool):
            return None
        return cls(
            id=session_id,
            title=title,
            state=state,
            turn=turn,
            origin=origin,
            turn_started_at=parse_ts(raw.get("turnStartedAt")),
            current_tool=_optional_text(raw.get("currentTool")),
        )


@dataclass(frozen=True, slots=True)
class SessionState:
    """会话状态快照。

    `sessions` 是全量替换而非增量（data-model.md 不变量 4）：托盘收到就整体换掉，
    不做合并——插件侧因此不必维护「哪些会话已下线」的账本。
    """

    v: int
    ts: datetime
    sessions: tuple[SessionRow, ...]

    @classmethod
    def from_json(cls, raw: Mapping[str, Any]) -> "SessionState | None":
        """从 spool 行构造。

        @param raw - 已 `json.loads` 的字典
        @returns 快照；版本不符或结构错误时 None
        """
        if raw.get("v") != SCHEMA_VERSION:
            return None
        if raw.get("type") != "session-state":
            return None
        ts = parse_ts(raw.get("ts"))
        rows = raw.get("sessions")
        if ts is None or not isinstance(rows, list):
            return None
        parsed: list[SessionRow] = []
        for item in rows:
            if not isinstance(item, Mapping):
                continue
            row = SessionRow.from_json(item)
            if row is not None:
                parsed.append(row)
        return cls(v=SCHEMA_VERSION, ts=ts, sessions=tuple(parsed))


def parse_row(raw: Any) -> "NotificationEntry | SessionState | None":
    """把一行 spool 数据解析成契约对象。

    未知 `type` 与版本不符都返回 None，由调用方计入跳过数——托盘不该因为插件先
    升级或写了半行就崩掉（contracts C1）。

    @param raw - 已 `json.loads` 的任意值
    @returns 通知条目或会话快照；无法识别时 None
    """
    if not isinstance(raw, Mapping):
        return None
    row_type = raw.get("type")
    if row_type == "notification":
        return NotificationEntry.from_json(raw)
    if row_type == "session-state":
        return SessionState.from_json(raw)
    return None
