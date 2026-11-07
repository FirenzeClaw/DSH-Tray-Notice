"""托盘界面：图标、菜单、状态刷新、确认对话框。

所有生命周期动作都丢到工作线程执行，主线程只负责界面：start 最长要等 45 s
（冷启动实测 13.1 s），在 UI 线程里同步调用会把整个托盘冻住，Plasma 甚至会
判它无响应。
"""

from __future__ import annotations

import threading
import webbrowser
from typing import Callable

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, QTimer, pyqtSignal
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from .. import icons
from ..lifecycle import Instance, Lifecycle, LifecycleResult, State
from ..notify.click import handle_click
from ..notify.sessionstate import SessionTable
from .control import ControlArea
from .notiflist import NotificationListPage, read_count, unread_count
from .overview import OverviewPage
from ..platform import create_sampler
from ..platform.linux import LinuxWindowAnchor
from .panel import PANEL_WIDTH, TAB_OVERVIEW, TAB_READ, TAB_UNREAD, TAB_WORKING, Panel
from .working import WorkingPage
from ..notify.consumer import Consumer
from ..notify.delivery import DeliveryResult, PopupRegistry, deliver
from ..notify.log import Logger, default_log_path
from ..platform.linux import LinuxActionListener

#: 探测外部启停的间隔。2 s 足够让手动启动在托盘上"很快"出现，
#: 又不至于让 /proc 扫描变成可观测的负担。
POLL_INTERVAL_MS = 2000


class _ActionRunner(QObject):
    """把一个阻塞的生命周期动作放到线程池里跑，结果回到主线程。"""

    finished = pyqtSignal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._pool = QThreadPool.globalInstance()

    def run(self, work: Callable[[], LifecycleResult]) -> None:
        """提交动作；完成时发 finished 信号。

        信号从工作线程发出，Qt 的队列连接会把它送回主线程，所以槽函数里可以
        安全地碰界面。
        """

        class _Task(QRunnable):
            def __init__(self, emitter: _ActionRunner, job: Callable[[], LifecycleResult]) -> None:
                super().__init__()
                self._emitter = emitter
                self._job = job

            def run(self) -> None:
                try:
                    result = self._job()
                except Exception as error:  # noqa: BLE001 - 兜底：任何异常都要回到 UI
                    result = LifecycleResult.failure(
                        State.FAILED, f"内部错误: {error}", repr(error)
                    )
                self._emitter.finished.emit(result)

        self._pool.start(_Task(self, work))


