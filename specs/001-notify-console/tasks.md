---
description: "Task list for 托盘通知控制台"
---

# Tasks: 托盘通知控制台

**Input**: Design documents from `/specs/001-notify-console/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: 本项目宪法 §II 规定「没有失败的测试就不写生产代码」，因此每个用户故事都含测试任务。
Python 用 `python3 -m unittest discover -s dsh_tray/tests -t .`；插件用 `npm --prefix plugin test`（`node --test`）。
GUI 交互无法自动测的部分，在对应任务下写明手工验收步骤。

**Organization**: 按用户故事分组；切片标签（V1–V6）对齐 plan.md 的 Implementation Strategy。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行（不同文件、无未完成依赖）
- **[Story]**: 所属用户故事（US1…US8）；Setup / Foundational / Polish 阶段无此标签
- 每个任务下缩进列出**独立验收标准**，执行者不必翻别的任务即可判断完成

## Path Conventions

双语言单仓库：托盘 `dsh_tray/`、插件 `plugin/`、测试 `dsh_tray/tests/` 与 `plugin/tests/`。

---

## Phase 1: Setup

**Purpose**: 两个语言侧的包骨架与测试入口

- [ ] T001 创建插件包骨架 `plugin/package.json`
  - [ ] 字段含 `name: "dsh-tray-notify"`、`type: "module"`、`dsh.manifestVersion: 1`、`dsh.bundle.patch` 指针、`peerDependencies`（cordis ~4.0.5 与用到的 dsh-* 0.2.1-rc.5）、`engines.node >=22`
  - [ ] `scripts` 含 `build`（`tsc -p tsconfig.json && tsc -p tsconfig.client.json && node scripts/build-client.mjs`）、`test`（`node --test dist-test/`）、`typecheck`
  - [ ] `npm --prefix plugin install` 成功，`npm --prefix plugin run typecheck` 在空实现下通过

- [ ] T002 [P] 配置 TS 编译 `plugin/tsconfig.json` 与 `plugin/tsconfig.client.json`
  - [ ] 均 `module/moduleResolution: NodeNext`、`strict: true`、`outDir: dist`（client 为 `dist/client`）
  - [ ] 客户端配置 `lib: ["DOM","ES2022"]`、`jsx: "react-jsx"`、`types` 不含 node
  - [ ] 验收：`npx tsc -p plugin/tsconfig.json --noEmit` 无错误

- [ ] T003 [P] 编写 bundle 补丁 `plugin/dsh.bundle.patch`
  - [ ] 顶层 YAML 数组，仅 `insert`，条目 `id: tray-notify`、`name: dsh-tray-notify`
  - [ ] 不改动宿主既有条目（不得出现 `disable` 或其他 id 的覆盖）
  - [ ] 验收：`dsh plugin --profile web add "link:$PWD/plugin"` 后 `~/.dsh/profiles/web/cordis.patch.yml` 出现该条目

- [ ] T004 [P] 创建托盘通知域包 `dsh_tray/notify/__init__.py`
  - [ ] 只导出模块级常量与类型，不 import Qt（对齐 `lifecycle.py` 的硬约束）
  - [ ] 验收：`python3 -c "import dsh_tray.notify"` 在无 DISPLAY 环境成功

- [ ] T005 [P] 创建面板包 `dsh_tray/ui/__init__.py`
  - [ ] 延迟 import PyQt6（模块导入本身不触发 Qt 加载）
  - [ ] 验收：无 DISPLAY 下 `import dsh_tray.ui` 不报错

- [ ] T006 [P] 创建平台层骨架 `dsh_tray/platform/__init__.py` 与 `dsh_tray/platform/base.py`
  - [ ] `base.py` 定义 `NotificationBackend`、`WindowAnchor`、`ProcessSampler` 三个 `Protocol`（签名见 contracts C3）
  - [ ] `__init__.py` 按 `sys.platform` 分派，Windows 未实现时抛 `NotImplementedError("多平台规格交付")`
  - [ ] 验收：`from dsh_tray.platform import backend` 在 Linux 返回 Linux 实现；`python3 -c "import dsh_tray.platform"` 通过

- [ ] T007 建立 Python 测试入口 `dsh_tray/tests/__init__.py` 与 `dsh_tray/tests/test_smoke.py`
  - [ ] `test_smoke.py` 断言 `DEFAULT_PORT == 3080` 与 `dsh_tray.notify` 可导入
  - [ ] 验收：`python3 -m unittest discover -s dsh_tray/tests -t .` 输出 `OK`（1 个测试）

---

## Phase 2: Foundational（阻塞所有用户故事）

**Purpose**: 跨进程契约与两侧的基础原语。**任何用户故事开工前必须完成。**

- [ ] T008 [P] 定义 TS 侧契约类型 `plugin/src/types.ts`
  - [ ] `NotificationEntry`、`SessionStateEntry`、`SessionRow` 字段与 `data-model.md` 逐字对齐（含 `v: 1`）
  - [ ] `kind` 用字面量联合类型，编译期挡住拼错
  - [ ] 验收：`npx tsc -p plugin/tsconfig.json --noEmit` 通过；字段名与 data-model.md 表格完全一致

- [ ] T009 [P] 定义 Py 侧契约类型 `dsh_tray/notify/types.py`
  - [ ] `@dataclass(frozen=True)` 的 `NotificationEntry` / `SessionRow` / `SessionState`，字段名与 T008 相同（snake→camel 映射集中在一处 `from_json`）
  - [ ] `from_json` 对缺字段/错类型返回 `None` 而不是抛异常
  - [ ] 验收：单测 `test_types.py` 覆盖「正常行」「缺 body」「v 不匹配」三种输入

- [ ] T010 [P] 插件侧 spool 写入 `plugin/src/spool.ts`
  - [ ] `append(row)`：JSON.stringify 单行 + `\n`；写前若文件 > 1 MiB 则改名 `events.jsonl.1` 后新建
  - [ ] 单行超 64 KiB 时截断 `body` 字段（不是丢弃整行）
  - [ ] 写失败只记日志、绝不抛出（不能影响 agent loop）
  - [ ] 验收：`plugin/tests/spool.test.ts` 覆盖轮转、截断、写失败吞掉三例

- [ ] T011 [P] 托盘侧 spool 读取 `dsh_tray/notify/spool.py`
  - [ ] 偏移持久化 `~/.local/state/dsh-tray/spool-offset.json`，内容 `{inode, offset}`；inode 变化 → 从 0 重读
  - [ ] 逐行解析为 `NotificationEntry` 或 `SessionState`，坏行/未知 `type` 跳过并计数
  - [ ] `read_new()` 返回 `(notifications, session_states, skipped_count)`
  - [ ] 验收：`dsh_tray/tests/test_spool.py` 覆盖「增量读」「轮转后重读」「坏行跳过」

- [ ] T012 [P] 插件侧预设与配置 schema `plugin/src/config.ts`
  - [ ] 三预设的组默认值（quiet: needs-you+notice；standard: +done/error；verbose: 全量），字段见 contracts C2
  - [ ] 导出 `resolveGroups(preset, overrides)` 纯函数，返回最终开关集合
  - [ ] 验收：`plugin/tests/config.test.ts` 断言三预设的并集关系与 override 优先级

- [ ] T013 [P] 事件分类常量 `plugin/src/kinds.ts`
  - [ ] `TurnEndReason` 七种 → `kind` 映射；`kind` → 四组归属；`aborted`/`interrupted`/`forked` 归「环境」且默认关
  - [ ] 验收：`plugin/tests/events.test.ts` 中「七种 reason 全覆盖」用例通过

- [ ] T014 [P] 两侧日志工具 `plugin/src/log.ts` 与 `dsh_tray/notify/log.py`
  - [ ] 统一格式 `<iso> <level> <component> <msg>`；单文件 1 MiB 轮转；写日志失败静默
  - [ ] 令牌脱敏：任何以 `token=` 开头的查询串替换为 `token=***`
  - [ ] 验收：两侧各一条单测断言 `token=abc` 被替换为 `token=***`

- [ ] T015 插件设置读取与热更新 `plugin/src/settings.ts`
  - [ ] 挂载时读 ns=`tray-notify`，订阅设置变更事件后重读并重建策略对象
  - [ ] 读失败回退到「标准」预设（不得因此不工作）
  - [ ] 验收：单测用假 settings 服务断言「变更后策略更新」「读失败回退标准」

**Checkpoint**: 契约冻结，两侧可各自独立开发。

---

## Phase 3: User Story 1 - 离开电脑后知道「跑完了」或「需要我」(Priority: P1) 🎯 MVP

**Goal**: 事件从 DSH 流到桌面通知（切片 V1 + V2）。

**Independent Test**: 触发审批 → 出现 critical 通知；跑完一轮 → 出现「已完成」通知；`tail events.jsonl` 能看到两类行。

### Tests for User Story 1

- [ ] T016 [P] [US1] 通知意图生成测试 `plugin/tests/events.test.ts`
  - [ ] `turn/end(completed)` → `kind:"done"`、`urgency:"normal"`、`dedupeKey:"done:<sid>:<turn>"`
  - [ ] `turn/end(error)` → `kind:"error"`，正文含错误码
  - [ ] `approval/asked` → `kind:"needs-approval"`、`urgency:"critical"`、`dedupeKey:"approval:<id>"`
  - [ ] 子会话 `turn/end` 在 `subagents:false` 下不产生意图
  - [ ] 验收：上述四例先红后绿

- [ ] T017 [P] [US1] 托盘展示模型测试 `dsh_tray/tests/test_intents.py`
  - [ ] 同 `dedupeKey` 且 10 秒内第二条被丢弃；11 秒后允许
  - [ ] `urgency` 映射：critical → 通知不自动消失，normal → 按系统默认
  - [ ] 验收：两例通过

- [ ] T018 [P] [US1] 投递后端测试 `dsh_tray/tests/test_delivery.py`
  - [ ] 注入假 runner：断言 `gdbus` 命令行含 `Notify`、app_name、summary、body、actions 数组
  - [ ] runner 返回非零 → `deliver()` 返回 `False` 且不抛异常
  - [ ] 验收：两例通过，且断言中**不出现**任何令牌字符串

### Implementation for User Story 1

- [ ] T019 [US1] 实现通知意图生成 `plugin/src/events.ts`
  - [ ] `toNotification(event)` 覆盖 `turn/end` 与 `approval/asked`；正文超 `bodyLimit`（默认 200）截断加省略号
  - [ ] `openUrl` 只写 `http://127.0.0.1:<port>/?session=<sid>`，**不含令牌**（contracts C2）
  - [ ] 验收：T016 转绿

