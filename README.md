# dsh-tray

KDE Plasma 6 (Wayland) 桌面上带托盘的 DeepSeek-Harness（`dsh web`）启动器 **+ 通知控制台**。
从托盘启动 / 停止 / 打开 Web UI，所有启停路径带竞态规避；DSH 的事件（跑完了、出错了、
需要你审批、需要你回答）会被抬成系统通知，点通知直接回到那个会话。

![托盘图标](icons/dsh-tray.svg)

## 它解决什么问题

DSH 本身**没有**桌面通知：它只在 Web UI 里显示状态。所以你让它跑一个长任务，只能
盯着浏览器；切到别的事上，就不知道它跑完没有、有没有在等你。

这个仓库做两件事：

1. **托盘启动器**（原有能力）：启停 DSH、管令牌、竞态安全。
2. **通知控制台**（本规格新增）：插件把事件写进 spool，托盘读出来投递成系统通知，
   并存进历史供事后回查。托盘是**唯一投递者**，插件是**唯一策略点**。

分工的理由：策略（哪些事件值得打扰你）随版本变，放在插件里改起来快；投递（系统通知、
点击、历史）依赖桌面环境，放在托盘里才能跨平台。

## 用法

```sh
# 图形托盘（推荐，也可从应用菜单 "DSH Tray" 启动）
./scripts/dsh-tray.sh

# 命令行
./dsh-tray.py --status      # 打印当前状态（只读）
./dsh-tray.py --start       # 确保 DSH 在运行（已有则接管）
./dsh-tray.py --restart     # 重启 DSH（停 + 起，中间态不可见）
./dsh-tray.py --stop        # 停止 DSH
./dsh-tray.py --selftest    # 竞态自检（假 dsh，不碰 3080）
```

开机自启已装到 `~/.config/autostart/dsh-tray.desktop`：登录后托盘出现，
**DSH 本身不会自动启动**，需要时从托盘菜单点「启动 DSH」。

## 面板（左键托盘图标）

四个标签：

| 标签 | 内容 |
|---|---|
| 未查看 | 还没看过的通知；点一条即标记已读并跳到该会话 |
| 已查看 | 看过的通知，按日期分组（今天 / 昨天 / 本周 / 日期），**不删除**，可随时翻回去 |
| 工作中 | 正在跑的会话：标题、第几轮、当前工具、已跑时长（每秒自增） |
| 概览 | DSH 及其子进程的 CPU / 内存；只在面板打开时采样 |

面板顶部是控制区，五态显示（未运行 / 启动中 / 运行中·自有 / 运行中·接管 / 停止中 /
失败），主操作随状态切换。接管态会提示「拿不到访问令牌」，并建议用「重启」换成自有实例。

右键托盘图标仍是菜单，新增「打开面板」。

## 通知

### 三档预设

| 预设 | 会通知什么 |
|---|---|
| 安静 | 需要你（审批 / 提问）+ 提示（例如「你可能卡住了」） |
| 标准 | 安静 + 完成与出错（跑完、出错、阻塞、超限） |
| 详细 | 标准 + 其它信息性（后台任务、目标变更、取消与中断） |

在 DSH 设置页的「DSH 通知」分区切换，**即时生效**，不需要重启。逐组改动后标签变成
「自定义」；把值改回与某档一致时标签自动回到该档。

### 通知的行为

- **点通知回到会话**：点通知本体或「打开会话」按钮，直接落在该会话。
- **需要你的通知停留 5 分钟**（可在设置页调成 5 秒 ~ 1 小时），其余 5 秒后消失。
  刻意不提供「永不消失」：实测那样会占住 Plasma 的通知弹窗位，你不点掉它，**后续通知
  全部排队不显示**，看起来就像通知功能坏了。
- **同一会话的新通知顶替旧横幅**（D-Bus `replaces_id`），不会在屏幕上排一串过期的
  「需要你审批」。历史里全都留着。
- **跑完的通知会等子会话**：父会话结束但子代理还在跑时，先等最多 2 秒；
  超过 15 分钟仍未收尾就丢弃，不误报。
- **托盘不在时不丢**：事件留在 spool 里，托盘下次启动补投。超过 2 小时的只进历史、
  不弹系统通知，tooltip 与面板顶部显示「错过 N 条」。
- **与 target-monitor 兼容**：它注入的 notice（「你可能卡住了」）会被抬成「提示」类
  桌面通知，会话内的那条提示照旧存在。

## 菜单

