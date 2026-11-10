# Tasks: 面板视觉与定位修正

**Input**: Design documents from `/specs/002-panel-visual-polish/`

**Prerequisites**: plan.md（必需）、spec.md（用户故事）、research.md、quickstart.md

**Tests**: 宪章 §II 规定「没有失败的测试就不写生产代码，无例外」，故每个实现任务都以失败测试开头。

**Organization**: 任务按用户故事分组，每个故事可独立实现与验证。

> **2026-11-10 变更**：US2（缩放）经实测撤回，对应任务 T010–T012 已删除，其余任务重编号。
> 撤回理由见 `spec.md` 的 US2「已撤回」一节——基线渲染本来就是 1.5×，人为校正反而错成 2.25×。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可与其他任务并行（不同文件、无未完成依赖）
- **[Story]**: 所属用户故事（US1 / US3 / US4）
- 每条任务附缩进验收子项

## Path Conventions

单项目仓库：托盘代码在 `dsh_tray/`，测试在 `dsh_tray/tests/`，脚本在 `scripts/`。
**仓库路径含 `&`，所有 shell 命令中的路径必须加引号。**

---

## Phase 1: Setup（共享基础）

**Purpose**: 补齐平台层契约

- [x] T001 在 `dsh_tray/platform/base.py` 新增 `PanelPlacement` Protocol
  - [x] 含 `apply(widget, width, height, screen) -> bool`
  - [x] `@returns` 说明「成功锚定 True，不可用 False，调用方退回既有路径」
  - [x] 加入 `dsh_tray/platform/__init__.py` 的导入与 `__all__`
  - [x] ~~`DisplayScale`~~ 已随 US2 撤回删除

- [x] T002 在 `dsh_tray/platform/__init__.py` 新增工厂函数
  - [x] `create_placement()` → Linux 返回 `LinuxPanelPlacement`，其它抛 `_unsupported("面板定位")`
  - [x] 顺带把 `LinuxActionListener` 也收进工厂（`create_action_listener()`），消除 `tray.py` 里对 `platform.linux` 的直接导入
  - [x] 既有测试全绿

**检查点**: 平台契约可导入 → 各故事可开始

---

## Phase 2: Foundational（阻塞性前置）

**Purpose**: 把状态文案抽成纯函数，供标题行与底栏共用

**⚠️ 关键**: 本阶段完成前，US3 与 US4 无法开始

- [x] T003 在 `dsh_tray/tests/test_status.py` 写状态文案的失败测试
  - [x] 五种状态各一条断言，`status_text` 返回短语且**不含数字**
  - [x] `detail_text` 在「运行·自有」时含 PID、端口、`由托盘启动`、`带令牌`
  - [x] `detail_text` 在「运行·接管」时含 `外部启动`、`无令牌`，且与自有态文本不同
  - [x] `detail_text` 在「未运行」时含端口、不含 `PID`
  - [x] 任何状态的底栏都不为空串
  - [x] 跑测试确认**全部失败**（`ImportError`/`AttributeError`）

- [x] T004 新建 `dsh_tray/ui/status.py` 实现 `status_text()` 与 `detail_text()`
  - [x] `STATUS_TEXT` 映射五种状态
  - [x] `status_text(state: State) -> str`
  - [x] `detail_text(state: State, instance: Instance | None, error: str, port: int) -> str`
  - [x] 运行中时端口取 `instance.port` 而非入参（避免显示与实际服务不一致）
  - [x] T003 的测试全部通过（13 条）

  > **偏离 plan.md**：plan 写的是把两个函数放进 `dsh_tray/ui/control.py`。
  > 实际放进新模块 `status.py`：`control.py` 已有 181 行且职责是「控制区渲染」，
  > 而这两个函数被面板标题行与底栏共用，与 ControlArea 无耦合关系。

**检查点 0**: 文案纯函数可用 → US3 / US4 可开始

---

## Phase 3: User Story 1 - 面板出现在托盘附近而非屏幕中央 (Priority: P1) 🎯 MVP

**Goal**: 面板锚到屏幕右上角

**Independent Test**: 读合成器报告的实际 frame 的 x；应 > 屏幕逻辑宽度的 3/4

- [x] T005 [P] [US1] 在 `dsh_tray/tests/test_placement.py` 写锚点计算的失败测试
  - [x] 屏幕 1707×1067、面板 378 宽时，预期 x = 1707-378-8 = 1321
  - [x] 面板宽度超过屏幕宽度时，x 钳制为屏幕左边界（不出现负值）
  - [x] 副屏起点非 0 时锚点跟着偏移
  - [x] `right_margin` / `top_margin` 可注入
  - [x] 跑测试确认失败

- [x] T006 [P] [US1] 在 `dsh_tray/tests/test_placement.py` 追加降级路径测试
  - [x] 层外壳不可用时 `apply()` 返回 `False` 且不抛异常
  - [x] `widget.windowHandle()` 为 `None` 时返回 `False`
  - [x] 控件没有 `windowHandle` 方法时返回 `False`
  - [x] 跑测试确认失败

