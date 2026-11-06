# Research: 托盘通知控制台

**Feature**: specs/001-notify-console | **Date**: 2026-11-06
**环境**: KDE Plasma 6.6.6 / Wayland / PyQt6 6.10.2 / Python 3.14.4 / DSH 0.2.1-rc.5

本文件记录规划期完成的实测探针与结论。每个条目都有本机证据，没有凭记忆的 API。

## D1. 面板窗口类型（Wayland 硬约束）

**决策**: 面板用 `Qt.WindowType.Tool | FramelessWindowHint`，显示时手动定位，关闭用「失焦即隐藏」。

**证据**（`/tmp/wl_popup_spike.py`、`wl_popup_spike2.py`，2026-11-06 实测）:

| 窗口类型 | 结果 |
|---|---|
| `Qt.Popup` | **创建失败**：`Failed to create grabbing popup … has no transientParent`，窗口不可见。Wayland 的 popup 必须挂在父 surface 上，托盘图标不是 surface |
| `Qt.Tool + Frameless` | ✅ 坐标被遵守（1300,60 两次显示都在原地），可见，不进任务栏；会抢焦点（`activeWindow=True`，即使设了 `WA_ShowWithoutActivating`） |
| 普通 `Window` | 被合成器挪到 (0,0)，定位请求被忽略 |

**推论**:
- 「贴着托盘弹出的面板」在 Wayland 上**不能**用 Popup 语义实现，必须是有定位权的 Tool 窗口。
- 抢焦点是可接受的行为（用户本来就要交互），但要实现点外部关闭：安装全局事件过滤器，
  在面板外按下鼠标即隐藏。
- 面板拖动 + 记忆位置：Tool 窗口默认可被用户拖动吗？无边框窗口**不会**自带拖动，
  需要自己实现（mousePressEvent 里记录偏移 + mouseMoveEvent 移动）。首版不做拖动，
  固定锚点即可（见 D2），留作后续增强。

## D2. 面板锚点（托盘几何拿不到）

**决策**: 锚点优先级 = `tray.geometry()` 有效 → 用它贴图标；否则固定屏幕右上角。

**证据**（`/tmp/tray_probe.py`）: `tray.geometry()` 在 Plasma Wayland 返回 **0x0**（`valid=False`）。
X11 会话下它可用，Wayland 下拿不到。`QCursor.pos()` 在无指针输入的进程里返回 (0,0)，
也不可靠。

**推论**: 不能指望「贴着图标弹出」。首版固定锚到屏幕右上角（与 Plasma 默认托盘位置一致），
**不做可配置**（YAGNI：托盘一侧没有现成的设置存储，为一个角落引入配置文件不值得；
真需要时再加）。X11 会话下 `geometry()` 有效，优先用它贴图标。

## D3. 系统通知投递（libnotify 会误判）

**决策**: Linux 通知用**显式类型的 D-Bus 调用**，不用 `notify-send`。

**证据**（2026-11-06 实测）:
- `notify-send --action` 被拒：`Actions are not supported by this notifications server`——
  但同一台机器的 `GetCapabilities` 明确列出了 `actions`、`persistence`、`inline-reply`。
  这是 libnotify 的客户端判断问题，不是服务端能力问题。
- 显式构造的 `Notify` 调用**成功**（`gdbus` 返回 `uint32 155`），动作数组照常传。

**实现路径**: 每条通知 `subprocess` 调 `gdbus call`（显式类型：`uint32:0`、`array:string:…`、
`dict:string:variant:`），fire-and-forget；点击回执用进程内 `QDBusConnection.connect(..., "ActionInvoked", slot)`
订阅（已验证 `connect ok: True`，slot 必须是 `@pyqtSlot("uint","QString")` 修饰的 QObject 方法）。
`gdbus` 不存在时降级为 `notify-send`（无动作、无点击），再不行只记入面板列表。

**备选（不采用）**: PyQt6 直接构造 `QDBusMessage`——它的类型推断是错的（`uint32`→`int`、
`as`→`av`，两次实测报签名 `sisssava{sv}i`），需要手工 `QDBusArgument` 逐字段构造，复杂度高且没有收益。

## D4. Windows 通知（未验证，按生态已知做法设计）

**决策**: PowerShell + `Windows.UI.Notifications`，自建 AppUserModelID，`launch` 参数带深链。

**依据**（research/harness-notifications.md 引用的社区实现）: 借用 `powershell.exe` 的身份会被
用户在设置里关掉 PowerShell 通知时连带失效；必须注册自己的 AUMID **并**放一个带该 AUMID 的
开始菜单快捷方式，否则只进通知中心、没有横幅和声音。点击激活用 toast 的 `launch` 参数
（浏览器深链），不需要 COM 回调。

**验证状态**: 未在真机验证。交付时必须标注，并提供 `--platform-check` 类诊断命令。

## D5. DSH 事件面（本机契约，`0.2.1-rc.5`）

以下均来自本机安装包的类型定义（路径前缀
`…/node_modules/@deepseek-ai/`，写代码前要重新核对）:

