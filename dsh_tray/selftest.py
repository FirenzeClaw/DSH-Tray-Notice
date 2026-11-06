"""竞态自检：用假 dsh 验证 docs/design.md 竞态矩阵里的关键场景。

为什么不拿真实 3080 测：那个端口上跑着为当前会话服务的 dsh，停掉它会中断
正在进行的对话。所以这里全部用临时端口 + 假 dsh 进程，互不干扰。

假 dsh 有两个变体，分别模拟真 dsh 的两种行为：
- 正常启动：占住端口，打印令牌行，然后挂住直到 SIGTERM。
- 抢跑：启动时发现端口已被占，立刻以非零退出（模拟 EADDRINUSE 早退）。
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from . import probe
from .locks import SingleInstanceLock, operation_lock
from .lifecycle import Lifecycle, State

_FAKE_DSH_TEMPLATE = textwrap.dedent(
    """\
    #!{python}
    import signal, socket, sys, time

    port = 3080
    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg == "--port" and i + 1 < len(args):
            port = int(args[i + 1])

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("127.0.0.1", port))
        sock.listen(8)
    except OSError as error:
        print(f"fake-dsh: cannot bind {{port}}: {{error}}", file=sys.stderr, flush=True)
        sys.exit(1)

    print(f"[fake] listening on {{port}}", flush=True)
    time.sleep(0.2)
    print(f"dsh web: http://127.0.0.1:{{port}}/?token=FAKE{{port}}", flush=True)

    stopping = False
    def on_term(signum, frame):
        global stopping
        stopping = True
    signal.signal(signal.SIGTERM, on_term)

    while not stopping:
        time.sleep(0.05)
    sock.close()
    sys.exit(0)
    """
)

_HANGING_DSH = textwrap.dedent(
    """\
    #!{python}
    # 永不打印令牌行，也不绑端口：用来触发「等待令牌超时」路径。
    import time
    while True:
        time.sleep(1)
    """
)


@dataclass
class CheckResult:
    """一条自检结果。"""

    name: str
    passed: bool
    note: str


def _write_script(directory: Path, variant: str, body: str) -> Path:
    """在独立子目录里写一个名为 `dsh` 的可执行文件。

    名字必须是 `dsh`：lifecycle 用 basename 判定「这是不是一个 dsh 进程」，
    换成别的名字会被当成陌生进程占端口，于是走错分支。
    """
    target = directory / variant
    target.mkdir(parents=True, exist_ok=True)
    path = target / "dsh"
    path.write_text(body.replace("{python}", sys.executable), encoding="utf-8")
    path.chmod(0o755)
    return path


def _free_port() -> int:
    """问内核要一个当前空闲的端口，降低自检端口本身被占的概率。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _patch_resolver(lifecycle_module, command: Path) -> None:
    """让 lifecycle 用假 dsh 而不是真启动器。"""
    lifecycle_module.resolve_dsh_command = lambda: [str(command)]


def run_selftest() -> list[CheckResult]:
    """跑全部场景，返回结果列表。不修改真实环境。"""
    import dsh_tray.lifecycle as lifecycle_module

    original_resolver = lifecycle_module.resolve_dsh_command
    results: list[CheckResult] = []
    with tempfile.TemporaryDirectory(prefix="dsh-tray-selftest-") as raw_dir:
        workdir = Path(raw_dir)
        good = _write_script(workdir, "ok", _FAKE_DSH_TEMPLATE)
        hanging = _write_script(workdir, "hang", _HANGING_DSH)

        try:
            _patch_resolver(lifecycle_module, good)

            results.append(_check_r1_concurrent_start())
            results.append(_check_r2_foreign_listener(workdir))
            results.append(_check_r3_race_loss(workdir))
            results.append(_check_r5_token_timeout(hanging))
            results.append(_check_r6_concurrent_stop())
            results.append(_check_r7_orphan_cleanup(workdir))
            results.append(_check_r8_external_change())
            results.append(_check_r9_second_tray())
            results.append(_check_r10_restart_during_stop(workdir))
            results.append(_check_r11_restart(workdir))
        finally:
            lifecycle_module.resolve_dsh_command = original_resolver
    return results


