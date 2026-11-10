# 面板视觉与定位修正 实现计划

> **面向 AI 代理的工作者：** 使用 subagent-driven-development（推荐）或 executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法跟踪进度。

**Branch**: `002-panel-visual-polish` | **Date**: 2026-11-09 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/002-panel-visual-polish/spec.md`

**目标：** 让托盘面板出现在屏幕右上角而非中央、带一个明确的关闭按钮，并把 PID 等细节从标题行挪到底栏。

**架构：** 新增平台能力 `PanelPlacement`（把面板锚到右上角），放在既有的 `dsh_tray/platform/` 之下，遵循项目既定的「平台分支只出现在那一层」硬约束。面板本身增加底栏、关闭按钮两个纯 Qt 部件，状态文案抽到新模块 `dsh_tray/ui/status.py`。**缩放校正已撤回**——实测基线渲染本来就是 1.5×，人为设 `QT_SCALE_FACTOR` 反而错成 2.25×。

**技术栈：** Python 3.14 + PyQt6 6.10.2（系统 dist-packages，禁 venv）；ctypes 调用 `libLayerShellQtInterface.so.6`；SQLite 无、无新增依赖。

## Summary

四个相互独立、可分别回退的改动：

| # | 改动 | 回退条件 |
|---|---|---|
| 1 | layer-shell 锚定右上角 | 库/协议不可用 → 退回既有 `move()` |
| 2 | 标题栏关闭按钮 | 纯 UI，无回退需求 |
| 3 | 标题行显示状态，新增底栏放细节 | 纯 UI，无回退需求 |

**已撤回**：启动脚本注入 `QT_SCALE_FACTOR`。实测基线已是 1.5×，该改动会让渲染变成 2.25×。

## Technical Context

**Language/Version**: Python 3.14.4（`/usr/bin/python3`，PyQt6 来自 `/usr/lib/python3/dist-packages`，**禁止 venv**）

**Primary Dependencies**:
- PyQt6 6.10.2（现有）
- `libLayerShellQtInterface.so.6`（系统已装 `liblayershellqtinterface6:amd64 6.6.4-0ubuntu1`，经 ctypes 调用，**不新增 pip 依赖**）

**Storage**: 无新增持久化。面板高度/行数已由既有 `tray-settings` spool 行承载。

**Testing**: `QT_QPA_PLATFORM=offscreen python3 -m unittest discover -s dsh_tray/tests -t .`（当前 224 条）；真实桌面验证用 `scripts/check-banner.py` 的截图与 OCR 能力 + `kwin-mcp window_geometry` 读实际 frame。

**Target Platform**: Linux / KDE Plasma 6 / Wayland（开发机）。其它平台走退化路径。

**Project Type**: 桌面托盘应用（Python + PyQt6），双语言仓库（托盘 Python / DSH 插件 TypeScript）。

**Performance Goals**: 面板打开 ≤ 300ms；关闭 ≤ 200ms（SC-003）。定位在面板 `show()` 时一次性完成，不进入轮询路径。

**Constraints**:
- 平台分支只允许出现在 `dsh_tray/platform/`（AGENTS.md 硬约束 3）
- 不新增 pip 依赖
- **不要设 `QT_SCALE_FACTOR`**：实测基线渲染已是 1.5×，设 1.5 会变成 2.25×
- 托盘图标坐标在 Plasma Wayland 恒为 `0×0`，定位不得依赖它

**Scale/Scope**: 4 个功能改动，涉及 2 个新模块 + 3 个既有模块修改 + 1 个启动脚本修改。无数据库、无网络、无 API。

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| 原则 | 本计划的合规情况 |
|---|---|
| **I 简单性优先** | 新增两个模块职责单一。撤回缩放缓片后，代码里没有任何「为可能存在的偏差预先补偿」的逻辑——没有偏差就不写代码。拒绝为「记住拖动位置」等未提需求加复杂度。 |
| **II 测试先行** | 每个任务以失败测试开头，且实际验过 RED（定位 7 条、文案 13 条、外框 15 条均先失败后通过）。锚点计算、关闭按钮、底栏文案都可在离屏断言；layer-shell 的真实落点标注为「需真实桌面验证」并给出测量方法。 |
| **III 安全无例外** | 无密钥、无认证、无外部输入解析。读 `kwinrc` 仅取一个浮点数并做范围校验（0.5–4.0），越界按 1.0 处理。ctypes 调用前用 `hasattr` 探测符号存在性。 |
| **IV 原子提交与主干开发** | 四个改动各自独立提交，每个提交自带测试。UI 改动（3、4）与能力改动（1、2）分开。 |
| **V 不审查不合并** | 计划经用户审查后执行；实现完成后跑三条基线。 |
| **VI 可读性与显式契约** | `PanelPlacement` 的 Protocol 定义放在 `platform/base.py`，与既有三组契约并列。状态文案的契约是 `status.py` 的两个函数签名。 |

**结论**：无违规，无需 Complexity Tracking。

## Project Structure

### Documentation (this feature)

```text
specs/002-panel-visual-polish/
├── plan.md              # 本文件
├── research.md          # Phase 0 输出：ctypes 契约与定位的实测结论（含缩放的撤回依据）
├── quickstart.md        # Phase 1 输出：真实桌面验收步骤
└── tasks.md             # /speckit-tasks 生成
```

无 `data-model.md`：本特性不引入新数据实体（位置是算出的坐标，不落盘）。
无 `contracts/`：不新增跨进程接口——定位与界面改动都在托盘进程内部。

### Source Code (repository root)

```text
dsh_tray/
├── platform/
│   ├── base.py                 # [修改] 新增 PanelPlacement Protocol
│   ├── __init__.py             # [修改] 新增 create_display_scale() / create_placement()
│   ├── linux.py                # [修改] LinuxPanelPlacement
│   └── layershell.py           # [新增] LayerShellQt 的 ctypes 绑定（纯机制，不含业务判断）
├── ui/
│   ├── status.py                # [修改] 关闭按钮、底栏、apply_placement()；高度重算含底栏
│   ├── control.py              # [修改] render() 拆出 status_text() / detail_text() 两个纯函数
│   └── tray.py                 # [修改] 打开面板时调用 apply_placement()
└── tests/
    ├── test_status.py          # [新增] 标题行与底栏文案
    ├── test_panel_chrome.py    # [新增] 关闭按钮与底栏
    ├── test_placement.py       # [新增] 锚点计算与降级
    ├── test_panel_chrome.py    # [新增] 关闭按钮、底栏文案、高度含底栏
    └── test_status.py          # [新增] status_text / detail_text 的文案与状态映射