- [ ] T020 [US1] 实现会话状态快照 `plugin/src/sessionstate.ts`
  - [ ] `turn/start` → `working` + `turnStartedAt`；`tool/call` → 更新 `currentTool`；`turn/end` → 移出快照
  - [ ] 快照变化时才写一行（相同内容不重复写）
  - [ ] 验收：单测断言「三次事件后只写两行」（turn/start 一行、tool/call 一行，turn/end 再一行移出）

- [ ] T021 [US1] 接线插件入口 `plugin/src/index.ts`
  - [ ] 订阅 `session/event`、`approval/asked`；`user-questions/request` 用 **prepend 监听器**：先写通知与 waiting-user 快照，再 `await next()`
  - [ ] 所有监听器包 try/catch，异常只记日志
  - [ ] 验收：单测断言监听器顺序（用假 ctx 记录调用序列：`write` 在 `next` 之前）

- [ ] T022 [US1] 托盘投递后端 `dsh_tray/notify/delivery.py`
  - [ ] `deliver(entry) -> bool`；内部按 `platform.backend` 分派；失败返回 False（FR-012）
  - [ ] 验收：T018 转绿

- [ ] T023 [US1] Linux 通知实现 `dsh_tray/platform/linux.py`（投递部分）
  - [ ] `gdbus call --session … Notify` 参数：app_name `DSH-Tray`、replaces_id `uint32:0`、icon `""`、summary、body、actions `['default','打开会话']`、hints `{}`、`expire_timeout`（critical=0，normal=5000）
  - [ ] `gdbus` 不存在 → 回退 `notify-send`（无动作）；两者都无 → 返回 False
  - [ ] 验收：`test_delivery.py` 的命令构造断言通过；手工 `notify-send` 路径单独验证一次

