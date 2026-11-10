# Tasks: 面板视觉与定位修正

**Input**: Design documents from `/specs/002-panel-visual-polish/`

**Prerequisites**: plan.md（必需）、spec.md（用户故事）、research.md、quickstart.md

**Tests**: 本规格的宪章 §II 规定「没有失败的测试就不写生产代码，无例外」，故每个实现任务都以失败测试开头。

**Organization**: 任务按用户故事分组，每个故事可独立实现与验证。切片划分与检查点位置严格对齐 plan.md 的 Implementation Strategy 节。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可与同阶段其他任务并行（不同文件、无未完成依赖）
- **[Story]**: 所属用户故事（US1–US4）
- 每条任务附缩进验收子项，执行者无需翻阅其他任务即可判断完成

## Path Conventions

单项目仓库：托盘代码在 `dsh_tray/`，测试在 `dsh_tray/tests/`，启动脚本在 `scripts/`。所有路径相对仓库根。

**注意**：仓库路径含 `&`，所有 shell 命令中的路径必须加引号。

---

## Phase 1: Setup（共享基础）

**Purpose**: 补齐平台层契约，让后续四个故事都有可依赖的接口定义

- [ ] T001 在 `dsh_tray/platform/base.py` 新增两个 Protocol
  - [ ] `DisplayScale` 含 `real_scale() -> float` 方法，docstring 说明「真实输出缩放，读不到时返回 1.0」
  - [ ] `PanelPlacement` 含 `apply(widget: object, width: int, height: int, screen: object) -> bool` 方法，`@returns` 说明「成功锚定返回 True，不可用返回 False」
  - [ ] 两个 Protocol 追加到 `__all__`
  - [ ] `QT_QPA_PLATFORM=offscreen python3 -c "from dsh_tray.platform.base import DisplayScale, PanelPlacement"` 退出码 0

- [ ] T002 在 `dsh_tray/platform/__init__.py` 新增两个工厂函数
  - [ ] `create_display_scale()` → Linux 返回 `LinuxDisplayScale`，其它抛 `_unsupported("显示缩放读取")`
  - [ ] `create_placement()` → Linux 返回 `LinuxPanelPlacement`，其它抛 `_unsupported("面板定位")`
  - [ ] 两个名字加入 `__all__`
  - [ ] 既有测试 224 条仍全绿

---

## Phase 2: Foundational（阻塞性前置）

**Purpose**: 把状态文案抽成纯函数。四个故事里有三个要消费这些文案，必须先有稳定输入

**⚠️ 关键**: 本阶段完成前，US3 与 US4 无法开始

- [ ] T003 在 `dsh_tray/tests/test_control_split.py` 写 `status_text()` 与 `detail_text()` 的失败测试
  - [ ] 六种状态各一条断言（`IDLE`/`STARTING`/`RUNNING`/`STOPPING`/`FAILED`），`status_text` 返回短语且不含数字
  - [ ] `detail_text` 在「运行·自有」时含 PID、端口、`由托盘启动`、`带令牌`
  - [ ] `detail_text` 在「运行·接管」时含 `外部启动`、`无令牌`
  - [ ] `detail_text` 在「未运行」时含端口、不含 `PID`
  - [ ] 跑测试确认**全部失败**（`ImportError` 或 `AttributeError`）

- [ ] T004 在 `dsh_tray/ui/control.py` 实现 `status_text()` 与 `detail_text()` 两个模块级纯函数
  - [ ] `status_text(state: State) -> str`，映射见 plan.md「底栏与顶栏文案」表
  - [ ] `detail_text(state: State, instance: object | None, error: str, port: int) -> str`
  - [ ] `render()` 改为调用这两个函数，**输出与改动前逐字符相同**（这是回归保障）
  - [ ] T003 的测试全部通过
  - [ ] 既有控制区相关测试不回退

**检查点 0**: 文案纯函数可用 → US3 / US4 可开始（plan.md 无此检查点，属 Phase 2 的交付门）

---

## Phase 3: User Story 1 - 面板出现在托盘附近而非屏幕中央 (Priority: P1) 🎯 MVP

**Goal**: 面板锚到屏幕右上角，而不是合成器随意放置的中央位置

**Independent Test**: 打开面板后读合成器报告的实际 frame 的 x 坐标；x 应 > 屏幕逻辑宽度的 3/4

### Tests for User Story 1

