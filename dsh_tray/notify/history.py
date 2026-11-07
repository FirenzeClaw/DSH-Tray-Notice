"""通知历史：持久化、淘汰、已读标记、日期分组。

为什么「已查看不删除」：用户回查进度时要能看到三天前那条「已完成」，点进去回到
当时的会话。删除只会让历史变成一次性通知中心，失去回查价值。

存储：`~/.local/state/dsh-tray/notifications.json`，原子写（临时文件 + replace）。
上限 500 条 / 30 天：超过就淘汰最旧的——这两个数不是拍脑袋，500 条在 378 px 面板里
按日期分组后仍需滚动很久，而 30 天覆盖「上周那个任务后来怎么样了」。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..locks import operation_lock, state_dir
from .types import NotificationEntry

# 历史上限。
MAX_ENTRIES = 500

# 过期天数。
MAX_AGE_DAYS = 30

# 文件名。
HISTORY_FILENAME = "notifications.json"


def history_path() -> Path:
    """历史文件路径。

    @returns `~/.local/state/dsh-tray/notifications.json`
    """
    return state_dir() / HISTORY_FILENAME


@dataclass(frozen=True, slots=True)
class StoredNotification:
    """落盘的一条通知：条目本体 + 已读状态 + 是否补投。"""

    entry: NotificationEntry
    read: bool = False
    replayed: bool = False
    """是否为托盘缺席期间的补投（US7）。"""


def _serialize(item: StoredNotification) -> dict[str, object]:
    """序列化一条记录。

    @param item - 记录
    @returns 可 JSON 化的字典
    """
    entry = item.entry
    return {
        "v": entry.v,
        "id": entry.id,
        "ts": entry.ts.isoformat(),
        "kind": entry.kind,
        "sessionId": entry.session_id,
        "sessionTitle": entry.session_title,
        "workspace": entry.workspace,
        "title": entry.title,
        "body": entry.body,
        "urgency": entry.urgency,
        "openUrl": entry.open_url,
        "dedupeKey": entry.dedupe_key,
        # 显式白名单容易漏字段：加字段时必须同时改这里（`_deserialize` 走 from_json，
        # 是宽进的，所以漏了不会报错，只会静默丢数据——已踩过一次）。
        "timeoutMs": entry.timeout_ms,
        "read": item.read,
        "replayed": item.replayed,
    }


def _deserialize(raw: object) -> StoredNotification | None:
    """反序列化一条记录。

    @param raw - JSON 值
    @returns 记录；坏数据返回 None
    """
    if not isinstance(raw, dict):
        return None
    payload = dict(raw)
    payload.setdefault("v", 1)
    payload.setdefault("type", "notification")
    entry = NotificationEntry.from_json(payload)
    if entry is None:
        return None
    return StoredNotification(
        entry=entry,
        read=bool(raw.get("read", False)),
        replayed=bool(raw.get("replayed", False)),
    )


def load() -> list[StoredNotification]:
    """读全部历史（按时间升序）。

    文件不存在、损坏、权限不足都返回空列表：历史是辅助能力，不该让托盘起不来。

    @returns 记录列表
    """
    path = history_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(raw, list):
        return []
    items = [_deserialize(item) for item in raw]
    return [item for item in items if item is not None]


def _save(items: list[StoredNotification]) -> None:
    """原子写回。

    先写同目录临时文件再 `replace`：并发读到的要么是旧文件、要么是新文件，
    不会读到半截 JSON。

    @param items - 记录列表
    """
    path = history_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps([_serialize(item) for item in items], ensure_ascii=False)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def _prune(items: list[StoredNotification], now: datetime) -> list[StoredNotification]:
    """按条数与时间淘汰。

    先按时间过滤，再按条数截断（保留最近的）。顺序不能反：反了会让「500 条以内
    但全都很旧」的历史留下来。

    @param items - 记录列表
    @param now - 当前时刻
    @returns 淘汰后的列表
    """
    cutoff = now - timedelta(days=MAX_AGE_DAYS)
    fresh = [item for item in items if item.entry.ts >= cutoff]
    if len(fresh) > MAX_ENTRIES:
        fresh = fresh[-MAX_ENTRIES:]
    return fresh


def append(entry: NotificationEntry, now: datetime | None = None, replayed: bool = False) -> None:
    """追加一条通知。

    写前用 `operation_lock` 串行化：托盘只有一个实例，但 `--start` 等 CLI 也可能
    间接触发写，跨进程串行比进程内锁更可靠。

    @param entry - 通知条目
    @param now - 当前时刻；测试注入
    @param replayed - 是否为补投
    """
    current = now or datetime.now(timezone.utc)
    with operation_lock("notify-history.lock"):
        items = load()
        if any(item.entry.id == entry.id for item in items):
            return
        items.append(StoredNotification(entry=entry, read=False, replayed=replayed))
        _save(_prune(items, current))


def mark_read(entry_id: str) -> bool:
    """把一条标为已查看。

    @param entry_id - 条目 id
    @returns 找到并修改为 True
    """
    with operation_lock("notify-history.lock"):
        items = load()
        changed = False
        updated: list[StoredNotification] = []
        for item in items:
            if item.entry.id == entry_id and not item.read:
                updated.append(replace(item, read=True))
                changed = True
            else:
                updated.append(item)
        if changed:
            _save(updated)
        return changed


def mark_all_read(now: datetime | None = None) -> int:
    """把全部未查看标为已查看。

    @param now - 当前时刻；测试注入
    @returns 被标记的条数
    """
    with operation_lock("notify-history.lock"):
        items = load()
        count = 0
        updated: list[StoredNotification] = []
        for item in items:
            if item.read:
                updated.append(item)
            else:
                updated.append(replace(item, read=True))
                count += 1
        if count:
            _save(_prune(updated, now or datetime.now(timezone.utc)))
        return count


def clear_read(now: datetime | None = None) -> int:
    """清空已查看，保留未查看。

    @param now - 当前时刻；测试注入
    @returns 被删除的条数
    """
    with operation_lock("notify-history.lock"):
        items = load()
        kept = [item for item in items if not item.read]
        removed = len(items) - len(kept)
        if removed:
            _save(_prune(kept, now or datetime.now(timezone.utc)))
        return removed


def unread_count() -> int:
    """未查看条数（不含 test 类别）。

    @returns 条数
    """
    return sum(1 for item in load() if not item.read and item.entry.kind != "test")


def group_by_day(
    items: list[StoredNotification] | None = None,
    now: datetime | None = None,
) -> list[tuple[str, list[StoredNotification]]]:
    """按本地日期分组。

    分组键用本地时区：用户说的「今天」是墙上的今天，不是 UTC 的今天。跨时区旅行时
    这会带来一点歧义，但那比「昨天下午的事显示在今天」更符合直觉。

    @param items - 记录；缺省读历史
    @param now - 当前时刻；测试注入
    @returns [(组标题, 该组记录)]，组按时间倒序
    """
    records = items if items is not None else load()
    current = (now or datetime.now(timezone.utc)).astimezone()
    today = current.date()
    yesterday = today - timedelta(days=1)

    buckets: dict[str, list[StoredNotification]] = {}
    for item in sorted(records, key=lambda record: record.entry.ts, reverse=True):
        local_date = item.entry.ts.astimezone().date()
        if local_date == today:
            label = "今天"
        elif local_date == yesterday:
            label = "昨天"
        elif (today - local_date).days <= 7:
            label = "本周"
        else:
            label = local_date.strftime("%Y-%m-%d")
        buckets.setdefault(label, []).append(item)

    # 组顺序按组内最新一条的时间倒序，而不是字典插入顺序——跨天补投时插入顺序不可靠。
    ordered = sorted(
        buckets.items(),
        key=lambda pair: max(record.entry.ts for record in pair[1]),
        reverse=True,
    )
    return ordered
