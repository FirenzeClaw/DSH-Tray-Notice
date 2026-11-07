# Data Model: 托盘通知控制台

**Feature**: specs/001-notify-console | **Date**: 2026-11-06

本文件定义跨进程的数据形状。两侧（DSH 插件 / 托盘）只通过这些形状耦合，
任何字段变更都必须递增协议版本号（spool 行的 `v`）。

## 实体

### NotificationEntry（通知条目）

一条可被感知的事件记录。由插件生成、写入 spool，托盘消费并持久化。

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `v` | int | ✓ | 协议版本，当前 `1` |
| `type` | str | ✓ | 固定 `"notification"` |
| `id` | str | ✓ | UUID，托盘侧主键 |
| `ts` | str | ✓ | ISO-8601 UTC，事件发生时刻 |
| `kind` | str | ✓ | `needs-approval` / `needs-answer` / `done` / `error` / `blocked` / `max-tokens` / `cancelled` / `interrupted` / `job` / `goal` / `subagent` / `tool-failure` / `notice` / `test` |
| `sessionId` | str | ✓ | DSH 会话标识（深链定位用） |
| `sessionTitle` | str | ✓ | 会话标题（显示用） |
| `workspace` | str | — | 工作目录短名，次要信息 |
| `title` | str | ✓ | 通知标题（如「需要你审批」） |
| `body` | str | ✓ | 正文；超过 200 字符由插件截断 |
| `urgency` | str | ✓ | `critical`（需要你）/ `normal`（其余） |
| `openUrl` | str | ✓ | 会话定位链接，**不含令牌**（`http://127.0.0.1:3080/?session=<id>`）。令牌由托盘在投递/打开时按 owned/adopted 注入——令牌只能存在于托盘一侧（contracts C2） |
| `dedupeKey` | str | ✓ | 去重键，规则见下 |
| `timeoutMs` | int | — | 横幅停留毫秒数；缺省时投递端按紧急度兜底 |

**去重键规则**: `kind:sessionId:turn`（轮次类）；`approval:<approvalId>`；`question:<requestId>`；
`job:<jobId>`。托盘对同键且 10 秒内的第二条直接丢弃。

**状态机**: `unread → read`（用户点击或「全部标为已查看」）→ 淘汰（超 500 条 / 30 天）。

### SessionStateEntry（会话状态条目）

会话的当前运行态。由插件在**状态变化时**写入（变了才写，不是心跳）。

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `v` / `type` | | ✓ | `1` / `"session-state"` |
| `ts` | str | ✓ | 快照时刻 |
| `sessions` | list | ✓ | 全量快照（不是增量），见下 |
| `sessions[].id` | str | ✓ | 会话标识 |
| `sessions[].title` | str | ✓ | |
| `sessions[].state` | str | ✓ | `working` / `waiting-user` / `idle` |
| `sessions[].turn` | int | ✓ | 当前轮次号 |
| `sessions[].turnStartedAt` | str | — | 本轮开始时刻（ISO-8601）；idle 时缺省 |
| `sessions[].currentTool` | str | — | 正在执行的工具名 + 参数摘要，如 `Bash · pnpm build` |
| `sessions[].origin` | str | ✓ | `root` / `subagent`（子会话默认不显示，见 FR-004） |

**时序规则**: `turn/start` 写 working 快照；`tool/call` / `tool/result` 更新 `currentTool`；
`approval/asked` 或 `user-questions/request` 置 `waiting-user`；`turn/end` 置 idle 并从快照移除
（轮次结束通知由 notification 行承担，快照只管「现在谁在跑」）。
**托盘侧时长 = 本地时钟 − `turnStartedAt`**，每秒自增，不依赖心跳（FR-029）。

### ProcessSample（进程采样条目）

托盘自采（面板打开期间，每 2 秒），不落盘、不进 spool。