| 契约 | 位置 | 用途 |
|---|---|---|
| `session/event` 全局火管 | `dsh-session/lib/types/index.d.ts:61` | 订阅入口 |
| `turn/end` `{turn, reason}` | `dsh-session/lib/types/types.d.ts:274` | 完成类通知 |
| `TurnEndReasonMap` 七种 | 同上 `:166`（completed/aborted/blocked/error/max-tokens/interrupted/forked） | 分类 |
| `approval/asked` `{id, toolName}` | `dsh-user-approval/lib/types/types.d.ts:37` | 审批通知 |
| `user-questions/request` 瀑布 | `dsh-user-questions/lib/types/types.d.ts:145` | 提问通知（**必须 `next()`**） |
| `user/message` 带 `source.form='notice'` | `dsh-llm/lib/types/message.d.ts:86` | 提示类通知（target-monitor 兼容） |
| `job/settled` | `dsh-jobs/lib/types/types.d.ts:58` | 后台任务 |
| `goal/changed` | `dsh-goal/lib/types/domain.d.ts:86` | 目标轮次 |
| 设置服务 | `ctx.settings` / 客户端 `ctx.remote.settings`（`describe/update(ns,patch,revision)`） | 设置页 |
| 设置命名空间 = 插件条目 id | `dsh-settings/lib/types/types.d.ts:5`（`SettingsNamespace = Branded<…>`，ns 形如 `llm-pi-ai`） | ns 取 `tray-notify` |
| 客户端导航 | `ctx.uiWorkspace.openSession(target)`（`dsh-client-ui-workspace/lib/types/client/navigation.d.ts:21`） | 深链跳转 |
| 令牌 URL 形态 | 本机 `~/.local/state/dsh-tray/owned-3080.json`：`http://127.0.0.1:3080/?token=…` | 深链拼接 |

**生态先例**（不是本机实测，但已被他人验证同一套接线）: `lalilulelo3/dsh-notify` 的 README
确认了 `session/event` → `turn/end`、`approval/asked`、`user-questions/request` 的订阅方式
（prepend + `next()`，通知失败吞掉不打扰 agent loop）。

## D6. 插件装载与本地开发

- npm 包声明 `dsh.bundle.patch`（顶层 YAML 数组，只 `insert`），安装用
  `dsh plugin --profile web add <pkg>`；本地开发用 `package.json` 的 `link:` 依赖
  （本机 `~/.dsh/profiles/web/package.json` 已有 `dsh-target-monitor` 的先例）。
- 客户端半必须**自包含**（宿主模块表只解析裸模块名，React 与 ui-primitives 由宿主提供），
  参照 `DSH-Target-achieved/src/client/index.ts` 的单文件产物约束。
- profile 的 HMR 热加载 patch，改插件不必重启 `dsh web`。

## D7. 本地事件通道（spool）

**决策**: NDJSON 追加文件 + 托盘按字节偏移增量读。目录 `$DSH_HOME/run/tray-notify/`，
权限 0700 / 文件 0600。

**理由**:
- 跨平台一致（unix socket 在 Windows 不可用；TCP 需要服务端与令牌管理）。
- 托盘缺席时事件天然保留（spool 就是持久层），托盘启动后补投——直接满足 FR-034/035。
- 单写者（插件）单读者（托盘），无双向握手的复杂度。
- 轮转策略：单文件超 1 MiB 改名归档、再开新文件；托盘读 offset 越界即重置。

**代价**: 毫秒级轮询延迟（可接受，SC-001 是 2 秒）；没有「托盘 → 插件」的反向通道——
按设计不需要（托盘只读，设置走 DSH 自己的设置存储）。

## D8. 概览的进程采样

**决策**: 托盘自采，不经过插件。

**理由**: DSH 卡死时正是最需要看进程的时候，而那时插件也不工作；自采不依赖 DSH 存活。

**Linux 实现**: `/proc/<pid>/stat` 的 utime+stime 求差 / 两次采样墙钟差 = CPU%；
`/proc/<pid>/status` 的 VmRSS = 内存。子进程枚举沿用现有 `probe.child_pids()`。
**Windows**: CIM 查询（S3 交付）。**不引入 psutil**（AGENTS.md 硬约束 4）。

CPU 百分比口径：单核（100% = 占满一核），与 `top`/`ps` 一致；内存合计 = ΣRSS，
页脚注明含共享页重复计算。

## D9. 已验证可用的底层能力清单

| 能力 | 结果 | 证据 |
|---|---|---|
| PyQt6.QtDBus 存在 | ✅ | `import PyQt6.QtDBus` 成功 |
| 会话总线连接 | ✅ | `isConnected()` True |
| 通知服务能力 | actions / persistence / inline-reply / sound | GetCapabilities |
| gdbus 带动作投递 | ✅ `uint32 155` | D3 |
| ActionInvoked 订阅 | ✅ connect ok | D3 |
| Qt.Tool 定位 | ✅ 两次显示坐标一致 | D1 |
| tray.geometry | ❌ 0x0 | D2 |
| notify-send --action | ❌ libnotify 拒绝 | D3 |
| Qt.Popup | ❌ 无 transientParent | D1 |
