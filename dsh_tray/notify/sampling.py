"""进程采样：只读 `/proc`，不 fork 外部命令。

为什么自采而不是问 DSH：概览页要回答的问题是「DSH 是不是卡住了、谁在吃 CPU」。
如果 DSH 卡住，它自己上报的数据也不可信——采样必须独立于被观测对象。

为什么首次 CPU 是 `None` 而不是 0：CPU 占用是**差值**，没有上一次读数就没有分母。
显示 0% 会让人以为进程真的闲着，而实际可能是满载。

解析容错：进程在两次读取之间退出、`/proc/<pid>/stat` 的 comm 里带空格与括号、
VmRSS 缺失——三种都按「读不到」处理，不抛错。
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Callable, Iterable, Sequence


@dataclass(frozen=True, slots=True)
class ProcessRow:
    """一行采样。"""

    pid: int
    role: str
    label: str
    cpu_percent: float | None
    rss_bytes: int
    age_seconds: int | None


@dataclass(frozen=True, slots=True)
class SampleSummary:
    """合计值。"""

    cpu_percent: float
    rss_bytes: int
    process_count: int

    @classmethod
    def from_rows(cls, rows: Sequence[ProcessRow]) -> "SampleSummary":
        """由采样行求和。

        `None` 的 CPU 不参与求和（首次采样还没基准），但进程数照算——它确实存在。

        @param rows - 采样行
        @returns 合计
        """
        cpu = sum(row.cpu_percent for row in rows if row.cpu_percent is not None)
        return cls(
            cpu_percent=round(cpu, 1),
            rss_bytes=sum(row.rss_bytes for row in rows),
            process_count=len(rows),
        )


def parse_stat(line: str) -> tuple[float, float] | None:
    """解析 `/proc/<pid>/stat` 的一行。

    comm 字段可能含空格与括号（实测 `dsh web (main)`），所以必须从**最后一个** `)`
    之后开始切分，否则字段会整体错位。

    @param line - stat 内容
    @returns (utime+stime 的 jiffies, starttime 的 jiffies)；无法解析时 None
    """
    close = line.rfind(")")
    if close < 0:
        return None
    tail = line[close + 1 :].split()
    if len(tail) < 20:
        return None
    try:
        # tail[0] 是 state，utime/stime 是第 12/13 个字段（去掉 pid 与 comm 后偏移 11/12）
        ticks = float(tail[11]) + float(tail[12])
        starttime = float(tail[19])
    except (ValueError, IndexError):
        return None
    return ticks, starttime


def parse_rss_bytes(status: str) -> int:
    """从 `/proc/<pid>/status` 取 VmRSS。

    @param status - status 内容
    @returns 字节数；缺失或格式不对时 0
    """
    for line in status.splitlines():
        if line.startswith("VmRSS:"):
            parts = line.split()
            if len(parts) >= 2:
                try:
                    return int(parts[1]) * 1024
                except ValueError:
                    return 0
    return 0


class CpuTracker:
    """跨两次采样求 CPU 百分比。"""

    def __init__(self, clock_ticks: int | None = None) -> None:
        """构造。

        @param clock_ticks - 每秒 jiffies；缺省读 sysconf
        """
        self._ticks = clock_ticks or os.sysconf("SC_CLK_TCK")
        self._previous: dict[int, float] = {}

    def update(self, pid: int, ticks: float, elapsed_seconds: float) -> float | None:
        """更新一个进程的 CPU 占用。

        @param pid - 进程号
        @param ticks - 累计 CPU jiffies
        @param elapsed_seconds - 距上次采样的秒数
        @returns 单核百分比；首次或时间不可用时 None
        """
        previous = self._previous.get(pid)
        self._previous[pid] = ticks
        if previous is None or elapsed_seconds <= 0:
            return None
        delta = ticks - previous
        if delta <= 0:
            return 0.0
        return round(delta / self._ticks / elapsed_seconds * 100.0, 1)

    def forget(self, alive: set[int]) -> None:
        """丢掉已消失进程的记录。

        @param alive - 当前存活的 pid 集合
        """
        for pid in list(self._previous):
            if pid not in alive:
                del self._previous[pid]


def sample_rows(
    pids: Iterable[int],
    *,
    read_stat: Callable[[int], tuple[float, float] | None],
    read_rss: Callable[[int], int],
    classify: Callable[[int], tuple[str, str]] = lambda pid: ("other", f"pid {pid}"),
    tracker: CpuTracker | None = None,
    elapsed_seconds: float | None = None,
    clock_ticks: int | None = None,
    uptime: float | None = None,
) -> list[ProcessRow]:
    """对一批 pid 采样。

    所有外部读取都通过参数注入，测试因此不需要真的进程。

    @param pids - 进程号列表
    @param read_stat - 读 stat，返回 (ticks, starttime)
    @param read_rss - 读 VmRSS 字节数
    @param classify - 判定 (role, label)
    @param tracker - CPU 求差器；None 时新建（此时全部为首次采样）
    @param elapsed_seconds - 距上次采样的秒数
    @param clock_ticks - 每秒 jiffies
    @param uptime - 系统运行秒数，用于算进程年龄
    @returns 采样行；读不到 stat 的 pid 被跳过
    """
    cpu_tracker = tracker or CpuTracker(clock_ticks)
    rows: list[ProcessRow] = []
    for pid in pids:
        stat = read_stat(pid)
        if stat is None:
            continue
        ticks, starttime = stat
        cpu = cpu_tracker.update(pid, ticks, elapsed_seconds or 0.0)
        role, label = classify(pid)
        age = None
        if uptime is not None:
            age = max(0, int(uptime - starttime / (clock_ticks or os.sysconf("SC_CLK_TCK"))))
        rows.append(
            ProcessRow(
                pid=pid,
                role=role,
                label=label,
                cpu_percent=cpu,
                rss_bytes=read_rss(pid),
                age_seconds=age,
            )
        )
    return rows


def _read_proc_stat(pid: int) -> tuple[float, float] | None:
    """读真实 `/proc/<pid>/stat`。"""
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8", errors="replace") as handle:
            return parse_stat(handle.read())
    except OSError:
        return None


def _read_proc_rss(pid: int) -> int:
    """读真实 `/proc/<pid>/status`。"""
    try:
        with open(f"/proc/{pid}/status", encoding="utf-8", errors="replace") as handle:
            return parse_rss_bytes(handle.read())
    except OSError:
        return 0


def _uptime() -> float:
    """系统运行秒数。"""
    try:
        with open("/proc/uptime", encoding="utf-8") as handle:
            return float(handle.read().split()[0])
    except (OSError, ValueError, IndexError):
        return 0.0


class ProcSampler:
    """真实采样器（读 `/proc`）。"""

    def __init__(self) -> None:
        """构造。"""
        self._tracker = CpuTracker()
        self._last: float | None = None

    def sample(self, pids: Iterable[int]) -> list[ProcessRow]:
        """采一次样。

        @param pids - 要采的 pid 列表
        @returns 采样行
        """
        now = time.monotonic()
        elapsed = None if self._last is None else now - self._last
        rows = sample_rows(
            list(pids),
            read_stat=_read_proc_stat,
            read_rss=_read_proc_rss,
            tracker=self._tracker,
            elapsed_seconds=elapsed,
            uptime=_uptime(),
        )
        self._tracker.forget({row.pid for row in rows})
        self._last = now
        return rows
