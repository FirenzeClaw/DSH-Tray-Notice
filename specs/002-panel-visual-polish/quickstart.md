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

**基线值**（改动前）：Python 224 / 插件 131 / 自检 10；**改动后** Python 259。

## 1. 缩放（SC-001）— 已达成，无需改动

**结论**：基线渲染已是 1.5×。三处独立实测（真实面板 1.49、探针窗口 1.50、屏幕整体 1.50）
互相印证。**不要在启动脚本里设 `QT_SCALE_FACTOR`**——实测会让渲染变成 2.25×。

回归工具（将来若怀疑有偏差时用它一测）：
```bash
DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus QT_QPA_PLATFORM=wayland \
  python3 scripts/probe-scale.py --out /tmp/scale.png --expect 1.5
```
退出码 0 = 一致、1 = 不一致、2 = 环境不满足。

## 2. 面板定位（SC-002）— 已验证通过

`kwin-mcp` 在本机常返回 `Connection closed`，故用截图法：起一个已知尺寸与颜色的
探针窗口，锚 `Top|Right`，截图后数像素。

```bash
# 探针：200×120 纯绿窗口，layershell 锚右上角，保持 12 秒
DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus \
QT_QPA_PLATFORM=wayland PYTHONPATH="$PWD" python3 /tmp/probe-hold.py &
sleep 5
spectacle -b -n -f -o /tmp/hold.png
# 用 PIL 数绿色范围，除以 1.5 得逻辑坐标
```

**实测结果**：绿色窗口物理范围 `x 2250–2547` → 逻辑 `x = 1500`。
期望 `1707 - 200 - 8 = 1499`。**偏差 1 像素，通过。**

**失败特征**：逻辑 x ≈ 664 —— 那正是 `(1707-378)/2`，说明仍在走 `move()` 旧路径。

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

## 4. 标题行 / 底栏（SC-004）— 已验证通过

**自动**：断言 `status_text()` 与 `detail_text()` 的三种状态文案。

**人工**：打开面板，全屏 OCR：
```bash
tesseract /tmp/panel.png stdout -l chi_sim+eng --psm 11 | grep -E "DSH|PID|端口"
```
**实测读到**（2026-11-10）：
```
DSH 运行中
PID 4512 - 端口 3080 - 由托盘启动 . 带令牌
```
四项齐全，**未换行截断**。

## 5. 回归

- [ ] Python 224 + 新增用例全绿
- [ ] 插件 131 全绿（本特性不动插件，应零变化）
- [ ] `--selftest` 10/10
- [ ] 通知仍能弹出（注入一条 spool 事件，OCR 能看到横幅文字）
- [ ] 四个标签页仍可切换

## 已知限制（不算缺陷）

- 托盘图标坐标不可得 → 面板锚屏幕右上角；把 Plasma 面板移到底部后不再贴近图标。
- 多显示器下出现在主屏右上角，不是图标所在屏。
- **不要设 `QT_SCALE_FACTOR`**：实测基线已是 1.5×，设了会让元素放大到 2.25×。