- [ ] T024 [US1] 托盘展示模型 `dsh_tray/notify/intents.py`
  - [ ] `accept(entry) -> bool`（去重窗口）、`to_display(entry)`（图标类别、相对时间）
  - [ ] 验收：T017 转绿

- [ ] T025 [US1] 通知历史写入 `dsh_tray/notify/history.py`（最小版）
  - [ ] `append(entry)` 原子写 `notifications.json`（临时文件 + `replace`），上限 500 条
  - [ ] 并发：写前读改写，文件锁用既有 `locks.operation_lock`
  - [ ] 验收：单测断言写入后可读回、超 500 条淘汰最旧

- [ ] T026 [US1] 托盘消费循环 `dsh_tray/notify/consumer.py`
  - [ ] QTimer 200ms → `spool.read_new()` → 去重 → `deliver()` → `history.append()`；投递失败仍入库
  - [ ] DSH 未运行时降低到 1s 轮询（省 CPU），启动后恢复 200ms
  - [ ] 验收：单测注入假 spool/后端，断言「失败仍入库」「间隔切换」

- [ ] T027 [US1] 接入托盘主程序 `dsh_tray/ui.py`
  - [ ] `TrayApp.__init__` 创建 consumer 并在 `show()` 后启动；`quit` 时停掉
  - [ ] tooltip 增加「通知不可用」提示（当 backend 全程失败时）
  - [ ] 验收：`./scripts/dsh-tray.sh` 启动后 `~/.local/state/dsh-tray/notifications.json` 出现条目