scripts/
└── dsh-tray.sh                 # [不变]
```

**Structure Decision**: 沿用既有的「平台能力在 `platform/`、Qt 部件在 `ui/`、平台分支只在 `platform/`」分层。新增的 `layershell.py` 单独成文件而不是塞进 `linux.py`，因为它是纯粹的 ctypes 协议绑定（没有任何业务判断），与 `linux.py` 里读配置、算坐标的逻辑职责不同；这样 `linux.py` 保持可读，绑定层也可独立测试其降级行为。

## Dependency Graph

```
platform/base.py (新增 PanelPlacement Protocol)
        │
        ├── platform/layershell.py (ctypes 绑定，无业务逻辑)
        │           │
        │           └── platform/linux.py::LinuxPanelPlacement
        │                       │
        └── platform/__init__.py::create_placement()
                                │
                        ui/panel.py::apply_placement
                                │
                        ui/tray.py (打开面板时调用)

ui/status.py::status_text / detail_text (纯函数，无依赖)
                    │
        ui/panel.py (标题行用 status_text，底栏用 detail_text)
```

**实施顺序**：Protocol → 定位 → 纯函数 → 关闭按钮 → 底栏。

原计划把定位放最后（技术风险最高，失败时前面几片仍可用）。**实际按用户指示改为最先做定位**——它与其余部分无文件冲突，且是最影响日常使用的一条。缩放切片已撤回。

## Implementation Strategy

### 垂直切片划分

本特性是单一关注点（面板外观与定位）下的三个独立改动，不存在「schema + API + UI」式的横向依赖。按「先能力、后呈现」切片：

| 切片 | 端到端路径 | 交付物 | 状态 |
|---|---|---|---|
| **V1 状态文本分层** | `status.py` 纯函数 → `panel.py` 用它填标题行 → 测试断言文案 | 标题行显示状态；为 V3 铺路 | 已完成 |
| **V2 关闭按钮** | `panel.py` 加按钮 → 接 `hide()` → 测试断言 200ms 内不可见 | 用户能明确关闭面板 | 已完成 |
| ~~V3 缩放校正~~ | ~~`linux.py` 读缩放 → 启动脚本 export → 色块实测~~ | ~~元素尺寸与真实缩放一致~~ | **已撤回** |
| **V3 底栏** | `status.py` 的 `detail_text()` → `panel.py` 底栏 → 高度重算含底栏 | PID/端口等落到底栏 | 已完成 |
| **V4 定位** | `layershell.py` 绑定 → `LinuxPanelPlacement` → `panel.apply_placement()` → 真机读实际 frame | 面板出现在右上角 | 已完成 |

### XS-XL 工作量预估

| 任务 | 规模 | 依据 |
|---|---|---|
| `PanelPlacement` Protocol + 工厂 | XS | 2 文件，纯类型声明与分派 |
| `layershell.py` ctypes 绑定 + 降级测试 | M | 2 文件，符号探测 + 句柄管理 |
| `LinuxPanelPlacement` + 测试 | S | 2 文件，坐标计算 |
| `panel.apply_placement()` + tray 接线 | S | 3 文件 |
| 真实桌面验证定位 | S | 无新代码，测量与记录 |
| `status.py` 纯函数 + 测试 | S | 2 文件，13 条文案测试 |
| `panel.py` 关闭按钮 + 测试 | S | 2 文件，一个按钮 + 信号 |
| `panel.py` 底栏 + 高度重算 + 测试 | S | 2 文件 |
| `tray.py` 接线 + 补 stub | XS | 2 文件 |

无 L 及以上，无需再拆。

### 检查点规划

**检查点 A（定位）**：面板锚到右上角。
- [x] 离屏：7 条锚点与降级测试通过
- [x] 真机：探针窗口物理 x 2250–2547 → 逻辑 x=1500，期望 1499
- [x] 失败特征已记录：x ≈ 664 说明仍在走 `move()` 旧路径

**检查点 B（关闭按钮 + 文案）**：两者都可在离屏断言。
- [x] 关闭按钮 15 条测试通过（含 200ms 时限，SC-003）
- [x] 文案纯函数 13 条通过

**检查点 C（底栏 + 全量）**：
- [x] 底栏三态文案正确；标题行无数字
- [x] 真机 OCR 读到 `DSH 运行中` 与 `PID 4512 · 端口 3080 · 由托盘启动 · 带令牌`
- [x] Python 全绿 259 条（基线 224 + 新增 35）
- [ ] layer-shell 库被移除（改名）时面板仍能显示（降级真机验证，待做）
- [ ] 三条基线全绿：Python / 插件 131 / `--selftest` 10

## 关键实现细节（避免执行者猜）

### 缩放：为什么不做（撤回依据）

原计划读 `kwinrc` 的 `Xwayland Scale`（1.5）并在启动脚本里 `export QT_SCALE_FACTOR=1.5`，
理由是 Qt 报 `devicePixelRatio = 2.0` 与真实缩放不一致。

**实测推翻了该理由**：

| 测量对象 | 逻辑 | 物理 | 比例 |
|---|---|---|---|
| 真实面板（洋红铺底） | 378 宽 | 564 px | **1.49** |
| 独立 200×100 探针窗口 | 200×100 | 299×149 | **1.50** |
| 屏幕整体 | 1707 | 2560 | **1.50** |

基线渲染**本来就是对的**。`devicePixelRatio = 2.0` 是缓冲区倍率，不是最终输出比例；
合成器按 1.5 输出，视觉尺寸正确。

**反证**：设 `QT_SCALE_FACTOR=1.5` 后同一色块实测 **225 物理像素 = 2.25 倍**——人为引入 50% 放大错误。

**保留的产出**：`scripts/probe-scale.py`（画已知逻辑宽度的色块、截图、量物理宽度）。
将来若真有环境出现偏差，用它一测即知。**不要**在启动脚本里加缩放校正。

### LayerShellQt 绑定要点（T7 的依据）

已实测可用的符号（`nm -D` 确认）：

| C++ 签名 | mangled 名 |
|---|---|
| `LayerShellQt::Window::get(QWindow*)` | `_ZN12LayerShellQt6Window3getEP7QWindow` |
| `setAnchors(QFlags<Anchor>)` | `_ZN12LayerShellQt6Window10setAnchorsE6QFlagsINS0_6AnchorEE` |
| `setMargins(QMargins const&)` | `_ZN12LayerShellQt6Window10setMarginsERK8QMargins` |
| `setDesiredSize(QSize const&)` | `_ZN12LayerShellQt6Window14setDesiredSizeERK5QSize` |

**Anchor 枚举值（实测校正）**：Qt 风格 `Top=1 Bottom=2 Left=4 Right=8`。右上角 = `Top|Right` = **9**。（我最初按 freedesktop 风格猜 `6`，实测落到左下角，故此处以实测值为准。）

**取 QWindow 指针**：必须用 `sip.unwrapinstance(widget.windowHandle())`，不能用 `winId()`——后者返回的不是 QWindow 指针，实测 `get()` 会返回空。

**QMargins / QSize 传参**：都用 `ctypes.Structure`，按引用传。

- `QMargins`：四字段（l/t/r/b）。
- `QSize`：两字段（w/h）。**`setDesiredSize(const QSize&)` 是按引用**——我最初按
  `(c_int, c_int)` 按值传，C++ 侧把两个整数当指针解引用，**直接段错误**
  （`unittest` 退出码 139）。这是本特性唯一一次进程级崩溃。

**配置时机（两个都必须遵守）**：

1. `Shell::useLayerShell()` 是进程级设置，必须在 `QApplication` 创建**之前**调用。
2. `Window::get()` + `setAnchors` + `setMargins` 必须在 `show()` **之前**做。
   写成 `show()` 之后调用时，日志报
   `already has a shell integration. Call QWindow::close() first and show it again.`
   随后 `is not a wayland window. Not creating zwlr_layer_surface`——定位无声失效。

### 底栏与标题行文案

新建 `dsh_tray/ui/status.py` 放两个纯函数（**偏离原计划把它们放进 `control.py`**：
`control.py` 的职责是控制区渲染，而这两个函数被标题行与底栏共用，与 ControlArea 无耦合）：

```python
def status_text(state: State) -> str:
    """标题行状态短语。"""

