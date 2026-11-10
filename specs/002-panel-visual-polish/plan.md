# 面板视觉与定位修正 实现计划

> **面向 AI 代理的工作者：** 使用 subagent-driven-development（推荐）或 executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法跟踪进度。

**Branch**: `002-panel-visual-polish` | **Date**: 2026-11-09 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/002-panel-visual-polish/spec.md`

**目标：** 让托盘面板按屏幕真实缩放渲染、出现在屏幕右上角而非中央、带一个明确的关闭按钮，并把 PID 等细节从顶栏挪到底栏。

**架构：** 新增两个平台能力——`DisplayScale`（读真实输出缩放）与 `PanelPlacement`（把面板锚到右上角）——都放在既有的 `dsh_tray/platform/` 之下，遵循项目既定的「平台分支只出现在那一层」硬约束。面板本身增加底栏、关闭按钮两个纯 Qt 部件。缩放校正通过启动脚本注入环境变量完成，因为该设置只在进程启动时生效。

**技术栈：** Python 3.14 + PyQt6 6.10.2（系统 dist-packages，禁 venv）；ctypes 调用 `libLayerShellQtInterface.so.6`；bash 启动脚本 + `kreadconfig6`。

## Summary

四个相互独立、可分别回退的改动：

| # | 改动 | 回退条件 |
|---|---|---|
| 1 | 启动脚本按 KWin 输出缩放设置 `QT_SCALE_FACTOR` | 读不到配置 → 不设置，行为不变 |
| 2 | layer-shell 锚定右上角 | 库/协议不可用 → 退回既有 `move()` |
| 3 | 标题栏关闭按钮 | 纯 UI，无回退需求 |
| 4 | 顶栏只留状态，新增底栏放细节 | 纯 UI，无回退需求 |

## Technical Context

**Language/Version**: Python 3.14.4（`/usr/bin/python3`，PyQt6 来自 `/usr/lib/python3/dist-packages`，**禁止 venv**）

**Primary Dependencies**:
- PyQt6 6.10.2（现有）
- `libLayerShellQtInterface.so.6`（系统已装 `liblayershellqtinterface6:amd64 6.6.4-0ubuntu1`，经 ctypes 调用，**不新增 pip 依赖**）
- `kreadconfig6`（KDE 配置读取，KDE 桌面自带）

**Storage**: 无新增持久化。面板高度/行数已由既有 `tray-settings` spool 行承载。

**Testing**: `QT_QPA_PLATFORM=offscreen python3 -m unittest discover -s dsh_tray/tests -t .`（当前 224 条）；真实桌面验证用 `scripts/check-banner.py` 的截图与 OCR 能力 + `kwin-mcp window_geometry` 读实际 frame。

**Target Platform**: Linux / KDE Plasma 6 / Wayland（开发机）。其它平台走退化路径。

**Project Type**: 桌面托盘应用（Python + PyQt6），双语言仓库（托盘 Python / DSH 插件 TypeScript）。

**Performance Goals**: 面板打开 ≤ 300ms（既有 SC-005 要求，本改动不引入新的阻塞调用）。缩放与定位都在面板构造/显示时一次性完成，不进入轮询路径。

**Constraints**:
- 平台分支只允许出现在 `dsh_tray/platform/`（AGENTS.md 硬约束 3）
- 不新增 pip 依赖
- `QT_SCALE_FACTOR` 只在进程启动时生效 → 校正必须放在启动脚本
- 托盘图标坐标在 Plasma Wayland 恒为 `0×0`，定位不得依赖它

**Scale/Scope**: 4 个功能改动，涉及 2 个新模块 + 3 个既有模块修改 + 1 个启动脚本修改。无数据库、无网络、无 API。

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| 原则 | 本计划的合规情况 |
|---|---|
| **I 简单性优先** | 新增两个模块各 ~60 行，职责单一。拒绝为「记住拖动位置」等未提需求加复杂度。缩放校正复用系统已有工具（`kreadconfig6`），不自建配置解析。 |
| **II 测试先行** | 每个任务以失败测试开头。缩放换算、锚点计算、关闭按钮、底栏文案都可在离屏环境断言；layer-shell 不可测的部分标注为「需真实桌面验证」并给出具体命令。 |
| **III 安全无例外** | 无密钥、无认证、无外部输入解析。读 `kwinrc` 仅取一个浮点数并做范围校验（0.5–4.0），越界按 1.0 处理。ctypes 调用前用 `hasattr` 探测符号存在性。 |
| **IV 原子提交与主干开发** | 四个改动各自独立提交，每个提交自带测试。UI 改动（3、4）与能力改动（1、2）分开。 |
| **V 不审查不合并** | 计划经用户审查后执行；实现完成后跑三条基线。 |
| **VI 可读性与显式契约** | 新增 `DisplayScale` / `PanelPlacement` 的 Protocol 定义放在 `platform/base.py`，与既有三组契约并列。 |

**结论**：无违规，无需 Complexity Tracking。

## Project Structure

### Documentation (this feature)

```text
specs/002-panel-visual-polish/
├── plan.md              # 本文件
├── research.md          # Phase 0 输出：ctypes 契约与缩放来源的实测结论
├── quickstart.md        # Phase 1 输出：真实桌面验收步骤
└── tasks.md             # /speckit-tasks 生成
```

无 `data-model.md`：本特性不引入新数据实体（缩放是读出来的数值，位置是算出的坐标，都不落盘）。
无 `contracts/`：不新增跨进程接口——缩放与定位都在托盘进程内部。

### Source Code (repository root)

```text
dsh_tray/
├── platform/
│   ├── base.py                 # [修改] 新增 DisplayScale / PanelPlacement 两个 Protocol
│   ├── __init__.py             # [修改] 新增 create_display_scale() / create_placement()
│   ├── linux.py                # [修改] LinuxDisplayScale / LinuxPanelPlacement
│   └── layershell.py           # [新增] LayerShellQt 的 ctypes 绑定（纯机制，不含业务判断）
├── ui/
│   ├── panel.py                # [修改] 关闭按钮、底栏、apply_placement()；高度重算含底栏
│   ├── control.py              # [修改] render() 拆出 status_text() / detail_text() 两个纯函数
│   └── tray.py                 # [修改] 打开面板时调用 apply_placement()
└── tests/
    ├── test_scaling.py         # [新增] 缩放换算与钳制
    ├── test_placement.py       # [新增] 锚点计算与降级
    ├── test_panel_chrome.py    # [新增] 关闭按钮、底栏文案、高度含底栏
    └── test_control_split.py   # [新增] status_text / detail_text 的文案与状态映射

