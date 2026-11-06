#!/usr/bin/env python3
"""dsh-tray：带托盘的 DSH Web 启动器。

用法：
    dsh-tray.py                 打开托盘（默认动作）
    dsh-tray.py --autostart     同上，但托盘不可用时直接退出而不是静默常驻
    dsh-tray.py --status        打印当前状态后退出，不碰界面
    dsh-tray.py --start         确保 DSH 在运行，然后退出
    dsh-tray.py --restart        重启 DSH，然后退出
    dsh-tray.py --stop          停止 DSH，然后退出
    dsh-tray.py --selftest      跑竞态自检，用假 dsh，不碰真实端口

设计说明见 docs/design.md。
"""

from __future__ import annotations

import argparse
import signal
import sys

from dsh_tray import lifecycle as lifecycle_module
from dsh_tray.lifecycle import DEFAULT_PORT, Lifecycle, State


def _describe(state: State, instance, error: str) -> str:
    """把状态三元组压成一行，供 --status 输出。"""
    if state is State.RUNNING and instance is not None:
        origin = "由托盘启动" if instance.owned else "外部启动"
        token = "带令牌 URL" if instance.has_token else "无令牌（接管）"
        return (
            f"运行中: PID {instance.pid}, 端口 {instance.port}, "
            f"{origin}, {token}"
        )
    if state is State.FAILED:
        return f"失败: {error}" if error else "失败"
    return f"{state.value}"


def _cli_status(port: int) -> int:
    instance_controller = Lifecycle(port=port)
    state, instance = instance_controller.poll()
    print(_describe(state, instance, instance_controller.last_error))
    return 0


def _cli_start(port: int) -> int:
    instance_controller = Lifecycle(port=port)
    result = instance_controller.start()
    print(result.message)
    if result.detail:
        print(result.detail)
    if result.ok and result.instance is not None:
        print(f"PID {result.instance.pid}, 地址 {result.instance.open_url}")
    return 0 if result.ok else 1


def _cli_stop(port: int) -> int:
    instance_controller = Lifecycle(port=port)
    result = instance_controller.stop()
    print(result.message)
    if result.detail:
        print(result.detail)
    return 0 if result.ok else 1


def _cli_restart(port: int) -> int:
    instance_controller = Lifecycle(port=port)
    result = instance_controller.restart()
    print(result.message)
    if result.detail:
        print(result.detail)
    if result.ok and result.instance is not None:
        print(f"PID {result.instance.pid}, 地址 {result.instance.open_url}")
    return 0 if result.ok else 1


def _cli_selftest() -> int:
    from dsh_tray.selftest import format_results, run_selftest

    results = run_selftest()
    print(format_results(results))
    return 0 if all(item.passed for item in results) else 1


def _tool_scope_of_self() -> str | None:
    """返回本进程所在的 DSH 工具作用域名；不在其中时返回 None。

    DSH 的每次工具调用都跑在自己的 systemd scope（`dsh-subprocess-*.scope`）里。
    托盘若在其中启动，那个 scope 一拆除（工具调用结束、或 DSH 退出/重启），
    systemd 会按 cgroup 把托盘连同整棵树一起 SIGTERM + SIGKILL。
    实测事故：托盘就这样跟着一次 DSH 重启一起消失，用户看到的是"托盘不见了"。

    这不是进程组或会话能规避的——杀它的是 cgroup，`setsid` 无效。所以只能
    在入口处识别并拒绝，把用法指到正确的地方。
    """
    try:
        with open("/proc/self/cgroup", "r", encoding="utf-8") as handle:
            content = handle.read()
    except OSError:
        return None
    for line in content.splitlines():
        _, _, path = line.partition("::")
        for segment in path.split("/"):
            if segment.startswith("dsh-subprocess-"):
                return segment
    return None