- [ ] T005 [P] [US1] 在 `dsh_tray/tests/test_placement.py` 写锚点计算的失败测试
  - [ ] 屏幕 1707×1067、面板 378 宽时，预期 x = 1707-378-8 = 1321
  - [ ] 面板宽度超过屏幕宽度时，x 钳制为 8（不出现负值）
  - [ ] y 恒为顶部边距 8
  - [ ] `right_margin` / `top_margin` 可注入以便断言
  - [ ] 跑测试确认失败

- [ ] T006 [P] [US1] 在 `dsh_tray/tests/test_placement.py` 追加降级路径测试
  - [ ] 模拟库不可用（`ctypes.CDLL` 抛 `OSError`）时 `apply()` 返回 `False` 且不抛异常
  - [ ] 模拟符号缺失（`getattr` 取不到）时返回 `False`
  - [ ] `widget.windowHandle()` 为 `None` 时返回 `False`
  - [ ] 跑测试确认失败

- [ ] T007 [US1] 新建 `dsh_tray/platform/layershell.py`：LayerShellQt 的 ctypes 绑定
  - [ ] 常量 `ANCHOR_TOP = 1`、`ANCHOR_RIGHT = 8`、`ANCHOR_TOP_RIGHT = 9`（**Qt 风格，非 freedesktop**，注释写明曾按 6 猜错）
  - [ ] `QMargins` 用 `ctypes.Structure`（`_fields_ = [("left", c_int), ("top", c_int), ("right", c_int), ("bottom", c_int)]`）
  - [ ] `load() -> object | None`：`ctypes.CDLL("libLayerShellQtInterface.so.6")`，`OSError` 返回 `None`
  - [ ] `window_get(lib, qwindow_ptr) -> int`：符号 `_ZN12LayerShellQt6Window3getEP7QWindow`
  - [ ] `set_anchors(lib, handle, anchors)`、`set_margins(lib, handle, margins)`、`set_desired_size(lib, handle, w, h)`
  - [ ] 每个符号用 `getattr(lib, name, None)` 探测，缺任一即整体返回不可用
  - [ ] T006 的降级测试通过

- [ ] T008 [US1] 在 `dsh_tray/platform/linux.py` 实现 `LinuxPanelPlacement`
  - [ ] `apply(widget, width, height, screen)`：取 `screen.geometry()`，算 x/y，调 layershell
  - [ ] QWindow 指针取 `sip.unwrapinstance(widget.windowHandle())`——**不能用 `winId()`**（注释写明实测返回空）
  - [ ] 计算 x 时取 `screen.width() - width - right_margin`，下限 0
  - [ ] T005 的测试通过

- [ ] T009 [US1] 在 `dsh_tray/ui/panel.py` 加 `apply_placement(placement)` 方法并在 `dsh_tray/ui/tray.py` 接线
  - [ ] `Panel.apply_placement(placement: object) -> bool`：`show()` 之后调用，成功返回 True
  - [ ] 失败时退回既有 `move()` 路径，不抛异常
  - [ ] `tray.py` 的 `toggle_panel()` 在 `_panel.show()` 后调用 `self._panel.apply_placement(self._placement)`
  - [ ] `TrayApp.__init__` 构造 `self._placement = create_placement()`，构造失败时置 `None`
  - [ ] 离屏测试：`apply_placement(None)` 不抛异常

**检查点 A**（对应 plan.md「检查点 A（T1–T3 之后）」）: V1 状态分层 + V2 关闭按钮完成（T003/T004/T013/T014）
- [ ] `QT_QPA_PLATFORM=offscreen python3 -m unittest discover -s dsh_tray/tests -t .` 全绿
- [ ] 离屏断言：顶栏文本不含 PID/端口；点击关闭后 `panel.isVisible()` 为 False
- [ ] 既有 224 条基线不回退

---

## Phase 4: User Story 2 - 界面元素尺寸与实际缩放一致 (Priority: P2)

**Goal**: 按 1.5 输出缩放渲染，而非框架误报的 2.0

**Independent Test**: 面板内 100 逻辑像素色块实测 150 物理像素（±1）

- [ ] T010 [P] [US2] 在 `dsh_tray/tests/test_scaling.py` 写缩放读取的失败测试
  - [ ] 读到 `1.5` 时 `real_scale()` 返回 `1.5`
  - [ ] 读到空串 / 非数字 / `0` / `-1` / `5.0` 时返回 `1.0`
  - [ ] `kreadconfig6` 不存在时返回 `1.0` 且不抛异常
  - [ ] 跑测试确认失败

