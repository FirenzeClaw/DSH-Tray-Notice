"""面板定位测试：锚点计算与降级。

本文件的坐标断言全部按**逻辑坐标**（Qt 的坐标系），不是物理像素。本机逻辑
1707×1067、物理 2560×1600、scale 1.5——把两者混起来是之前踩过的坑。

`LinuxPanelPlacement.apply()` 在真实桌面依赖层外壳协议；测试里把它要用的
`windowHandle()` 与 `screen` 都换成假对象，只验证「算不算得对」与「拿不到
能力时是否老实返回 False」。
"""

from __future__ import annotations

import unittest

from dsh_tray.platform.linux import LinuxPanelPlacement

#: 本机实测逻辑宽度（物理 2560 / scale 1.5）。
SCREEN_WIDTH = 1707
SCREEN_HEIGHT = 1067
#: 面板宽度，与 `dsh_tray/ui/panel.py` 的 PANEL_WIDTH 一致。
PANEL_WIDTH = 378


class FakeGeometry:
    """模拟 QRect。"""

    def __init__(self, x: int, y: int, width: int, height: int) -> None:
        self._x = x
        self._y = y
        self._width = width
        self._height = height

    def x(self) -> int:
        return self._x

    def y(self) -> int:
        return self._y

    def width(self) -> int:
        return self._width

    def height(self) -> int:
        return self._height

    def left(self) -> int:
        return self._x

    def top(self) -> int:
        return self._y

    def right(self) -> int:
        return self._x + self._width - 1


class FakeScreen:
    """模拟 QScreen。"""

    def __init__(self, x: int = 0, y: int = 0, width: int = SCREEN_WIDTH, height: int = SCREEN_HEIGHT) -> None:
        self._geometry = FakeGeometry(x, y, width, height)

    def geometry(self) -> FakeGeometry:
        return self._geometry

    def availableGeometry(self) -> FakeGeometry:
        return self._geometry


class Target:
    """记录 apply() 想放到哪里。"""

    def __init__(self) -> None:
        self.x = -1
        self.y = -1
        self.margins: tuple[int, int, int, int] | None = None
        self.anchors: int | None = None
        self.size: tuple[int, int] | None = None


class FakePlacement(LinuxPanelPlacement):
    """把真实的层外壳调用换成记录器，只测坐标计算。"""

    def __init__(self) -> None:
        super().__init__(right_margin=8, top_margin=8)
        self.target = Target()
        self._available = True

    def _apply_native(self, widget, width, height, screen) -> bool:  # noqa: ANN001 - 测试替身
        if not self._available:
            return False
        x, y = self.target_rect(screen.geometry(), width)
        self.target.x = x
        self.target.y = y
        self.target.size = (width, height)
        return True


class PlacementGeometryTest(unittest.TestCase):
    """坐标计算。"""

    def test_anchors_top_right(self) -> None:
        placement = FakePlacement()
        screen = FakeScreen()
        ok = placement.apply(object(), PANEL_WIDTH, 600, screen)
        self.assertTrue(ok)
        # 1707 - 378 - 8 = 1321
        self.assertEqual(placement.target.x, 1321)
        self.assertEqual(placement.target.y, 8)

    def test_x_never_negative_when_panel_wider_than_screen(self) -> None:
        placement = FakePlacement()
        screen = FakeScreen(width=300)
        placement.apply(object(), PANEL_WIDTH, 600, screen)
        self.assertGreaterEqual(placement.target.x, 0)

    def test_respects_screen_offset(self) -> None:
        """副屏起点不是 0 时，锚点要跟着偏移。"""
        placement = FakePlacement()
        screen = FakeScreen(x=1707, y=0)
        placement.apply(object(), PANEL_WIDTH, 600, screen)
        self.assertEqual(placement.target.x, 1707 + 1707 - PANEL_WIDTH - 8)

    def test_margins_injectable(self) -> None:
        placement = LinuxPanelPlacement(right_margin=20, top_margin=32)
        self.assertEqual(placement.right_margin, 20)
        self.assertEqual(placement.top_margin, 32)


class PlacementFallbackTest(unittest.TestCase):
    """能力不可用时必须老实返回 False，不抛异常。"""

    def test_returns_false_when_native_unavailable(self) -> None:
        placement = FakePlacement()
        placement._available = False
        self.assertFalse(placement.apply(object(), PANEL_WIDTH, 600, FakeScreen()))

    def test_returns_false_when_window_handle_missing(self) -> None:
        """真实实现里 windowHandle() 为 None 时必须降级。"""
        placement = LinuxPanelPlacement()

        class NoHandle:
            def windowHandle(self):  # noqa: N802 - Qt 命名
                return None

        self.assertFalse(placement.apply(NoHandle(), PANEL_WIDTH, 600, FakeScreen()))

    def test_returns_false_when_widget_has_no_window_handle(self) -> None:
        placement = LinuxPanelPlacement()
        self.assertFalse(placement.apply(object(), PANEL_WIDTH, 600, FakeScreen()))


