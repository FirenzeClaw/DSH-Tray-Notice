"""托盘侧 spool 读取：增量读、轮转识别、坏行跳过。

三条设计要点，每条都对应一个真实失败模式：

1. **偏移必须带 inode**。只记 offset 的话，插件轮转后新文件从头写，而托盘会从旧
   offset 继续读——正好跳过新文件的头部。记 inode，变了就从 0 重读。
2. **坏行不能中断整批**。spool 里出现半行是正常工况（写入被打断、插件升级中），
   跳过并计数，让调用方决定是否提示。
3. **半行不推进偏移**。读到没有换行结尾的尾巴时，说明写入方还没写完这一行；
   把它留给下一轮，否则会解析失败并永久丢掉这条事件。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from .types import NotificationEntry, SessionState, TraySettings, parse_row

# 偏移文件名（放在 state 目录，与锁和日志同处）。
OFFSET_FILENAME = "spool-offset.json"

# 一次最多读多少行，防止插件疯狂写入时单轮卡住 GUI 线程。
MAX_ROWS_PER_READ = 200


@dataclass(frozen=True, slots=True)
class SpoolBatch:
    """一轮增量读的结果。"""

    notifications: tuple[NotificationEntry, ...]
    session_states: tuple[SessionState, ...]
    skipped: int
    """解析失败或版本不符的行数（含未知 type）。"""
    tray_settings: "TraySettings | None" = None
    """本批里最后一条托盘外观设置；一个批次内只认最后一条。"""

    @property
    def is_empty(self) -> bool:
        """本轮是否什么都没读到。"""
        return (
            not self.notifications
            and not self.session_states
            and self.tray_settings is None
            and self.skipped == 0
        )


def _state_path(state_dir: Path) -> Path:
    """偏移文件路径。"""
    return state_dir / OFFSET_FILENAME


def load_offset(state_dir: Path, spool_path: Path) -> int:
    """读出应从哪里继续读。

    返回 0 的三种情况：偏移文件不存在、内容损坏、inode 与当前文件不符（说明轮转
    过或文件被重建）。三种都意味着「从头读」，而重读是安全的——托盘按 `id` 去重。

    @param state_dir - 状态目录
    @param spool_path - spool 文件
    @returns 字节偏移
    """
    path = _state_path(state_dir)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    if not isinstance(raw, dict):
        return 0
    inode = raw.get("inode")
    offset = raw.get("offset")
    if not isinstance(inode, int) or not isinstance(offset, int) or offset < 0:
        return 0
    try:
        if spool_path.stat().st_ino != inode:
            return 0
    except OSError:
        return 0
    return offset


def save_offset(state_dir: Path, spool_path: Path, offset: int) -> None:
    """持久化读取位置。

    写失败静默：下一轮会从头重读并靠 `id` 去重，代价是重复解析，不是丢事件。

    @param state_dir - 状态目录
    @param spool_path - spool 文件
    @param offset - 已消费到的字节偏移
    """
    try:
        inode = spool_path.stat().st_ino
    except OSError:
        return
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        path = _state_path(state_dir)
        path.write_text(json.dumps({"inode": inode, "offset": offset}), encoding="utf-8")
        # 偏移文件不含敏感内容，但状态目录整体按 0700/0600 收口更简单一致。
        path.chmod(0o600)
    except OSError:
        return


def read_new(spool_path: Path, state_dir: Path) -> SpoolBatch:
    """读自上次以来新增的完整行。

    @param spool_path - spool 文件（可能尚不存在）
    @param state_dir - 状态目录，用于偏移文件
    @returns 本轮解析结果
    """
    offset = load_offset(state_dir, spool_path)
    try:
        size = spool_path.stat().st_size
    except OSError:
        return SpoolBatch((), (), 0)
    if size < offset:
        # 文件变短了（被截断或重建但 inode 未变，例如同 inode 的 truncate）。
        offset = 0

    try:
        with spool_path.open("rb") as handle:
            handle.seek(offset)
            chunk = handle.read()
    except OSError:
        return SpoolBatch((), (), 0)

    if not chunk:
        return SpoolBatch((), (), 0)

    consumed = chunk.rfind(b"\n")
    if consumed < 0:
        # 没有完整行：写入方还没写完，等下一轮。
        return SpoolBatch((), (), 0)
    payload = chunk[: consumed + 1]
    next_offset = offset + consumed + 1

    notifications: list[NotificationEntry] = []
    states: list[SessionState] = []
    settings: TraySettings | None = None
    skipped = 0
    for raw_line in payload.split(b"\n"):
        if not raw_line.strip():
            continue
        if len(notifications) + len(states) >= MAX_ROWS_PER_READ:
            # 到量就停：把偏移停在本行之前，下一轮继续，避免单轮占满 GUI 线程。
            next_offset -= len(raw_line) + 1
            break
        try:
            parsed_json = json.loads(raw_line.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            skipped += 1
            continue
        row = parse_row(parsed_json)
        if row is None:
            skipped += 1
        elif isinstance(row, NotificationEntry):
            notifications.append(row)
        elif isinstance(row, TraySettings):
            # 只保留本批最后一条：设置是全量覆盖，中间态没有意义。
            settings = row
        else:
            states.append(row)

    save_offset(state_dir, spool_path, next_offset)
    return SpoolBatch(tuple(notifications), tuple(states), skipped, settings)


def spool_path_for(dsh_home: Path) -> Path:
    """spool 的规范位置：`$DSH_HOME/run/tray-notify/events.jsonl`。

    @param dsh_home - DSH home 根目录
    @returns spool 路径
    """
    return dsh_home / "run" / "tray-notify" / "events.jsonl"


def resolve_dsh_home() -> Path:
    """解析 DSH home：`$DSH_HOME` 优先，其次 `~/.dsh`。

    与 `@deepseek-ai/dsh-home-paths` 的 `resolveDshHome` 同规则（空白值视为未设置），
    但这里不 import 那个包——托盘是纯 Python 侧，不该为了一个路径引入 Node 依赖。

    @returns DSH home 路径
    """
    override = os.environ.get("DSH_HOME", "").strip()
    if override:
        return Path(override).expanduser()
    return Path(os.path.expanduser("~/.dsh"))
