"""托盘消费循环：读 spool → 去重 → 投递 → 存历史。

三条关键行为：

1. **投递失败仍入库**。系统通知弹不出来（没有通知服务、D-Bus 挂了）不代表事件没发生；
   面板里照样要能看到，否则用户会以为那一轮没跑完。
2. **DSH 未运行时降频**。200 ms 轮询是为了「跑完立刻看到」；DSH 没在跑时这个频率只是
   空转读文件，降到 1 s。
3. **重启不重复投递**。偏移由 spool 层持久化（含 inode），所以托盘重启只会读新行；
   已消费区间不会被再投一次。

消费循环不直接依赖 Qt：定时器由调用方（`ui.py`）驱动，`poll()` 是纯函数式的
「跑一轮」。这样纯逻辑测试不需要 QApplication。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Sequence

from .delivery import DeliveryResult
from .history import append as history_append
from .intents import DisplayModel
from .log import Logger
from .spool import read_new, resolve_dsh_home, spool_path_for
from .types import NotificationEntry, SessionState, TraySettings

# 轮询间隔（毫秒）。DSH 在跑时 200 ms，不在跑时 1000 ms。
FAST_INTERVAL_MS = 200
SLOW_INTERVAL_MS = 1000

# 补投时间窗：超过 2 小时的事件不再弹系统通知（仍进历史）。
REPLAY_WINDOW = timedelta(hours=2)


@dataclass(frozen=True, slots=True)
class DeliveredNotification:
    """一条成功投递的记录：桌面通知 id 与会话/条目的对应关系。"""

    notification_id: int
    session_id: str
    entry_id: str


@dataclass(frozen=True, slots=True)
class PollResult:
    """一轮消费的结果。"""

    delivered: int
    stored: int
    skipped: int
    replayed: int
    """补投条数（超过时间窗的不计）。"""
    deliveries: tuple[DeliveredNotification, ...] = ()
    """成功投递的明细，供托盘建立点击回执的映射。"""

    @property
    def is_empty(self) -> bool:
        """本轮是否什么都没发生。"""
        return self.delivered == 0 and self.stored == 0 and self.skipped == 0


class Consumer:
    """spool 消费器。

    持有去重模型与会话快照；`poll()` 可以任意频繁调用，内部按 spool 偏移增量读。
    """

    def __init__(
        self,
        *,
        spool_path: Path | None = None,
        state_path: Path | None = None,
        deliverer: Callable[[dict[str, object]], DeliveryResult] | None = None,
        history_writer: Callable[..., None] | None = None,
        logger: Logger | None = None,
        now: Callable[[], datetime] | None = None,
        fast_interval_ms: int = FAST_INTERVAL_MS,
        slow_interval_ms: int = SLOW_INTERVAL_MS,
    ) -> None:
        """构造。

        @param spool_path - spool 文件；缺省按 DSH home 解析
        @param state_path - 偏移文件目录；缺省与 spool 同源的 state 目录
        @param deliverer - 投递函数；缺省用真实 D-Bus
        @param history_writer - 历史写入函数；缺省用真实文件
        @param logger - 日志器
        @param now - 取当前时刻
        @param fast_interval_ms - DSH 运行时的轮询间隔
        @param slow_interval_ms - DSH 未运行时的轮询间隔
        """
        self._spool_path = spool_path or spool_path_for(resolve_dsh_home())
        self._state_path = state_path
        self._deliverer = deliverer
        self._history_writer = history_writer or history_append
        self._logger = logger or Logger(None, "consumer")
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._fast = fast_interval_ms
        self._slow = slow_interval_ms
        self.model = DisplayModel()
        self.session_states: tuple[SessionState, ...] = ()
        #: 最近一次收到的托盘外观设置；None 表示插件还没下发过。
        self.tray_settings: TraySettings | None = None
        self.replayed_total = 0
        self._primed = False

    def _deliver(self, entry: NotificationEntry) -> DeliveryResult:
        """投递一条；未注入 deliverer 时用真实实现。"""
        if self._deliverer is not None:
            payload = {
                "title": entry.title,
                "body": entry.body,
                "urgency": entry.urgency,
                "id": entry.id,
                "kind": entry.kind,
                "openUrl": entry.open_url,
            }
            return self._deliverer(payload)
        from .delivery import deliver

        return deliver(
            {
                "title": entry.title,
                "body": entry.body,
                "urgency": entry.urgency,
                "id": entry.id,
                "kind": entry.kind,
                "openUrl": entry.open_url,
            }
        )

    def poll(self, dsh_running: bool = True) -> PollResult:
        """跑一轮消费。

        @param dsh_running - DSH 是否在跑（决定下一轮的间隔，不影响本轮处理）
        @returns 本轮结果
        """
        batch = read_new(self._spool_path, self._state_path or self._spool_path.parent)
        if batch.session_states:
            # 全量替换：只保留最后一条快照。
            self.session_states = (batch.session_states[-1],)
        if batch.tray_settings is not None:
            # 同样全量覆盖：设置改回默认值时，旧值必须被丢掉而不是合并。
            self.tray_settings = batch.tray_settings

        delivered = 0
        stored = 0
        replayed = 0
        deliveries: list[DeliveredNotification] = []
        now = self._now()
        for entry in batch.notifications:
            if not self.model.accept(entry, now):
                self._logger.debug(f"去重丢弃 {entry.dedupe_key}")
                continue
            is_old = now - entry.ts > REPLAY_WINDOW
            if is_old:
                replayed += 1
                self._logger.info(f"补投窗口外，仅入库：{entry.id}")
            else:
                result = self._deliver(entry)
                if result.delivered:
                    delivered += 1
                    if result.notification_id is not None:
                        deliveries.append(
                            DeliveredNotification(result.notification_id, entry.session_id, entry.id)
                        )
                else:
                    self._logger.warn(f"投递失败（仍入库）：{result.reason}")
            try:
                self._history_writer(entry, now=now, replayed=is_old)
                stored += 1
            except Exception as error:  # noqa: BLE001 - 历史写失败不该中断消费
                self._logger.error(f"历史写入失败：{error}")
        self.replayed_total += replayed
        return PollResult(delivered, stored, batch.skipped, replayed, tuple(deliveries))

    def next_interval_ms(self, dsh_running: bool) -> int:
        """下一轮该用多长的间隔。

        @param dsh_running - DSH 是否在跑
        @returns 毫秒
        """
        return self._fast if dsh_running else self._slow

    def replay_pending(self) -> int:
        """启动补投：把上次未消费的条目读完并入库（不弹已过窗口的）。

        与 `poll()` 的区别只是语义：它明确表示「这是启动时补投」，调用方据此显示
        「错过 N 条」提示。

        @returns 补投条数
        """
        result = self.poll(dsh_running=False)
        self._primed = True
        return result.replayed

    @property
    def primed(self) -> bool:
        """是否已完成启动补投。"""
        return self._primed
