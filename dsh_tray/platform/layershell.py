"""LayerShellQt 的 ctypes 绑定。

**这是纯机制层**：只负责把「C++ 静态方法」翻译成 Python 可调用对象，不做任何
业务判断（该放哪儿、边距多少都由 `linux.py` 决定）。单独成文件的理由是它的
失败模式与业务代码不同——它可能在导入时就碰不到库，而业务层永远不该因为
「库缺失」而崩溃。

## 为什么要走这条路

该合成器不接受客户端指定的窗口位置：普通窗口 `move()` 不生效（实测面板恒落在
水平居中处 `(664, 237)`，而代码算出的是 `(1329, 8)`）。要精确贴右上角只能走
合成器的层外壳协议，而 Qt 已经提供了 `LayerShellQt` 接口库。

## 两个已踩过的坑（改动前务必看）

1. **QWindow 指针不能用 `winId()` 取**。`winId()` 返回的是原生窗口句柄，不是
   `QWindow*`；传给 `Window::get()` 会返回空指针，然后静默什么都不发生。必须用
   `PyQt6.sip.unwrapinstance(widget.windowHandle())`。

2. **Anchor 枚举是 Qt 风格，不是 freedesktop 风格**。实测 `Top=1 Bottom=2
   Left=4 Right=8`；我曾按 freedesktop 的 `Left=1 Right=2 Top=4 Bottom=8` 推出
   「右上角 = 6」，结果窗口出现在**左下角**。右上角是 `Top|Right` = **9**。
"""

from __future__ import annotations

import ctypes

#: 层外壳锚边。Qt 风格位标志（实测值，见模块文档第 2 条）。
ANCHOR_TOP = 1
ANCHOR_BOTTOM = 2
ANCHOR_LEFT = 4
ANCHOR_RIGHT = 8
ANCHOR_TOP_RIGHT = ANCHOR_TOP | ANCHOR_RIGHT  # = 9

#: 库名。系统包 `liblayershellqtinterface6` 提供它。
LIBRARY_NAME = "libLayerShellQtInterface.so.6"

#: C++ 符号（mangled）。Qt6 的 ABI 稳定，这几个名字直接用。
_SYM_WINDOW_GET = "_ZN12LayerShellQt6Window3getEP7QWindow"
_SYM_SET_ANCHORS = "_ZN12LayerShellQt6Window10setAnchorsE6QFlagsINS0_6AnchorEE"
_SYM_SET_MARGINS = "_ZN12LayerShellQt6Window10setMarginsERK8QMargins"
_SYM_SET_DESIRED_SIZE = "_ZN12LayerShellQt6Window14setDesiredSizeERK5QSize"
_SYM_USE_LAYER_SHELL = "_ZN12LayerShellQt5Shell13useLayerShellEv"


class QSize(ctypes.Structure):
    """`QSize` 的内存布局（两个 int）。

    `setDesiredSize` 的签名是 `const QSize&`——**按引用**传。早先我按
    `(c_int, c_int)` 按值传，C++ 侧把两个整数当指针解引用，直接段错误。
    """

    _fields_ = [("width", ctypes.c_int), ("height", ctypes.c_int)]


class QMargins(ctypes.Structure):
    """`QMargins` 的内存布局（四个 int，顺序 l/t/r/b）。"""

    _fields_ = [
        ("left", ctypes.c_int),
        ("top", ctypes.c_int),
        ("right", ctypes.c_int),
        ("bottom", ctypes.c_int),
    ]


class LayerShell:
    """已加载的接口库。构造失败请走 `load()` 而不是直接实例化。"""

    def __init__(self, library: ctypes.CDLL) -> None:
        """构造。

        @param library - 已加载的 CDLL
        """
        self._lib = library
        self._window_get = self._bind(_SYM_WINDOW_GET, ctypes.c_void_p, [ctypes.c_void_p])
        self._set_anchors = self._bind(_SYM_SET_ANCHORS, None, [ctypes.c_void_p, ctypes.c_int])
        self._set_margins = self._bind(_SYM_SET_MARGINS, None, [ctypes.c_void_p, ctypes.POINTER(QMargins)])
        self._set_desired_size = self._bind(
            _SYM_SET_DESIRED_SIZE, None, [ctypes.c_void_p, ctypes.POINTER(QSize)]
        )
        # 这个不是可选的：不调它，Qt 仍按普通 xdg-shell 建窗口，
        # 前面设的 anchors/margins 全都不起作用（窗口照旧被合成器放到中央）。
        self._use_layer_shell = self._bind(_SYM_USE_LAYER_SHELL, None, [])

    def _bind(self, symbol: str, restype, argtypes):  # noqa: ANN001 - ctypes 类型
        """取符号并固定签名。

        @param symbol - mangled 名
        @param restype - 返回类型
        @param argtypes - 参数类型列表
        @returns 可调用对象
        @throws LookupError - 符号不存在时
        """
        func = getattr(self._lib, symbol, None)
        if func is None:
            raise LookupError(f"{LIBRARY_NAME} 缺少符号 {symbol}")
        func.restype = restype
        func.argtypes = argtypes
        return func

    def use_layer_shell(self) -> None:
        """启用层外壳集成。

        **必须在创建窗口之前调用**。实测：不调它时 anchors 与 margins 设置了也
        不生效，窗口仍被合成器放到水平居中处。
        """
        self._use_layer_shell()

    def window_get(self, qwindow: int) -> int:
        """`LayerShellQt::Window::get(QWindow*)`。

        @param qwindow - QWindow 指针（用 sip.unwrapinstance 取得，不是 winId）
        @returns 层外壳窗口句柄；无对应窗口时返回 0
        """
        return int(self._window_get(ctypes.c_void_p(qwindow)) or 0)

    def set_anchors(self, handle: int, anchors: int) -> None:
        """设置锚边。

        @param handle - window_get 的返回值
        @param anchors - ANCHOR_* 的位或
        """
        self._set_anchors(ctypes.c_void_p(handle), anchors)

    def set_margins(self, handle: int, left: int, top: int, right: int, bottom: int) -> None:
        """设置四边边距。

        @param handle - window_get 的返回值
        @param left - 左边距
        @param top - 上边距
        @param right - 右边距
        @param bottom - 下边距
        """
        margins = QMargins(left, top, right, bottom)
        self._set_margins(ctypes.c_void_p(handle), ctypes.byref(margins))

    def set_desired_size(self, handle: int, width: int, height: int) -> None:
        """设置期望尺寸（逻辑像素）。

        @param handle - window_get 的返回值
        @param width - 宽
        @param height - 高
        """
        size = QSize(width, height)
        self._set_desired_size(ctypes.c_void_p(handle), ctypes.byref(size))


def load() -> LayerShell | None:
    """加载接口库。

    三种失败都返回 None 而不是抛错：库不存在（非 KDE 或未装包）、符号缺失
    （版本差异）、加载期的其它 OSError。调用方据此退回既有定位路径。

    @returns 已加载实例；不可用时 None
    """
    try:
        library = ctypes.CDLL(LIBRARY_NAME)
    except OSError:
        return None
    try:
        return LayerShell(library)
    except LookupError:
        return None