**Checkpoint 1（对齐 plan.md）**: 数据流贯通——`tail events.jsonl` 两类行齐备；审批出现 critical 通知；完成出现 normal 通知；`--selftest` 仍 10/10；kill dsh 后托盘自动接上且不重复消费。**与人审查后再继续。**

---

## Phase 4: User Story 2 - 点通知直接回到那个会话 (Priority: P1)

**Goal**: 通知可点击，点击落在对应会话（切片 V3）。

**Independent Test**: 三个会话同时开，点其中一个的通知 → 落在该会话；刷新不重复跳转。

### Tests for User Story 2

- [ ] T028 [P] [US2] 深链拼接测试 `dsh_tray/tests/test_deeplink.py`
  - [ ] owned 实例（`owned-3080.json` 存在且 pid 匹配）→ `?token=<t>&session=<id>`
  - [ ] adopted → `?session=<id>`（无 token）
  - [ ] 端口非默认时用实际端口
  - [ ] 验收：三例通过；断言拼接结果中 token 与 session 顺序固定

- [ ] T029 [P] [US2] 客户端深链解析测试 `plugin/tests/client.test.ts`
  - [ ] `?session=abc` → 调 `uiWorkspace.openSession("abc")` 一次，随后 `history.replaceState` 被调用
  - [ ] `?session=` 空值或会话不存在 → 不调用 openSession，不抛错
  - [ ] 验收：两例通过（用假 ctx 与假 history）

### Implementation for User Story 2

- [ ] T030 [US2] 深链拼接 `dsh_tray/notify/deeplink.py`
  - [ ] `build(entry, instance) -> str`：令牌只从 `locks.read_owned_record()` 取，且仅当 pid 与实例一致
  - [ ] 令牌绝不出现在日志/通知正文（只进 URL）
  - [ ] 验收：T028 转绿

- [ ] T031 [US2] 点击回执订阅 `dsh_tray/platform/linux.py`（ActionInvoked 部分）
  - [ ] `QDBusConnection.sessionBus().connect(..., "ActionInvoked", slot)`，slot 用 `@pyqtSlot("uint","QString")` 修饰的 QObject 方法
  - [ ] 回调签名 `(notif_id, action_key)`，仅 `action_key in ("default","open")` 时触发打开
  - [ ] 验收：手工按 quickstart §5 发一条带动作通知，点按钮后托盘日志出现 `ActionInvoked`

- [ ] T032 [US2] 点击处理 `dsh_tray/notify/click.py`
  - [ ] 标记已查看（`history.mark_read(entry_id)`）→ 拼深链 → `QDesktopServices.openUrl`
  - [ ] 打开失败（无浏览器）→ 记日志并在 tooltip 提示，不弹错误框
  - [ ] 验收：单测注入假 opener 断言「先标记后打开」的顺序

- [ ] T033 [P] [US2] 客户端深链实现 `plugin/src/client/index.ts`（深链部分）
  - [ ] 挂载时读 `location.search`；成功跳转后 `history.replaceState` 移除 `session` 参数
  - [ ] 会话不存在 → 静默落首页（不 alert、不 console.error 刷屏）
  - [ ] 验收：T029 转绿

- [ ] T034 [US2] 客户端构建脚本 `plugin/scripts/build-client.mjs`
  - [ ] 产物单文件自包含（不得有相对 import）；React 与 ui-primitives 保持外部裸模块引用
  - [ ] 验收：`npm --prefix plugin run build` 产出 `dist/client.js`，`grep -c "from '\./"` 为 0