- [ ] T011 [US2] 在 `dsh_tray/platform/linux.py` 实现 `LinuxDisplayScale`
  - [ ] `real_scale()` 调 `kreadconfig6 --file kwinrc --group Xwayland --key Scale`
  - [ ] 用 `subprocess.run(..., timeout=2, check=False)`，非零退出或超时返回 `1.0`
  - [ ] 解析出的浮点钳制到 `0.5–4.0`，越界返回 `1.0`
  - [ ] T010 的测试通过

- [ ] T012 [US2] 在 `scripts/dsh-tray.sh` 的 `exec` 之前注入 `QT_SCALE_FACTOR`
  - [ ] 读 `kreadconfig6 --file kwinrc --group Xwayland --key Scale`，`|| true` 兜底
  - [ ] 用 `case` 做格式校验（`''|*[!0-9.]*` 归为 1.0）
  - [ ] 用 `awk -v s=... 'BEGIN{exit !(s>1.0 && s<4.0)}'` 做浮点比较（**shell 不支持小数比较**，注释写明理由）
  - [ ] `kreadconfig6` 缺失时脚本正常启动，不设变量（用 `PATH=/usr/bin:/bin` 裁剪后手工验证）
  - [ ] `bash -n scripts/dsh-tray.sh` 通过

**检查点 B**（对应 plan.md「检查点 B（T4–T6 之后）」）: V3 缩放校正 + V4 底栏完成（T010–T012/T015–T017）
- [ ] 缩放换算单测覆盖 1.0 / 1.25 / 1.5 / 1.75 / 2.0 与越界值
- [ ] 底栏在三态下文案正确（运行自有 / 未运行 / 接管）
- [ ] `bash -n scripts/dsh-tray.sh` 通过；`kreadconfig6` 缺失时不设变量

---

## Phase 5: User Story 3 - 面板有关闭按钮 (Priority: P3)

**Goal**: 标题栏右侧一个可见按钮，点击收起面板且不退出应用

**Independent Test**: 点击按钮后 `panel.isVisible()` 为 False，托盘进程仍存活

- [ ] T013 [P] [US3] 在 `dsh_tray/tests/test_panel_chrome.py` 写关闭按钮的失败测试
  - [ ] `panel.close_button` 存在且可见
  - [ ] 按钮 `cursor().shape()` 为 `PointingHandCursor`
  - [ ] 调用 `panel.close_button.click()` 后 `panel.isVisible()` 为 False
  - [ ] 按钮矩形位于面板右半侧（`x > panel.width() / 2`）
  - [ ] 跑测试确认失败

- [ ] T014 [US3] 在 `dsh_tray/ui/panel.py` 实现关闭按钮
  - [ ] `QPushButton` 无边框 + `setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_TitleBarCloseButton))`
  - [ ] `setIconSize(QSize(14, 14))`、`setCursor(Qt.CursorShape.PointingHandCursor)`
  - [ ] 点击接 `self.hide()`——**不调 `QApplication.quit()`**（FR-013）
  - [ ] 与 `_missed` 提示共存：提示右边界让出按钮宽度
  - [ ] 关闭后不被立刻重新显示（既有 `_hide_if_inactive` 不受影响，验证无重入）
  - [ ] T013 的测试通过

**说明**: V5 定位（T005–T009）排在 US3/US4 之后执行——见「Implementation Strategy」的执行顺序。本 Phase 的关闭按钮在检查点 A 验收，底栏在检查点 B 验收。

---

## Phase 6: User Story 4 - 状态与细节信息分层展示 (Priority: P3)

**Goal**: 顶栏只留状态，PID/端口/来源/令牌落到底栏一行

**Independent Test**: 读面板文本，顶栏不含数字，底栏四项齐全且不截断

- [ ] T015 [US4] 在 `dsh_tray/tests/test_panel_chrome.py` 追加底栏的失败测试
  - [ ] 面板有 `footer` 且可见
  - [ ] `footer.text()` 在运行态含 `PID`、`端口`、`由托盘启动`、`带令牌`
  - [ ] 未运行时 `footer.text()` 不含 `PID`
  - [ ] 接管态 `footer.text()` 含 `外部启动` 与 `无令牌`
  - [ ] 跑测试确认失败

