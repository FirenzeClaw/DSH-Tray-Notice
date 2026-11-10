# 验收走查：面板视觉与定位

**Date**: 2026-11-09 | **Feature**: 002-panel-visual-polish

本文是**可执行的验收步骤**，每条都给出判定依据。自动化能覆盖的部分标「自动」，必须在真实桌面看的标「人工」。

## 前置

```bash
cd "/home/firenzeclaw/Code/DSH-Tray&Notice"     # 路径含 &，必须加引号

# 三条基线（改动前后各跑一次）
QT_QPA_PLATFORM=offscreen python3 -m unittest discover -s dsh_tray/tests -t .
(cd plugin && npm test)
./dsh-tray.py --selftest
```

**基线值**（改动前）：Python 224 / 插件 131 / 自检 10。

## 1. 缩放校正（SC-001）

**自动**：单测覆盖换算与钳制。
```bash
QT_QPA_PLATFORM=offscreen python3 -m unittest dsh_tray.tests.test_scaling -v
```

**人工**（唯一能证明「真的按 1.5 渲染」的方法）：

1. 启动托盘（必须在 DSH 作用域外，否则被守卫拒绝）：
   ```bash
   systemd-run --user --scope --unit=dsh-tray-check ./scripts/dsh-tray.sh
   ```
2. 用探针画一个 100 逻辑像素宽的纯色块（`QPainter.fillRect(QRect(0,0,100,40))`）。
3. 截图并量物理像素：
   ```bash
   python3 - <<'PY'
   from PIL import Image
   im = Image.open("/tmp/probe.png").convert("RGB")
   # 找纯色块的边界（改为你的颜色）
   ys = [y for y in range(im.height) if im.getpixel((im.width//2, y)) == (255,0,255)]
   print("物理高度:", len(ys))
   PY
   ```
4. **判定**：物理宽度应为 **150 ± 1**。若为 200，说明校正未生效（仍在按 2× 渲染）。

## 2. 面板定位（SC-002）

**人工**（`move()` 的返回值不可信，必须读合成器）：

1. 点击托盘图标打开面板。
2. 读实际窗口位置：
   ```bash
   # 用 kwin-mcp
   mcp__kwin-mcp__window_geometry({"app_name": "dsh-tray"})
   ```
3. **判定**：
   - x 应接近 `屏幕逻辑宽 - 378 - 8`。本机逻辑宽 1707 → 期望 x ≈ **1321**
   - **不通过的特征**：x ≈ 664（恰好居中，说明仍走旧路径）
   - y 应 ≈ 8～40（避开顶部面板）

**降级验证**（SC-005）：

```bash
# 临时改名让库不可用，面板仍应能打开
sudo mv /usr/lib/x86_64-linux-gnu/libLayerShellQtInterface.so.6{,.bak}
# 重启托盘 → 点图标 → 面板应出现在合成器默认位置，不报错
sudo mv /usr/lib/x86_64-linux-gnu/libLayerShellQtInterface.so.6{.bak,}
```

## 3. 关闭按钮（SC-003）

**自动**：离屏断言点击后 `panel.isVisible()` 为 False。

**人工**：
1. 打开面板，点击标题栏右上角关闭按钮。
2. **判定**：面板消失，托盘图标仍在，`ps` 能看到托盘进程存活。

## 4. 顶栏 / 底栏（SC-004）

**自动**：断言 `status_text()` 与 `detail_text()` 的三种状态文案。

**人工**：打开面板，OCR 底部一行：
```bash
tesseract /tmp/panel.png stdout -l chi_sim+eng --psm 6 | tail -3
```
**判定**：能看到 `PID <数字>`、`端口 3080`、`由托盘启动`/`外部启动`、`带令牌`/`无令牌` 四项，且**不换行截断**。

## 5. 回归

- [ ] Python 224 + 新增用例全绿
- [ ] 插件 131 全绿（本特性不动插件，应零变化）
- [ ] `--selftest` 10/10
- [ ] 通知仍能弹出（注入一条 spool 事件，OCR 能看到横幅文字）
- [ ] 四个标签页仍可切换

## 已知限制（不算缺陷）

- 托盘图标坐标不可得 → 面板锚屏幕右上角；把 Plasma 面板移到底部后不再贴近图标。
- 多显示器下出现在主屏右上角，不是图标所在屏。
- 改变缩放需重启托盘才生效（`QT_SCALE_FACTOR` 只在启动时读）。