def _check_r1_concurrent_start() -> CheckResult:
    """R1：两个线程同时 start，只能产生一个实例。"""
    port = _free_port()
    lifecycle = Lifecycle(port=port)
    outcomes: list[object] = []
    barrier = threading.Barrier(2)

    def worker() -> None:
        barrier.wait()
        outcomes.append(lifecycle.start())

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    try:
        listeners = [r for r in outcomes if getattr(r, "ok", False)]
        pids = {r.instance.pid for r in outcomes if getattr(r, "instance", None)}
        ok = len(listeners) == 2 and len(pids) == 1
        note = f"两次调用均成功={len(listeners)==2}, 唯一 PID 数={len(pids)}"
        return CheckResult("R1 并发 start 只起一个实例", ok, note)
    finally:
        lifecycle.stop(grace=3)


def _check_r2_foreign_listener(workdir: Path) -> CheckResult:
    """R2：端口被非 dsh 进程占用时应报错，且不 spawn、不 kill 对方。"""
    port = _free_port()
    squatter = subprocess.Popen(
        [sys.executable, "-c", textwrap.dedent(f"""
            import socket, time
            s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("127.0.0.1", {port})); s.listen(4)
            time.sleep(30)
            """)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_until(lambda: probe.find_listener(port) is not None, 5.0)
        lifecycle = Lifecycle(port=port)
        result = lifecycle.start()
        survived = squatter.poll() is None
        ok = (not result.ok) and result.state is State.FAILED and survived
        note = f"被拒绝={not result.ok}, 占用者存活={survived}, 提示={result.message!r}"
        return CheckResult("R2 非 dsh 占用端口时拒绝启动", ok, note)
    finally:
        squatter.terminate()
        try:
            squatter.wait(timeout=5)
        except subprocess.TimeoutExpired:
            squatter.kill()


def _check_r3_race_loss(workdir: Path) -> CheckResult:
    """R3：自家子进程因端口被 dsh 抢走而早退时，应接管胜出者而非报错。"""
    port = _free_port()
    winner = subprocess.Popen(
        [sys.executable, str(workdir / "ok" / "dsh"), "web", "--port", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_until(lambda: _listener_is_fake(port, workdir / "ok" / "dsh"), 8.0)
        lifecycle = Lifecycle(port=port)
        result = lifecycle.start()
        adopted = result.instance is not None and not result.instance.owned
        ok = result.ok and adopted and result.instance.pid == winner.pid
        note = (
            f"成功={result.ok}, 接管={adopted}, "
            f"PID={getattr(result.instance, 'pid', None)}（期望 {winner.pid}）"
        )
        return CheckResult("R3 竞态失败方接管胜出者", ok, note)
    finally:
        winner.terminate()
        try:
            winner.wait(timeout=5)
        except subprocess.TimeoutExpired:
            winner.kill()


def _check_r5_token_timeout(hanging: Path) -> CheckResult:
    """R5：等不到令牌行时应超时失败，并把卡住的子进程收掉。"""
    import dsh_tray.lifecycle as lifecycle_module

    port = _free_port()
    original = lifecycle_module.TOKEN_TIMEOUT_SECONDS
    original_resolver = lifecycle_module.resolve_dsh_command
    lifecycle_module.TOKEN_TIMEOUT_SECONDS = 2.0
    lifecycle_module.resolve_dsh_command = lambda: [str(hanging)]
    try:
        lifecycle = Lifecycle(port=port)
        token = str(hanging)
        before = set(_all_pids_with(token))
        result = lifecycle.start()
        after = set(_all_pids_with(token))
        leaked = after - before
        ok = (not result.ok) and result.state is State.FAILED and not leaked
        note = f"失败={not result.ok}, 状态={result.state.value}, 残留进程={len(leaked)}"
        return CheckResult("R5 等待就绪超时后收尾", ok, note)
    finally:
        lifecycle_module.TOKEN_TIMEOUT_SECONDS = original
        lifecycle_module.resolve_dsh_command = original_resolver


def _check_r6_concurrent_stop() -> CheckResult:
    """R6：并发 stop 应幂等，都能干净返回。"""
    port = _free_port()
    lifecycle = Lifecycle(port=port)
    started = lifecycle.start()
    if not started.ok:
        return CheckResult("R6 并发 stop 幂等", False, f"前置启动失败: {started.message}")

    outcomes: list[object] = []
    barrier = threading.Barrier(2)

    def worker() -> None:
        barrier.wait()
        outcomes.append(lifecycle.stop(grace=5))

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=40)

    all_ok = all(getattr(r, "ok", False) for r in outcomes) and len(outcomes) == 2
    final = lifecycle.poll()[0]
    ok = all_ok and final is State.STOPPED
    note = f"两次均成功={all_ok}, 终态={final.value}"
    return CheckResult("R6 并发 stop 幂等", ok, note)


def _check_r7_orphan_cleanup(workdir: Path) -> CheckResult:
    """R7：停止时留下的子进程应按快照清理干净。"""
    port = _free_port()
    child_py = workdir / "orphan-child.py"
    child_py.write_text("import time\nwhile True: time.sleep(1)\n", encoding="utf-8")

    child_dir = workdir / "withchild"
    child_dir.mkdir(exist_ok=True)
    script = child_dir / "dsh"
    script.write_text(
        textwrap.dedent(
            f"""\
            #!{sys.executable}
            import subprocess, sys, socket, time, signal
            port = {port}
            s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("127.0.0.1", port)); s.listen(4)
            child = subprocess.Popen([sys.executable, {str(child_py)!r}])
            print(f"dsh web: http://127.0.0.1:{{port}}/?token=ORPHAN", flush=True)
            stop = False
            def on_term(n, f):
                global stop
                stop = True
            signal.signal(signal.SIGTERM, on_term)
            while not stop:
                time.sleep(0.05)
            # 故意不杀 child，模拟留下孤儿
            s.close()
            sys.exit(0)
            """
        ),
        encoding="utf-8",
    )
    script.chmod(0o755)

    import dsh_tray.lifecycle as lifecycle_module

    original_resolver = lifecycle_module.resolve_dsh_command
    lifecycle_module.resolve_dsh_command = lambda: [str(script)]
    try:
        lifecycle = Lifecycle(port=port)
        started = lifecycle.start()
        if not started.ok:
            return CheckResult("R7 停止后清理子进程", False, f"前置启动失败: {started.message}")
        main_pid = started.instance.pid
        children = probe.child_pids(main_pid)
        result = lifecycle.stop(grace=5)
        time.sleep(0.5)
        survivors = [c for c in children if probe.is_alive(c)]
        ok = result.ok and not survivors
        note = f"子进程数={len(children)}, 残留={len(survivors)}, 停止={result.message!r}"
        return CheckResult("R7 停止后清理子进程", ok, note)
    finally:
        lifecycle_module.resolve_dsh_command = original_resolver


def _check_r8_external_change() -> CheckResult:
    """R8：外部启动/停止应被轮询吸收，托盘状态跟随事实。"""
    port = _free_port()
    lifecycle = Lifecycle(port=port)
    external = subprocess.Popen(
        [sys.executable, "-c", textwrap.dedent(f"""
            import socket, time, sys
            s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("127.0.0.1", {port})); s.listen(4)
            time.sleep(30)
            """)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_until(lambda: probe.find_listener(port) is not None, 5.0)
        # 非 dsh 监听者：poll 不应把它当成 DSH。
        state, instance = lifecycle.poll()
        not_confused = instance is None
        external.terminate()
        external.wait(timeout=5)
        _wait_until(lambda: probe.find_listener(port) is None, 5.0)
        state2, instance2 = lifecycle.poll()
        ok = not_confused and instance2 is None
        note = f"非 dsh 未误判={not_confused}, 消失后状态={state2.value}"
        return CheckResult("R8 轮询吸收外部变化", ok, note)
    finally:
        if external.poll() is None:
            external.kill()


def _check_r9_second_tray() -> CheckResult:
    """R9：第二个托盘实例拿不到单实例锁。"""
    first = SingleInstanceLock("selftest-tray.lock")
    second = SingleInstanceLock("selftest-tray.lock")
    try:
        got_first = first.acquire()
        got_second = second.acquire()
        ok = got_first and not got_second
        note = f"首个获得={got_first}, 第二个被拒绝={not got_second}"
        return CheckResult("R9 托盘单实例锁生效", ok, note)
    finally:
        second.release()
        first.release()
        # 自检创建的锁文件不属于运行期产物，用完删掉。
        try:
            first.path.unlink()
        except OSError:
            pass


def _check_r10_restart_during_stop(workdir: Path) -> CheckResult:
    """R10：停止过程中外部又起了 dsh，停完应以事实为准接管它。"""
    port = _free_port()
    lifecycle = Lifecycle(port=port)
    started = lifecycle.start()
    if not started.ok:
        return CheckResult("R10 停止期间新实例被接管", False, f"前置启动失败: {started.message}")

    revived: list[subprocess.Popen[bytes]] = []

    def revive_later() -> None:
        # 等主进程开始退出了再抢占端口，模拟「刚停就有人又拉起一个」。
        _wait_until(lambda: not probe.is_alive(started.instance.pid), 15.0)
        revived.append(
            subprocess.Popen(
                [sys.executable, str(workdir / "ok" / "dsh"), "web", "--port", str(port)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        )

    thread = threading.Thread(target=revive_later, daemon=True)
    thread.start()
    result = lifecycle.stop(grace=6)
    thread.join(timeout=20)
    time.sleep(0.5)

    try:
        if not revived:
            # 没能及时复活：这不是失败，只是该分支未被触发。
            return CheckResult(
                "R10 停止期间新实例被接管",
                result.ok and result.state is State.STOPPED,
                f"未触发复活分支；停止结果={result.message!r}",
            )
        state, instance = lifecycle.poll()
        adopted = instance is not None and instance.pid == revived[0].pid
        ok = adopted or (not result.ok)
        note = (
            f"复活 PID={revived[0].pid}, 当前状态={state.value}, "
            f"接管={adopted}, 停止结果={result.message!r}"
        )
        return CheckResult("R10 停止期间新实例被接管", ok, note)
    finally:
        for process in revived:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()


def _check_r11_restart(workdir: Path) -> CheckResult:
    """R11：restart 应换掉进程、换掉令牌，并把接管实例升级为自有实例。

    这是 restart 独有的性质：停止再启动后令牌是新的，所以原本拿不到令牌的
    接管实例会变成自有实例，401 问题顺带被解决。
    """
    port = _free_port()
    # 先手工起一个"外部"实例，让 lifecycle 只能接管它。
    external = subprocess.Popen(
        [sys.executable, str(workdir / "ok" / "dsh"), "web", "--port", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_until(lambda: _listener_is_fake(port, workdir / "ok" / "dsh"), 8.0)
        lifecycle = Lifecycle(port=port)
        adopted = lifecycle.start()
        if not adopted.ok or adopted.instance is None or adopted.instance.owned:
            return CheckResult(
                "R11 重启换进程并升级为自有实例",
                False,
                f"前置接管失败: {adopted.message}, owned={getattr(adopted.instance, 'owned', None)}",
            )
        old_pid = adopted.instance.pid
        old_url = adopted.instance.url

        result = lifecycle.restart(grace=5)
        time.sleep(0.3)
        instance = result.instance
        ok = (
            result.ok
            and instance is not None
            and instance.pid != old_pid
            and instance.owned
            and instance.url is not None
            and instance.url != old_url
        )
        note = (
            f"成功={result.ok}, 旧 PID={old_pid} → 新 PID={getattr(instance,'pid',None)}, "
            f"变为自有={getattr(instance,'owned',None)}, 拿到令牌={bool(getattr(instance,'url',None))}"
        )
        return CheckResult("R11 重启换进程并升级为自有实例", ok, note)
    finally:
        try:
            Lifecycle(port=port).stop(grace=3)
        except Exception:  # noqa: BLE001 - 清理失败不应掩盖断言结果
            pass
        if external.poll() is None:
            external.terminate()
            try:
                external.wait(timeout=5)
            except subprocess.TimeoutExpired:
                external.kill()


def _wait_until(predicate, timeout: float, interval: float = 0.05) -> bool:
    """轮询等待条件成立。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def _listener_is_fake(port: int, script: Path | None = None) -> bool:
    """端口上的监听者是否为我们的假 dsh（按脚本路径精确匹配）。"""
    listener = probe.find_listener(port)
    if listener is None or not listener.cmdline:
        return False
    if script is not None:
        return str(script) in listener.cmdline
    return any(os.path.basename(arg) == "dsh" for arg in listener.cmdline)


def _all_pids_with(token: str) -> list[int]:
    """扫全部 /proc 找命令行含 token 的进程，用于检测残留。"""
    found: list[int] = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        command = probe.read_cmdline(int(entry))
        if command and any(token in part for part in command):
            found.append(int(entry))
    return found


def format_results(results: list[CheckResult]) -> str:
    """把自检结果排成便于阅读的表格。"""
    lines: list[str] = []
    passed = sum(1 for item in results if item.passed)
    lines.append(f"自检: {passed}/{len(results)} 通过")
    lines.append("")
    for item in results:
        mark = "PASS" if item.passed else "FAIL"
        lines.append(f"[{mark}] {item.name}")
        lines.append(f"       {item.note}")
    return "\n".join(lines)
