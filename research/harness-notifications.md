# 调研：市面 harness 的用户通知能力

调研日期：2026-11-06
目的：为「托盘插件集成 DSH 通知能力」确定事件模型、投递后端与交互形态。
方法：一手文档优先（官方 hooks 参考）；对无法直接抓取的页面（403）改用二手聚合结果并标注。
本机 DSH 版本：`0.2.1-rc.5`（`@deepseek-ai/dsh/package.json`）。

## 一、市面 harness 的事件模型

| harness | 「跑完了」信号 | 「需要你」信号 | 其它 | 机制 | 来源 |
|---|---|---|---|---|---|
| Claude Code | `Stop`、`StopFailure`（API 错误） | `Notification`（子类型 `permission_prompt` / `idle_prompt` / `agent_needs_input` / `elicitation_dialog` …）、`PermissionRequest` | `SubagentStart` / `SubagentStop`、`TaskCreated` / `TaskCompleted`、`SessionStart` / `SessionEnd`、`PreCompact`、`MessageDisplay` | hooks（shell / HTTP / MCP / prompt），`terminalSequence` 仅允许 OSC 0/1/2/9/99/777 与 BEL | [官方 Hooks 参考](https://code.claude.com/docs/en/hooks)（2026-11-03 抓取） |
| code CLI（Codex） | `hooks.Stop`（需 `[features] codex_hooks = true`，0.125 起；早期 `hooks = true`） | 官方 `notify = [...]` 只在完成时回调，审批/`request_permissions` 不走该通道 | 0.93 起停止时发终端 bell | `config.toml` 的 `notify` 程序 + hooks | [OpenAI hooks 文档](https://developers.openai.com/codex/hooks)（页面 403，转引 [社区实测](https://community.openai.com/t/feature-request-notification-when-codex-web-finishes-a-task/1364744/9)、[SO 回答](https://stackoverflow.com/questions/79933632/how-to-get-a-notification-whenever-codex-cli-finishes-its-current-task/79933633)） |
| Gemini CLI | 无独立「完成」事件，靠 `Notification` | `Notification` 的 `ToolPermission`（等待授权） | — | 扩展注册 `Notification` hook | [gemini-notifier](https://github.com/thoreinstein/gemini-notifier) |
| OpenCode | `complete` | `permission`、`question`、`plan_exit` | `error`、`subagent_complete`、`user_cancelled`、`session_started`、`client_connected` | 插件（`opencode.json` 的 `plugin`/`plugins`），每事件可独立配 sound/notification/command/bell | [mohak34/opencode-notifier](https://github.com/mohak34/opencode-notifier) |

## 二、跨产品收敛出的设计要点

1. **事件分三类，噪音预算不同**：`complete`（每轮一次，可调）、`needs-you`（审批/提问/计划待审，必须穿透）、`ambient`（subagent 完成、取消、会话开始——默认静默）。OpenCode 的默认值就是这套：`subagent_complete` / `user_cancelled` 全静默。
2. **「需要你」的通知不可丢**：Claude Code 把 `permission_prompt` 与 `idle_prompt` 并进 `Notification`；DSH 侧对应 `approval/asked` 与 `user-questions/request`，都必须单独触发。
3. **焦点抑制是可选开关，不是默认行为**：`dsh-desktop-notify` 以「所有前端失焦」为门控；`dsh-notify-plugins` 默认 `backgroundOnly: false`（前台也提醒）并把它写成常见问题。默认取「总提醒」更安全，把抑制留作开关。
4. **延迟完成（deferred completion）**：OpenCode 的 `deferCompleteUntilChildrenIdle` 会等子会话全部结束再报父会话完成，且父会话在 2 s 内恢复则取消本次提醒。对 DSH 尤其重要——DSH 有 subagent、agent team、workflow、job 四层并发，父轮 `turn/end` 常常不是「活干完了」。
5. **点击必须落地到具体会话**：`dsh-desktop-notify` 的做法是「复用已打开的 DSH 页面并切回对应对话」。这要求通知携带会话标识，且前端能接受深链——我们的 Web UI 目前**没有**深链路由（见第四节），所以要么补客户端深链，要么退化为打开裸 UI。
6. **投递后端按平台分派，且有平台硬约束**：
   - Linux：`notify-send`（libnotify）。GNOME Shell 50（Notification Spec 1.2）**不支持 Actions**，`notify-send --action` 会报 `Actions are not supported by this notifications server`，需直接走 D-Bus 并在 `dbus-monitor` 里听点击。
   - macOS：`osascript` / `terminal-notifier`；点击回调要 `terminal-notifier -execute`。
   - Windows：PowerShell + `Windows.UI.Notifications`；**必须**注册自己的 AppUserModelID **且**放一个带该 AUMID 的开始菜单快捷方式，否则通知只进通知中心、没有横幅也没有声音（借用 `powershell.exe` 的身份还会被用户在设置里关掉 PowerShell 通知时连带失效）。
   - 终端内：OSC 9 / OSC 777 / BEL；需按 `TERM_PROGRAM` 判定 Ghostty / iTerm2 / Kitty / VS Code，Ghostty 还需用户显式开 `desktop-notifications = true`。
7. **观察型插件不得干扰 agent loop**：`lalilulelo3/dsh-notify` 的 `user-questions/request` 监听器是 **prepend + 必须调用 `next()`**，失败的通知被吞掉。这是硬约束——通知失败不能让提问永远悬挂。

## 三、DSH 生态已有的通知插件（重要：避免重复造轮子）

| 插件 | 形态 | 平台 | 关键做法 |
|---|---|---|---|
| [`lalilulelo3/dsh-notify`](https://github.com/lalilulelo3/dsh-notify) | 宿主插件，无客户端半 | Windows | 订阅 `session/event` 取 `turn/end`（`reason.kind`：completed/error/blocked/max-tokens）与 `approval/asked`；prepend `user-questions/request` 后 `next()`。顶层会话按 workspace 目录名标注，子会话默认静默（`subagents: true` 开启）。自建 AppUserModelID + 开始菜单快捷方式 |
| [`haytham818/dsh-notify`](https://github.com/haytham818/dsh-notify) | 宿主插件 | Linux/macOS/Windows | `node-notifier` 封装（notify-send / terminal-notifier / snoretoast）；配置项 `notifyOnComplete/Error/Question/Approval`、`rootsOnly`、urgency 分级 |
| [`1514100951/dsh-notify-plugins`](https://github.com/1514100951/dsh-notify-plugins) | 宿主 + 浏览器双通道 | 浏览器 + Windows | 三档总开关（关 / 浏览器 / 浏览器 + 系统）；`dsh-notify-jobs` 另包监听后台任务结算 |
| [`carbonzhao/dsh-desktop-notify`](https://dsh-plugin.org/zh/plugins/carbonzhao-02692/dsh-desktop-notify) | 宿主 + 客户端 | Windows | 全局失焦门控、可切换右下角自绘卡片、点击切回会话、设置页测试按钮 |

**结论**：事件接线已被社区验证，不必重新摸索；但全部四个都是「插件直接把通知推给操作系统」，**没有一个和桌面托盘进程协同**——没有托盘图标的未读态、没有托盘里的通知历史、也不管 DSH 是否由托盘拉起。这正是本仓库的差异点。

## 四、DSH 本机可用的接入点（实测证据）

### 事件总线

DSH 用 cordis 事件系统，无需改 DSH 本体即可订阅：

| 事件 | 声明位置 | 载荷要点 |
|---|---|---|
| `session/event`（全局火管） | `@deepseek-ai/dsh-session/lib/types/index.d.ts:61` | 每会话事件都过一次 |
| `turn/end` | `.../dsh-session/lib/types/types.d.ts:274` | `{ turn, reason: TurnEndReason }` |
| `TurnEndReason` 变体 | `.../dsh-session/lib/types/types.d.ts:166` | `completed` / `aborted` / `blocked` / `error` / `max-tokens` / `interrupted` / `forked` |
| `approval/asked` | `.../dsh-user-approval/lib/types/types.d.ts:37` | `{ id, toolName }`；配对的 `approval/decided`（`:48`） |
| `user-questions/request`（瀑布） | `.../dsh-user-questions/lib/types/types.d.ts:145` | `this: Scoped<Agent>`，必须 `next()` |
| `job/settled` / `job/registered` | `.../dsh-jobs/lib/types/types.d.ts:58` / `:53` | 后台任务结算 |
| `goal/changed` | `.../dsh-goal/lib/types/domain.d.ts:86` | 目标状态翻转 |
| `tool/call` / `tool/result` | `.../dsh-session/lib/types/types.d.ts:355` / `:375` | 如需按工具名细分 |

**DSH 本身没有内置桌面通知**：在全部已装包中检索 `new Notification` / `notify-send` / `osascript` / OSC 序列，命中的都是无关实现（PDF 预览、终端组件等），没有任何通知模块。

### 插件装载

- 生态惯例：npm 包声明 `dsh.bundle.patch`（顶层 YAML 数组，只做 `insert`），`dsh plugin --profile web add <pkg>` 写进 profile 的 `dsh.profile.bundles`。参考本机既有插件 `/home/firenzeclaw/Code/DSH-Target-achieved/dsh.bundle.patch`。
- 本地开发用 `link:` 依赖，见 `~/.dsh/profiles/web/package.json`（`"dsh-target-monitor": "link:/home/firenzeclaw/Code/DSH-Target-achieved"`）。
- profile 的 HMR 会热加载 patch，改动不必重启 `dsh web`。

### 本地 IPC 惯例

已有插件用的是「unix socket + 一行一条 JSON（NDJSON）」：`$DSH_HOME/run/<name>.sock`，权限 0700，单行上限 64 KiB，协议版本号显式递增。参考 `/home/firenzeclaw/Code/DSH-Target-achieved/src/paths.ts` 与 `src/ipc/protocol.ts`。这套惯例可直接复用，**但 unix socket 在 Windows 上不可用**（见待决策项）。

### Web UI 深链

`dsh-web-frontend` 打包产物里检索 `location.search/hash/pathname` 与 `URLSearchParams`，只有一个无关的 `location.href` 判断；客户端各 `dsh-client-ui-*` 包里也没有 `pushState/replaceState`。**结论：当前 Web UI 不支持用 URL 直接定位某个会话**，点击通知只能打开 UI 首页。

## 五、待决策清单

1. 目标平台范围（决定 IPC 选型、进程探测实现、通知后端）。
2. 通知事件集与各自默认开关（含是否延迟到子会话结束）。
3. 点击行为：打开裸 UI / 补客户端深链后精确跳转 / 不响应点击。
4. 架构：插件 + 托盘协同，还是托盘独立读会话日志（不装插件）。
5. 是否复用生态既有插件的事件映射，还是自写（我们本就要做托盘侧，自写更可控）。
