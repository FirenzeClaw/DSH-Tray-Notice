"""深链拼接：把通知点击变成「打开那个会话」。

令牌规则（AGENTS.md 安全红线）：令牌只存在于 owned 账本里，且只在该账本的 pid 与
当前实例一致时才使用。pid 不符意味着账本是上一次运行留下的，沿用它的令牌会打开
一个 401 页面——比不带令牌更糟，因为用户会以为链接坏了。

插件只写 `?session=<id>`，令牌由这里注入：令牌因此始终只有托盘一侧见过。
"""

from __future__ import annotations

from typing import Protocol
from urllib.parse import quote


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


class OwnedRecordLike(Protocol):
    """`locks.OwnedRecord` 的最小投影。"""

    @property
    def pid(self) -> int:
        """账本记录的进程号。"""

    @property
    def url(self) -> str:
        """带令牌的完整 URL。"""


def build(session_id: str, instance: InstanceLike, record: OwnedRecordLike | None) -> str:
    """拼接会话深链。

    @param session_id - 会话标识（原样来自通知条目）
    @param instance - 当前运行实例
    @param record - 自有实例账本；adopted 或 pid 不符时传 None 或忽略
    @returns 可交给浏览器打开的 URL
    """
    encoded = quote(session_id, safe="")
    base = f"http://127.0.0.1:{instance.port}/"
    if instance.owned and record is not None and record.pid == instance.pid:
        # 账本里的 URL 已带 `?token=…`，追加 session 即可；顺序固定为 token 在前。
        separator = "&" if "?" in record.url else "?"
        return f"{record.url}{separator}session={encoded}"
    return f"{base}?session={encoded}"