| 状态 | 菜单 |
|---|---|
| 未运行 | 打开 Web UI（灰）· **启动 DSH** · 打开面板 · 退出托盘 |
| 启动/停止中 | 打开（灰）· 重启/停止（灰）· 退出托盘 |
| 运行中 | **打开 Web UI** · **重启 DSH** · **停止 DSH** · 退出托盘 |

左键单击图标 = 打开 Web UI；右键 = 菜单。**「重启 DSH」与「停止 DSH」都有
确认对话框，默认按钮是「取消」**——两者都会连带结束 DSH 下所有会话与 MCP
子进程，其中可能就有你正在对话的那个。

重启除了换新进程，还有一个顺带的效果：接管的实例（拿不到访问令牌）重启后会
变成自有实例，重新获得带令牌的 URL，把 401 一并解决。

## 托盘状态与令牌

图标：白鲸 = 运行中（含启动/停止进行中），灰鲸 = 未运行/失败。图标是方形画布
+ 每侧 12% 透明留白，字形约占 76% 宽——与面板上邻居图标的视觉重量对齐（实测
邻居字形 21–26 px、槽位 38–44 px）。托盘里显示的名字是 `DSH-Tray`。
tooltip 会写明「由托盘启动」还是「外部启动 PID nnn」。

这个区别是承重的：`dsh web` 的访问令牌是**进程级随机数**，只出现在
启动时的 stdout 里。所以：

- **由托盘启动**：托盘存了带令牌的 URL（`~/.local/state/dsh-tray/owned.json`），
  打开即登录。
- **外部启动**（手动从终端跑的、或重启托盘前就存在的）：拿不到令牌，
  只能打开裸 URL，依赖浏览器里已有的登录 cookie（默认 30 天）。
  如果浏览器提示未授权，从菜单「停止 DSH」再「启动 DSH」一次即可。

## 竞态规避

全部 10 条竞态的设计与验证见 [docs/design.md](docs/design.md)。
`--selftest` 用假 dsh 在临时端口复现其中 10 条（R1/R2/R3/R5/R6/R7/R8/R9/R10/R11），
当前 10/10 通过。核心手段：

- **操作锁**（`flock`）串行化所有 start/stop：连点、autostart 撞手动、
  托盘与命令行同时操作都只会产生一次实际动作。
- **锁后重探**：拿到锁的第一件事是按 `/proc` 事实重算状态，不信任操作前
  的观察。
- **端口反查身份**：`/proc/net/tcp` 取 listening inode → 扫 `/proc/*/fd`
  归属 → 校验 cmdline。端口上是不是 dsh、是谁起的，都以探测为准。
- **竞态败方接管**：并发 start 输掉的一方（子进程因 EADDRINUSE 早退）
  会接管胜出者，而不是报错。
- **单实例托盘**：第二个托盘进程直接退出。

## 故障排查

| 症状 | 处置 |
|---|---|
| tooltip 显示"启动失败：端口被非 dsh 进程占用" | 有别的程序占了 3080。`ss -ltnp \| grep 3080` 找到它，处理掉再启动 |
| 外部启动的实例打开后 401 | 令牌拿不到是设计如此；菜单里停止再启动一次即可。或直接在浏览器访问带 token 的旧 URL（30 天 cookie 内不需要） |
| 托盘不出现 | `./dsh-tray.py --status` 先看 DSH 状态；`ps -eo pid,args \| grep dsh-tray` 看进程在不在。Plasma 托盘设置里可能把图标藏了（系统设置 → 通知与时间 → 托盘） |
| 启动托盘时报「不能从 DSH 的工具会话里启动」 | 这是有意拦截。DSH 的每次工具调用都在独立的 systemd scope 里，scope 一拆除（工具调用结束、DSH 重启）会连带杀掉托盘。请从应用菜单「DSH-Tray」或开机自启启动 |
| 通知弹不出来 | 看 tooltip 是否写着「通知不可用」。`gdbus call --session --dest org.freedesktop.Notifications --object-path /org/freedesktop/Notifications --method org.freedesktop.Notifications.GetCapabilities` 确认服务在。没有 `gdbus` 时会退回 `notify-send`（**没有动作按钮**，点通知不会跳转） |
| 点通知没反应 | 通知动作需要 `gdbus`。`which gdbus` 为空时只能回退 `notify-send`。另外「接管」的实例拿不到令牌，跳过去可能 401，用「重启」换成自有实例 |
| 设置页没有「DSH 通知」分区 | 确认插件已装：`dsh --profile web --dump-config \| grep tray-notify`。改完插件要重启 DSH 才生效 |
| 面板不出现（左键无反应） | 面板用 `Qt.Tool` 窗口，不抢任务栏；若被其他窗口遮住，用右键菜单「打开面板」。Wayland 下 `tray.geometry()` 返回 0×0 是已知行为，面板会退化到屏幕右上角 |
| 日志 | `~/.local/state/dsh-tray/logs/dsh-web.log`（子进程 stdout/stderr）、`~/.local/state/dsh-tray/tray.log`（托盘与通知管线，令牌已脱敏）、`~/.dsh/run/tray-notify/plugin.log`（插件侧）、`~/.dsh/run/tray-notify/events.jsonl`（spool，可 `tail -f` 看事件流） |