def detail_text(state: State, instance: Instance | None, error: str, port: int) -> str:
    """底栏细节：PID · 端口 · 启动方式 · 令牌状态。"""
```

底栏文案映射：

| 状态 | 底栏 |
|---|---|
| 运行·自有 | `PID 4512 · 端口 3080 · 由托盘启动 · 带令牌` |
| 运行·接管 | `PID 8801 · 端口 3080 · 外部启动 · 无令牌` |
| 未运行 | `端口 3080 · 空闲` |
| 启动中 | `冷启动通常需要十几秒` |
| 停止中 | `正在结束会话与子进程` |
| 失败 | `<error> · 端口 3080` |

### 面板高度重算

`apply_height()` 现有公式需加底栏高度。底栏固定单行，实测 `sizeHint().height()` 约 26px（字体 + 上下 padding），按实测值累加而非写死。

### 关闭按钮

放在标题行最右，与 `_missed` 提示共存（提示移到按钮左边）。

**实现方式已定**：用 `QStyle.StandardPixmap.SP_TitleBarCloseButton` 取平台标准关闭图标，配 `setIconSize(QSize(14, 14))` 与无边框的 `QPushButton`。理由：设计稿要求的另外两个头部图标是线性 SVG，而关闭按钮在系统里已有约定俗成的图形，用标准图标能让用户一眼认出，也省去一份资源维护。不自绘 SVG。

**必须设 `setCursor(Qt.CursorShape.PointingHandCursor)`**：面板是无边框窗口，没有这个提示，用户不会知道这里可点。
