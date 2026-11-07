#!/usr/bin/env python3
"""横幅可见性自动化检查。

为什么需要它：这台机器上「横幅到底有没有弹」只能靠看屏幕判断，而模型读不了图。
这个脚本把判断变成可重复的数字——**发送通知前后各截一张，比对横幅区域的像素变化**。
如果横幅出现了，右上角那块区域会大面积改变；没出现则几乎为零。

用法：
    ./scripts/check-banner.py                # 跑一遍，打印结论
    ./scripts/check-banner.py --keep         # 保留截图便于人工复核
    ./scripts/check-banner.py --region 1050,20,1463,320

退出码：0 = 检测到横幅；1 = 未检测到；2 = 环境不满足（无 spectacle / 无通知服务）。

已知边界（实测）：Plasma 的 `expire_timeout` 只关横幅，通知本体仍留在通知中心，
所以「id 仍可顶替」不能用来判断横幅是否可见——必须看像素。
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# 横幅区：**按比例**给出，不是像素。
#
# 踩过的坑：spectacle 抓的是物理分辨率（本机 2560x1600），而早期版本写死了预览坐标
# （1463x915）下的像素值，于是实际裁剪的是图片中左部——横幅明明在右上角，却测出
# 0.00% 变化，得出「Plasma 不渲染通知」的错误结论。比例坐标对分辨率免疫。
DEFAULT_REGION_FRAC = (0.74, 0.02, 0.99, 0.50)

# 判定阈值：变化像素占比超过这个比例即认为横幅出现。
# 实测横幅约占该区域 30%~60%；无横幅时差分 < 0.1%（只有时钟秒数变化）。
CHANGE_THRESHOLD_PERCENT = 5.0

# 像素差超过它才算「变了」；JPEG 压缩噪声在 12 以内。
PIXEL_DELTA = 12


def capture(path: Path) -> bool:
    """截一张全屏图。

    @param path - 输出文件
    @returns 成功与否
    """
    if shutil.which("spectacle") is None:
        return False
    result = subprocess.run(
        ["spectacle", "-b", "-n", "-f", "-o", str(path)],
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    return result.returncode == 0 and path.exists()


def region_pixels(size: tuple[int, int], frac: tuple[float, float, float, float]) -> tuple[int, int, int, int]:
    """把比例区域换算成该图的像素区域。

    @param size - 图像 (宽, 高)
    @param frac - (x0, y0, x1, y1)，各分量 0~1
    @returns 像素区域
    """
    width, height = size
    x0, y0, x1, y1 = frac
    return (
        int(width * x0),
        int(height * y0),
        int(width * x1),
        int(height * y1),
    )


def brightness_of_banner_region(path: Path, frac: tuple[float, float, float, float]) -> float:
    """取横幅区域的平均亮度（用于给出可读的诊断数字）。

    @param path - 截图
    @param region - (x0, y0, x1, y1)
    @returns 平均亮度 0~255；读不了返回 -1
    """
    try:
        from PIL import Image
    except ImportError:
        return -1
    with Image.open(path) as image:
        region = region_pixels(image.size, frac)
        raw = image.convert("L").crop(region).tobytes()
    return sum(raw) / len(raw) if raw else -1


def changed_percent(before: Path, after: Path, frac: tuple[float, float, float, float]) -> float:
    """两张图在指定区域的差异像素占比。

    @param before - 基线截图
    @param after - 之后截图
    @param region - (x0, y0, x1, y1)
    @returns 百分比 0~100
    """
    try:
        from PIL import Image
    except ImportError:
        return -1.0
    with Image.open(before) as first, Image.open(after) as second:
        region = region_pixels(first.size, frac)
        a = first.convert("L").crop(region)
        b = second.convert("L").crop(region)
        if a.size != b.size:
            # 分辨率变了就无法差分：按「有变化」处理，避免误报为无横幅。
            return 100.0
        pa = a.tobytes()
        pb = b.tobytes()
    if len(pa) != len(pb):
        return 100.0
    changed = sum(1 for x, y in zip(pa, pb) if abs(x - y) > PIXEL_DELTA)
    return changed * 100.0 / len(pa) if pa else 0.0


def notification_server_available() -> bool:
    """通知服务是否在。

    @returns 是否可用
    """
    result = subprocess.run(
        [
            "gdbus",
            "call",
            "--session",
            "--dest",
            "org.freedesktop.Notifications",
            "--object-path",
            "/org/freedesktop/Notifications",
            "--method",
            "org.freedesktop.Notifications.GetServerInformation",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    return result.returncode == 0


def send_test_notification(title: str, body: str, timeout_ms: int) -> int | None:
    """发一条不会自动消失的测试通知。

    @param title - 标题
    @param body - 正文
    @param timeout_ms - 横幅停留毫秒
    @returns 通知 id；失败 None
    """
    import re

    result = subprocess.run(
        [
            "gdbus",
            "call",
            "--session",
            "--dest",
            "org.freedesktop.Notifications",
            "--object-path",
            "/org/freedesktop/Notifications",
            "--method",
            "org.freedesktop.Notifications.Notify",
            "BannerCheck",
            "uint32 0",
            "",
            title,
            body,
            "[]",
            "{}",
            f"int32 {timeout_ms}",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    if result.returncode != 0:
        return None
    match = re.search(r"uint32\s+(\d+)", result.stdout)
    return int(match.group(1)) if match else None


def close_notification(notification_id: int) -> None:
    """关掉一条通知，避免污染后续检查。

    @param notification_id - 通知 id
    """
    subprocess.run(
        [
            "gdbus",
            "call",
            "--session",
            "--dest",
            "org.freedesktop.Notifications",
            "--object-path",
            "/org/freedesktop/Notifications",
            "--method",
            "org.freedesktop.Notifications.CloseNotification",
            f"uint32 {notification_id}",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )


def selftest() -> int:
    """验证差分逻辑本身：同一对图应 0%，人为改动应远超阈值。

    「测出来 0.00%」必须先证明检测器有效，否则可能只是区域选错了。

    @returns 退出码
    """
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        print("缺少 Pillow，无法自检", file=sys.stderr)
        return 2

    workdir = Path(tempfile.mkdtemp(prefix="banner-selftest-"))
    base = workdir / "base.png"
    same = workdir / "same.png"
    changed = workdir / "changed.png"

    canvas = Image.new("L", (1463, 915), 40)
    canvas.save(base)
    canvas.save(same)

    # 在横幅区画一块亮矩形，模拟「横幅出现」
    drawn = canvas.copy()
    x0, y0, x1, y1 = region_pixels(canvas.size, DEFAULT_REGION_FRAC)
    ImageDraw.Draw(drawn).rectangle([x0 + 10, y0 + 20, x1 - 10, y1 - 40], fill=200)
    drawn.save(changed)

    unchanged_percent = changed_percent(base, same, DEFAULT_REGION_FRAC)
    changed_rect_percent = changed_percent(base, changed, DEFAULT_REGION_FRAC)

    print(f"同一对图: {unchanged_percent:.2f}%（应为 0）")
    print(f"横幅区改动: {changed_rect_percent:.2f}%（应 >= {CHANGE_THRESHOLD_PERCENT}）")
    shutil.rmtree(workdir, ignore_errors=True)

    ok = unchanged_percent == 0.0 and changed_rect_percent >= CHANGE_THRESHOLD_PERCENT
    print("自检:", "通过——检测器能识别横幅" if ok else "失败——差分逻辑不可信")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    """跑一次检查。

    @param argv - 命令行参数
    @returns 退出码
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep", action="store_true", help="保留截图")
    parser.add_argument(
        "--region",
        default=",".join(str(v) for v in DEFAULT_REGION_FRAC),
        help="横幅区域比例 x0,y0,x1,y1（0~1，与分辨率无关）",
    )
    parser.add_argument("--timeout-ms", type=int, default=30_000, help="测试通知停留毫秒")
    parser.add_argument("--selftest", action="store_true", help="只验证差分逻辑（不需要桌面）")
    args = parser.parse_args(argv)

    if args.selftest:
        return selftest()

    region = tuple(float(part) for part in args.region.split(","))
    if len(region) != 4 or not all(0.0 <= v <= 1.0 for v in region):
        print("region 需要四个 0~1 的比例：x0,y0,x1,y1", file=sys.stderr)
        return 2

    if not notification_server_available():
        print("环境不满足：通知服务不可用", file=sys.stderr)
        return 2

    workdir = Path(tempfile.mkdtemp(prefix="banner-check-"))
    before = workdir / "before.png"
    after = workdir / "after.png"

    if not capture(before):
        print("环境不满足：截图失败（spectacle 不可用或没有会话总线）", file=sys.stderr)
        return 2

    notification_id = send_test_notification("横幅可见性检查", "收到这条说明横幅正常", args.timeout_ms)
    if notification_id is None:
        print("环境不满足：通知发送失败", file=sys.stderr)
        return 2

    time.sleep(1.2)
    if not capture(after):
        print("环境不满足：第二次截图失败", file=sys.stderr)
        return 2

    percent = changed_percent(before, after, region)
    before_brightness = brightness_of_banner_region(before, region)
    after_brightness = brightness_of_banner_region(after, region)

    print(f"横幅区变化: {percent:.2f}%  (阈值 {CHANGE_THRESHOLD_PERCENT}%)")
    try:
        from PIL import Image as _Image

        with _Image.open(after) as shot:
            print(f"截图分辨率: {shot.size[0]}x{shot.size[1]}  → 裁剪区 {region_pixels(shot.size, region)}")
    except ImportError:
        pass
    print(f"区域亮度: 之前 {before_brightness:.1f} → 之后 {after_brightness:.1f}")
    print(f"截图目录: {workdir}")

    close_notification(notification_id)

    if percent < 0:
        print("无法差分：缺少 Pillow", file=sys.stderr)
        return 2

    if percent >= CHANGE_THRESHOLD_PERCENT:
        print("结论: 检测到横幅")
        return 0

    print("结论: 未检测到横幅——通知已被服务端接受，但屏幕上没有出现")
    if not args.keep:
        shutil.rmtree(workdir, ignore_errors=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