**Checkpoint**: 点通知可精确回到会话；URL 参数被清除；刷新不重跳。

---

## Phase 5: User Story 3 - 面板里看「谁在跑、跑了多久」(Priority: P2) + User Story 6 - 事后回查 (Priority: P3)

**Goal**: 左键打开面板；控制区五态；未查看/已查看两页与历史（切片 V4a + V4b + V5a 的「工作中」）。

**Slice note**: US6 与 US3 同属 V4 切片（面板容器与列表是一体的），故 US6 提前到 US4 之前。
这是 plan.md 的切片约束优先于故事优先级，**不改变任何需求内容**。

**Independent Test**: 左键面板出现且控制区显示运行中·自有；「工作中」一行且时长每秒自增；点未查看条目移入已查看；重启托盘历史保留。

### Tests for User Story 3

- [ ] T035 [P] [US3] 锚点策略测试 `dsh_tray/tests/test_anchor.py`
  - [ ] `tray.geometry()` 有效 → 面板贴图标（右下对齐）
  - [ ] 返回 0x0 → 用屏幕右上角，且不越出 `availableGeometry`
  - [ ] 验收：两例通过（注入假 geometry 与假 screen）

- [ ] T036 [P] [US3] 工作时长计时测试 `dsh_tray/tests/test_working.py`
  - [ ] 给定 `turnStartedAt` 与假时钟 → `elapsed()` 返回正确秒数
  - [ ] 快照刷新后时长不倒退（新快照的 `turnStartedAt` 更晚时以新值为准，否则保留旧值）
  - [ ] 验收：两例通过

- [ ] T037 [P] [US6] 历史分组与淘汰测试 `dsh_tray/tests/test_history.py`
  - [ ] 500 条上限、30 天过期；分组「今天/昨天/更早」按本地时区
  - [ ] `mark_read` 后条目仍在（不删除）
  - [ ] 验收：三例通过

### Implementation for User Story 3

- [ ] T038 [US3] 面板容器 `dsh_tray/ui/panel.py`
  - [ ] `Qt.Tool | FramelessWindowHint`；显示前按锚点策略 `move()`；`focusOut`/`WindowDeactivate` 隐藏
  - [ ] 四个标签用 `flex: 1` 等宽，文字居中，计数标记绝对定位（对照 design/notification-panel.html）
  - [ ] 验收：手工——左键托盘面板出现；点桌面空白处面板消失；四个标签等宽且文字不随数字偏移

- [ ] T039 [US3] 控制区 `dsh_tray/ui/control.py`
  - [ ] 五态渲染（未运行/启动中/运行中·自有/运行中·接管/停止中/失败）与元信息
  - [ ] 主操作随状态切换；接管态显示琥珀提示；失败态显示占用者
  - [ ] 验收：手工切换 `--start`/`--stop` 观察五态；接管态用外部启动的实例验证

- [ ] T040 [US3] 控制区动作接线 `dsh_tray/ui/control.py` + `dsh_tray/ui.py`
  - [ ] 启动/停止/重启/打开复用既有 `Lifecycle` 与 `_confirm`；危险操作默认按钮为「取消」
  - [ ] 进行中禁用全部按钮
  - [ ] 验收：手工——停止时出现确认框且默认取消；启动中按钮全灰

- [ ] T041 [US3] 左键开面板 + 右键菜单 `dsh_tray/ui.py`
  - [ ] `Trigger` → 面板；`Context` → 既有菜单 + 新增「打开面板」
  - [ ] 验收：手工——左键出面板，右键出菜单且含新条目

- [ ] T042 [US3] 未读徽标 `dsh_tray/icons.py`
  - [ ] 在图标 pixmap 右上叠加圆点 + 数字（≤9 显示数字，>9 显示「9+」）；0 条不叠加
  - [ ] 验收：手工——有未查看时托盘图标带角标；全部标为已查看后角标消失

- [ ] T043 [US6] 历史完整实现 `dsh_tray/notify/history.py`
  - [ ] 淘汰（500/30 天）、日期分组、`mark_read`、`clear_read`、原子写
  - [ ] 验收：T037 转绿

