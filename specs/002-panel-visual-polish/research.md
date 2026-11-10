# 实施前调研：缩放与定位的技术可行性

**Date**: 2026-11-09 | **Feature**: 002-panel-visual-polish

本文只记录**实测结论**。凭直觉猜错的项已标注「曾猜错」，避免后续执行者重蹈。

## D1. 屏幕真实缩放从哪里读

**决策**：读 `kwinrc` 的 `[Xwayland] Scale`，经 `kreadconfig6`。

**证据**：
```
$ kreadconfig6 --file kwinrc --group Xwayland --key Scale
1.5
$ kreadconfig6 --file kdeglobals --group KScreen --key ScaleFactor
1.75
```

`Xwayland Scale` = 1.5 与逻辑分辨率吻合（物理 2560 ÷ 1.5 = 1706.7 ≈ Qt 报告的 1707）。`kdeglobals` 的 1.75 与产物尺寸不符，故不采用。

**替代方案**：
- `wp_fractional_scale_manager_v1`（协议存在，v1）——需要自建 Wayland 客户端读取 preferred_scale，成本远高于收益。
- `QScreen.devicePixelRatio()`——**就是有问题的那一方**，实测返回 2.0 而真实是 1.5。

**放弃的理由**：缩放值只用于启动脚本里的一个环境变量，任何需要额外进程或协议的方案都不划算。

## D2. 为什么 Qt 报 2.0 而实际是 1.5

**结论**：Qt 把小数缩放按「向上取整」的方式折算成了整数 DPR，于是按 2× 分配缓冲区；合成器按 1.5× 放大，视觉上元素比应得的大约 33%。

**实测排除项**：三种 `QT_SCALE_FACTOR_ROUNDING_POLICY`（`Round` / `PassThrough` / `RoundPreferFloor`）下 `devicePixelRatio` **都是 2.0**，逻辑尺寸恒为 1707×1067。说明该策略不解决此问题，必须显式设 `QT_SCALE_FACTOR`。

**曾猜错**：一度以为改舍入策略即可，实测三次全部无效。

## D3. layer-shell 能否精确控制位置

**决策**：用 `LayerShellQt` 的 C++ 静态 API（ctypes 调用），锚 `Top|Right`。

**证据**：
- `wayland-info` 显示 `zwlr_layer_shell_v1` version 5 可用
- Qt6 自带 `liblayer-shell.so` 外壳集成插件，设置 `QT_WAYLAND_SHELL_INTEGRATION=layer-shell` 后生效
- `libLayerShellQtInterface.so.6` 导出 `Window::get(QWindow*)`、`setAnchors`、`setMargins`、`setDesiredSize`
- 实测：`sip.unwrapinstance(widget.windowHandle())` → `Window::get()` 返回**非空句柄**

**曾猜错两处**：
1. 用 `winId()` 当 QWindow 指针 → `get()` 返回空。必须用 `sip.unwrapinstance`。
2. 按 freedesktop 惯例把 Anchor 猜成 `Left=1 Right=2 Top=4 Bottom=8`（右上角 = 6），实测窗口落到**左下角**。Qt 风格是 `Top=1 Bottom=2 Left=4 Right=8`，右上角 = **9**。

**替代方案**：
- 自写 wlr-layer-shell 协议客户端（`pywayland` 已装但缺 `pywayland.protocol` 子模块，不可用）→ 成本高
- `wtype` / `ydotool` 间接挪窗口 → 不可靠且需要额外权限

## D4. 普通窗口为什么不能靠 move() 定位

**结论**：该合成器不接受客户端指定的窗口位置。

**证据**：真实托盘里面板实际落在 `(664, 237)`，而代码算出的是 `(1329, 8)`；`664 = (1707 - 378) / 2`，正是水平居中值。

**曾猜错**：早先用独立探针看到 `pos()` 返回 `(1200, 60)` 就判定「定位生效」。`pos()` 只反映 Qt 自己的记录，不代表窗口实际落点——真实落点只能从合成器读（`kwin-mcp window_geometry`）。

## D5. 托盘图标坐标不可得

**结论**：`QSystemTrayIcon.geometry()` 在 Plasma Wayland 恒返回 `0×0`，`setAnchors` 只能锚屏幕边缘。

**影响与接受理由**：当前用户的 Plasma 面板固定在顶部、托盘在 x 1361–1595，所以「锚屏幕右上角」与「锚图标」结果相同。此限制写入 spec 的 Assumptions 与 Edge Cases。

## D6. 降级路径必须存在

**结论**：`libLayerShellQtInterface.so.6` 缺失、符号缺失、或非 Wayland 会话时，必须退回既有 `move()` 路径，面板仍能显示。

**理由**：本项目的用户群体可能换桌面环境；定位是体验优化，不该成为启动前提。

**实现要点**：`ctypes.CDLL` 调用包在 `try/except OSError` 里；每个符号用 `getattr(lib, name, None)` 探测；任一失败即返回「不可用」，调用方退回旧路径。

## D7. 测试策略

| 可离屏测试 | 必须真实桌面 |
|---|---|
| 缩放换算与钳制 | 色块实测物理像素（SC-001） |
| 锚点坐标计算 | 面板实际 frame（SC-002） |
| 关闭按钮点击 → 不可见 | — |
| 底栏文案三态 | — |
| ctypes 降级（模拟库缺失） | — |

真实桌面验证命令（写入 quickstart.md）：
```
kwin-mcp window_geometry          # 读实际 frame
scripts/check-banner.py 的 capture() + PIL 量色块
```
