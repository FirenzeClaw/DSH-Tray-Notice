"""展示模型：去重、紧急度、相对时间、类别标签。

把「一条 spool 条目该怎么呈现」收在一处：面板与系统通知都用它，避免两处各写一套
标签导致同一件事在通知里叫「完成」、在面板里叫「跑完了」。

去重窗口 10 秒：同 `dedupeKey` 的条目在这段时间内只接受第一条。窗口是权衡——
短了挡不住插件重发，长了会把「连续两次真实事件」合并掉。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Mapping

from .types import NotificationEntry

# 同 dedupeKey 的去重窗口。
DEDUPE_WINDOW_SECONDS = 10

# 类别 → 中文标签。未知类别归「其它」。
CATEGORY_LABELS: Mapping[str, str] = {
    "needs-approval": "需要你",
    "needs-answer": "需要你",
    "done": "完成",
    "error": "出错",
    "blocked": "阻塞",
    "max-tokens": "超限",
    "cancelled": "取消",
    "interrupted": "中断",
    "notice": "提示",
    "job": "其它",
    "goal": "其它",
    "subagent": "其它",
    "tool-failure": "其它",
    "test": "测试",
}


@dataclass(frozen=True, slots=True)
class Display:
    """一条通知的展示字段。"""

    entry: NotificationEntry
    category: str
    relative_time: str
    critical: bool
    expire_timeout_ms: int
    is_test: bool
    counts_toward_unread: bool


def _relative(ts: datetime, now: datetime) -> str:
    """把时间差写成中文相对时间。

    超过 30 天就不再说「N 天前」——那时用户关心的是日期本身，由列表的分组头承担。

    @param ts - 事件时刻
    @param now - 当前时刻
    @returns 相对时间文本
    """
    delta = now - ts
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return "刚刚"
    if seconds < 3600:
        return f"{seconds // 60} 分钟前"
    if seconds < 86400:
        return f"{seconds // 3600} 小时前"
    days = seconds // 86400
    if days <= 30:
        return f"{days} 天前"
    return ts.astimezone().strftime("%Y-%m-%d")


def to_display(entry: NotificationEntry, now: datetime | None = None) -> Display:
    """构造展示字段。

    @param entry - 通知条目
    @param now - 当前时刻；测试注入
    @returns 展示字段
    """
    current = now or datetime.now(timezone.utc)
    critical = entry.urgency == "critical"
    is_test = entry.kind == "test"
    return Display(
        entry=entry,
        category=CATEGORY_LABELS.get(entry.kind, "其它"),
        relative_time=_relative(entry.ts, current),
        critical=critical,
        # critical 用 0 = 不自动消失；normal 交回系统默认（5 秒）。
        expire_timeout_ms=0 if critical else 5000,
        is_test=is_test,
        # test 是设置页的自检类别，不该污染未读计数与统计。
        counts_toward_unread=not is_test,
    )


class DisplayModel:
    """去重窗口与未读计数。

    只保留每个 dedupeKey 的最近一次接受时刻；表的大小与「最近 10 秒内出现过的
    不同事件数」同阶，不会无限增长。
    """

    def __init__(self) -> None:
        """构造空模型。"""
        self._seen: dict[str, datetime] = {}
        self._unread = 0

    def accept(self, entry: NotificationEntry, now: datetime | None = None) -> bool:
        """判断是否接受这条通知（同键且窗口内则丢弃）。

        接受时顺带推进未读计数（`test` 类别不计）。

        @param entry - 通知条目
        @param now - 当前时刻；缺省用条目自身时刻
        @returns 接受为 True
        """
        current = now or entry.ts
        previous = self._seen.get(entry.dedupe_key)
        if previous is not None and (current - previous).total_seconds() < DEDUPE_WINDOW_SECONDS:
            return False
        self._seen[entry.dedupe_key] = current
        self._prune(current)
        if to_display(entry, current).counts_toward_unread:
            self._unread += 1
        return True

    def _prune(self, now: datetime) -> None:
        """清掉窗口外的记录，避免表长期增长。

        @param now - 当前时刻
        """
        cutoff = now - timedelta(seconds=DEDUPE_WINDOW_SECONDS)
        stale = [key for key, seen in self._seen.items() if seen < cutoff]
        for key in stale:
            del self._seen[key]

    @property
    def unread_count(self) -> int:
        """本轮会话内接受的未读条数。"""
        return self._unread

    def reset_unread(self) -> None:
        """把未读计数清零（用户全部标为已查看后调用）。"""
        self._unread = 0
