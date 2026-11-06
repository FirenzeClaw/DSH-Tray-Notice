"""托盘侧日志：与插件侧同格式，写失败静默，令牌脱敏。

格式与 `plugin/src/log.ts` 一致：`<iso> <level> <component> <msg>`，两侧日志可以
直接 `cat` 在一起看。

为什么托盘需要自己的日志而不是复用 `logging` 模块：托盘是单文件级的常驻小程序，
不引配置、不建 handler 树，一行 append 足够；而 `logging` 的默认行为（stderr）在
由 .desktop 启动时无处可看。
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path

# 单文件上限，与插件侧 LOG_MAX_BYTES 保持一致。
LOG_MAX_BYTES = 1024 * 1024

# 令牌脱敏。两条规则对应两种真实形态：
# 1. URL 查询串 `?token=abc&session=x`；
# 2. JSON / 赋值形态 `"token":"abc"`、`apiKey: sk-123`。
_QUERY_TOKEN = re.compile(r"(\b(?:token|apiKey|api_key|password|secret)=)(?!\*\*\*)[^&\s\"'#]+", re.I)
_ASSIGN_TOKEN = re.compile(
    r"(\"?(?:token|apiKey|api_key|password|secret)\"?\s*[:=]\s*)(\"?)(?!\*\*\*)([^\s,\"'}\]]+)",
    re.I,
)


def redact(text: str) -> str:
    """把令牌值替换成 `***`。

    只覆盖真实出现过的两种形态；不追求穷尽编码变体——过度匹配会误伤正文里的
    普通单词（例如「token 已过期」）。

    @param text - 原始文本
    @returns 脱敏后的文本
    """
    text = _QUERY_TOKEN.sub(r"\1***", text)
    return _ASSIGN_TOKEN.sub(r"\1\2***", text)


def _rotate_if_needed(path: Path) -> None:
    """按大小轮转，只保留一代 `.1`。

    @param path - 日志文件
    """
    try:
        if not path.exists() or path.stat().st_size <= LOG_MAX_BYTES:
            return
        path.replace(path.with_name(path.name + ".1"))
    except OSError:
        # 轮转失败不该阻断写入：继续追加，最坏是文件更大。
        return


class Logger:
    """一个组件的日志器。

    所有写操作都吞掉 `OSError`：日志是诊断手段，磁盘满时让托盘崩掉等于用诊断
    工具制造故障。
    """

    def __init__(self, path: Path | None, component: str) -> None:
        """构造。

        @param path - 日志文件路径；None 表示不落盘（测试用）
        @param component - 组件名，出现在每行第三列
        """
        self._path = path
        self._component = component

    def _write(self, level: str, message: str) -> None:
        if self._path is None:
            return
        stamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        line = f"{stamp} {level} {self._component} {redact(message)}\n"
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            _rotate_if_needed(self._path)
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(line)
        except OSError:
            return

    def debug(self, message: str) -> None:
        """调试级。"""
        self._write("debug", message)

    def info(self, message: str) -> None:
        """信息级。"""
        self._write("info", message)

    def warn(self, message: str) -> None:
        """警告级。"""
        self._write("warn", message)

    def error(self, message: str) -> None:
        """错误级。"""
        self._write("error", message)


def default_log_path() -> Path:
    """托盘日志的默认位置：`$XDG_STATE_HOME/dsh-tray/tray.log`。

    @returns 日志文件路径（不保证父目录已存在）
    """
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return Path(base) / "dsh-tray" / "tray.log"