def _run_tray(port: int, autostart: bool) -> int:
    """启动图形托盘。延迟导入 Qt，让纯命令行路径不受 Qt 影响。"""
    scope = _tool_scope_of_self()
    if scope is not None:
        message = (
            f"dsh-tray 不能从 DSH 的工具会话里启动（当前在 {scope} 中）。\n"
            "该作用域会在工具调用结束或 DSH 重启时被整体回收，托盘会跟着消失。\n"
            "请改为从应用菜单「DSH-Tray」启动，或依赖开机自启"
            "（~/.config/autostart/dsh-tray.desktop）。\n"
            "命令行 --status / --start / --stop / --restart / --selftest 不受影响。"
        )
        print(f"dsh-tray: {message}", file=sys.stderr)
        return 2
    from PyQt6.QtWidgets import QApplication, QSystemTrayIcon

    from dsh_tray.locks import SingleInstanceLock
    from dsh_tray.ui import TrayApp

    app = QApplication(sys.argv[:1])
    # 应用名决定 Plasma 托盘里显示什么。不设置时 Qt 用脚本文件名
    # （dsh-tray.py），看起来像个没装好的脚本；设成 DSH-Tray 并绑定 desktop
    # 文件名，Plasma 就能关联到 .desktop 条目、用它的名字与图标。
    app.setApplicationName("DSH-Tray")
    app.setApplicationDisplayName("DSH-Tray")
    app.setDesktopFileName("dsh-tray")
    app.setOrganizationName("DSH")
    # 关掉窗口时的默认退出：托盘没有窗口，quitOnLastWindowClosed 会让空的
    # QMessageBox 一关就退掉整个应用。
    app.setQuitOnLastWindowClosed(False)

    if not QSystemTrayIcon.isSystemTrayAvailable():
        message = "当前桌面没有可用的系统托盘（StatusNotifier），托盘无法显示"
        if autostart:
            # autostart 下不留一个看不见的常驻进程：直接退出并留下原因。
            print(f"dsh-tray: {message}", file=sys.stderr)
            return 1
        print(f"dsh-tray: {message}；请检查 Plasma 托盘服务", file=sys.stderr)
        return 1

    single = SingleInstanceLock()
    if not single.acquire():
        holder = single.holder_pid()
        suffix = f"（PID {holder}）" if holder else ""
        print(f"dsh-tray: 已有托盘实例在运行{suffix}")
        return 0

    controller = Lifecycle(port=port)
    tray = TrayApp(controller, app.quit)
    tray.show()

    # SIGTERM/SIGINT 也要走正常退出路径，否则 Qt 事件循环不会自己停下来。
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: app.quit())

    try:
        return app.exec()
    finally:
        single.release()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dsh-tray",
        description="带托盘的 DSH Web 启动器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "不带参数时打开托盘。\n"
            "托盘固定使用 3080 端口：Web UI 的登录 cookie 绑定 host:port，\n"
            "换端口会让浏览器里已有的登录态失效。"
        ),
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"DSH Web 端口（默认 {DEFAULT_PORT}；仅测试时改）",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--autostart", action="store_true", help="开机自启模式：托盘不可用则退出")
    mode.add_argument("--status", action="store_true", help="打印状态后退出")
    mode.add_argument("--start", action="store_true", help="确保 DSH 在运行后退出")
    mode.add_argument("--restart", action="store_true", help="重启 DSH 后退出")
    mode.add_argument("--stop", action="store_true", help="停止 DSH 后退出")
    mode.add_argument("--selftest", action="store_true", help="跑竞态自检后退出")

    args = parser.parse_args(argv)

    if args.selftest:
        return _cli_selftest()
    if args.status:
        return _cli_status(args.port)
    if args.start:
        return _cli_start(args.port)
    if args.restart:
        return _cli_restart(args.port)
    if args.stop:
        return _cli_stop(args.port)
    return _run_tray(args.port, args.autostart)


if __name__ == "__main__":
    sys.exit(main())
