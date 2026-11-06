# Contracts: 托盘通知控制台

**Feature**: specs/001-notify-console | **Date**: 2026-11-06

四份契约：spool 协议、DSH 插件接线、平台后端接口、深链。变更任何一份都必须同步
data-model.md 的协议版本，并在 CHANGELOG 记录。

## C1. Spool 协议（插件 → 托盘）

- **传输**: `$DSH_HOME/run/tray-notify/events.jsonl`，NDJSON，UTF-8，单行 ≤ 64 KiB
  （超长的字段在写侧截断，不让半行进流）。
- **写入**: 追加模式；每行一条 JSON 对象；写后不 fsync（事件可容忍极端情况丢一条，
  不值得为此拖慢 DSH 的事件循环）。
- **轮转**: 写前检查文件大小 > 1 MiB → 改名 `events.jsonl.1`（保留上一代）→ 新建。
- **读取**: 托盘启动时从头扫一遍未消费部分（配合 FR-034），之后按偏移增量读；
  偏移持久化在 `~/.local/state/dsh-tray/spool-offset.json`，记录 `(inode, offset)`——
  inode 变了（轮转/重建）就从 0 重读。
- **行类型**: `"notification"`（data-model.md 的 NotificationEntry）与
  `"session-state"`（SessionStateEntry）。未知 `type` 或 `v` ≠ 1 的行：跳过 + 计数，
  单条日志汇总，不报错。

### 行示例

```json
{"v":1,"type":"notification","id":"7c0e…","ts":"2026-11-06T11:40:00.512Z","kind":"needs-approval",
 "sessionId":"session-1dc80bc4","sessionTitle":"通知面板设计","workspace":"DSH-Tray&Notice",
 "title":"需要你审批","body":"Bash · rm -rf dist && pnpm build","urgency":"critical",
 "openUrl":"http://127.0.0.1:3080/?session=session-1dc80bc4","dedupeKey":"approval:appr_01"}
```

> `openUrl` 里**没有令牌**：插件拿不到令牌，也不该拿。托盘投递前按 owned/adopted
> 拼成 `…?token=<t>&session=<id>` 或原样使用（contracts C2 / AGENTS.md 安全红线）。

```json
{"v":1,"type":"session-state","ts":"2026-11-06T11:40:05Z","sessions":[
  {"id":"session-1dc80bc4","title":"通知面板设计","state":"working","turn":4,
   "turnStartedAt":"2026-11-06T11:36:48Z","currentTool":"Bash · pnpm build","origin":"root"}]}
```

## C2. DSH 插件接线（host 半）

**入口**: cordis 插件，条目 id `tray-notify`（= 设置命名空间）。

**订阅清单**（全部 observe-only，任何失败吞掉并记日志，绝不影响 agent loop）:

| 订阅 | 产生动作 |
|---|---|
| `session/event`（全局） | `turn/end` → 分类后写 notification 行；`tool/call`/`tool/result` → 更新快照 `currentTool`；`user/message` 且 `source.form==='notice'` → `notice` 通知 |
| `user-questions/request`（瀑布） | **prepend 监听器：先写 needs-answer 通知与 waiting-user 快照，再 `await next()`**——顺序不能反，否则 Web 端先拿到请求、用户可能在通知发出前已答完 |
| `approval/asked` | 写 needs-approval 通知 |
| `job/settled` | verbose 组开启时写 job 通知 |
| `goal/changed` | verbose 组开启时写 goal 通知 |

**挂起完成（FR-005）**: `turn/end(completed)` 时若该会话的子会话（`origin` 反查或宿主
`agents.isOwnedBy`）仍有 working，则登记挂起；最后一个子会话结束后 2 秒内父会话未恢复
才落通知；挂起上限 15 分钟，超时丢弃（记日志，不误报）。

**令牌与深链**: 插件**不持有**令牌。`openUrl` 的令牌部分由插件从会话上下文拿不到——
实际做法：托盘拥有 owned 实例的令牌（既有 `owned-<port>.json`），**插件只写
`?session=<id>` 形态的裸链接**，托盘投递前按 owned/adopted 注入 `&token=…`。
这保证令牌始终只存在于一侧。

**设置**: ns=`tray-notify`，schema（schemastery）含 `preset`、`groups{…}`、
`subagents`、`deferWhileChildrenRun`、`bodyLimit`。变更即时生效（插件监听设置事件重读）。

## C3. 平台后端接口（托盘侧）

```
NotificationBackend         # 投递
  deliver(entry) -> delivered: bool
  on_action(callback(notif_id, action_key))   # 点击回执，平台可选

WindowAnchor                # 面板锚点
  anchor_for(tray) -> QPoint | None   # None → 用配置角落

ProcessSampler              # 概览
  sample_once() -> list[ProcessSample]   # 含首次 null CPU
```

**Linux 实现**: gdbus 投递 + QtDBus ActionInvoked 订阅；`/proc` 采样；锚点 D2 策略。
**Windows 实现**（S3）: PowerShell toast（AUMID + 开始菜单快捷方式，`launch` 参数即深链）；
CIM 采样。接口不变，实现替换。

**失败语义**: `deliver()` 失败不抛出——返回 False，托盘照常把条目记入列表（FR-012），
并在 tooltip/日志标注「系统通知不可用」。

## C4. 深链（托盘 → 浏览器 → 客户端插件）

- **URL 形态**: `http://127.0.0.1:3080/?token=<t>&session=<id>`（owned）或
  `http://127.0.0.1:3080/?session=<id>`（adopted）。`session` 参数**总是**由托盘拼接，
  插件侧不感知令牌。
- **客户端行为**（`plugin/src/client.ts`）: 挂载时读 `location.search` 的 `session`；
  有效 → `ctx.uiWorkspace.openSession(id)`，随后 `history.replaceState` 移除该参数
  （FR-017）；无效/会话不存在 → 静默落首页（FR-016，不弹错误）。
- **点击复用（FR-018）**: 通知点击统一走系统「打开 URL」——浏览器把同一站点聚焦为已有标签。
  不承诺跨浏览器精确去重；这是环境行为，不是本功能职责。

## C5. 设置页契约（client 半）

- 分区 id：接管「设置 → DSH 通知」slot（同 target-monitor 的接管方式）。
- 控件：预设三选一（分段）、各组开关（Switch）、「发送测试通知」按钮（写一条 `kind:"test"`
  的 notification 行）、版本与冲突检测（`describe` → `update(ns, patch, revision)`，
  409 时提示刷新）。
- 「自定义」判定：当前值 ≠ 任一预设默认值即显示「自定义」（FR-008）。