- [ ] T044 [US6] 通知列表页 `dsh_tray/ui/notiflist.py`
  - [ ] 未查看/已查看两页；行含类别图标、标题、会话名、相对时间；hover 出现「打开会话 / 标为已查看」
  - [ ] 点击行 → 标记已查看 + 打开会话
  - [ ] 验收：手工——点行后条目移入已查看且徽标减一；hover 出按钮

- [ ] T045 [US6] 批量操作 `dsh_tray/ui/notiflist.py`
  - [ ] 「全部标为已查看」（双勾图标）与「清空已查看」（垃圾桶图标）均需二次确认
  - [ ] 验收：手工——两操作生效且清空不影响未查看

**Checkpoint 2（对齐 plan.md）**: 点通知落会话、参数被清除、刷新不重跳；面板五态与设计稿一致；停止/重启仍有确认框；托盘重启后未查看数字与已查看历史都保留。**与人审查后再继续。**

---

## Phase 6: User Story 4 - 概览里看 DSH 的子进程开销 (Priority: P2)

**Goal**: 概览页列出子进程的 CPU/内存，面板关闭即停（切片 V5b）。

**Independent Test**: 启动长跑工具 → 该进程出现在列表且 CPU 明显高于空闲进程；首次打开 CPU 显示待采样。

### Tests for User Story 4

- [ ] T046 [P] [US4] 采样测试 `dsh_tray/tests/test_sampling.py`
  - [ ] 两次 `/proc/<pid>/stat` 读数（假数据）→ CPU% 正确；首次采样返回 `None`
  - [ ] `VmRSS` 解析为字节；进程消失 → 该行从结果中移除而不是报错
  - [ ] 验收：三例通过

### Implementation for User Story 4

- [ ] T047 [US4] 采样实现 `dsh_tray/notify/sampling.py`
  - [ ] `sample_once()` 返回 `list[ProcessSample]`；内部保留上一次读数用于求差
  - [ ] 只读 `/proc`，不 fork 外部命令
  - [ ] 验收：T046 转绿

- [ ] T048 [US4] 进程角色归类 `dsh_tray/platform/linux.py`（ProcessSampler 部分）
  - [ ] `core`（cmdline 含 `dsh web`）/ `mcp`（含 `mcp`）/ `tool`（dsh 子孙且非前两者）/ `other`
  - [ ] 复用 `probe.child_pids()` 枚举
  - [ ] 验收：手工——概览里 MCP 与 bash 子进程标签正确

- [ ] T049 [US4] 概览页 `dsh_tray/ui/overview.py`
  - [ ] 顶部合计（CPU/内存/进程数）、按角色分组的行、页脚口径说明
  - [ ] QTimer 2s 仅在页面可见时运行；`hide` 即 `stop()`
  - [ ] 验收：手工——首次打开 CPU 显示「待采样」，2 秒后出数；切走后 `ps` 无额外 CPU

---

## Phase 7: User Story 5 - 在设置页决定提醒哪些事 (Priority: P2)

**Goal**: 设置分区可切预设与逐组开关，即时生效（切片 V6a + V6b）。

**Slice note**: V6a = 设置分区与预设写入（T051–T052）；V6b = 测试通知与插件响应设置变化（T053–T054）。

**Independent Test**: 切「安静」后完成通知消失、审批照常；切回「标准」恢复。

### Tests for User Story 5

- [ ] T050 [P] [US5] 设置映射测试 `plugin/tests/config.test.ts`（扩展）
  - [ ] 任一预设选中 → 各开关等于该预设默认值
  - [ ] 单改一项 → 标记 `custom`；改回与预设一致 → 不再是 `custom`
  - [ ] 验收：两例通过

### Implementation for User Story 5

- [ ] T051 [US5] 设置分区渲染 `plugin/src/client/index.ts`（设置部分）
  - [ ] 预设分段控件 + 分组开关 + 「发送测试通知」按钮 + 「自定义」标记
  - [ ] 冲突（409）时提示「设置已被其他窗口修改，请刷新」
  - [ ] 验收：手工——设置页出现「DSH 通知」分区，四项可操作

- [ ] T052 [US5] 设置读写接线 `plugin/src/client/index.ts`
  - [ ] 挂载 `describe()` → 渲染；变更 `update(ns, patch, revision)`
  - [ ] 验收：手工——改开关后刷新页面值保留

- [ ] T053 [US5] 测试通知 `plugin/src/index.ts`
  - [ ] 按钮触发一条 `kind:"test"` 的通知行（绕过组开关，仅用于验证链路）
  - [ ] 验收：手工——点按钮立即出现一条测试通知

