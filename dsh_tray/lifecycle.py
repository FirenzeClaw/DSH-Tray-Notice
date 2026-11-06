"""DSH 生命周期：探测、启动、接管、停止。

本模块不依赖 Qt。所有状态转换都通过同一把操作锁串行化，因此并发调用
（连点、autostart 撞手动启动、托盘与命令行同时操作）不会产生两个实例或
互相矛盾的结论。

设计要点见 docs/design.md 的竞态矩阵；这里每处关键判断都标注了对应的编号。
"""

from __future__ import annotations

import os
import queue
import re
import shutil
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import BinaryIO

from . import probe
from .locks import (
    OwnedRecord,
    clear_owned_record,
    operation_lock,
    read_owned_record,
    state_dir,
    write_owned_record,
)

# 生产路径固定 3080：鉴权 cookie 的 audience 绑定 host:port，换端口会让用户
# 在所有浏览器里静默掉登录。只有自检与测试才覆盖它。
DEFAULT_PORT = 3080

# 实测冷启动到打印令牌行约 13.1 s。但通过 systemd scope 启动时，首次实测
# 出现过 45 s 仍未就绪的情况（冷 cgroup、插件并发初始化），所以取更宽的余量：
# 超时只是失败判定的上限，正常情况 13 s 左右就返回，放宽不拖慢成功路径。
TOKEN_TIMEOUT_SECONDS = 90.0

# dsh 自身优雅退出窗口是 5 s（PROCESS_SHUTDOWN_TIMEOUT_MS）；留一倍余量再强杀。
DEFAULT_STOP_GRACE_SECONDS = 10.0

# 强杀后给内核回收的时间。
_KILL_WAIT_SECONDS = 3.0

_TOKEN_LINE = re.compile(r"^dsh web:\s+(\S+)\s*$")
_LOG_TAIL_LINES = 200


class State(Enum):
    """托盘需要区分的运行状态。"""

    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    FAILED = "failed"


@dataclass(frozen=True)
class Instance:
    """一个正在运行的 DSH Web 实例。"""

    pid: int
    port: int
    owned: bool
    """True 表示由本进程拉起；只有这种实例才拿得到带令牌的 URL。"""
    url: str | None
    """带令牌的完整 URL；接管来的实例为 None（令牌是进程级随机数，拿不到）。"""

    @property
    def open_url(self) -> str:
        """打开 Web UI 应使用的地址。

        owned 用带令牌 URL，浏览器会据此换到长期 cookie；adopted 只能给裸
        URL，依赖浏览器里已有的 cookie。
        """
        return self.url or f"http://127.0.0.1:{self.port}/"

    @property
    def has_token(self) -> bool:
        return self.url is not None


@dataclass
class LifecycleResult:
    """一次状态转换的结果。不作为异常抛出：调用方是 UI，需要一律拿到可展示信息。"""

    ok: bool
    state: State
    message: str
    instance: Instance | None = None
    detail: str = ""
    """多行细节（日志尾部、冲突进程信息等），仅在需要时展示。"""

    @staticmethod
    def failure(state: State, message: str, detail: str = "") -> "LifecycleResult":
        return LifecycleResult(ok=False, state=state, message=message, detail=detail)


def resolve_dsh_command() -> list[str] | None:
    """定位 dsh 启动器。

    优先 ~/.local/bin/dsh（NVM 包装脚本，自带正确的 node 版本），避免把
    node 版本号硬编码进来。
    """
    wrapper = Path.home() / ".local" / "bin" / "dsh"
    if wrapper.is_file() and os.access(wrapper, os.X_OK):
        return [str(wrapper)]
    found = shutil.which("dsh")
    if found:
        return [found]
    return None


def _scope_wrapper(argv: list[str]) -> list[str]:
    """给 dsh 套一层独立的 systemd scope，把它移出调用者的 cgroup。

    为什么必需：托盘若由桌面环境以 systemd 单元（`app-*.service`）启动，
    该单元默认 `KillMode=control-group`。dsh 作为它的子进程会落在同一 cgroup
    里，于是「退出托盘」会把 dsh 连同全部 MCP 子进程一起带走——与「托盘和
    DSH 生命周期分开」的设计相悖。放进独立 scope 后，托盘退出不再波及 dsh。

    实测：`systemd-run --user --scope` 下 Popen.pid 与命令自身 pid 一致（不会
    打破既有的 pid 跟踪）；stdout 会多一行 `Running as unit: ...`，而令牌解析是
    按 `^dsh web:` 精确匹配，不受影响。

    systemd-run 不存在或不在 systemd 会话里时原样返回：宁可丢掉这层隔离，
    也不能因为包装器缺失而启动不了。
    """
    runner = shutil.which("systemd-run")
    if runner is None or not _scope_available(runner):
        return argv
    unit = f"dsh-web-{os.getpid()}-{int(time.time())}"
    return [
        runner, "--user", "--scope", "--collect", f"--unit={unit}", "--",
        *argv,
    ]


