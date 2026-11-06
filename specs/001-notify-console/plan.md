# 托盘通知控制台 实现计划

> **面向 AI 代理的工作者：** 使用 subagent-driven-development（推荐）或 executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法跟踪进度。

**Branch**: `001-notify-console` | **Date**: 2026-11-06 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-notify-console/spec.md`

## Summary

把 DSH 的会话事件抬成真人可感知的通知，并让托盘面板成为「状态 + 操作 + 通知回查」的
唯一入口。DSH 侧新增一个 observe-only 插件（订阅事件、应用预设策略、把通知意图与会话
状态快照写入本地事件文件），托盘侧消费该文件：投递系统通知（Linux 显式 D-Bus）、
维护未查看/已查看历史、提供四个标签页的面板（含「工作中」实时时长与「概览」进程采样）。
点击通知经深链直达对应会话。平台相关实现收敛到单一后端层，Windows 由多平台规格另行交付。

## Technical Context

**Language/Version**: Python 3.14（系统 `/usr/bin/python3` + PyQt6 6.10.2，禁 venv）；
TypeScript 5.7（DSH 插件，`tsc` 直出，无 bundler）

**Primary Dependencies**: PyQt6 / QtDBus（托盘）；`@deepseek-ai/cordis` ~4.0.5 与
`@deepseek-ai/dsh-*` 0.2.1-rc.5（插件，peer 由宿主提供）；Node ≥ 22

**Storage**: 事件流 `$DSH_HOME/run/tray-notify/events.jsonl`（NDJSON）；
通知历史 `~/.local/state/dsh-tray/notifications.json`；设置走 DSH 设置存储（ns=`tray-notify`）

**Testing**: Python：`./dsh-tray.py --selftest`（既有 10 条竞态回归，必须保持 10/10）+
新增 `node --test` 风格的纯函数测试；TS：`node --test`（对齐 DSH-Target-achieved 的做法）

**Target Platform**: Linux KDE Plasma 6 / Wayland（Windows 实现属多平台规格，本计划只保证接口不写死平台）

**Project Type**: 桌面托盘应用 + DSH 宿主插件（双语言单仓库）

**Performance Goals**: 事件→通知可见 < 2s（SC-001）；面板打开 < 300ms；面板关闭零采样开销（SC-006）

**Constraints**: 令牌只允许出现在 owned-<port>.json 与打开的 URL；插件绝不能阻塞 agent loop；
spool 单写者；不引入 psutil 等新第三方运行时依赖（AGENTS.md 硬约束 3/4/5）

**Scale/Scope**: 单用户单机；面板 378px 宽、四标签页；历史 500 条 / 30 天

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| 宪法原则 | 计划的应对 | 状态 |
|---|---|---|
| I 简单性优先 | spool 文件而不是 socket/TCP 服务；不做拖动/动画等未确认特性；`deferWhileChildrenRun` 只在标准/详细预设生效 | ✅ |
| II 测试先行 | 每个任务先写失败测试：插件侧纯函数（分类/去重/挂起/截断）用 `node --test`；托盘侧 spool 解析、历史淘汰、CPU 配对采样为纯函数可测；GUI 行为列入手工验证清单（quickstart §4） | ✅ |
| III 安全无例外 | 令牌不进日志/通知正文/插件侧（contracts C2：插件只写裸链接，托盘注入令牌）；文件 0600/目录 0700；外部输入（spool 行）边界校验 | ✅ |
| IV 原子提交 | 每任务一个 commit；切片顺序见 Implementation Strategy | ✅ |
| V 不审查不合并 | 每个切片结束设检查点，用户审查后再继续 | ✅ |
| VI 可读性与显式契约 | 跨进程契约收敛在 data-model.md/contracts，`v` 显式；公开函数写 JSDoc/docstring | ✅ |

**无违规项。** 唯一需要说明的取舍：把「挂起完成」的 2 秒宽限定为常量，是宪法 I（简单性）
与 FR-005（正确性）之间的平衡点，不做可配置（YAGNI，证据：OpenCode 同样用固定 2s）。

## Project Structure

### Documentation (this feature)

```text
specs/001-notify-console/
├── plan.md              # 本文件
├── research.md          # Phase 0：实测探针与选型
├── data-model.md        # Phase 1：跨进程数据形状
├── quickstart.md        # Phase 1：端到端验证路径
├── contracts/contracts.md  # Phase 1：四份接口契约
└── tasks.md             # speckit-tasks 产出（不在本计划内）
```

### Source Code (repository root)

```text
dsh_tray/
├── probe.py               # [现有] /proc 探测，概览采样复用其 child_pids()
├── locks.py               # [现有] 单实例/操作锁
├── lifecycle.py           # [现有] 状态机（不依赖 Qt）
├── icons.py               # [现有] 两态图标
├── ui.py                  # [修改] 左键开面板；右键菜单加「打开面板」
├── selftest.py            # [现有+扩充] 竞态回归 + 新增纯函数测试
├── notify/                # [新增] 通知域（全部不依赖 Qt，除 backend）
│   ├── __init__.py
│   ├── spool.py           # spool 读取：偏移持久化、inode 轮转检测、行解析/校验
│   ├── history.py         # 通知历史：读写 notifications.json、淘汰、已查看迁移
│   ├── intents.py         # 行 → 展示模型（分类、去重、urgency 判定）
│   ├── delivery.py        # NotificationBackend 接口 + 失败语义（Qt 自由）
│   ├── sessionstate.py    # 快照 → 活动会话表（本地计时基准）
│   └── sampling.py        # 进程采样：两次 /proc 读数配对出 CPU%
├── platform/              # [新增] 平台后端（唯一允许平台分支处）
│   ├── __init__.py        # sys.platform 分派
│   ├── base.py            # NotificationBackend / WindowAnchor / ProcessSampler 协议
│   └── linux.py           # gdbus 投递 + ActionInvoked 订阅 + Qt.Tool 锚点策略
└── ui/                    # [新增] 面板（Qt）
    ├── __init__.py
    ├── panel.py           # 面板容器：锚点、失焦关闭、状态切换
    ├── control.py         # 控制区五态
    ├── notiflist.py       # 未查看/已查看两页
    ├── working.py         # 工作中页（本地计时器）
    └── overview.py        # 概览页（采样驱动）