- [ ] T054 [US5] 插件响应设置变化 `plugin/src/settings.ts` + `index.ts`
  - [ ] 设置变更 → 重建策略 → 立即影响后续事件（不需要重启）
  - [ ] 验收：手工——切「安静」后触发完成无通知，审批仍有

**Checkpoint 3（对齐 plan.md）**: 工作中时长每秒自增且刷新不跳变、DSH 停止后该页清空；概览首次待采样、面板关闭无采样；设置三预设即时生效、并发保存后者被拒；SC-001~008 逐条核对。**与人审查后再继续。**

---

## Phase 8: User Story 7 - 托盘不在时也不丢事件 (Priority: P3)

**Goal**: 托盘缺席期间的事件在下次启动补投（FR-034/035）。

**Independent Test**: 关托盘 → 触发两条 → 启动托盘 → 出现「错过 N 条」并能在未查看里看到。

- [ ] T055 [P] [US7] 补投测试 `dsh_tray/tests/test_replay.py`
  - [ ] 未消费区间全部投递；超 2 小时的事件被过滤不投递
  - [ ] 已消费区间不重复投递（offset 语义）
  - [ ] 验收：两例通过

- [ ] T056 [US7] 启动补投 `dsh_tray/notify/consumer.py`
  - [ ] 启动时先 `read_new()` 全量补投（受时间窗限制），再进入轮询
  - [ ] 补投条目进未查看并带「补投」标记
  - [ ] 验收：T055 转绿 + 手工按 Independent Test 走一遍

- [ ] T057 [US7] 汇总提示 `dsh_tray/ui.py`
  - [ ] 补投 > 0 时 tooltip 与面板顶部出现「错过 N 条通知」一次性提示，用户查看后消失
  - [ ] 验收：手工——补投后提示出现，点开面板后不再重复提示

---

## Phase 9: User Story 8 - 与既有的「可能卡住」提示兼容 (Priority: P3)

**Goal**: `source.form === 'notice'` 的会话内消息抬成通知（FR-038/039/040）。

**Independent Test**: 让 target-monitor 触发一次「可能卡住」→ 收到「提示」类通知，会话内提示仍在。

- [ ] T058 [P] [US8] notice 识别测试 `plugin/tests/notices.test.ts`
  - [ ] `source.kind === 'target-monitor'` 且 `form === 'notice'` → 生成 `kind:"notice"`，正文取 `source.summary`
  - [ ] 未知 `source.kind` → 不生成（白名单）
  - [ ] 文案任意变化仍识别（只依赖 kind 与 form）
  - [ ] 验收：三例通过

- [ ] T059 [US8] notice 映射实现 `plugin/src/notices.ts`
  - [ ] 白名单默认含 `target-monitor`；可通过配置增删
  - [ ] 验收：T058 转绿

- [ ] T060 [US8] 接线与开关 `plugin/src/index.ts` + `config.ts`
  - [ ] `user/message` 事件中识别 notice 并写通知行；受「提示」组开关控制
  - [ ] 验收：手工——触发 target-monitor 提醒后收到通知，关掉该组后不再收到

- [ ] T061 [US8] 反向不污染校验
  - [ ] 断言插件不调用任何写会话 API（代码审阅 + grep `agent.inject|steer|followup` 无命中）
  - [ ] 验收：`grep -rn "agent\.\(inject\|steer\|followup\)" plugin/src` 无输出

---

## Phase 10: Polish & Cross-Cutting

- [ ] T062 [P] 更新 `README.md`：从「托盘启动器」扩写为「托盘 + 通知控制台」，含安装、预设说明、故障排查
  - [ ] 验收：README 中所有命令可在仓库根直接执行通过

- [ ] T063 [P] 更新 `docs/design.md`：并入面板四标签与控制区五态的设计共识（保留原竞态矩阵）
  - [ ] 验收：无残留「不含 DSH 本体改动」这类过期表述

- [ ] T064 [P] 更新 `AGENTS.md` 构建/测试命令：补插件构建与 Python 单测命令
  - [ ] 验收：`AGENTS.md` 中每条命令实测可跑

- [ ] T065 走查 `quickstart.md`：按 §0–§5 逐步执行，修正与实际不符处
  - [ ] 验收：无步骤失败；§5 需人工点击的部分标注清楚