- [ ] T016 [US4] 在 `dsh_tray/ui/panel.py` 加底栏并调整顶栏
  - [ ] 顶栏 `_title` 文本改为只用 `status_text()` 的结果（不再拼 URL）
  - [ ] 新增 `self.footer = QLabel()`，样式与既有 `_meta` 一致（小字号、次要色）
  - [ ] `set_control()` 或新增 `set_status(state, instance, error, port)` 统一驱动顶栏与底栏
  - [ ] `apply_height()` 公式累加 `self.footer.sizeHint().height()`，**按实测值累加不写死**（注释说明）
  - [ ] T015 的测试通过
  - [ ] 既有高度相关测试（5 条 630px / 8 条 820px）更新期望值或验证仍成立

- [ ] T017 [US4] 在 `dsh_tray/ui/tray.py` 接线底栏数据
  - [ ] 状态刷新时调用 `panel.set_status(...)` 传 `instance`、`error`、`port`
  - [ ] 离屏测试：三态各调用一次不抛异常
  - [ ] 接管态与正常态的底栏文本不同（FR-018 的可区分性）

**检查点 C**（对应 plan.md「检查点 C（T7–T10 之后）」）: V5 定位完成 + 真机验收（T005–T009/T018–T022）
- [ ] `kwin-mcp window_geometry` 读出面板 frame 的 x > 屏幕宽 3/4
- [ ] 100 逻辑像素色块实测 150±1 物理像素
- [ ] layer-shell 库移除时面板仍能显示
- [ ] 三条基线全绿：Python / 插件 131 / `--selftest` 10

---

## Phase 7: Polish & 真机验收

- [ ] T018 [P] 真机验收：缩放色块（SC-001），结果写入 `specs/002-panel-visual-polish/quickstart.md`
  - [ ] 用 `scripts/probe-scale.py`（新建，30 行）渲染 100 逻辑像素纯色块并落盘
  - [ ] `spectacle -b -n -o /tmp/probe.png` 截图
  - [ ] `python3` 用 `PIL` 数纯色行的物理宽度
  - [ ] 实测值落在 `150 ± 1`
  - [ ] 把实测值记入 `specs/002-panel-visual-polish/quickstart.md` 的「实测记录」节

- [ ] T019 真机验收：面板定位（SC-002），结果写入 `specs/002-panel-visual-polish/quickstart.md`
  - [ ] 用 `mcp__kwin-mcp__window_geometry` 读 `dsh_tray/ui/panel.py` 所建面板的 frame
  - [ ] x > 1707 × 3/4 = 1280
  - [ ] **失败特征**：x ≈ 664 说明仍在走 `dsh_tray/ui/panel.py` 的 `move()` 旧路径（那是水平居中值）
  - [ ] 实测坐标记入 quickstart.md

- [ ] T020 [P] 真机验收：降级路径（SC-005），验证 `dsh_tray/platform/layershell.py` 的 `load()` 返回 `None` 时行为
  - [ ] 临时改名 `/usr/lib/x86_64-linux-gnu/libLayerShellQtInterface.so.6` 后重启托盘
  - [ ] 面板仍能打开与关闭，`~/.local/state/dsh-tray/tray.log` 无异常栈
  - [ ] 恢复库文件后确认恢复正常定位

- [ ] T021 更新 `docs/design.md` 与 `README.md` 的已知限制
  - [ ] 写明 `dsh_tray/platform/linux.py` 拿不到托盘图标坐标 → 锚屏幕右上角
  - [ ] 写明多显示器下在主屏右上角
  - [ ] 写明改变缩放需重启托盘（`scripts/dsh-tray.sh` 只在启动时读）

- [ ] T022 跑三条基线并记录到 `specs/002-panel-visual-polish/quickstart.md`
  - [ ] `QT_QPA_PLATFORM=offscreen python3 -m unittest discover -s dsh_tray/tests -t .` 全绿（预期 > 224）
  - [ ] `(cd plugin && npm test)` 131 通过（本特性不动 `plugin/`，应零变化）
  - [ ] `./dsh-tray.py --selftest` 10/10

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 Setup（T001–T002）**：无依赖，立即开始
- **Phase 2 Foundational（T003–T004）**：依赖 T001（类型存在才能标注）；**阻塞 US3 与 US4**
- **US1（T005–T009）**：依赖 T001/T002；不依赖 T003/T004
- **US2（T010–T012）**：依赖 T001/T002；不依赖 T003/T004
- **US3（T013–T014）**：依赖 T003/T004（`status_text` 存在）
- **US4（T015–T017）**：依赖 T003/T004
- **Polish（T018–T022）**：依赖全部四个故事

