# DSH-Tray&Notice — AGENTS.md

<!-- AUTO:PROJECT-META -->
## 项目元信息

- 项目：DSH-Tray&Notice
- 目标：在桌面托盘里管理 `dsh web` 的生命周期，并把 DSH 的事件抬成真人可感知的通知；
  托盘本身要跨 Linux（KDE Plasma / Wayland）与 Windows。
- 技术栈：Python 3.14（系统 `python3` + PyQt6，**不能用 venv**）；TypeScript（DSH 宿主插件，`tsc` 直出，无 bundler）
- 类型：桌面托盘应用 + DSH 宿主插件（双语言仓库）
- 初始化日期：2026-11-06
<!-- /AUTO:PROJECT-META -->

<!-- SPECKIT START -->
## 当前规格

- 规格：`specs/001-notify-console/spec.md`（托盘通知控制台，S1 通知管线 + S2 面板）
- 实现计划：`specs/001-notify-console/plan.md`（6 个垂直切片 V1–V6，3 个检查点）
- 设计制品：`research.md`（实测探针与选型）/ `data-model.md`（跨进程数据形状）/
  `contracts/contracts.md`（spool、插件接线、平台后端、深链）/ `quickstart.md`
- 交互基准：`design/notification-panel.html`（实现对照它验收）
- 多平台底座（S3）尚未立规格
<!-- SPECKIT END -->

<!-- AUTO:STRUCTURE -->
## 目录结构

```
DSH-Tray&Notice/
├── dsh-tray.py            入口与 CLI（Qt 延迟导入）
├── dsh_tray/
│   ├── probe.py           /proc 探测：端口→pid 反查、cmdline 判定、子进程
│   ├── locks.py           flock 单实例锁、操作锁、自有实例账本
│   ├── lifecycle.py       状态机与 start/adopt/stop（不依赖 Qt）
│   ├── ui/                托盘与面板（tray.py 为托盘本体）
│   ├── icons.py           鲸鱼 SVG → QIcon
│   ├── selftest.py        竞态自检（假 dsh，不碰 3080）
│   ├── notify/            通知域（spool、投递、历史、会话表、采样）
│   └── platform/          平台层（base 协议 + linux 实现）
├── plugin/                DSH 插件（TypeScript，服务端 + 客户端）
├── design/                交互设计稿（HTML，可交互）
├── research/              调研记录
├── docs/                  设计共识与说明
├── scripts/               启动包装与 .desktop
├── icons/                 桌面图标
└── .specify/              speckit 脚手架（模板、memory、脚本）
```

> **路径含 `&`**：仓库目录名带 `&`，任何 shell 命令里的路径都必须加引号，
> 否则 `&` 会被当成后台执行。`cd "…/DSH-Tray&Notice"` 而不是裸写。
<!-- /AUTO:STRUCTURE -->

<!-- AUTO:BUILD -->
## 构建与运行

- 运行托盘：`./scripts/dsh-tray.sh`（补 NVM/PATH 环境；**不要**用 venv）
- 只读状态：`./dsh-tray.py --status`
- 启停：`./dsh-tray.py --start | --restart | --stop`
- 竞态自检：`./dsh-tray.py --selftest`（用假 dsh 在临时端口跑，不碰 3080）
- 插件：`cd plugin && npm install --legacy-peer-deps` → `npm run typecheck` / `npm test` / `npm run build`
- 托盘测试（含离屏 GUI）：`python3 -m unittest discover -s dsh_tray/tests -t .`
  （GUI 用例需 `QT_QPA_PLATFORM=offscreen`；直接跑 discover 也能过，因为用例内部自己设了）
- 装插件进 profile：`dsh plugin --profile web add "link:$PWD/plugin"`，再用
  `dsh --profile web --dump-config | grep tray-notify` 确认（**不写 cordis.patch.yml**，
  走的是 `package.json` 的 `dsh.profile.bundles` + 插件自带 patch）
- 代码索引：`~/.local/bin/codegraph status`（`~/.local/bin` 不在 PATH 里，用绝对路径）
<!-- /AUTO:BUILD -->

## 硬约束

这几条是踩过坑换来的，改动时先读理由再动手。

1. **用系统 `python3`，不用 venv**。PyQt6 来自 `/usr/lib/python3/dist-packages`，
   venv 化会丢掉它，托盘直接起不来。
2. **`lifecycle.py` 与 `probe.py` 不 import Qt**。这条保证 `--status/--start/--stop/--selftest`
   能在无图形环境跑，也保证竞态路径可被自动验证。加 Qt 依赖会让这条能力消失。
3. **平台分支只允许出现在 `dsh_tray/platform/`**。其余模块通过接口调用，不写 `if sys.platform`。
4. **不引入 `psutil` 等新第三方依赖**。现有探测刻意不 fork、不依赖外部命令；
   跨平台能力用标准库 + `ctypes` 解决。
5. **插件是唯一策略点，托盘是唯一投递点**。插件决定"哪些事件值得通知、文案是什么"，
   托盘负责系统通知、历史与点击。托盘**不解析** DSH 的配置文件（那是要读全文、要确认的那类文件）。
