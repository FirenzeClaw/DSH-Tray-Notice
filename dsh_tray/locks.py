"""文件锁原语。

两种锁，用途不同，都不依赖 Qt：

- 托盘单实例锁：整台机器上只允许一个托盘进程。进程一死内核自动释放，
  所以不需要清理陈旧锁文件。
- 操作锁：把 start/stop 这类状态转换串行化。跨进程也生效，以防用户既
  开了托盘又手动跑了 `dsh-tray.py --stop`。
"""

from __future__ import annotations

import errno
import fcntl
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


def state_dir() -> Path:
    """放置锁与日志的目录，遵循 XDG。

    XDG_STATE_HOME 本机未设置，退到 ~/.local/state。锁放这里而不是 /tmp：
    /tmp 可能被 tmpwatch 清理，且多用户机器上 /tmp 是共享命名空间。
    """
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    path = Path(base) / "dsh-tray"
    path.mkdir(parents=True, exist_ok=True)
    return path


class SingleInstanceLock:
    """非阻塞独占锁，用于托盘自身的单实例保证。

    用 flock 而非 pid 文件：pid 文件需要「检查进程是否存活」的启发式判断，
    而那正是竞态的来源（检查与写入之间进程可能刚好启动）。flock 由内核
    维护，进程消失即释放。
    """

    def __init__(self, name: str = "tray.lock") -> None:
        self.path = state_dir() / name
        self._fd: int | None = None

    def acquire(self) -> bool:
        """尝试获取锁；已被其他进程持有则返回 False。"""
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            os.close(fd)
            if error.errno in (errno.EACCES, errno.EAGAIN):
                return False
            raise
        self._fd = fd
        # 写入 pid 仅供人工排查；判定权威始终是 flock 本身。
        os.ftruncate(fd, 0)
        os.write(fd, f"{os.getpid()}\n".encode("ascii"))
        return True

    def release(self) -> None:
        """释放锁。重复调用安全。"""
        if self._fd is None:
            return
        try:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            os.close(self._fd)
            self._fd = None

    def holder_pid(self) -> int | None:
        """读锁文件里记录的 pid，仅用于提示「已被谁占用」。"""
        try:
            return int(self.path.read_text(encoding="ascii").strip())
        except (OSError, ValueError):
            return None


@contextmanager
def operation_lock(name: str = "op.lock", blocking: bool = True) -> Iterator[None]:
    """把一次状态转换括起来，跨进程串行。

    用 flock 独占而不只是读内容：这样 `--stop` 在托盘正在 start 时会等它
    做完，而不是看到中间态后做出错误决定。
    """
    path = state_dir() / name
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    flags = fcntl.LOCK_EX if blocking else fcntl.LOCK_EX | fcntl.LOCK_NB
    try:
        fcntl.flock(fd, flags)
    except OSError:
        os.close(fd)
        raise
    try:
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def _owned_path(port: int) -> Path:
    """自有实例账本的文件路径，按端口隔离。

    用单一 `owned.json` 会让不同端口的实例互相覆盖：测过 3187 之后，3080 的
    账本就被顶掉了，`--status` 于是把由托盘启动的实例误报成「外部启动」。
    """
    return state_dir() / f"owned-{port}.json"


def read_owned_record(port: int) -> "OwnedRecord | None":
    """读自有实例账本；没有或已失效返回 None。

    账本解决一个真实问题：托盘与 `--start` 是不同进程，托盘重启后无法凭
    内存判断"这个 dsh 是不是我起的"。令牌是进程级随机数，只存在于启动者的
    stdout 里，所以必须把 URL 落盘，重启后才能继续打开带令牌的地址。
    """
    path = _owned_path(port)
    try:
        import json

        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    try:
        record = OwnedRecord(
            pid=int(data["pid"]),
            port=int(data["port"]),
            url=str(data["url"]),
        )
    except (KeyError, TypeError, ValueError):
        return None
    if record.pid <= 0:
        return None
    return record


def write_owned_record(record: "OwnedRecord") -> None:
    """写入自有实例账本。"""
    import json

    path = _owned_path(record.port)
    payload = json.dumps(
        {"pid": record.pid, "port": record.port, "url": record.url},
        ensure_ascii=False,
    )
    # 先写临时文件再原子替换：读到半截 JSON 比读到旧账本更糟。
    tmp = path.with_suffix(".tmp")
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(path)


def clear_owned_record(port: int) -> None:
    """删除该端的自有实例账本。"""
    path = _owned_path(port)
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


class OwnedRecord:
    """跨进程的自有实例账本（pid、端口、带令牌 URL）。"""

    def __init__(self, pid: int, port: int, url: str) -> None:
        self.pid = pid
        self.port = port
        self.url = url
