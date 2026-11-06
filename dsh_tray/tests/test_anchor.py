"""锚点策略测试：贴图标 vs 退化到屏幕右上角。

`QSystemTrayIcon.geometry()` 在 Plasma Wayland 上返回 0×0（实测），所以「退化」
不是异常分支而是常态分支——必须和正常分支一样被断言。
"""

from __future__ import annotations

import unittest

from dsh_tray.platform.linux import LinuxWindowAnchor


class FakeRect:
    """模拟 QRect 的 availableGeometry 返回值。"""

    def __init__(self, left: int, top: int, width: int, height: int) -> None:
        self._left = left
        self._top = top
        self._width = width
        self._height = height

    def right(self) -> int:
        return self._left + self._width - 1

    def top(self) -> int:
        return self._top

    def width(self) -> int:
        return self._width

    def height(self) -> int:
        return self._height


class FakeScreen:
    """模拟 QScreen。"""

    def __init__(self, rect: FakeRect) -> None:
        self._rect = rect

    def availableGeometry(self) -> FakeRect:  # noqa: N802 - 模拟 Qt 命名
        return self._rect


class AnchorTest(unittest.TestCase):
    """锚点计算。"""

    def setUp(self) -> None:
        self.screen = FakeScreen(FakeRect(0, 0, 1920, 1080))

    def test_uses_tray_geometry_when_valid(self) -> None:
        anchor = LinuxWindowAnchor(margin=8)
        x, y = anchor.anchor_for((1800, 1040, 24, 24), self.screen)
        self.assertEqual((x, y), (1824, 1064))

    def test_falls_back_to_screen_corner_on_zero_geometry(self) -> None:
        anchor = LinuxWindowAnchor(margin=8)
        x, y = anchor.anchor_for((0, 0, 0, 0), self.screen)
        # 右上角，向内留 8 px
        self.assertEqual(y, 8)
        self.assertLess(x, 1920)
        self.assertGreater(x, 1800)

    def test_none_geometry_falls_back(self) -> None:
        anchor = LinuxWindowAnchor(margin=8)
        x, y = anchor.anchor_for(None, self.screen)
        self.assertEqual(y, 8)
        self.assertLess(x, 1920)

    def test_negative_geometry_falls_back(self) -> None:
        anchor = LinuxWindowAnchor(margin=8)
        x, _y = anchor.anchor_for((-1, -1, 0, 0), self.screen)
        self.assertGreater(x, 1800)

    def test_margin_is_configurable(self) -> None:
        anchor = LinuxWindowAnchor(margin=32)
        _x, y = anchor.anchor_for(None, self.screen)
        self.assertEqual(y, 32)


if __name__ == "__main__":
    unittest.main()
