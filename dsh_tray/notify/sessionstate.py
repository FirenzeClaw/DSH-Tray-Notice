"""托盘侧会话状态表：把 spool 的快照折成「现在谁在跑」。

与插件侧 `plugin/src/sessionstate.ts` 的分工：那边负责**产生**快照（变了才写），
这边负责**消费**快照（全量替换、过滤子会话、算时长）。两侧都维护一份「当前状态」，
但来源不同，所以不能合并。

时长用本地时钟减 `turnStartedAt`，不依赖心跳：插件崩了、托盘刚启动，只要快照还在，
时长就还能算——这正是「卡住了」需要看到的信号。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from .types import SessionRow, SessionState


@dataclass(frozen=True, slots=True)
class ActiveSession:
    """「工作中」页的一行。"""

    id: str
    title: str
    turn: int
    current_tool: str | None
    waiting_for_user: bool
    origin: str
    turn_started_at: datetime | None


class SessionTable:
    """活动会话表。

    只保留最近一次快照的内容；`apply()` 是全量替换。
    """

    def __init__(self, show_subagents: bool = False) -> None:
        """构造。

        @param show_subagents - 是否显示子会话；默认关闭（子会话的完成通常不是
            用户关心的事，混进列表反而稀释信号）
        """
        self._show_subagents = show_subagents
        self._rows: tuple[SessionRow, ...] = ()

    def apply(self, snapshot: SessionState) -> None:
        """应用一份全量快照。

        @param snapshot - 会话快照
        """
        self._rows = snapshot.sessions

    def clear(self) -> None:
        """清空（DSH 停止时调用）。"""
        self._rows = ()

    def active(self) -> tuple[ActiveSession, ...]:
        """当前活动的会话行。

        `idle` 的会话不在「工作中」页显示：它已经跑完了，留在列表里会让人误以为
        还在等。

        @returns 会话行（按标题排序，避免每次刷新顺序抖动）
        """
        rows = [
            ActiveSession(
                id=row.id,
                title=row.title,
                turn=row.turn,
                current_tool=row.current_tool,
                waiting_for_user=row.state == "waiting-user",
                origin=row.origin,
                turn_started_at=row.turn_started_at,
            )
            for row in self._rows
            if row.state != "idle" and (self._show_subagents or row.origin != "subagent")
        ]
        return tuple(sorted(rows, key=lambda entry: (entry.title, entry.id)))

    def elapsed(self, session_id: str, now: datetime | None = None) -> int | None:
        """某会话本轮已跑秒数。

        @param session_id - 会话标识
        @param now - 当前时刻；测试注入
        @returns 秒数；会话不存在或没有起始时刻时 None
        """
        row = next((candidate for candidate in self._rows if candidate.id == session_id), None)
        if row is None or row.turn_started_at is None:
            return None
        current = now or datetime.now(timezone.utc)
        delta = (current - row.turn_started_at).total_seconds()
        # 时钟回拨或快照来自「未来」时钳到 0：显示负时长比显示 0 更让人困惑。
        return max(0, int(delta))

    @staticmethod
    def format_elapsed(seconds: int | None) -> str:
        """把秒数写成紧凑中文。

        @param seconds - 秒数；None 表示未知
        @returns 形如 `2 分 5 秒` / `1 时 2 分`
        """
        if seconds is None:
            return "—"
        if seconds < 60:
            return f"{seconds} 秒"
        if seconds < 3600:
            return f"{seconds // 60} 分 {seconds % 60} 秒"
        return f"{seconds // 3600} 时 {(seconds % 3600) // 60} 分"