### User Story Dependencies

- **US1（P1）**：独立。只有它在 T009 触及 `tray.py` 的 `toggle_panel()`
- **US2（P2）**：独立。完全不碰 UI，只碰 `platform/linux.py` 与 shell 脚本
- **US3（P3）**：独立。只碰 `panel.py` 的标题行区域
- **US4（P3）**：与 US3 都改 `panel.py`，但区域不重叠（US3 改标题行右侧，US4 改顶部文本 + 新增底栏）。**若并行需先协调**

### Within Each User Story

- 测试必须先写并确认失败（宪章 §II）
- 绑定层（`layershell.py`）在平台实现（`linux.py`）之前
- 平台实现在使用方（`panel.py` / `tray.py`）之前

### Parallel Opportunities

- T005 与 T006 同文件，**不可并行**
- T010（test_scaling.py）与 T005/T006（test_placement.py）**不同文件，可并行**
- T013 与 T015 同文件（test_panel_chrome.py），**不可并行**
- US1 与 US2 完全独立，**可并行**

---

## Parallel Example: US1 与 US2

```bash
# 两条独立轨道：
# 轨道 A（US1 定位）
QT_QPA_PLATFORM=offscreen python3 -m unittest dsh_tray.tests.test_placement -v

# 轨道 B（US2 缩放）
QT_QPA_PLATFORM=offscreen python3 -m unittest dsh_tray.tests.test_scaling -v
```

---

## Implementation Strategy

### 切片与 plan.md 的对应

| plan.md 切片 | tasks.md 任务 |
|---|---|
| V1 状态文本分层 | T003, T004 |
| V2 关闭按钮 | T013, T014 |
| V3 缩放校正 | T010, T011, T012 |
| V4 底栏 | T015, T016, T017 |
| V5 定位 | T005–T009 |

**执行顺序**（按 plan.md 的「实施顺序」）：T001 → T002 → T003 → T004 → T013 → T014 → T010 → T011 → T012 → T015 → T016 → T017 → T005 → T006 → T007 → T008 → T009 → T018–T022。

**偏离说明**：tasks.md 的 Phase 分组按用户故事（这是 speckit-tasks 的格式要求），而 plan.md 的切片顺序是 V1→V2→V3→V4→V5。两者的映射关系见上表——**同一组任务，两种视角**，不构成偏离。

### 检查点

| 检查点 | 位置（执行顺序） | 覆盖任务 | 验收 |
|---|---|---|---|
| 检查点 0 | V1 之后 | T003, T004 | 纯函数测试通过 |
| **检查点 A** | V1–V2 之后 | T001–T004, T013, T014 | 离屏全绿；顶栏无数字；关闭可收 |
| **检查点 B** | V3–V4 之后 | T010–T012, T015–T017 | 缩放单测；底栏三态；`bash -n` |
| **检查点 C** | V5 + 真机之后 | T005–T009, T018–T022 | frame 的 x > 1280；色块 150±1；降级可用；三基线 |

**与 plan.md 的对应**：plan.md 的检查点 A（T1–T3 后）、B（T4–T6 后）、C（T7–T10 后）是按它的编号 T1–T10 排的；本文件按用户故事重编号为 T001–T022，任务内容一致。本文件的检查点 A 额外包含 US3 的关闭按钮，因为按执行顺序它恰好在缩放之前。

### MVP 范围

**US1（定位）单独就是一个可用 MVP**：它解决最影响使用的问题（面板在中央遮挡内容）。US2/US3/US4 都是观感改进，可分批交付。

但**执行顺序上 US1 排在最后**（plan.md 决定，因为技术风险最高）。这意味着 MVP 不是第一个交付的切片。若需要尽早见效，可把 T005–T009 提前——它们与 T010–T017 无文件冲突。

---

## Notes

- [P] 任务 = 不同文件、无未完成依赖
- 每条任务以独立 commit 结束，遵循 Conventional Commits（`feat(panel):` / `fix(panel):` / `refactor(control):`）
- 真机验收（T018–T020）无法离屏完成，必须在真实桌面会话执行
- 基线值：Python 224 / 插件 131 / 自检 10——任何回退都要停下查因