- [x] T007 [US1] 新建 `dsh_tray/platform/layershell.py`：LayerShellQt 的 ctypes 绑定
  - [x] 常量 `ANCHOR_TOP = 1`、`ANCHOR_RIGHT = 8`、`ANCHOR_TOP_RIGHT = 9`（**Qt 风格，非 freedesktop**；注释写明曾按 6 猜错落到左下角）
  - [x] `QMargins` 与 `QSize` 用 `ctypes.Structure`
  - [x] `load() -> LayerShell | None`：`OSError` 或符号缺失均返回 `None`
  - [x] `use_layer_shell()`：符号 `_ZN12LayerShellQt5Shell13useLayerShellEv`，注释写明必须在 `QApplication` 创建前调用
  - [x] `window_get()` / `set_anchors()` / `set_margins()` / `set_desired_size()`
  - [x] **`setDesiredSize` 必须传 `QSize*`**（`const QSize&`），按值传 `(c_int, c_int)` 会段错误
  - [x] T006 的降级测试通过

- [x] T008 [US1] 在 `dsh_tray/platform/linux.py` 实现 `LinuxPanelPlacement`
  - [x] `apply(widget, width, height, screen) -> bool`，前置检查集中在 `_apply_native()`
  - [x] QWindow 指针取 `sip.unwrapinstance(widget.windowHandle())`——**不能用 `winId()`**（注释写明实测返回空）
  - [x] `target_rect(geometry, width)` 公开，供测试验算
  - [x] 锚 `ANCHOR_TOP_RIGHT`，边距 `(0, top_margin, right_margin, 0)`
  - [x] T005 的测试通过

- [x] T009 [US1] 在 `dsh_tray/ui/panel.py` 加 `apply_placement()` 并在 `dsh_tray/ui/tray.py` 接线
  - [x] `Panel.apply_placement(placement) -> bool`，在 `show()` **之后**调用（层外壳需窗口已创建）
  - [x] 捕获 `RuntimeError`/`ValueError`/`OSError` 后返回 `False`，定位失败不影响面板显示
  - [x] `TrayApp.__init__` 构造 `self._placement = create_placement()`，`NotImplementedError` 时置 `None`
  - [x] `toggle_panel()` 在 `panel.show_at()` 后调 `panel.apply_placement(self._placement)`
  - [x] 离屏测试通过

- [x] T010 [US1] 真实桌面验证定位
  - [x] 起 200×120 探针窗口锚 `Top|Right`，截图量物理像素
  - [x] **实测**：物理 x 2250–2547 → 逻辑 x = 1500，期望 1499 ✓
  - [x] 失败特征记录：x ≈ 664 说明仍在走 `move()` 旧路径（水平居中值）

**检查点 A**: 定位完成并真机验证 → US1 可交付

---

## Phase 4: User Story 3 - 面板有关闭按钮 (Priority: P3)

**Goal**: 标题栏右侧一个可见按钮，点击收起面板且不退出应用

**Independent Test**: 点击按钮后 `panel.isVisible()` 为 False，托盘进程仍存活

- [x] T011 [P] [US3] 在 `dsh_tray/tests/test_panel_chrome.py` 写关闭按钮的失败测试
  - [x] `panel.close_button` 存在且可见
  - [x] 光标为 `PointingHandCursor`
  - [x] 点击后 `panel.isVisible()` 为 False
  - [x] 按钮中心位于面板右半侧
  - [x] **SC-003**：用 `time.monotonic()` 量点击到不可见的耗时，断言 < 0.2s
  - [x] 点击后应用未退出
  - [x] 跑测试确认失败

- [x] T012 [US3] 在 `dsh_tray/ui/panel.py` 实现关闭按钮
  - [x] `QPushButton` + `setFlat(True)`
  - [x] 图标用 `QStyle.StandardPixmap.SP_TitleBarCloseButton`（不引新资源文件）
  - [x] `setIconSize(QSize(14, 14))`、`setFixedSize(22, 22)`、`PointingHandCursor`
  - [x] 点击接 `self.hide()`——**不调 `QApplication.quit()`**（FR-010）
  - [x] 与 `_missed` 提示共存：按钮在最右，提示在它左边
  - [x] T011 的测试通过

**检查点 B**: 关闭按钮可用

---

## Phase 5: User Story 4 - 状态与细节信息分层展示 (Priority: P3)

**Goal**: 标题行只留状态，PID/端口/来源/令牌落到底栏一行

**Independent Test**: 读面板文本，标题行不含数字，底栏四项齐全

- [x] T013 [US4] 在 `dsh_tray/tests/test_panel_chrome.py` 追加底栏的失败测试
  - [x] 面板有 `footer` 且可见
  - [x] 运行态含 `PID`、`端口`、`由托盘启动`、`带令牌`
  - [x] 未运行时不含 `PID`
  - [x] 接管态含 `外部启动` 与 `无令牌`
  - [x] 标题行显示状态且不含 PID
  - [x] 标题行与底栏结论一致（FR-016）
  - [x] 底栏高度计入面板总高
  - [x] 跑测试确认失败