- [ ] T066 SC 逐条核对（SC-001~008），把实测值写进 `specs/001-notify-console/` 的验收记录
  - [ ] 验收：八条各有实测数据或明确的「未验证」标注

- [ ] T067 [P] 清理探针残留：删除 `/tmp/wl_popup_spike*.py`、`/tmp/tray_probe.py`、`/tmp/notify_probe.py`、`/tmp/sig_probe.py`、`/tmp/anchor_probe.py`
  - [ ] 验收：`ls /tmp/*probe*.py /tmp/wl_popup_spike*.py` 无输出

- [ ] T068 安全复查：`grep -rn "token=" plugin/ dsh_tray/` 确认令牌只出现在 deeplink 拼接与 owned 账本读取处
  - [ ] 验收：无日志/通知正文中出现令牌；spool 与状态文件权限为 0600

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: 无依赖
- **Foundational (Phase 2)**: 依赖 Setup 完成；**阻塞所有用户故事**
- **US1 (Phase 3)**: 依赖 Foundational → 完成后即 MVP 可交付
- **US2 (Phase 4)**: 依赖 US1（需要通知已投递）
- **US3+US6 (Phase 5)**: 依赖 US1（需要通知数据）与 US2 的点击处理（列表行点击复用）
- **US4 (Phase 6)**: 依赖 US3（概览是面板的一个标签）
- **US5 (Phase 7)**: 依赖 US1（策略对象）
- **US7 (Phase 8)**: 依赖 US1（consumer）
- **US8 (Phase 9)**: 依赖 US1（通知管线）
- **Polish (Phase 10)**: 依赖全部所需故事完成

### 关键顺序约束

1. T021（`user-questions/request` 接线）必须先写测试断言「write 在 next 之前」——顺序错了会卡死提问。
2. T023（gdbus 投递）必须在 T031（点击回执）之前，否则无法手工验证点击。
3. T038（面板容器）必须先于 T044/T049（列表页与概览页），它们都挂在容器里。
4. T043（历史完整实现）必须先于 T044（列表渲染），列表读的是历史模块。

### 并行机会

- Setup：T002–T006 五条互不依赖，可同时开工
- Foundational：T008/T009 与 T010–T014 分属不同语言，可并行
- 每个故事的测试任务（[P]）可并行编写，但必须先红后绿
- US7 与 US8 相互独立，可并行

---

## Parallel Example: User Story 1

```bash
# 三条测试同时开工（不同文件、互不依赖）
Task: "T016 通知意图生成测试 plugin/tests/events.test.ts"
Task: "T017 托盘展示模型测试 dsh_tray/tests/test_intents.py"
Task: "T018 投递后端测试 dsh_tray/tests/test_delivery.py"

# 测试转绿后再并行实现
Task: "T019 通知意图生成 plugin/src/events.ts"
Task: "T022 托盘投递后端 dsh_tray/notify/delivery.py"
```

---

## Implementation Strategy

### MVP First

1. Phase 1 Setup → Phase 2 Foundational
2. Phase 3（US1）→ **停下验证检查点 1**
3. 此时「不看屏幕也知道跑完了」已可用，可以先用起来

### Incremental Delivery

| 增量 | 交付价值 | 检查点 |
|---|---|---|
| Setup + Foundational | 契约冻结，两侧可并行 | — |
| + US1 | MVP：通知能弹出来 | 检查点 1 |
| + US2 | 点通知回到会话 | — |
| + US3 + US6 | 面板可操作、历史可回查 | 检查点 2 |
| + US4 + US5 | 工作中/概览/设置齐备 | 检查点 3 |
| + US7 + US8 | 补投与 target-monitor 兼容 | — |
| + Polish | 文档、验收数据、清理 | — |

### 规模分布

XS/S：T004–T007、T014、T029、T042、T061、T067–T068 等
M：T010–T013、T019–T027、T030–T034、T038–T041、T043–T049、T051–T054
无 L / XL：V4 与 V6 在 plan 阶段已拆为 a/b，落到任务后最大 3 文件。

---

## Notes

- [P] = 不同文件、无未完成依赖
- 每个任务以独立 commit 结束；先红后绿
- 手工验收项（GUI）在任务下已写明操作步骤，不依赖额外文档
- 偏离说明：无。US6 顺序前移的原因已在 Phase 5 的 Slice note 中写明