## 与 DSH 的进程隔离

两处隔离，都是为了「托盘和 DSH 互不牵连」：

1. **托盘不钻进 DSH 的工具 scope**。`dsh-tray` 启动时读 `/proc/self/cgroup`，
   发现自己在 `dsh-subprocess-*` 里就拒绝启动（exit 2）并说明原因——那个 scope
   被回收时会把托盘一起带走，这正是「重启 DSH 后托盘消失」的成因。
2. **dsh 不留在托盘的 cgroup 里**。托盘若由桌面以 systemd 单元启动，该单元
   `KillMode=control-group`，dsh 作为子进程会同处一个 cgroup，于是「退出托盘」
   会把 dsh 连根拔掉。所以托盘用 `systemd-run --user --scope` 把 dsh 放进独立
   scope：实测父进程被 SIGKILL 后，scope 内的 dsh 仍存活。
   `systemd-run` 不可用时会自动退回不加包装的启动方式（宁可少一层隔离，也不能起不来）。

## 依赖

- 系统 `python3`（PyQt6 在 `/usr/lib/python3/dist-packages`，**不要用 venv 跑**，
  venv 里没有 PyQt6）
- `~/.local/bin/dsh`（已有的 NVM 包装脚本；找不到时退回 PATH 里的 `dsh`）
- Plasma 的 StatusNotifier 托盘宿主（KDE 默认有）
- **`gdbus`**（`glib2` 提供）——通知的动作按钮靠它；缺失时退回 `notify-send`，
  通知仍会弹出，但点通知不会跳转会话
- Node ≥ 22（只用于构建与测试插件；运行时不需要 Node）

## 文件

```
dsh-tray.py                    入口与 CLI
dsh_tray/probe.py              /proc 探测（端口→pid 反查、cmdline 判定、子进程枚举）
dsh_tray/locks.py              flock 单实例锁、操作锁、自有实例账本
dsh_tray/lifecycle.py          状态机与 start/adopt/stop（不依赖 Qt）
dsh_tray/selftest.py           竞态自检
dsh_tray/icons.py              鲸鱼 SVG → QIcon（含未读角标）
dsh_tray/notify/types.py       跨进程契约类型（与 plugin/src/types.ts 对齐）
dsh_tray/notify/spool.py       增量读 spool（偏移带 inode）
dsh_tray/notify/intents.py     去重窗口、紧急度、相对时间
dsh_tray/notify/delivery.py    gdbus 投递（回退 notify-send）
dsh_tray/notify/history.py     历史持久化、淘汰、日期分组
dsh_tray/notify/consumer.py    消费循环（读→去重→投递→入库）
dsh_tray/notify/sessionstate.py 活动会话表与时长
dsh_tray/notify/sampling.py    /proc 采样
dsh_tray/notify/deeplink.py    会话深链拼接（令牌注入）
dsh_tray/notify/click.py       点击处理（标记已读→拼链接→打开）
dsh_tray/notify/log.py         托盘日志（令牌脱敏）
dsh_tray/platform/             平台层（base 协议 + linux 实现）
dsh_tray/ui/tray.py            托盘图标、菜单、面板接线
dsh_tray/ui/panel.py           面板容器与四标签
dsh_tray/ui/control.py         控制区五态
dsh_tray/ui/notiflist.py       通知列表与批量操作
dsh_tray/ui/working.py         工作中页
dsh_tray/ui/overview.py        概览页
plugin/                        DSH 插件（TypeScript）
  src/index.ts                 事件接线 → spool
  src/events.ts                事件 → 通知意图（纯函数）
  src/config.ts                四组开关与三档预设
  src/spool.ts                 NDJSON 写入与轮转
  src/client/index.ts          深链 + 设置分区（客户端）
scripts/dsh-tray.sh            启动包装（补 NVM/PATH 环境）
scripts/build-plugin.sh        插件构建与安装
docs/design.md                 设计共识（已批准）
specs/001-notify-console/      规格、计划、任务、验收记录
design/notification-panel.html 交互设计稿
icons/                         桌面图标（方形画布版）
```

## 设计取舍从哪来