if __name__ == "__main__":
    unittest.main()


class ProductionOrderTest(unittest.TestCase):
    """生产路径的顺序契约。

    这组测试的存在理由：上面那个缺陷（层外壳在 show() 之后配置）**绕过了全部
    259 条测试**。`apply()` 返回 True、`isVisible()` 也是 True，只有真机截图才
    看得出来面板根本没画出来。所以这里断言的是「可观测的行为契约」，不是内部调用：

    - `apply_placement()` 必须在 `show()` 之前被调用（它自己负责强制创建 QWindow）
    - 调用后窗口的原生句柄必须已存在，否则层外壳拿不到 handle
    """

    def setUp(self) -> None:
        from PyQt6.QtWidgets import QApplication

        self.app = QApplication.instance() or QApplication([])
        from dsh_tray.ui.panel import Panel

        self.panel = Panel()

    def tearDown(self) -> None:
        from PyQt6.QtWidgets import QApplication

        self.panel.deleteLater()
        QApplication.processEvents()

    def test_window_handle_ready_when_apply_is_called(self) -> None:
        """`apply()` 被调用时 `windowHandle()` 必须已可用。

        这是层外壳的硬前提：`LayerShellQt::Window::get()` 需要一个真实的 QWindow
        指针，否则返回空句柄、后面所有配置静默无效。

        为什么这样断言：不能直接断言 `winId() != 0`——`winId()` 自己就会创建
        原生窗口，那样测试会自我满足、永远通过。必须在替身的 `apply()` 里
        **当场**观察 `windowHandle()`。
        """
        from dsh_tray.ui.panel import Panel

        observed: list[bool] = []

        class ProbePlacement:
            """在 apply() 内部记录 windowHandle 是否已存在。"""

            def apply(self, widget, width, height, screen):
                observed.append(widget.windowHandle() is not None)
                return True

        panel = Panel()
        try:
            self.assertFalse(panel.isVisible())
            ok = panel.apply_placement(ProbePlacement())
            self.assertTrue(ok)
            self.assertEqual(observed, [True], "apply() 时 windowHandle 必须已存在")
            self.assertFalse(panel.isVisible(), "apply_placement 不应自己 show()")
        finally:
            panel.deleteLater()

    def test_apply_before_show_is_the_documented_order(self) -> None:
        """文档字符串必须说明正确顺序，否则下一个人会照旧写错。"""
        from dsh_tray.ui.panel import Panel

        doc = Panel.apply_placement.__doc__ or ""
        self.assertIn("show()", doc)
        self.assertIn("之前", doc)

    def test_returns_false_without_placement(self) -> None:
        self.assertFalse(self.panel.apply_placement(None))


class LoadRetryTest(unittest.TestCase):
    """库加载失败后必须能重试。

    为什么需要：包管理器替换 `.so` 的瞬间 `dlopen` 可能失败。若把失败结果永久
    缓存，托盘要在重启后才能恢复定位能力——而定位失败是静默的，用户只会觉得
    「面板又跑到中间了」。
    """

    def test_retries_after_load_failure(self) -> None:
        from unittest.mock import patch

        from dsh_tray.platform import layershell
        from dsh_tray.platform.linux import LinuxPanelPlacement

        placement = LinuxPanelPlacement()
        with patch.object(layershell, "load", return_value=None) as first:
            self.assertIsNone(placement._load())
            self.assertEqual(first.call_count, 1)

        # 第二次：库恢复可用，必须重新尝试而不是返回缓存的 None
        sentinel = object()
        with patch.object(layershell, "load", return_value=sentinel) as second:
            self.assertIs(placement._load(), sentinel)
            self.assertEqual(second.call_count, 1)

    def test_caches_after_success(self) -> None:
        from unittest.mock import patch

        from dsh_tray.platform import layershell
        from dsh_tray.platform.linux import LinuxPanelPlacement

        placement = LinuxPanelPlacement()
        sentinel = object()
        with patch.object(layershell, "load", return_value=sentinel) as loader:
            self.assertIs(placement._load(), sentinel)
            self.assertIs(placement._load(), sentinel)
            self.assertEqual(loader.call_count, 1, "成功后不该重复加载")