6. **未在真机验证的平台必须标注**。没有 Windows 机器就写"未验证 + 验证步骤"，
   不得在文档、提交信息或汇报里暗示已验证。
7. **绝不要给 `plugin/node_modules` 建指向 DSH 全局安装的符号链接**。
   npm 会顺着符号链接进入目标目录，把 DSH 的 `node_modules/@deepseek-ai/*` 判为
   "extraneous" 并删除——本机实测删掉 306 个包，`dsh` 命令当场失效（2026-11-06，
   已用 `npm i -g @deepseek-ai/dsh@0.2.1-rc.5` 恢复）。需要宿主类型时，把
   `@deepseek-ai/*` 装成 `devDependencies`（代码里只 `import type`，运行时不依赖）。

## 工具优先级

1. 理解代码结构优先用 codegraph（`codegraph_explore`），不可用时降级为 grep/glob/read。
2. 文件操作用专用工具（read/write/edit/glob/grep），不滥用 shell。
3. 涉及 DSH 宿主契约（事件名、类型、设置 API）时，**以本机安装的包为准**：
   `/home/firenzeclaw/.nvm/versions/node/v24.22.1/lib/node_modules/@deepseek-ai/dsh/node_modules/@deepseek-ai/<pkg>/lib/types/`。
   不要凭记忆写事件名或字段。

<!-- AUTO:CONVENTIONS -->
## 编码约定

### 命名

- 函数：动宾结构（`find_listener`、`read_owned_record`）
- 变量：名词短语（`token_timeout`），禁 1-2 字符名（循环下标、`_` 除外）
- 常量：`UPPER_SNAKE_CASE`；类：PascalCase

### 控制流

- Guard clauses 优先，嵌套 ≤3 层
- 复杂条件提取为具名布尔变量
- 函数超过约 50 行、文件超过约 400 行时考虑拆分（既有例外须写明理由）

### 注释

**沿用仓库既有风格**：模块用 docstring 说明职责与关键约束，注释解释 why 而非 how。
不套用"每文件前两行必须写变更历史"这类模板——现有 2000 行代码不是那个形态，
强行引入会让新旧文件风格分裂。

- 注释与 docstring 用中文；标识符、命令、API 名保留英文
- 状态标记：`[WIP]` / `[DONE]` / `[UNCERTAIN]` / `[WORKAROUND]`
- 必须写清理由的位置：竞态规避手段、平台差异、超时与阈值常量的取值依据、
  与 DSH 宿主契约的对应关系（引用具体文件与行号）
- 禁止：行尾注释解释代码本身、TODO 当状态用

### 类型与不可变

- Python：公开函数标注完整签名；避免可变默认参数；数据类优先 `@dataclass(frozen=True)`
- TypeScript：禁止 `any`，禁止非必要断言；外部输入在边界处校验一次

### 错误处理

- 捕获后要么处理、要么带上下文抛出；空 `except` / 空 `catch` 一律不可接受
- 面向用户的错误信息要给出**下一步动作**，不要只说"失败了"
<!-- /AUTO:CONVENTIONS -->

## 设计约束（本项目特有）

- **设计稿先行**：托盘面板的交互改动先在 `design/notification-panel.html` 里改，
  用户确认后再落 Qt 控件。改稿比改代码便宜。
- **通知与托盘的分工不得混**：面板负责"看状态 + 操作 + 回会话"，
  系统通知负责"你不在电脑前也能知道"。两者共用同一份数据，但不共用代码路径。
- **概览页的进程采样必须自采**，不能走插件上报——DSH 卡死时正是最需要看进程的时候。
- **跨进程只通过 spool 耦合**：`plugin/src/types.ts` 与 `dsh_tray/notify/types.py` 各写
  一份契约类型（刻意不共享代码），改字段必须同时改两侧并把 `SCHEMA_VERSION` / `v` 加一。
  契约文档是 `specs/001-notify-console/contracts/contracts.md`，数据形状见 `data-model.md`。

## Git 约定

- 提交格式：`<type>(<scope>): <subject>`，type ∈ `feat`/`fix`/`refactor`/`test`/`docs`/`chore`
- 一次提交一件事；格式化/重构与功能变更分开
- 提交前：`git diff --staged` 自查 → 查密钥 → 跑 `--selftest`
- 破坏性操作（`reset --hard`、`clean -fd`、强推）执行前必须说明会丢什么并等确认

## 安全红线

- 令牌（`dsh web` 的访问令牌）只允许出现在 `~/.local/state/dsh-tray/owned-<port>.json`
  与打开的 URL 里，**不得写入日志、不得进 git、不得在通知正文里出现**
- 通知正文可能含命令与路径：默认截断到合理长度，不整段回显
- spool 与状态文件权限收紧到 0600；目录 0700

## 质量门

- 没有失败的测试就不写生产代码（TDD）
- 三条回归基线，重构后必须全部保持：
  - `python3 -m unittest discover -s dsh_tray/tests -t .`（当前 186 tests）
  - `cd plugin && npm test`（当前 116 tests）
  - `./dsh-tray.py --selftest`（10/10，竞态行为）
- 不审查不合并：正确性 / 可读性 / 架构 / 安全 / 性能五轴
- 详细原则见 `.specify/memory/constitution.md`