@lru_cache(maxsize=1)
def _scope_available(runner: str) -> bool:
    """探测 systemd-run 能否真正建立 scope（结果缓存一次）。

    只做 `import shutil; shutil.which` 是不够的：二进制可能在、但当前会话没有
    可用的 user manager（例如 ssh 登录、容器内）。那种情况下包装命令会直接失败，
    DSH 就永远起不来。这里用 `/bin/true` 真跑一次，失败就退回不加包装的路径
    ——宁可丢掉 cgroup 隔离，也不能牺牲「能启动」这个基本功能。
    """
    try:
        probe = subprocess.run(
            [runner, "--user", "--scope", "--collect",
             f"--unit=dsh-tray-probe-{os.getpid()}", "--", "/bin/true"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return probe.returncode == 0


def _log_path() -> Path:
    logs = state_dir() / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    return logs / "dsh-web.log"


@dataclass
class _Owned:
    """自有子进程的运行时账本。"""

    process: subprocess.Popen[bytes]
    log: Path
    tail: list[str] = field(default_factory=list)
    reader: threading.Thread | None = None


class Lifecycle:
    """串行化的 DSH 生命周期控制器。

    线程安全：UI 线程与工作线程都可调用；所有转换持同一把 RLock 与文件操作锁。
    """

    def __init__(self, port: int = DEFAULT_PORT) -> None:
        self.port = port
        self._lock = threading.RLock()
        self._state = State.STOPPED
        self._instance: Instance | None = None
        self._owned: _Owned | None = None
        self._last_error = ""

    # ------------------------------------------------------------------ 只读视图

    @property
    def state(self) -> State:
        with self._lock:
            return self._state

    @property
    def instance(self) -> Instance | None:
        with self._lock:
            return self._instance

    @property
    def last_error(self) -> str:
        with self._lock:
            return self._last_error

    def snapshot(self) -> tuple[State, Instance | None, str]:
        """一次性取出状态三元组，避免 UI 分三次读时看到撕裂的中间态。"""
        with self._lock:
            return self._state, self._instance, self._last_error

    # ------------------------------------------------------------------ 轮询

    def poll(self) -> tuple[State, Instance | None]:
        """按真实探测结果刷新状态，而不是假设上一次操作的结果仍然成立。

        对应 R8：外部启停（手动跑 dsh、进程崩溃）会被吸收，托盘不说谎。
        正在 STARTING/STOPPING 时不覆盖——那些中间态由对应操作自己结束。
        """
        with self._lock:
            if self._state in (State.STARTING, State.STOPPING):
                return self._state, self._instance
            self._refresh_locked()
            return self._state, self._instance

    def _refresh_locked(self) -> None:
        """持锁时按端口事实重算状态。"""
        self._sweep_stale_record()
        owned = self._owned
        if owned is not None:
            # 自有子进程是权威：它活着就是运行中，死了就不再是。
            if owned.process.poll() is None:
                self._state = State.RUNNING
                return
            # 子进程已退出，账本作废，落到下面的端口探测。
            self._owned = None
            self._instance = None

        listener = probe.find_listener(self.port)
        if listener is not None and listener.is_dsh_web and listener.pid is not None:
            self._state = State.RUNNING
            self._instance = Instance(
                pid=listener.pid,
                port=self.port,
                owned=self._is_owned_by_us(listener.pid),
                url=self._owned_url_for(listener.pid),
            )
            return

        self._instance = None
        if self._state is not State.FAILED:
            self._state = State.STOPPED

    # ------------------------------------------------------------------ 账本

    def _sweep_stale_record(self) -> None:
        """清掉指向已死进程的账本。

        pid 会被系统复用：留着一条 `pid=1234` 的陈旧账本，等 1234 恰好变成
        另一个监听同端口的进程时，我们就会把它误认成自己起的实例，甚至拿它
        去开一个早就失效的带令牌 URL。所以死账本必须及时删。
        """
        record = read_owned_record(self.port)
        if record is not None and not probe.is_alive(record.pid):
            clear_owned_record(self.port)

    def _owned_record_for(self, pid: int) -> OwnedRecord | None:
        """返回属于该 pid 且仍然有效的自有实例账本。

        内存里的 _owned 只在同一进程内有效；托盘重启或 `--start` 之后另开
        `--status` 时，只能靠落盘账本认亲。

        有效性三重校验：端口要对得上（避免跨端口误认）、pid 要对得上、
        进程还活着且仍在该端口监听（否则是上次崩溃留下的陈旧账本）。
        """
        record = read_owned_record(self.port)
        if record is None:
            return None
        if record.port != self.port or record.pid != pid:
            return None
        if not probe.is_alive(record.pid):
            clear_owned_record(self.port)
            return None
        return record

    def _is_owned_by_us(self, pid: int) -> bool:
        """该 pid 是否是本工具拉起的实例（跨进程判断）。"""
        return self._owned_record_for(pid) is not None

    def _owned_url_for(self, pid: int) -> str | None:
        """取自有实例的带令牌 URL；不是自有的返回 None。"""
        record = self._owned_record_for(pid)
        return record.url if record is not None else None

    # ------------------------------------------------------------------ 启动

    def start(self) -> LifecycleResult:
        """确保有一个 DSH 在运行；已存在则接管。

        对应 R1/R2/R3/R4/R5。整个判定 + spawn + 等待令牌的过程持操作锁，
        所以并发的第二次调用进入时看到的是最终状态，不会重复 spawn。
        """
        with self._lock, operation_lock():
            return self._start_locked()

    def _start_locked(self) -> LifecycleResult:
        """已持锁的启动实现。restart 复用它，避免嵌套 flock 自我死锁。"""
        # R1：拿到锁后重新探测，而不是信任调用前的观察。
        self._refresh_locked()
        if self._state is State.RUNNING and self._instance is not None:
            return self._adopted_or_owned_result("DSH 已在运行")

        # R2：端口被非 dsh 进程占着——报错，不 spawn、不 kill。
        listener = probe.find_listener(self.port)
        if listener is not None and not listener.is_dsh_web:
            self._state = State.FAILED
            self._last_error = f"端口 {self.port} 被非 dsh 进程占用"
            return LifecycleResult.failure(
                State.FAILED, self._last_error, listener.describe
            )

        command = resolve_dsh_command()
        if command is None:
            self._state = State.FAILED
            self._last_error = "找不到 dsh 启动器"
            return LifecycleResult.failure(
                State.FAILED,
                self._last_error,
                "已检查 ~/.local/bin/dsh 与 PATH",
            )

        self._state = State.STARTING
        self._last_error = ""
        return self._spawn_locked(command)

    def _spawn_locked(self, command: list[str]) -> LifecycleResult:
        """拉起子进程并等待令牌行。返回时状态已确定。"""
        log_path = _log_path()
        argv = _scope_wrapper(
            [*command, "web", "--no-open", "--port", str(self.port)]
        )
        try:
            log_handle = open(log_path, "wb")
        except OSError as error:
            self._state = State.FAILED
            self._last_error = f"无法写日志 {log_path}: {error}"
            return LifecycleResult.failure(State.FAILED, self._last_error)

        try:
            process = subprocess.Popen(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                # 独立会话：托盘退出不影响 dsh，也便于按会话整体善后。
                start_new_session=True,
                cwd=str(Path.home()),
            )
        except OSError as error:
            log_handle.close()
            self._state = State.FAILED
            self._last_error = f"启动失败: {error}"
            return LifecycleResult.failure(State.FAILED, self._last_error)

        ledger = _Owned(process=process, log=log_path)
        self._owned = ledger

        lines: queue.Queue[str | None] = queue.Queue()
        ledger.reader = threading.Thread(
            target=_pump_output,
            args=(process, log_handle, lines, ledger),
            name="dsh-output-pump",
            daemon=True,
        )
        ledger.reader.start()

        token_url = _await_token(process, lines, ledger, TOKEN_TIMEOUT_SECONDS)

        if token_url is not None:
            self._state = State.RUNNING
            self._instance = Instance(
                pid=process.pid, port=self.port, owned=True, url=token_url
            )
            # 落盘令牌：令牌只存在于本次 stdout，托盘重启后就再也拿不到了。
            try:
                write_owned_record(
                    OwnedRecord(pid=process.pid, port=self.port, url=token_url)
                )
            except OSError:
                # 账本写不进去只影响"重启后仍能免登录打开"，不该让启动失败。
                pass
            return LifecycleResult(
                ok=True,
                state=State.RUNNING,
                message="DSH 已启动",
                instance=self._instance,
            )

        # 没等到令牌行：要么子进程早退，要么卡住了。
        exit_code = process.poll()
        detail = _tail_text(ledger)

        if exit_code is not None:
            # R3：子进程因端口冲突早退，但端口上已经有一个 dsh——说明我们输掉了
            # 竞态，胜出者是别人。收拾自家账本并接管胜出者，而不是报错。
            winner = probe.find_listener(self.port)
            if winner is not None and winner.is_dsh_web and winner.pid is not None:
                self._owned = None
                self._instance = Instance(
                    pid=winner.pid, port=self.port, owned=False, url=None
                )
                self._state = State.RUNNING
                self._last_error = ""
                return LifecycleResult(
                    ok=True,
                    state=State.RUNNING,
                    message=f"已有 DSH 抢先启动，已接管（PID {winner.pid}）",
                    instance=self._instance,
                )
            self._owned = None
            clear_owned_record(self.port)
            self._state = State.FAILED
            self._last_error = f"DSH 启动后立即退出（exit {exit_code}）"
            return LifecycleResult.failure(State.FAILED, self._last_error, detail)

        # R5：超时。先收尾自家子进程，不留一个看不见的残留。
        self._terminate_process(process.pid, grace=2.0)
        self._owned = None
        clear_owned_record(self.port)
        self._state = State.FAILED
        self._last_error = f"等待启动超时（{TOKEN_TIMEOUT_SECONDS:.0f}s 内未就绪）"
        return LifecycleResult.failure(State.FAILED, self._last_error, detail)

    def _adopted_or_owned_result(self, prefix: str) -> LifecycleResult:
        """为已有的运行中实例构造结果，措辞区分自有与接管。"""
        instance = self._instance
        if instance is None:
            return LifecycleResult.failure(State.FAILED, "状态不一致：运行中但无实例")
        kind = "由托盘启动" if instance.owned else "外部启动"
        return LifecycleResult(
            ok=True,
            state=State.RUNNING,
            message=f"{prefix}（{kind}）",
            instance=instance,
        )

    # ------------------------------------------------------------------ 停止

    def stop(self, grace: float = DEFAULT_STOP_GRACE_SECONDS) -> LifecycleResult:
        """停止 DSH。

        先 SIGTERM 让 dsh 自己收拾会话与子进程，超时才 SIGKILL。对应 R6/R7/R10。
        """
        with self._lock, operation_lock():
            return self._stop_locked(grace)

    def _stop_locked(self, grace: float) -> LifecycleResult:
        """已持锁的停止实现。restart 复用它，避免嵌套 flock 自我死锁。"""
        self._refresh_locked()
        instance = self._instance
        if instance is None:
            self._state = State.STOPPED
            return LifecycleResult(
                ok=True, state=State.STOPPED, message="DSH 未在运行"
            )

        self._state = State.STOPPING
        pid = instance.pid
        # R7：杀之前快照子进程，否则杀完就无从知道该清理谁。
        # 受保护进程（自己与祖先）先剔掉：万一托盘恰好挂在这个 dsh 下面，
        # 清理孤儿就成了自杀。
        protected = self._protected_pids()
        orphans = [child for child in probe.child_pids(pid) if child not in protected]
        forced = self._terminate_process(pid, grace=grace)

        # 清理残留子进程。dsh 走优雅退出时自己就会收干净（实测 SIGTERM 后
        # 0.53 s 全退、无残留），这里只处理真正漏网的：被 SIGKILL 掉、或子进程
        # 不响应 SIGTERM 时留下的孤儿。受保护进程（自己与祖先）已在上面剔除。
        cleanup_failures: list[int] = []
        for orphan in orphans:
            if probe.is_alive(orphan):
                self._terminate_process(orphan, grace=1.0)
                if probe.is_alive(orphan):
                    cleanup_failures.append(orphan)

        self._owned = None
        self._instance = None
        clear_owned_record(self.port)

        # R10：停完重新探测，以事实为准，不假设现在是 STOPPED。
        still = probe.find_listener(self.port)
        if still is not None and still.is_dsh_web and still.pid is not None:
            self._instance = Instance(
                pid=still.pid, port=self.port, owned=False, url=None
            )
            self._state = State.RUNNING
            return LifecycleResult(
                ok=False,
                state=State.RUNNING,
                message="停止期间有新的 DSH 启动，已接管",
                instance=self._instance,
            )

        self._state = State.STOPPED
        self._last_error = ""
        note = "已强制结束" if forced else "已停止"
        detail = ""
        if cleanup_failures:
            detail = "未能结束的残留进程: " + ", ".join(
                str(pid_) for pid_ in cleanup_failures
            )
        return LifecycleResult(
            ok=True,
            state=State.STOPPED,
            message=f"DSH {note}（PID {pid}）",
            detail=detail,
        )

    # ------------------------------------------------------------------ 重启

    def restart(self, grace: float = DEFAULT_STOP_GRACE_SECONDS) -> LifecycleResult:
        """停止后重新启动，整个序列在一把操作锁内完成。

        为什么要单列一个方法而不是让调用方 stop() 再 start()：两步之间若放开
        操作锁，别的会话（另一份 `--start`、或用户在菜单里又点了启动）就可能
        插进中间态，产生「刚停完又被人抢起，然后我们再起一个」的分裂结果。
        持锁连续执行，中间态外部不可见。

        重启还有个副作用是想要的：接管的实例（拿不到令牌）重启后会变成自有
        实例，从而重新获得带令牌的 URL。
        """
        with self._lock, operation_lock():
            stopped = self._stop_locked(grace)
            if not stopped.ok:
                # 停止没能达成目标（例如停的过程中又有新的 dsh 顶上来）。
                # 此时贸然再起一个只会制造第二个实例，所以就此打住。
                return LifecycleResult(
                    ok=False,
                    state=stopped.state,
                    message=f"重启中止：{stopped.message}",
                    instance=stopped.instance,
                    detail=stopped.detail,
                )
            started = self._start_locked()
            if started.ok:
                return LifecycleResult(
                    ok=True,
                    state=started.state,
                    message=f"DSH 已重启（{started.message}）",
                    instance=started.instance,
                    detail=started.detail,
                )
            return started

    @staticmethod
    def _protected_pids() -> set[int]:
        """不该被本进程杀掉的 pid：自己，以及自己的祖先链。

        真实事故：托盘曾被从某个 DSH 会话的 bash 工具里拉起，于是它挂在那个
        dsh 的进程树下。停止 dsh 时若把「子进程」当孤儿清理，就会把自己连同
        祖先一起带走。这条保护让误伤在自己这一侧就不可能发生。
        """
        return {os.getpid(), *probe.ancestors(os.getpid())}

    def _terminate_process(self, pid: int, grace: float) -> bool:
        """SIGTERM → 等待 grace → SIGKILL。返回是否用了强杀。"""
        if not probe.is_alive(pid):
            return False
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return False
        except PermissionError:
            return False

        if _wait_for_exit(pid, grace):
            return False

        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            return True
        except PermissionError:
            return True
        _wait_for_exit(pid, _KILL_WAIT_SECONDS)
        return True


def _pump_output(
    process: subprocess.Popen[bytes],
    log_handle: "BinaryIO",
    lines: "queue.Queue[str | None]",
    ledger: _Owned,
) -> None:
    """持续把子进程输出写进日志并放进队列。

    必须一直读到 EOF：一旦停止读取，管道缓冲区（64 KiB）写满后 dsh 会阻塞在
    write 上，整个进程假死。所以这个循环在拿到令牌行之后仍然继续跑，只是
    队列无人消费。
    """
    stream = process.stdout
    if stream is None:
        return
    try:
        for raw in stream:
            try:
                log_handle.write(raw)
                log_handle.flush()
            except (OSError, ValueError):
                pass
            text = raw.decode("utf-8", "replace").rstrip("\n")
            ledger.tail.append(text)
            if len(ledger.tail) > _LOG_TAIL_LINES:
                del ledger.tail[: len(ledger.tail) - _LOG_TAIL_LINES]
            try:
                lines.put_nowait(text)
            except queue.Full:
                pass
    finally:
        try:
            stream.close()
        except OSError:
            pass
        try:
            lines.put_nowait(None)
        except queue.Full:
            pass


def _await_token(
    process: subprocess.Popen[bytes],
    lines: "queue.Queue[str | None]",
    ledger: _Owned,
    timeout: float,
) -> str | None:
    """等 `dsh web: <url>?token=...` 那一行；子进程先退出或超时都返回 None。

    判据是「令牌行 / 子进程退出 / 超时」三者先到者，而不是单纯等满时间：
    子进程已经死了还继续等，只会把真实错误拖成超时错误。
    """
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        try:
            line = lines.get(timeout=min(0.5, remaining))
        except queue.Empty:
            if process.poll() is not None:
                return None
            continue
        if line is None:
            return None
        match = _TOKEN_LINE.match(line.strip())
        if match:
            return match.group(1)
        if process.poll() is not None:
            return None


def _wait_for_exit(pid: int, timeout: float) -> bool:
    """轮询等待进程退出；超时返回 False。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not probe.is_alive(pid):
            return True
        time.sleep(0.1)
    return not probe.is_alive(pid)


def _tail_text(ledger: _Owned, count: int = 20) -> str:
    """取日志尾部若干行用于错误展示。"""
    if not ledger.tail:
        return ""
    return "\n".join(ledger.tail[-count:])
