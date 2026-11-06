"""点击处理：标记已读 → 拼深链 → 打开浏览器。

顺序是固定的，每一步都有理由：

1. **先 mark_read**：用户点了就说明看到了。若先打开浏览器再标记，浏览器抢焦点
   期间若用户立刻切回面板，会看到条目还在未查看里。
2. **再拼深链**：拼链接要读账本（磁盘 IO），失败时不该已经改了已读状态——
   但已读是用户意图，宁可选「已读但没打开」也不要「没打开还留着未读」。
   所以顺序是 1 → 2，而不是 2 → 1。
3. **最后 open**：打开失败只记日志 + 由调用方在 tooltip 提示，不弹错误框——
   点通知这个动作不该被一个模态框打断。
"""

from __future__ import annotations

from typing import Callable, Protocol

from ..locks import read_owned_record
from . import history
from .deeplink import build
from .log import Logger


class InstanceLike(Protocol):
    """`lifecycle.Instance` 的最小投影。"""

    @property
    def pid(self) -> int:
        """进程号。"""

    @property
    def port(self) -> int:
        """监听端口。"""

    @property
    def owned(self) -> bool:
        """是否由托盘拉起。"""


#: 打开 URL 的函数；测试注入假实现。
Opener = Callable[[str], bool]


def handle_click(
    entry_id: str,
    session_id: str,
    instance: InstanceLike | None,
    logger: Logger,
    opener: Opener,
) -> bool:
    """处理一次通知点击。

    @param entry_id - 通知条目 id
    @param session_id - 该条目所属会话
    @param instance - 当前实例；None 表示 DSH 没在跑
    @param logger - 日志器
    @param opener - 打开 URL 的函数，返回是否成功
    @returns 是否成功打开
    """
    history.mark_read(entry_id)

    if instance is None:
        logger.info(f"点击通知 {entry_id} 时 DSH 未运行，仅标记已读")
        return False

    record = read_owned_record(instance.port) if instance.owned else None
    url = build(session_id, instance, record)
    try:
        opened = opener(url)
    except Exception as error:  # noqa: BLE001 - 打开失败不该中断托盘
        logger.error(f"打开会话失败：{error}")
        return False

    if not opened:
        logger.warn(f"浏览器未能打开 {url.split('?')[0]}")
        return False
    # 只记主机与路径，不记查询串——那里可能有令牌。
    logger.info(f"已打开会话 {session_id}")
    return True
