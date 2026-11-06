"""托盘界面包：托盘本体与面板各页。

**导入本包不加载 PyQt6**：`dsh-tray.py` 在解析命令行参数时可能间接触达这里，而
`--status`/`--start`/`--stop`/`--selftest` 必须在没有 DISPLAY 的机器上也能跑
（AGENTS.md 硬约束 2）。因此 `TrayApp` 用模块级 `__getattr__` 惰性导入：
`from dsh_tray.ui import TrayApp` 仍然可用，但只有真正取属性时才碰 Qt。

历史：`dsh_tray/ui.py` 曾与包同名而被遮蔽（Python 里同名包优先于模块），
原托盘模块已移入本包作为 `tray.py`。
"""

from __future__ import annotations

from typing import Any

__all__ = ["tray", "panel", "control", "notiflist", "working", "overview", "TrayApp"]

#: 需要从 `tray` 子模块惰性取出的名字。
_LAZY = {"TrayApp": "tray"}


def __getattr__(name: str) -> Any:
    """按需导入子模块里的名字。

    @param name - 属性名
    @returns 属性值
    @throws AttributeError - 名字不存在时
    """
    module_name = _LAZY.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    module = import_module(f".{module_name}", __name__)
    return getattr(module, name)
