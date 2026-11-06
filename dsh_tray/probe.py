"""Linux 进程与端口的只读探测。

本模块不依赖 Qt，也不修改任何进程状态：只从 /proc 读取事实，供 lifecycle 判定。
放这里而不是塞进 lifecycle，是为了让「谁占着端口」「这进程是不是 dsh」这类
判定能被单独测试，而不必先起一个 GUI 或一个真实 dsh。
"""

from __future__ import annotations

import glob
import os
from dataclasses import dataclass

# /proc/net/tcp 的状态位：0A = LISTEN
_TCP_LISTEN = "0A"
_TCP_FILES = ("/proc/net/tcp", "/proc/net/tcp6")


@dataclass(frozen=True)
class Listener:
    """一个正在监听某端口的进程。"""

    pid: int | None
    """持有该 socket 的进程；None 表示 socket 在、但扫不到持有者（权限或已退出）。"""

    cmdline: tuple[str, ...]
    """进程命令行参数；空元组表示读不到。"""

    @property
    def is_dsh_web(self) -> bool:
        """命令行里是否明确是 `dsh ... web`。

        判据同时要求 basename 为 dsh 的参数和 web 子命令：只看端口会把
        任何监听者当成 dsh，只看 dsh 会把 `dsh headless` 误判为 Web 实例。
        """
        if not self.cmdline:
            return False
        has_dsh = any(os.path.basename(arg) == "dsh" for arg in self.cmdline)
        return has_dsh and "web" in self.cmdline[1:]

    @property
    def describe(self) -> str:
        """人类可读的一行描述，用于错误提示与 tooltip。"""
        if not self.cmdline:
            return f"PID {self.pid}（无法读取命令行）"
        rendered = " ".join(self.cmdline)
        if len(rendered) > 96:
            rendered = rendered[:93] + "..."
        return f"PID {self.pid}: {rendered}"


def listening_inode(port: int) -> int | None:
    """返回监听该端口的 socket inode；没有监听者则返回 None。

    监听状态的 socket 的 inode 可直接用于在 /proc/<pid>/fd 下反查持有进程。
    """
    if not 0 < port < 65536:
        raise ValueError(f"端口超出范围: {port}")
    wanted = f"{port:04X}"
    for path in _TCP_FILES:
        try:
            with open(path, "r", encoding="ascii") as handle:
                lines = handle.read().splitlines()[1:]
        except OSError:
            continue
        for line in lines:
            fields = line.split()
            if len(fields) < 10:
                continue
            local, state, inode = fields[1], fields[3], fields[9]
            if state != _TCP_LISTEN:
                continue
            if local.rsplit(":", 1)[-1] == wanted:
                try:
                    return int(inode)
                except ValueError:
                    continue
    return None


def inode_owner(inode: int) -> int | None:
    """扫 /proc/*/fd 找到持有该 socket inode 的进程。

    扫描而非用 `ss -p`：后者在多进程共享 socket 时只会报第一个，且需要额外
    子进程。扫描是纯 /proc 读取，不 fork，也不受命令是否安装影响。
    """
    target = f"socket:[{inode}]"
    for fd_path in glob.glob("/proc/[0-9]*/fd/*"):
        try:
            if os.readlink(fd_path) != target:
                continue
        except OSError:
            # 进程在此刻退出，或 fd 属于无权限访问的其他用户进程。
            continue
        try:
            return int(fd_path.split("/")[2])
        except (IndexError, ValueError):
            continue
    return None


def read_cmdline(pid: int) -> tuple[str, ...]:
    """读进程命令行；读不到返回空元组（进程可能已退出或无权限）。"""
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as handle:
            raw = handle.read()
    except OSError:
        return ()
    if not raw:
        return ()
    parts = [chunk.decode("utf-8", "replace") for chunk in raw.split(b"\0") if chunk]
    return tuple(parts)


def find_listener(port: int) -> Listener | None:
    """探测端口，返回监听者；无人监听返回 None。"""
    inode = listening_inode(port)
    if inode is None:
        return None
    pid = inode_owner(inode)
    return Listener(pid=pid, cmdline=read_cmdline(pid) if pid else ())


def is_alive(pid: int) -> bool:
    """进程是否存活。

    用信号 0 而非读 /proc/<pid>：zombie 进程 /proc 目录仍在，但已经不再运行，
    对它发 SIGTERM 永远等不到退出，会让停止流程白等到超时。
    """
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # 进程存在但不属于当前用户。
        return True
    return not _is_zombie(pid)


def _is_zombie(pid: int) -> bool:
    """读 /proc/<pid>/stat 的第 3 个字段（状态字符）判断是否为僵尸。"""
    try:
        with open(f"/proc/{pid}/stat", "r", encoding="utf-8") as handle:
            stat = handle.read()
    except OSError:
        return False
    # comm 字段可能含空格与括号，所以从最后一个 ')' 之后开始切分。
    try:
        after_comm = stat[stat.rindex(")") + 1 :].split()
    except ValueError:
        return False
    return bool(after_comm) and after_comm[0] == "Z"


def parent_pid(pid: int) -> int | None:
    """读 /proc/<pid>/stat 的 ppid。"""
    try:
        with open(f"/proc/{pid}/stat", "r", encoding="utf-8") as handle:
            stat = handle.read()
    except OSError:
        return None
    try:
        after_comm = stat[stat.rindex(")") + 1 :].split()
    except ValueError:
        return None
    if len(after_comm) < 2:
        return None
    try:
        ppid = int(after_comm[1])
    except ValueError:
        return None
    return ppid if ppid > 0 else None


def ancestors(pid: int, limit: int = 64) -> list[int]:
    """返回到根的祖先链（不含自身）。

    用来回答「我要杀的这个进程，会不会把我自己或我的父进程一起带走」。
    从 DSH 会话的 bash 里启动的托盘正是这种情况：托盘是 dsh 的后代，
    dsh 停掉时托盘会跟着消失，用户看到的就是"托盘不见了"。
    """
    chain: list[int] = []
    current = pid
    for _ in range(limit):
        parent = parent_pid(current)
        if parent is None or parent in chain:
            break
        chain.append(parent)
        current = parent
    return chain


def child_pids(pid: int) -> list[int]:
    """直接子进程列表。用于停止进程后清理它留下的孤儿。"""
    children: list[int] = []
    for stat_path in glob.glob("/proc/[0-9]*/stat"):
        try:
            with open(stat_path, "r", encoding="utf-8") as handle:
                stat = handle.read()
        except OSError:
            continue
        try:
            after_comm = stat[stat.rindex(")") + 1 :].split()
        except ValueError:
            continue
        # 字段顺序：state ppid pgrp ...
        if len(after_comm) >= 2:
            try:
                if int(after_comm[1]) == pid:
                    children.append(int(stat_path.split("/")[2]))
            except ValueError:
                continue
    return children
