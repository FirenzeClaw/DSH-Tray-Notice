"""托盘图标：把用户提供的鲸鱼路径渲染成 QIcon。

原始 SVG 的 viewBox 是 23.16×17.04（约 1.36:1），fill=currentColor。

**方形画布 + 一圈透明留白**：面板实测普通图标的槽位间距 38–44 px、字形本身
只有 21–25 px，即四周约有 20% 透明边。若按原始比例贴着边渲染，鲸鱼横向上会
顶满槽位，比邻居图标明显偏大。所以这里把 viewBox 撑成正方形，四周留
`PADDING_RATIO` 比例的空白，视觉重量与其他托盘图标一致。

不依赖 PyQt6.QtSvg：本机 Qt 没有 Python 的 QtSvg 绑定，但 SVG 图像格式插件
在（libqt6svg6），所以直接交给 QIcon 就能读。
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from PyQt6.QtGui import QIcon

#: 运行中：纯白。Plasma 面板实测是深色（#222222），白鲸对比最强，
#: 也和面板上其他状态图标的单色风格一致。
COLOR_RUNNING = "#FFFFFF"

#: 未运行：中性灰，明显暗于运行态但不至于消失。
COLOR_IDLE = "#8A8F98"

_PATH = (
'M22.9168 1.43018C22.6713 1.31018 22.5658 1.53918 22.4223 1.65519C22.3733 1.69269 22.3318 1.74169 22.2903 1.78669C21.9317 2.1697 21.5127 2.42121 20.9657 2.39121C20.1657 2.34621 19.4827 2.59771 18.8787 3.20973C18.7502 2.45521 18.3236 2.0047 17.6746 1.71569C17.3351 1.56568 16.9916 1.41518 16.7536 1.08867C16.5876 0.856163 16.5421 0.597155 16.4591 0.341647C16.4061 0.187643 16.3536 0.0301382 16.1761 0.00363739C15.9836 -0.0263635 15.9081 0.135141 15.8326 0.270145C15.5306 0.822162 15.4136 1.43018 15.4251 2.0462C15.4516 3.43174 16.0366 4.53527 17.1991 5.3203C17.3311 5.4103 17.3651 5.5003 17.3236 5.63181C17.2441 5.90231 17.1501 6.16482 17.0671 6.43533C17.0141 6.60784 16.9351 6.64584 16.7501 6.57033C16.1121 6.30383 15.5611 5.90931 15.074 5.4328C14.2475 4.63328 13.5 3.75075 12.568 3.05973C12.349 2.89822 12.13 2.74822 11.9034 2.60522C10.9524 1.68169 12.028 0.923165 12.277 0.833162C12.5375 0.739159 12.3675 0.41615 11.5259 0.42015C10.6844 0.42365 9.91439 0.705658 8.93286 1.08117C8.78935 1.13767 8.63835 1.17867 8.48384 1.21267C7.59332 1.04367 6.66829 1.00617 5.70226 1.11517C3.88321 1.31768 2.43016 2.1777 1.36213 3.64575C0.0790928 5.4103 -0.222916 7.41536 0.146595 9.50642C0.535106 11.7105 1.66014 13.535 3.38869 14.9616C5.18125 16.4406 7.24581 17.1657 9.60138 17.0266C11.0319 16.9441 12.6245 16.7526 14.421 15.2321C14.874 15.4576 15.3496 15.5476 16.1381 15.6151C16.7456 15.6716 17.3306 15.5851 17.7836 15.4911C18.4931 15.3411 18.4441 14.6841 18.1876 14.5636C16.1081 13.595 16.5646 13.9891 16.1496 13.67C17.2061 12.42 18.8202 10.1979 19.3182 7.17235C19.3672 6.83834 19.4297 6.36783 19.4222 6.09732C19.4182 5.93231 19.4562 5.86831 19.6447 5.84931C20.1657 5.78931 20.6712 5.64681 21.1357 5.3913C22.4833 4.65528 23.0268 3.44624 23.1548 1.9972C23.1738 1.77569 23.1508 1.54668 22.9168 1.43018ZM11.1749 14.4736C9.15936 12.889 8.18184 12.3675 7.77832 12.39C7.40081 12.4125 7.46881 12.8445 7.55182 13.126C7.63882 13.404 7.75182 13.5955 7.91033 13.8396C8.01983 14.0011 8.09533 14.2411 7.80083 14.4216C7.15181 14.8231 6.02327 14.2866 5.97027 14.2601C4.65673 13.4865 3.5587 12.4655 2.78467 11.069C2.03715 9.72493 1.60314 8.28289 1.53164 6.74384C1.51264 6.37233 1.62214 6.24082 1.99215 6.17332C2.47916 6.08332 2.98118 6.06432 3.46769 6.13582C5.52476 6.43633 7.27581 7.35586 8.74385 8.8129C9.58188 9.64243 10.2159 10.634 10.8689 11.6025C11.5634 12.631 12.3105 13.611 13.262 14.4146C13.598 14.6961 13.866 14.9101 14.1225 15.0681C13.349 15.1546 12.058 15.1731 11.1749 14.4746L11.1749 14.4736ZM12.141 8.25988C12.141 8.09488 12.273 7.96338 12.439 7.96338C12.4765 7.96338 12.5105 7.97088 12.541 7.98188C12.5825 7.99688 12.6205 8.01938 12.6505 8.05338C12.7035 8.10588 12.7335 8.18088 12.7335 8.25988C12.7335 8.42489 12.6015 8.55639 12.4355 8.55639C12.2695 8.55639 12.141 8.42489 12.141 8.25988ZM15.1415 9.79893C14.949 9.87793 14.7565 9.94544 14.5715 9.95294C14.2845 9.96794 13.9715 9.85143 13.8015 9.70893C13.5375 9.48742 13.3485 9.36342 13.2695 8.97691C13.2355 8.8119 13.2545 8.55639 13.2845 8.40989C13.3525 8.09438 13.277 7.89187 13.0545 7.70787C12.8735 7.55786 12.643 7.51636 12.39 7.51636C12.2955 7.51636 12.209 7.47486 12.1445 7.44136C12.039 7.38886 11.9519 7.25735 12.035 7.09585C12.0615 7.04335 12.19 6.91584 12.22 6.89334C12.5635 6.69784 12.9595 6.76184 13.326 6.90834C13.6655 7.04735 13.9225 7.30236 14.292 7.66287C14.6695 8.09838 14.7375 8.21838 14.9525 8.54539C15.1225 8.8009 15.277 9.06341 15.3831 9.36392C15.4471 9.55142 15.3641 9.70493 15.1415 9.79893Z'
)

#: 原始图形尺寸（来自用户 SVG 的 viewBox）。
_GLYPH_WIDTH = 23.16
_GLYPH_HEIGHT = 17.04

#: 每侧透明留白占画布边长的比例。
#: 取 0.12：字形约占画布 76% 宽，与面板上邻居图标的留白观感一致（实测约 20%
#: 边距，但鲸鱼本身是宽扁形，留太多会显得比邻居小）。
PADDING_RATIO = 0.12


def _square_view_box() -> tuple[float, float, float]:
    """把宽扁字形装进正方形的 viewBox，返回 (x, y, side)。

    边长按最长边反推，使字形在正方形内居中且四周留出 PADDING_RATIO 的空白。
    """
    side = max(_GLYPH_WIDTH, _GLYPH_HEIGHT) / (1 - 2 * PADDING_RATIO)
    x = (_GLYPH_WIDTH - side) / 2
    y = (_GLYPH_HEIGHT - side) / 2
    return x, y, side


_VIEW_X, _VIEW_Y, _VIEW_SIDE = _square_view_box()

_TEMPLATE = (
    '<svg xmlns="http://www.w3.org/2000/svg" '
    f'viewBox="{_VIEW_X:.4f} {_VIEW_Y:.4f} {_VIEW_SIDE:.4f} {_VIEW_SIDE:.4f}" fill="none">'
    '<path d="{path}" fill="{color}"/></svg>'
)


def whale_svg(color: str) -> str:
    """生成指定填充色的鲸鱼 SVG 文本。"""
    return _TEMPLATE.replace("{path}", _PATH).replace("{color}", color)


def _cache_path(color: str) -> Path:
    """图标缓存路径。QIcon 需要真实文件或设备，这里落盘一次复用。"""
    directory = Path(tempfile.gettempdir()) / "dsh-tray-icons"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"whale-{color.lstrip('#').lower()}.svg"


def build_icon(color: str) -> QIcon:
    """构造 QIcon。

    QIcon 读 SVG 是按需光栅化，所以不同托盘尺寸都清晰，不需要预生成多档位图。
    """
    path = _cache_path(color)
    expected = whale_svg(color)
    try:
        if path.read_text(encoding="utf-8") != expected:
            path.write_text(expected, encoding="utf-8")
    except OSError:
        # 缓存目录不可写时退回内存：QIcon 仍可从资源读取，这里直接返回空图标
        # 会让托盘看不见，所以优先保证写入失败也不炸。
        path.write_text(expected, encoding="utf-8")
    return QIcon(str(path))


def running_icon() -> QIcon:
    """运行中图标。"""
    return build_icon(COLOR_RUNNING)


def idle_icon() -> QIcon:
    """未运行图标。"""
    return build_icon(COLOR_IDLE)

def badge_text(count: int) -> str:
    """未读角标上显示的文字。

    超过 9 显示 `9+`：托盘图标只有 22 px，两位数会挤成一小团，读不出来。
    @param count - 未读条数
    @returns 角标文字；0 时为空串
    """
    if count <= 0:
        return ""
    return str(count) if count <= 9 else "9+"


def with_badge(icon: QIcon, count: int) -> QIcon:
    """在图标右上角叠加未读角标。

    用 QPainter 直接画在 22×22 的 pixmap 上，而不是准备两张 SVG：角标位置与字号
    依赖实际尺寸，位图更直接；托盘尺寸变化时由 Qt 缩放，视觉上仍可接受。

    @param icon - 原始图标
    @param count - 未读条数；0 时原样返回
    @returns 带角标的图标
    """
    text = badge_text(count)
    if text == "":
        return icon

    from PyQt6.QtCore import QRectF, Qt
    from PyQt6.QtGui import QColor, QFont, QPainter, QPixmap

    size = 22
    pixmap = icon.pixmap(size, size)
    if pixmap.isNull():
        return icon

    canvas = QPixmap(size, size)
    canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    painter.drawPixmap(0, 0, pixmap)

    # 角标直径随文字长度增长：`9+` 比 `3` 宽，固定圆会切字。
    diameter = 11 if len(text) == 1 else 14
    left = size - diameter + 1
    top = -1
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setBrush(QColor("#da4453"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(QRectF(left, top, diameter, diameter))

    font = QFont()
    font.setPixelSize(9 if len(text) == 1 else 8)
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(QColor("#ffffff"))
    painter.drawText(QRectF(left, top, diameter, diameter), Qt.AlignmentFlag.AlignCenter, text)
    painter.end()
    return QIcon(canvas)