scripts/
└── dsh-tray.sh                 # [修改] 启动前探测真实缩放并 export QT_SCALE_FACTOR
```

**Structure Decision**: 沿用既有的「平台能力在 `platform/`、Qt 部件在 `ui/`、平台分支只在 `platform/`」分层。新增的 `layershell.py` 单独成文件而不是塞进 `linux.py`，因为它是纯粹的 ctypes 协议绑定（没有任何业务判断），与 `linux.py` 里读配置、算坐标的逻辑职责不同；这样 `linux.py` 保持可读，绑定层也可独立测试其降级行为。

## Dependency Graph

```
platform/base.py (新增两个 Protocol)
        │
        ├── platform/layershell.py (ctypes 绑定，无业务逻辑)
        │           │
        │           └── platform/linux.py::LinuxPanelPlacement
        │                       │
        ├── platform/linux.py::LinuxDisplayScale (读 kwinrc，不依赖 layershell)
        │                       │
        └── platform/__init__.py (两个工厂函数)
                                │
                    ┌───────────┴───────────┐
                    │                       │
        ui/panel.py::apply_placement   scripts/dsh-tray.sh (缩放只能走环境变量)
                    │
        ui/tray.py (打开面板时调用)

ui/control.py::status_text / detail_text (纯函数，无依赖)
                    │
        ui/panel.py (顶栏用 status_text，底栏用 detail_text)