| 字段 | 类型 | 说明 |
|---|---|---|
| `pid` | int | 进程标识 |
| `role` | str | `core`（DSH 本体）/ `mcp` / `tool`（工具子进程）/ `other` |
| `label` | str | 可读名，如 `dsh web`、`codegraph`、`pnpm build` |
| `cpuPercent` | float \| null | 单核口径；首次采样为 `null`（FR-031） |
| `rssBytes` | int | VmRSS |
| `ageSeconds` | int \| null | 进程已存活时长（与「工作中」互参） |

**采样对**: CPU 需要连续两次 `/proc/<pid>/stat` 读数；两次样本在内存中配对，
面板关闭即丢弃。

### Preset（预设）

**枚举值**（持久化的就是这四个字符串，界面只做标签映射）：
`quiet` → 安静、`standard` → 标准、`verbose` → 详细、`custom` → 自定义。

**开关粒度 = 组**（对齐 spec FR-002 的四组）；「需要你」组内再拆两个子项：

| 组键 | 中文标签 | 含哪些 kind | 组内子项 |
|---|---|---|---|
| `needs-you` | 需要你 | `needs-approval`、`needs-answer` | `approval`、`answer`（可分别关） |
| `done-error` | 完成与出错 | `done`、`error`、`blocked`、`max-tokens` | — |
| `notice` | 提示 | `notice` | — |
| `other` | 其它信息性 | `job`、`goal`、`subagent`、`tool-failure`、`cancelled`、`interrupted` | — |

设置里还有一个不属于四组的项：

| 键 | 默认 | 说明 |
|---|---|---|
| `criticalTimeoutMs` | 300000（5 分钟） | critical 通知的横幅停留时限；范围钳到 5 秒 ~ 1 小时。**刻意不提供「永不消失」**——实测那样会占住 Plasma 的弹窗位，后续通知全部排队不显示 |
| `testNonce` | 0 | 设置页「发送测试通知」的触发计数 |

| 预设 | 开启的组 |
|---|---|
| `quiet` | `needs-you` + `notice` |
| `standard` | `quiet` + `done-error` |
| `verbose` | 全部四组 |

用户逐组覆盖后整体标记 `custom`；把值改回与某预设完全一致时，重新显示为该预设。

> `kind:"test"` 是设置页「发送测试通知」的内部验证用类别，不归属任何组、不受开关控制、
> 不计入历史统计（避免污染 SC-003 的计数）。

> **实现期修正（2026-11-06）**：初版契约的 kind 枚举只有四类轮次结束（`done`/`error`/
> `blocked`/`max-tokens`），而 FR-003 要求按原因分**六类**（含取消、中断）。已补
> `cancelled`（对应 `turn/end(aborted)` 与 `forked`）与 `interrupted`（对应
> `turn/end(interrupted)`），两者归 `other` 组，因此安静与标准预设下默认不通知。
> 协议版本仍为 `v:1`（未发布，扩展安全）。

## 存储位置与生命周期

| 数据 | 位置 | 写者 | 读者 | 生命周期 |
|---|---|---|---|---|
| 事件与快照流 | `$DSH_HOME/run/tray-notify/events.jsonl` | 插件 | 托盘 | 超 1 MiB 归档轮转 |
| 通知历史 | `~/.local/state/dsh-tray/notifications.json` | 托盘 | 托盘 | 500 条 / 30 天 |
| 读取偏移 | `~/.local/state/dsh-tray/spool-offset.json` | 托盘 | 托盘 | 随 spool 轮转重置 |
| 设置 | DSH 设置存储（ns=`tray-notify`） | 设置页 | 插件 | 随 profile 持久化 |

权限：目录 0700，文件 0600（AGENTS.md 安全红线；spool 里的 `openUrl` 含令牌）。

## 不变量

1. **spool 单写者**：只有插件追加；托盘只读。两个托盘实例由既有 flock 单实例保证互斥。
2. **协议演进**：`v` 不匹配的行跳过并计数（日志一条），不崩溃。
3. **幂等消费**：托盘用 `id` 去重，重启重读 spool 不会产生重复通知。
4. **快照即真相**：`sessions` 数组是全量替换，不是增量——托盘不做合并逻辑。