class TrayApp:
    """托盘应用：把 Lifecycle 的状态映射成图标与菜单。"""

    def __init__(self, lifecycle: Lifecycle, app_quit: Callable[[], None]) -> None:
        self._lifecycle = lifecycle
        self._quit = app_quit
        self._busy = False

        self._icon_running = icons.running_icon()
        self._icon_idle = icons.idle_icon()

        self._tray = QSystemTrayIcon(self._icon_idle)
        self._tray.setToolTip("DSH 未运行")

        self._menu = QMenu()
        self._action_open = QAction("打开 Web UI", self._menu)
        self._action_start = QAction("启动 DSH", self._menu)
        self._action_restart = QAction("重启 DSH", self._menu)
        self._action_stop = QAction("停止 DSH", self._menu)
        self._action_panel = QAction("打开面板", self._menu)
        self._action_quit = QAction("退出托盘", self._menu)

        self._action_open.triggered.connect(self._on_open)
        self._action_start.triggered.connect(self._on_start)
        self._action_restart.triggered.connect(self._on_restart)
        self._action_stop.triggered.connect(self._on_stop)
        self._action_panel.triggered.connect(self.toggle_panel)
        self._action_quit.triggered.connect(self._on_quit)

        for action in (
            self._action_open,
            self._action_start,
            self._action_restart,
            self._action_stop,
        ):
            self._menu.addAction(action)
        self._menu.addSeparator()
        self._menu.addAction(self._action_panel)
        self._menu.addAction(self._action_quit)

        self._tray.setContextMenu(self._menu)
        self._tray.activated.connect(self._on_activated)

        self._runner = _ActionRunner()
        self._runner.finished.connect(self._on_action_finished)

        self._poll_timer = QTimer()
        self._poll_timer.setInterval(POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self._refresh)

        # 通知管线：消费 spool、投递系统通知、写历史。
        # 与状态轮询分开计时——通知要快（200 ms），状态探测 2 s 足够。
        self._logger = Logger(default_log_path(), "tray")
        #: 会话 → 该会话最近一条弹窗的 id：同会话的新通知顶替旧横幅而不是排队。
        #: 排队会让用户看到一串过期的「需要你审批」，最旧那条还一直占着弹窗位。
        self._popups = PopupRegistry()
        self._consumer = Consumer(logger=self._logger, deliverer=self._deliver)
        self._notify_unavailable = False
        self._missed_total = 0
        #: 桌面通知 id → 会话 id；点击回执只有通知 id，要据此反查会话。
        self._notified: dict[int, str] = {}
        self._notified_entry: dict[int, str] = {}
        self._action_listener = LinuxActionListener(self._on_notification_action)

        # 面板：左键打开。会话表由消费循环的快照喂养。
        self._session_table = SessionTable()
        self._panel: Panel | None = None
        self._unread = 0
        self._read = 0
        self._notify_timer = QTimer()
        self._notify_timer.setInterval(self._consumer.next_interval_ms(False))
        self._notify_timer.timeout.connect(self._on_notify_tick)

    # ------------------------------------------------------------------ 生命周期

    def show(self) -> None:
        """显示托盘并启动轮询。"""
        self._refresh()
        self._tray.show()
        self._poll_timer.start()
        # 先补投上次缺席期间的事件，再进入常规轮询。顺序不能反：反了会让补投
        # 条目混在实时条目里，「错过 N 条」就算不准。
        self._missed_total = self._consumer.replay_pending()
        if self._missed_total > 0:
            self._logger.info(f"补投 {self._missed_total} 条")
        self._notify_timer.start()
        # 订阅失败不影响托盘：只是点通知不会跳转，tooltip 会说明通知不可用。
        if not self._action_listener.start():
            self._logger.info("通知点击回执订阅失败（无 D-Bus 或平台不支持）")

    def _refresh(self) -> None:
        """按当前探测结果重画图标、tooltip 与菜单可用性。"""
        if self._busy:
            # 动作进行中：保持中间态显示，不要被轮询打断。
            return
        state, instance = self._lifecycle.poll()
        self._render(state, instance, self._lifecycle.last_error)

    def _render(self, state: State, instance: Instance | None, error: str) -> None:
        """把状态渲染到界面。三类状态各有自己的图标与菜单组合。"""
        running = state is State.RUNNING and instance is not None
        # 启动/停止进行中沿用白图标：托盘正在做正事，灰掉反而像失败了。
        transitioning = state in (State.STARTING, State.STOPPING)

        base = self._icon_running if (running or transitioning) else self._icon_idle
        # 未读角标叠加在同一个图标上：0 条时原样返回，不额外分配 pixmap。
        self._tray.setIcon(icons.with_badge(base, self._unread))

        tooltip = self._tooltip(state, instance, error)
        if self._missed_total > 0:
            tooltip = f"{tooltip}\n错过 {self._missed_total} 条通知（打开面板查看）"
        if self._notify_unavailable:
            tooltip = f"{tooltip}\n通知不可用：系统通知服务没有响应"
        self._tray.setToolTip(tooltip)

        self._action_open.setEnabled(running)
        self._action_start.setEnabled(
            not running and not transitioning and not self._busy
        )
        self._action_stop.setEnabled(running and not self._busy)
        self._action_restart.setEnabled(running and not self._busy)

        # 启停互斥显隐：未运行时列一条灰掉的「停止/重启」纯属噪音。
        self._action_stop.setVisible(running or transitioning)
        self._action_restart.setVisible(running or transitioning)
        self._action_start.setVisible(not running and not transitioning)

    def _tooltip(self, state: State, instance: Instance | None, error: str) -> str:
        """tooltip 要能独立回答「现在什么状态、谁起的、为什么失败」。"""
        if state is State.RUNNING and instance is not None:
            origin = "由托盘启动" if instance.owned else f"外部启动 PID {instance.pid}"
            return f"DSH 运行中 · 127.0.0.1:{instance.port} · {origin}"
        if state is State.STARTING:
            return "DSH 正在启动…"
        if state is State.STOPPING:
            return "DSH 正在停止…"
        if state is State.FAILED:
            return f"DSH 启动失败：{error}" if error else "DSH 启动失败"
        return "DSH 未运行"

    # ------------------------------------------------------------------ 面板

    def _ensure_panel(self) -> Panel:
        """按需构造面板并挂好三个页面。

        @returns 面板实例
        """
        if self._panel is not None:
            return self._panel

        panel = Panel()
        control = ControlArea()
        control.primary_clicked.connect(self._on_panel_primary)
        control.restart_clicked.connect(self._on_restart)
        control.stop_clicked.connect(self._on_stop)
        panel.set_control(control)

        self._unread_page = NotificationListPage(only_unread=True)
        self._unread_page.entry_clicked.connect(self._on_entry_clicked)
        self._read_page = NotificationListPage(only_unread=False)
        self._read_page.entry_clicked.connect(self._on_entry_clicked)
        self._working_page = WorkingPage(self._session_table)
        self._working_page.session_clicked.connect(self._on_session_clicked)

        panel.add_page(TAB_UNREAD, self._unread_page)
        panel.add_page(TAB_READ, self._read_page)
        panel.add_page(TAB_WORKING, self._working_page)
        self._overview_page = OverviewPage(self._sample_processes)
        panel.add_page(TAB_OVERVIEW, self._overview_page)

        self._control = control
        self._panel = panel
        return panel

    def toggle_panel(self) -> None:
        """左键：显示或隐藏面板。"""
        panel = self._ensure_panel()
        if panel.isVisible():
            panel.hide()
            return
        self._refresh_panel()
        # 用户已经打开面板看到内容，一次性提示到此为止。
        if self._missed_total > 0:
            self._missed_total = 0
            self._refresh()
        anchor = LinuxWindowAnchor(margin=8)
        geometry = self._tray.geometry()
        tray_rect = (geometry.x(), geometry.y(), geometry.width(), geometry.height())
        screen = self._tray.screen() or QApplication.primaryScreen()
        x, y = anchor.anchor_for(tray_rect, screen)
        # 面板宽 378：贴右边时 x 会越界，往左挪回来。
        x = max(0, min(x, screen.availableGeometry().right() - PANEL_WIDTH + 1))
        panel.show_at(x, y)

    def _refresh_panel(self) -> None:
        """按当前历史与会话表刷新面板内容。"""
        panel = self._ensure_panel()
        state, instance = self._lifecycle.state, self._lifecycle.instance
        self._control.render(state, instance, self._lifecycle.last_error, busy=self._busy)
        self._unread = unread_count()
        self._read = read_count()
        panel.set_counts(self._unread, self._read, len(self._session_table.active()))
        panel.set_missed(self._missed_total)
        self._unread_page.refresh()
        self._read_page.refresh()
        self._working_page.refresh()

    def _sample_processes(self):
        """采样 DSH 及其子进程，供概览页使用。

        @returns 采样行；DSH 未运行时为空
        """
        instance = self._lifecycle.instance
        if instance is None or self._lifecycle.state is not State.RUNNING:
            return []
        sampler = create_sampler()
        return list(sampler.sample(instance.pid))

    def _on_panel_primary(self) -> None:
        """面板主操作：未运行时启动，运行中打开 Web UI。"""
        if self._lifecycle.state is State.RUNNING:
            self._on_open()
        else:
            self._on_start()

    def _on_entry_clicked(self, entry_id: str, session_id: str) -> None:
        """点通知条目：标记已读并打开会话。

        @param entry_id - 条目 id
        @param session_id - 会话 id
        """
        handle_click(
            entry_id,
            session_id,
            self._lifecycle.instance,
            self._logger,
            lambda url: webbrowser.open(url),
        )
        if self._panel is not None and self._panel.isVisible():
            self._refresh_panel()

    def _on_session_clicked(self, session_id: str) -> None:
        """点「工作中」的行：打开该会话。

        @param session_id - 会话 id
        """
        instance = self._lifecycle.instance
        if instance is None:
            return
        from ..locks import read_owned_record
        from ..notify.deeplink import build

        record = read_owned_record(instance.port) if instance.owned else None
        webbrowser.open(build(session_id, instance, record))

    # ------------------------------------------------------------------ 通知

    def _deliver(self, entry: dict[str, object]) -> DeliveryResult:
        """投递一条通知，并登记弹窗 id 供同会话后续顶替。

        @param entry - spool 条目的 dict 形态
        @returns 投递结果
        """
        session_id = str(entry.get("sessionId", ""))
        result = deliver(entry, replaces_id=self._popups.get(session_id))
        if result.delivered and result.notification_id is not None:
            self._popups.remember(session_id, result.notification_id)
        return result

    def _on_notify_tick(self) -> None:
        """一轮通知消费：读 spool、投递、入库，并按 DSH 状态调整间隔。

        投递失败只置标记、不抛异常——通知是旁路，不该让托盘看起来坏了。
        """
        running = self._lifecycle.state is State.RUNNING
        try:
            result = self._consumer.poll(dsh_running=running)
        except Exception as error:  # noqa: BLE001 - 消费失败不该中断托盘
            self._logger.error(f"通知消费失败：{error}")
            return

        # 会话快照是全量替换：直接喂给会话表，「工作中」页据此刷新。
        if self._consumer.session_states:
            self._session_table.apply(self._consumer.session_states[-1])

        # 记录「桌面通知 id → 会话」，点击回执只有 id，得靠这张表反查。
        for delivery in result.deliveries:
            self._notified[delivery.notification_id] = delivery.session_id
            self._notified_entry[delivery.notification_id] = delivery.entry_id
        if len(self._notified) > 200:
            # 桌面通知会被系统丢弃，映射表不能无限长；超限时丢最早的一半。
            for stale in list(self._notified)[:100]:
                self._notified.pop(stale, None)
                self._notified_entry.pop(stale, None)

        interval = self._consumer.next_interval_ms(running)
        if self._notify_timer.interval() != interval:
            self._notify_timer.setInterval(interval)

        if result.stored > 0 and result.delivered == 0:
            # 有事件但一条都没投出去：多半是通知服务不可用。
            if not self._notify_unavailable:
                self._logger.warn("系统通知不可用，后续只入库")
                self._notify_unavailable = True
                state, instance = self._lifecycle.state, self._lifecycle.instance
                self._render(state, instance, self._lifecycle.last_error)
        elif result.delivered > 0 and self._notify_unavailable:
            self._notify_unavailable = False
            state, instance = self._lifecycle.state, self._lifecycle.instance
            self._render(state, instance, self._lifecycle.last_error)

    def _on_notification_action(self, notification_id: int, action_key: str) -> None:
        """系统通知被点击：标记已读并跳到对应会话。

        @param notification_id - 桌面分配的通知 id
        @param action_key - 动作键（`default` / `open`）
        """
        session_id = self._notified.pop(notification_id, None)
        if session_id is None:
            # 不是我们发的通知，或已被替换；忽略即可。
            return
        entry_id = self._notified_entry.pop(notification_id, "")
        instance = self._lifecycle.instance
        handle_click(
            entry_id,
            session_id,
            instance,
            self._logger,
            lambda url: webbrowser.open(url),
        )

    @property
    def missed_total(self) -> int:
        """启动时补投的条数（面板顶部提示用）。"""
        return self._missed_total

    # ------------------------------------------------------------------ 交互

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        """左键单击开面板；右键由菜单接管。

        面板里既有状态也有启停入口，比直接打开 Web UI 更省一次点击：用户点托盘
        通常是想看「现在什么情况」，而不是立刻进浏览器。
        """
        if reason is QSystemTrayIcon.ActivationReason.Trigger:
            self.toggle_panel()

    def _on_open(self) -> None:
        """打开 Web UI。自有的用带令牌 URL，接管的用裸 URL。"""
        instance = self._lifecycle.instance
        if instance is None or self._lifecycle.state is not State.RUNNING:
            return
        try:
            webbrowser.open(instance.open_url)
        except Exception as error:  # noqa: BLE001 - 浏览器启动失败不该拖垮托盘
            self._notify("打开浏览器失败", f"{error}\n地址：{instance.open_url}")
            return
        if not instance.has_token:
            # 接管来的实例拿不到令牌（进程级随机数），只能靠浏览器已有 cookie。
            self._notify(
                "已打开 DSH Web UI",
                "这个实例不是托盘启动的，无法取得新的访问令牌；"
                "如果浏览器提示未授权，请在菜单里停止后重新启动一次。",
                icon=QSystemTrayIcon.MessageIcon.Information,
            )

    def _on_start(self) -> None:
        """启动 DSH。已有实例时 start() 自己会接管，这里不需要先判断。"""
        if self._busy:
            return
        self._begin_busy(State.STARTING)
        self._runner.run(self._lifecycle.start)

    def _confirm(self, title: str, question: str, consequence: str,
                 confirm_label: str) -> bool:
        """危险操作的确认框。默认按钮是「取消」，误触的代价为零。

        停止与重启都会结束该 DSH 下所有会话与 MCP 子进程——其中很可能就有
        用户正在对话的那个，所以两者都要确认。
        """
        instance = self._lifecycle.instance
        if instance is None:
            return False
        origin = "由托盘启动" if instance.owned else "外部启动"
        box = QMessageBox()
        box.setWindowTitle(title)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText(question)
        box.setInformativeText(f"{consequence}\n目标：PID {instance.pid}（{origin}）")
        cancel = box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        confirm = box.addButton(confirm_label, QMessageBox.ButtonRole.DestructiveRole)
        box.setDefaultButton(cancel)
        box.exec()
        return box.clickedButton() is confirm

    def _on_stop(self) -> None:
        """停止 DSH，先确认。"""
        if self._busy or self._lifecycle.instance is None:
            return
        if not self._confirm(
            "停止 DSH",
            "确定要停止 DSH 吗？",
            "这会结束该 DSH 进程及其全部会话和 MCP 子进程。",
            "停止",
        ):
            return
        self._begin_busy(State.STOPPING)
        self._runner.run(self._lifecycle.stop)

    def _on_restart(self) -> None:
        """重启 DSH：停掉再拉起，中间态对外不可见。

        副作用是想要的——接管的实例（拿不到访问令牌）重启后会变成自有实例，
        从而重新获得带令牌的 URL，顺手解决 401。
        """
        if self._busy or self._lifecycle.instance is None:
            return
        if not self._confirm(
            "重启 DSH",
            "确定要重启 DSH 吗？",
            "重启会先结束该进程及其全部会话和 MCP 子进程，随后重新启动。",
            "重启",
        ):
            return
        self._begin_busy(State.STOPPING)
        self._runner.run(self._lifecycle.restart)

    def _on_quit(self) -> None:
        """退出托盘。不停止 DSH：托盘和 DSH 的生命周期是分开的。"""
        self._poll_timer.stop()
        self._notify_timer.stop()
        self._action_listener.stop()
        self._tray.hide()
        self._quit()

    # ------------------------------------------------------------------ 动作结果

    def _begin_busy(self, state: State) -> None:
        """进入忙碌态：立刻重画，并禁用会重复触发的菜单项。"""
        self._busy = True
        instance = self._lifecycle.instance
        self._render(state, instance, self._lifecycle.last_error)

    def _on_action_finished(self, result: LifecycleResult) -> None:
        """动作完成：解除忙碌、按结果重画、必要时提示。"""
        self._busy = False
        state, instance = self._lifecycle.poll()
        self._render(state, instance, self._lifecycle.last_error)
        self._report(result)

    def _report(self, result: LifecycleResult) -> None:
        """把结果如实告诉用户：成功给一句，失败给一句加细节。"""
        if result.ok:
            if result.state is State.RUNNING and result.instance is not None:
                self._notify("DSH", result.message)
            elif result.detail:
                self._notify("DSH", f"{result.message}\n{result.detail}")
            return
        detail = f"\n\n{result.detail}" if result.detail else ""
        self._notify("DSH", f"{result.message}{detail}", error=True)

    def _notify(self, title: str, body: str, error: bool = False) -> None:
        """托盘气泡提示。系统不支持气泡时退化成日志式静默，不抛异常。"""
        icon = (
            QSystemTrayIcon.MessageIcon.Critical
            if error
            else QSystemTrayIcon.MessageIcon.Information
        )
        if not QSystemTrayIcon.supportsMessages():
            return
        self._tray.showMessage(title, body, icon, 8000)