- [x] T014 [US4] 在 `dsh_tray/ui/panel.py` 加底栏并调整标题行
  - [x] `self.footer = QLabel()`，`objectName="panelFooter"`，次要色
  - [x] 标题行 `_title` 初值改为 `"DSH"`，由 `set_status()` 驱动
  - [x] 新增 `set_status(state, instance, error, port)` 统一驱动两处，内部调 `apply_height()`
  - [x] 新增 `title_text` 只读属性供测试断言
  - [x] `apply_height()` 累加 `_footer_height()`，用 `sizeHint()` 实测而非写死
  - [x] T013 的测试通过

- [x] T015 [US4] 在 `dsh_tray/ui/tray.py` 接线
  - [x] `_refresh_panel()` 里调 `panel.set_status(state, instance, last_error, self._lifecycle.port)`
  - [x] 与 `control.render()` 读同一对 `state`/`instance`，不各自推导（FR-016）
  - [x] 既有 `_StubLifecycle` 补 `port` 属性
  - [x] 全量测试通过

- [x] T016 [US4] 真实桌面验证界面
  - [x] 起面板并 OCR 全屏
  - [x] **实测读到**：`DSH 运行中` / `PID 4512 · 端口 3080 · 由托盘启动 · 带令牌`

**检查点 C**: 三片全部完成

---

## Phase 6: Polish & 收尾

- [ ] T017 [P] 真机验收：降级路径（SC-005）
  - [ ] 临时改名 `/usr/lib/x86_64-linux-gnu/libLayerShellQtInterface.so.6` 后重启托盘
  - [ ] 面板仍能打开与关闭，`~/.local/state/dsh-tray/tray.log` 无异常栈
  - [ ] 恢复库文件后确认恢复正常定位

- [ ] T018 更新 `docs/design.md` 与 `README.md` 的已知限制
  - [ ] 写明 `dsh_tray/platform/linux.py` 拿不到托盘图标坐标 → 锚屏幕右上角
  - [ ] 写明多显示器下在主屏右上角（`apply_placement()` 用 `self.screen()`，降级路径用 `resolve_screen()`）
  - [ ] 写明 **不要设 `QT_SCALE_FACTOR`**——实测基线已是 1.5×，设了会变 2.25×
  - [ ] 保留 `scripts/probe-scale.py` 作为回归工具，说明用法

- [x] T019 跑三条基线并记录
  - [x] Python：**259 passed**（基线 224 + 新增 35）
  - [x] 插件：**131 pass / 0 fail**（本特性不动 `plugin/`）
  - [x] `--selftest`：**10 PASS / 0 FAIL**

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 Setup（T001–T002）**：无依赖
- **Phase 2 Foundational（T003–T004）**：**阻塞 US3 与 US4**
- **US1（T005–T010）**：依赖 T001/T002
- **US3（T011–T012）**：依赖 T003/T004
- **US4（T013–T016）**：依赖 T003/T004
- **Polish（T017–T019）**：依赖全部

### 实际执行顺序

用户指示「先做定位」，故实际顺序为：

```
T001 → T002 → T005 → T006 → T007 → T008 → T009 → T010（定位，已真机验证）
     → T003 → T004 → T011 → T012（关闭按钮）
     → T013 → T014 → T015 → T016（底栏）
     → T017 → T018 → T019（收尾）
```

与 plan.md 的「V5 定位排最后」不同——那是按技术风险排的；用户选择先见效，且定位与
US3/US4 无文件冲突，两者顺序可任意。

### 检查点

| 检查点 | 覆盖任务 | 验收 |
|---|---|---|
| 检查点 0 | T001–T004 | 平台契约可导入；文案纯函数 13 条通过 |
| **检查点 A** | T005–T010 | 定位真机验证 x=1500（期望 1499） |
| **检查点 B** | T011–T012 | 关闭按钮可收面板，200ms 内 |
| **检查点 C** | T013–T016 | 标题行与底栏 OCR 验证 |

### 与 plan.md 的差异

| plan.md | tasks.md 实际 | 原因 |
|---|---|---|
| V3 缩放切片（T4–T5） | **已撤回** | 实测基线已正确，见 spec.md US2 |
| 文案函数放 `control.py` | 新建 `ui/status.py` | `control.py` 职责是控制区渲染，两函数与它无耦合 |
| V5 定位最后 | 定位最先 | 用户指示 |

---

## 并行机会

- T005 与 T006 同文件，**不可并行**
- T011 与 T013 同文件（`test_panel_chrome.py`），**不可并行**
- US1 与 US3/US4 无文件冲突，**可并行**（不同人做时）

---

## Notes

- [P] 任务 = 不同文件、无未完成依赖
- 每条任务以独立 commit 结束，遵循 Conventional Commits
- 真机验收（T010/T016/T017）无法离屏完成，必须在真实桌面会话执行
- 基线值：Python 224 / 插件 131 / 自检 10；当前 Python 已 259（+35）
