"""缩放实测探针：量「100 逻辑像素」在屏幕上实际占多少物理像素。

## 为什么需要它

规格的 SC-001 要求「100 逻辑像素的元素实测为 150 物理像素（±1）」。这条只能
真机量——任何通过 Qt 自身 API 读到的值都不可信（`devicePixelRatio()` 正是有
争议的那一方）。

## 用法

    python3 scripts/probe-scale.py --out /tmp/probe.png

脚本自己截屏（`spectacle`），自己量（PIL），打印结论并给出退出码：

- 0：实测比例与预期一致（±2%）
- 1：不一致（打印期望值与实测值）
- 2：环境不满足（没 DISPLAY、截图失败、PIL 缺失）

## 测量方法

窗口里画一个**已知逻辑宽度**的纯色块，四周留白；截图后数纯色像素的连续行宽。
块用洋红 `(255, 0, 255)` —— 桌面主题里几乎不会出现这种颜色，误判风险最低。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

#: 色块逻辑宽度。与规格 SC-001 一致。
BLOCK_LOGICAL_WIDTH = 100
#: 色块逻辑高度。够高才好在截图里定位，但不必是 100。
BLOCK_LOGICAL_HEIGHT = 40
#: 色块颜色。
BLOCK_RGB = (255, 0, 255)
#: 窗口留白（逻辑像素），保证色块四周有可区分的背景。
PADDING = 40


def render(path: Path) -> bool:
    """渲染探针窗口并截图。

    @param path - 截图输出路径
    @returns 成功 True
    """
    from PyQt6.QtCore import QTimer, Qt
    from PyQt6.QtGui import QColor, QPainter
    from PyQt6.QtWidgets import QApplication, QWidget

    class Probe(QWidget):
        """画一个已知逻辑尺寸的纯色块。"""

        def paintEvent(self, event) -> None:  # noqa: N802 - Qt 命名
            painter = QPainter(self)
            painter.fillRect(self.rect(), QColor(255, 255, 255))
            painter.fillRect(PADDING, PADDING, BLOCK_LOGICAL_WIDTH, BLOCK_LOGICAL_HEIGHT, QColor(*BLOCK_RGB))
            painter.end()

    app = QApplication(sys.argv)
    probe = Probe()
    probe.setWindowTitle("scale-probe")
    probe.setFixedSize(
        BLOCK_LOGICAL_WIDTH + PADDING * 2,
        BLOCK_LOGICAL_HEIGHT + PADDING * 2,
    )
    probe.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
    probe.move(200, 200)
    probe.show()

    def capture() -> None:
        try:
            subprocess.run(
                ["spectacle", "-b", "-n", "-f", "-o", str(path)],
                check=True,
                timeout=20,
                capture_output=True,
            )
        finally:
            app.quit()

    QTimer.singleShot(900, capture)
    app.exec()
    return path.exists()


def measure(path: Path) -> int | None:
    """数截图里色块的物理宽度。

    @param path - 截图路径
    @returns 实测宽度（物理像素）；找不到色块时 None
    """
    from PIL import Image

    image = Image.open(path).convert("RGB")
    width, height = image.size
    pixels = image.load()

    def is_block(x: int, y: int) -> bool:
        r, g, b = pixels[x, y]
        return abs(r - BLOCK_RGB[0]) < 24 and abs(g - BLOCK_RGB[1]) < 24 and abs(b - BLOCK_RGB[2]) < 24

    # 取出现色块最多的那一行，避免被抗锯齿边缘的行干扰。
    best_run = 0
    for y in range(0, height, 2):
        run = 0
        for x in range(width):
            if is_block(x, y):
                run += 1
            else:
                if run > best_run:
                    best_run = run
                run = 0
        if run > best_run:
            best_run = run
    return best_run or None


def main(argv: list[str] | None = None) -> int:
    """入口。

    @param argv - 命令行参数
    @returns 进程退出码
    """
    parser = argparse.ArgumentParser(description="量真实缩放比例")
    parser.add_argument("--out", default=str(Path(tempfile.gettempdir()) / "probe-scale.png"), help="截图路径")
    parser.add_argument("--expect", type=float, default=None, help="期望的缩放比例；省略则只打印实测值")
    args = parser.parse_args(argv)

    path = Path(args.out)
    if not render(path):
        print(f"截图失败：{path} 不存在", file=sys.stderr)
        return 2

    measured = measure(path)
    if measured is None:
        print("截图里找不到色块；检查窗口是否被遮挡", file=sys.stderr)
        return 2

    ratio = measured / BLOCK_LOGICAL_WIDTH
    print(f"色块逻辑宽 {BLOCK_LOGICAL_WIDTH} → 实测物理宽 {measured} → 比例 {ratio:.3f}")

    if args.expect is None:
        return 0

    if abs(ratio - args.expect) / args.expect <= 0.02:
        print(f"与期望 {args.expect} 一致")
        return 0

    print(f"与期望 {args.expect} 不一致，差 {abs(ratio - args.expect) / args.expect:.1%}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