plugin/                    # [新增] DSH 插件（TypeScript）
├── package.json           # dsh.bundle.patch 指针、peer 依赖、scripts
├── dsh.bundle.patch       # 只做 insert：id tray-notify
├── tsconfig.json          # NodeNext；client 单文件产物
├── src/
│   ├── index.ts           # host 半入口：订阅、策略、spool 写入
│   ├── config.ts          # schema 与默认值（schemastery）
│   ├── events.ts          # DSH 事件 → 通知意图（分类/去重/截断）
│   ├── defer.ts           # 挂起完成：父会话结束而子会话仍在跑时的等待与超时
│   ├── notices.ts         # source.form==='notice' 的识别与映射
│   ├── sessionstate.ts    # 会话状态快照维护
│   ├── spool.ts           # NDJSON 追加 + 轮转
│   └── client/
│       └── index.ts       # client 半：设置分区 + 深链处理（自包含单文件）
└── tests/
    ├── events.test.ts
    ├── notices.test.ts
    └── spool.test.ts

design/notification-panel.html   # [现有] 交互基准，实现对照它验收
```

**Structure Decision**: 双语言单仓库。`dsh_tray/notify/` 与 `dsh_tray/ui/` 分离是因为
通知域必须可无 GUI 测试（对齐 lifecycle 不依赖 Qt 的既有硬约束）；`plugin/` 独立成包
是因为它要被 DSH 的 profile 以 `link:` 方式装载，有自己的构建与测试闭环。

## Implementation Strategy

### 垂直切片划分（6 片，每片端到端可验证）

| # | 切片 | 端到端路径 | 规模 |
|---|---|---|---|
| V1 | 插件骨架 + 事件流 | 订阅 turn/end → 分类 → 写 spool → `tail` 能看到行 | M |
| V2 | 托盘消费 + 系统通知 | 读 spool → gdbus 投递 → 桌面可见通知 | M |
| V3 | 点击回会话 | ActionInvoked → 拼深链 → 浏览器 → 客户端插件定位 | M |
| V4 | 面板：控制区 + 未查看/已查看 | 左键面板、五态控制区、历史持久化、徽标 | L |
| V5 | 工作中 + 概览 | 快照流 → 本地计时；/proc 配对采样 | M |
| V6 | 设置页 + 预设 | client 设置分区 → settings ns → 插件即时生效 | L |

V1/V2 是承重墙（数据流贯通），V3 依赖 V2，V4 依赖 V2 的数据，V5 的「工作中」依赖 V1 的
快照、「概览」独立，V6 依赖 V1 的配置读取。**每个切片交付后系统都处于可工作状态**——
V1 完成时虽然还没有 UI，但 `tail events.jsonl` 就是可验证的交付物。

### XS-XL 预估与拆分方案

- V4 标 L：拆为 V4a（面板容器 + 控制区，3 文件）与 V4b（两个通知页 + 徽标，3 文件），
  以「控制区可见且能启停」为 V4a 的完成线。
- V6 标 L：拆为 V6a（设置分区 + 预设写入，2 文件）与 V6b（插件响应设置变化 + 测试通知
  按钮，2 文件）。
- 其余 M；无 XL（最大切片 6 文件，在 L 上限内）。

### 检查点规划

高风险排前：V1 顶格做对（订阅与 `next()` 顺序错了会卡死提问），V2 的 D-Bus 投递有
libnotify 误判坑（research D3）。V4 是 UI 大头，放中间而不放最后，尽早暴露交互问题。

## 检查点 1：V1+V2 之后（数据流贯通）

- [ ] `tail events.jsonl` 能看到 notification 与 session-state 两类行
- [ ] 人手触发：审批 → critical 通知出现且不自动消失；完成 → normal 通知
- [ ] 插件单测全绿（node --test）；--selftest 仍 10/10
- [ ] kill dsh → 托盘自动接上，spool 不重复消费
- 与人审查后再继续

## 检查点 2：V3+V4 之后（价值闭环）

- [ ] 点通知落在对应会话；URL 参数被清除；刷新不重跳
- [ ] 面板五态与设计稿一致；停止/重启仍有确认框
- [ ] 托盘重启：未查看徽标数字不变，已查看历史保留
- 与人审查后再继续

## 检查点 3：V5+V6 之后（完整交付）

- [ ] 工作中时长每秒自增且刷新不跳变；DSH 停止后该页清空
- [ ] 概览首次 CPU 为待采样；面板关闭后无采样线程
- [ ] 设置页三预设即时生效；两窗口并发保存后者被拒
- [ ] SC-001~008 逐条核对
- 与人审查后再继续

## Requirement Coverage

每条 FR 必须至少落在一个切片里；`/speckit-tasks` 生成任务时据此校验覆盖度。

| 需求 | 切片 | 落点 |
|---|---|---|
| FR-001 事件采集 | V1 | `plugin/src/index.ts` 订阅清单（含 `job/settled`、`goal/changed`） |
| FR-002 四组分类 | V1 | `plugin/src/events.ts` 分类函数 |
| FR-003 轮次六分类 | V1 | `events.ts` 的 `TurnEndReason` → `kind` 映射 |
| FR-004 子会话默认静默 | V1 | `events.ts` 判 `origin`；配置 `subagents` |
| FR-005 挂起完成 | V1 | `plugin/src/defer.ts` 挂起表 + 2s 宽限 / 15min 上限 |
| FR-006 去重 | V1 + V2 | 插件生成 `dedupeKey`；托盘 10s 窗口二次去重 |
| FR-007 三预设 | V1 + V6 | `config.ts` 默认值；设置页展示 |
| FR-008 逐项覆盖 + 自定义标记 | V6 | `client/index.ts` 的 custom 判定 |
| FR-009 即时生效 | V6 | 插件监听设置变化重读 |
| FR-010 并发冲突检测 | V6 | `update(ns, patch, revision)` 409 处理 |
| FR-011 单进程投递 | V2 | 托盘独占投递；插件无平台代码 |
| FR-012 投递失败仍保留 | V2 | `delivery.py` 返回 False 但条目入库 |
| FR-013 需要你驻留更久 | V2 | `linux.py` 按 urgency 设 expire_timeout=0 |
| FR-014 正文不含令牌 | V1 + V2 | 插件写裸链接；托盘拼令牌仅用于 openUrl |
| FR-015 携带会话定位信息 | V1 | `NotificationEntry.sessionId` |
| FR-016 点击定位/会话不存在降级 | V3 | `client/index.ts` 深链处理 |
| FR-017 参数用后即除 | V3 | `history.replaceState` |
| FR-018 复用已开页面 | V3 | 打开 URL 而非新窗口；系统行为 |
| FR-019 左键面板/右键菜单 | V4a | `ui.py` + `ui/panel.py` |
| FR-020 控制区常驻状态 | V4a | `ui/control.py` 五态 |
| FR-021 四操作按状态启停 | V4a | `control.py` 读 `State` |
| FR-022 危险操作确认 | V4a | 复用既有 `_confirm` |
| FR-023 接管提示 | V4a | `control.py` 琥珀提示行 |
| FR-024 四标签等宽居中 | V4b | `panel.py` 的 tab 布局（计数绝对定位） |
| FR-025 未读徽标 | V4b | `icons.py` 徽标绘制 + `notiflist.py` 计数 |
| FR-026 点击移入已查看不删除 | V4b | `history.py` `mark_read()` |
| FR-027 日期分组 + 500/30 天 | V4b | `history.py` 淘汰与分组 |
| FR-028 工作中四要素 | V5 | `ui/working.py` + `sessionstate.py` |
| FR-029 本地累加计时 | V5 | `working.py` QTimer 1s，基准 `turnStartedAt` |
| FR-030 概览进程清单 | V5 | `sampling.py` + `ui/overview.py` |
| FR-031 首采样待采样 | V5 | `sampling.py` 返回 `cpuPercent=None` |
| FR-032 面板关停采样 | V5 | `overview.py` 随 `hide` 停止 QTimer |
| FR-033 口径说明 | V5 | 概览页脚文案 |
| FR-034 托盘缺席保留 | V2 | spool 即持久层；启动时扫未消费 |
| FR-035 过期保留清理 | V2 | 启动补投时按 `ts` 过滤 |
| FR-036 自动重连 | V2 | 偏移持久化 + inode 检测 |
| FR-037 跨重启保留 | V4b | `notifications.json` |
| FR-038 notice 抬成通知 | V1 | `plugin/src/notices.ts` |
| FR-039 基于来源非文案 | V1 | `notices.ts` 白名单 `source.kind` |
| FR-040 不写回会话 | V1 | 插件只 append spool，不调 `agent.inject` |
| FR-041 平台差异收敛 | V2 + V5 | `dsh_tray/platform/` 单一层 |

## Success Criteria Mapping

| 判据 | 验证方式 | 检查点 |
|---|---|---|
| SC-001 事件→通知 < 2s | 手工：触发事件到弹窗用秒表/日志时间戳比对 | 检查点 1 |
| SC-002 点击→可交互 < 3s | 手工计时（浏览器冷启动除外，记录冷/热两种） | 检查点 2 |
| SC-003 标准预设 ≤1.1×轮次 | 跑 20 轮，数 `notifications.json` 新增条数 | 检查点 3 |
| SC-004 历史保留 100% | 重启托盘前后比对条数与 id 集合 | 检查点 2 |
| SC-005 面板 < 300ms、概览 < 1s | 面板打开到首帧打点（`QElapsedTimer`） | 检查点 3 |
| SC-006 关闭后 CPU < 1% | 关闭面板静置 5 分钟后 `ps -o pcpu` 与 `top` 复核 | 检查点 3 |
| SC-007 免文档改预设 | 让非作者按 quickstart §4 操作一次 | 检查点 3 |
| SC-008 投递失败零丢失 | 把 `gdbus` 临时改名后触发事件，条目仍应在列表 | 检查点 2 |

## Risk Register

| 风险 | 证据 | 缓解 |
|---|---|---|
| Wayland 无 Popup；托盘几何 0x0 | research D1/D2 | Tool 窗口 + 固定右上锚点；X11 下 geometry() 生效则贴图标 |
| libnotify 拒绝动作 | research D3 | gdbus 显式调用；notify-send 仅作无动作降级 |
| `user-questions/request` 订阅顺序错误会吞回答 | 契约 C2；生态先例 | prepend + 立即 `next()`，单测锁定顺序 |
| 双通知插件共存双投 | research 第三节 | 文档提示卸载其他通知插件；不做自动检测（YAGNI） |
| Windows 全部未验证 | research D4 | 不在本计划范围；接口已冻结，多平台规格交付时用 quickstart §5 手工验证 |
| 客户端插件加载失败 | 生态已知风险 | 深链降级为打开首页；设置页不可用时预设走默认值 |

## Complexity Tracking

> 无宪法违规，无需记录。
