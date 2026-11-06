# dsh-tray

KDE Plasma 6 (Wayland) 桌面上带托盘的 DeepSeek-Harness（`dsh web`）启动器。
从托盘启动 / 停止 / 打开 Web UI，所有启停路径带竞态规避。

![托盘图标](icons/dsh-tray.svg)

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

## 菜单

| 状态 | 菜单 |
|---|---|
| 未运行 | 打开 Web UI（灰）· **启动 DSH** · 退出托盘 |
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
| 日志 | `~/.local/state/dsh-tray/logs/dsh-web.log`（子进程 stdout/stderr）与 `~/.local/state/dsh-tray/tray.lock`（锁持有者 pid） |

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

## 文件

```
dsh-tray.py              入口与 CLI
dsh_tray/probe.py        /proc 探测（端口→pid 反查、cmdline 判定、子进程枚举）
dsh_tray/locks.py        flock 单实例锁、操作锁、自有实例账本
dsh_tray/lifecycle.py    状态机与 start/adopt/stop（不依赖 Qt）
dsh_tray/ui.py           托盘图标、菜单、确认对话框
dsh_tray/icons.py        鲸鱼 SVG → QIcon
dsh_tray/selftest.py     竞态自检
scripts/dsh-tray.sh      启动包装（补 NVM/PATH 环境）
docs/design.md           设计共识（已批准）
icons/                   桌面图标（方形画布版）
```

安装位置：`~/.local/share/applications/dsh-tray.desktop`（应用菜单）、
`~/.config/autostart/dsh-tray.desktop`（自启）。