```

**实施顺序**：Protocol → 纯函数（control 拆分）→ 关闭按钮 → 缩放 → 底栏 → 定位。纯函数先做，因为它零风险且能立刻让后面的 UI 改动有稳定输入；定位放最后，它依赖最多、失败时前面四片仍完整可用。

## Implementation Strategy

### 垂直切片划分

本特性是单一关注点（面板外观与定位）下的四个独立改动，不存在「schema + API + UI」式的横向依赖。按「先能力、后呈现」切片：

| 切片 | 端到端路径 | 交付物 |
|---|---|---|
| **V1 状态文本分层** | `control.py` 拆出纯函数 → `panel.py` 用它填顶栏 → 测试断言文案 | 顶栏只显示状态；为 V4 铺路 |
| **V2 关闭按钮** | `panel.py` 加按钮 → 接 `closed` 信号 → 测试断言点击后不可见 | 用户能明确关闭面板 |
| **V3 缩放校正** | `linux.py` 读缩放 → 启动脚本 export → 色块实测物理像素 | 元素尺寸与真实缩放一致 |
| **V4 底栏** | `control.py` 的 `detail_text()` → `panel.py` 底栏 → 高度重算含底栏 | PID/端口等落到底栏 |
| **V5 定位** | `layershell.py` 绑定 → `LinuxPanelPlacement` → `panel.apply_placement()` → `kwin` 读实际 frame | 面板出现在右上角 |

V5 放最后：它依赖最多（ctypes 绑定 + 协议可用性），失败时前面四片仍完整可用。

### XS-XL 工作量预估

| 任务 | 规模 | 依据 |
|---|---|---|
| T1 两个 Protocol 定义 | XS | 1 文件，纯类型声明 |
| T2 `control.py` 拆纯函数 + 测试 | S | 2 文件，逻辑搬移 |
| T3 `panel.py` 关闭按钮 + 测试 | S | 2 文件，一个按钮 + 信号 |
| T4 `LinuxDisplayScale` + 测试 | S | 2 文件，读配置 + 钳制 |
| T5 启动脚本注入缩放 | XS | 1 文件，10 行 shell |
| T6 `panel.py` 底栏 + 高度重算 + 测试 | S | 2 文件 |
| T7 `layershell.py` ctypes 绑定 + 降级测试 | M | 2 文件，符号探测 + 句柄管理 |
| T8 `LinuxPanelPlacement` + 测试 | S | 2 文件，坐标计算 |
| T9 `panel.apply_placement()` + tray 接线 | S | 3 文件 |
| T10 真实桌面验收（三条硬指标） | S | 无新代码，验证与文档 |

无 L 及以上，无需再拆。

### 检查点规划

**检查点 A（T1–T3 之后）**：顶栏只剩状态、关闭按钮可关面板。
- [ ] `python3 -m unittest discover -s dsh_tray/tests -t .` 全绿
- [ ] 离屏断言：顶栏文本不含 PID/端口；点击关闭后 `panel.isVisible()` 为 False
- [ ] 既有 224 条基线不回退

**检查点 B（T4–T6 之后）**：缩放换算与底栏完成。
- [ ] 缩放换算单测覆盖 1.0 / 1.25 / 1.5 / 1.75 / 2.0 与越界值
- [ ] 底栏在三种状态下文案正确（运行自有 / 未运行 / 接管）
- [ ] 启动脚本在 `kreadconfig6` 缺失时不报错、不设置变量（用手工 PATH 裁剪验证）

**检查点 C（T7–T10 之后）**：定位完成并真实验收。
- [ ] `kwin-mcp window_geometry` 读出面板 frame 的 x > 屏幕宽 3/4
- [ ] 100 逻辑像素色块实测 150±1 物理像素
- [ ] layer-shell 库被移除（改名）时面板仍能显示（降级验证）
- [ ] 三条基线全绿：Python / 插件 131 / `--selftest` 10

## 关键实现细节（避免执行者猜）

### 缩放来源与校正

真实缩放的读取顺序：
1. `kreadconfig6 --file kwinrc --group Xwayland --key Scale`
2. 读不到或非数字 → 按 `1.0`

校正方式（在 `scripts/dsh-tray.sh` 的 `exec` 之前）：
```bash
REAL_SCALE=$(kreadconfig6 --file kwinrc --group Xwayland --key Scale 2>/dev/null || true)
case "$REAL_SCALE" in
  ''|*[!0-9.]*) REAL_SCALE=1.0 ;;
esac
# 只在真实缩放与 Qt 默认推断不一致时设置；用 awk 做浮点比较（shell 不支持小数）
if awk -v s="$REAL_SCALE" 'BEGIN{exit !(s>1.0 && s<4.0)}'; then
  export QT_SCALE_FACTOR="$REAL_SCALE"
fi
```

**为什么不用 Python 做**：`QT_SCALE_FACTOR` 必须在本进程启动前存在。脚本是唯一能做到这点的位置。

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

**QMargins 传参**：用 `ctypes.Structure` 定义四字段（l/t/r/b），按引用传。

### 底栏与顶栏文案

`control.py` 拆出两个纯函数，`render()` 改为调用它们（保持既有行为不变，便于回归）：

```python
def status_text(state: State) -> str:
    """顶栏状态短语。"""

def detail_text(state: State, instance: Instance | None, error: str) -> str:
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