- `research/harness-notifications.md`：Claude Code / Codex / Gemini CLI / OpenCode 四家的
  通知事件模型调研，以及「DSH 本身无桌面通知、生态里四个第三方插件都只直推系统通知」的
  结论——与本仓库「插件只写策略、托盘统一投递」的差异点由此而来。
- `docs/design.md`：托盘与面板的设计共识（含实测环境事实与通知行为决策表）。
- `specs/001-notify-console/`：规格、计划、契约、数据模型、任务与验收记录。

## 排查：横幅不出现

`scripts/check-banner.py` 把「横幅到底有没有弹」从主观判断变成可重复的数字：
发送前后各截一张图，比对右上角横幅区的像素变化。

```sh
python3 scripts/check-banner.py --selftest   # 先证明检测器有效（不需要桌面）
python3 scripts/check-banner.py --keep       # 实测；--keep 保留截图便于人工复核
```

退出码：0 = 检测到横幅，1 = 没检测到，2 = 环境不满足。

⚠️ **区域用比例坐标而不是像素**。截图的分辨率取决于工具：`spectacle` 在本机给物理像素
（2560×1600），而门户截图给的是预览尺寸（1463×915）。写死像素会让裁剪区落到别处，
测出「永远 0%」的假阴性——这个坑我踩过，并因此得出过「Plasma 不渲染通知」的错误结论。

⚠️ 这个脚本只回答「那一块区域的像素变了没有」，**不区分瞬时横幅与通知中心里的常驻卡片**。
判读时请先关掉现存通知再测（`for i in $(seq 1 300); do gdbus call … CloseNotification "uint32 $i"; done`），
`--keep` 会保留截图供核对。

### 本机限制：带动作按钮的通知不弹横幅

实测（Plasma 6.6.6）：`actions` 非空时，通知服务接受并返回 id，但**任何位置都不渲染**；
`actions` 为空则正常弹出。换动作键名、标签、hints、urgency、超时都不改变这个结果。
全屏 OCR 也确认它没渲染在别处。这与 `notify-send --action` 报「Actions are not supported
by this notifications server」互为印证。

因此「点横幅直接跳会话」与「横幅能弹出来」在本机二选一。当前实现的选择见
`specs/001-notify-console/acceptance.md` 的「待决策」一节。

**先查通知小程序在不在**。横幅由 Plasma 的「通知」小程序渲染；这个小程序不在面板上时，
`org.freedesktop.Notifications` 依然存在、依然接受通知并分配 id，但**什么都画不出来**——
连 `notify-send` 也一样。判断方法：

```sh
export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus
gdbus call --session --dest org.kde.plasmashell --object-path /PlasmaShell \
  --method org.kde.PlasmaShell.evaluateScript \
  "var out=[]; var ps=panels(); for(var i=0;i<ps.length;i++){ var ws=ps[i].widgets(); for(var j=0;j<ws.length;j++){ var t=String(ws[j].type); if(t.indexOf('notif')>=0){ out.push(t); } } } print(out.length?out.join(','):'no notifications applet');"
# 输出 'no notifications applet' → 横幅不可能出现，去「系统设置 → 通知」或托盘设置里把通知加回去
```

顺带确认勿扰状态（`false` 才是正常）：

```sh
gdbus call --session --dest org.freedesktop.Notifications \
  --object-path /org/freedesktop/Notifications \
  --method org.freedesktop.DBus.Properties.Get org.freedesktop.Notifications Inhibited
```

## 开发

```sh
# 托盘侧测试（含离屏 GUI 断言）
python3 -m unittest discover -s dsh_tray/tests -t .

# 竞态自检（用假 dsh，不碰 3080）
./dsh-tray.py --selftest

# 插件
cd plugin
npm install --legacy-peer-deps   # 会装 @deepseek-ai/* 作为 devDependency（仅类型）
npm run typecheck
npm test                          # node --test 自动发现 tests/*.test.ts
npm run build                     # tsc + 客户端单文件打包

# 装进 web profile（本地开发用 link:）
dsh plugin --profile web add "link:$PWD/plugin"
dsh --profile web --dump-config | grep tray-notify   # 确认已生效
```

**不要**给 `plugin/node_modules` 建指向 DSH 全局安装的符号链接：`npm install` 会顺着
链接进入目标目录，把 DSH 的 `@deepseek-ai/*` 判为 extraneous 并删除（实测删掉 306 个
包，`dsh` 命令当场失效）。

安装位置：`~/.local/share/applications/dsh-tray.desktop`（应用菜单）、
`~/.config/autostart/dsh-tray.desktop`（自启）。
