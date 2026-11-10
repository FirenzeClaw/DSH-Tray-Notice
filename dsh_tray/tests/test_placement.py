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
