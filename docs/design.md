# DSH 托盘启动器 + 通知控制台 · 设计共识

状态：已批准（2026-11-02 初版；2026-11-06 并入通知控制台）
范围：启动器 + 托盘 + 通知管线 + 面板。**DSH 本体不改动**——通知能力以插件形式
挂在 profile 上，托盘不解析 DSH 的配置文件。

## 目标

在 KDE Plasma 6 (Wayland) 桌面上，用一个带托盘的启动脚本管理 `dsh web`：
从托盘启动/停止/打开 Web UI，并对并发启停做竞态规避。

## 已确认的决策

| 决策点 | 结论 | 理由 |
|---|---|---|
| 托盘交互 | 右键菜单：打开 Web UI / 重启 DSH / 停止 DSH / 退出托盘 | 显式菜单项避免误触；符合 Plasma 惯例 |
| 关闭强度 | SIGTERM → 宽限超时 → SIGKILL | dsh 自带 5s 优雅退出窗口（`PROCESS_SHUTDOWN_TIMEOUT_MS = 5e3`） |
| 已有实例 | 探测并接管（单实例模型） | 避免同机跑多个 dsh；接管后菜单里的停止也能关它 |
| 开机自启 | 仅托盘自启，DSH 本身手动启动 | 不白白常驻一个 node 进程 |
| 图标颜色 | 纯白 `#FFFFFF`（运行）/ 灰 `#8A8F98`（停止） | 与 Plasma 面板单色图标风格一致；面板实测深色（#222222），白鲸对比最强 |
| 图标留白 | 方形画布 + 每侧 12% 透明边（字形占 76% 宽） | 面板实测邻居图标字形 21–26 px、槽位 38–44 px，即四周约 20% 透明边；原图 1.36:1 贴边渲染会横向顶满槽位，比邻居明显偏大 |
| dsh 的 cgroup | 用 `systemd-run --user --scope` 把 dsh 放进独立 scope | 托盘若由桌面以 systemd 单元启动，该单元 `KillMode=control-group`；dsh 作为子进程会同 cgroup，退出托盘就会把 dsh 带走。独立 scope 后父子分属不同 cgroup，实测父进程被 SIGKILL 后子进程存活 |
| 应用名 | `DSH-Tray`（`applicationName` + `DesktopFileName=dsh-tray`） | 不设置时 Qt 用脚本文件名 `dsh-tray.py`，在托盘里像是没装好的脚本 |
| 停止后 | 托盘常驻，图标变灰 | 符合"托盘自启、DSH 手动启动" |
| 实现方案 | 单 Python 进程（PyQt6），`lifecycle` 不依赖 Qt | 竞态在单进程内可真正串行化；CLI 路径可无 GUI 验证 |

## 通知控制台（2026-11-06 并入）

### 分工

| 角色 | 负责 | 不负责 |
|---|---|---|
| 插件（`plugin/`） | 决定哪些事件值得通知、文案是什么、去重键 | 投递、历史、点击 |
| 托盘（`dsh_tray/notify/`） | 读 spool、去重、投递、存历史、处理点击 | 判断该不该通知 |

契约是文件 spool：插件写 NDJSON，托盘增量读。选文件而不是 socket，是因为托盘可能比
DSH 晚启动、早退出、被杀重启——文件让两侧完全解耦，托盘下次启动照样补投。

### 面板

四标签（未查看 / 已查看 / 工作中 / 概览）+ 控制区五态。左键开面板、右键菜单。
设计稿见 `design/notification-panel.html`，实现对照它验收。

为什么用 `Qt.Tool | FramelessWindowHint` 而不是 `Qt.Popup`：**后者在 Wayland 上创建
失败**（实测 `Failed to create grabbing popup … has no transientParent`），窗口根本
不可见。代价是 `Qt.Tool` 会抢焦点，用 `focusOut` 自动隐藏补偿。

### 通知行为

| 决策 | 结论 | 理由 |
|---|---|---|
| 投递方式 | `gdbus` 显式类型调用 | `notify-send --action` 报「Actions are not supported」，而 `GetCapabilities` 含 `actions`；`gdbus` 实测成功返回 `uint32 155` |
| gdbus 参数格式 | `uint32 0`（空格） | 冒号写法报「解析 u 类型的第 2 个参数时发生错误」，且**静默回退到 notify-send**（通知照弹、没有按钮） |
| 点击回执 | `QDBusConnection.connect` + `@pyqtSlot("uint","QString")` | PyQt6 是 5 参数形式，直接传绑定方法；PyQt5 的六参数写法报 too many arguments |
| 令牌 | 只在托盘一侧，插件只写 `?session=` | 令牌是进程级随机数；插件拿不到也不该拿 |
| 已查看 | 不删除，按日期分组长期保留 | 回查「上周那个任务后来怎么样了」 |
| 预设 | 安静保留「提示」 | 提示承载「你可能卡住了」，是安静模式下仍值得打扰的信息 |
| 取消/中断 | 归 `other` 组，默认不通知 | 用户自己按的停止，再弹一条是噪声 |
| 挂起完成 | 父会话结束等子会话，宽限 2s / 上限 15min | 子代理还在跑时说「已完成」是谎报 |
| 补投窗口 | 2 小时 | 更早的事件弹出来只会让人困惑「这是刚发生的吗」 |

### 关键环境事实（通知部分，实测）

| 事实 | 证据 |
|---|---|
| `Qt.Popup` 在 Wayland 创建失败 | `Failed to create grabbing popup … has no transientParent` |
| `tray.geometry()` 在 Plasma Wayland 返回 0×0 | 锚点退化到屏幕右上角 |
| `notify-send --action` 不可用但 D-Bus 支持 actions | `GetCapabilities` 含 `actions`；`gdbus` 返回 `(uint32 158,)` |
| 离屏下 widget 可实例化且布局真实计算 | `QT_QPA_PLATFORM=offscreen` 下面板实测 378×276 |
| `ActionInvoked` 可端到端接收 | `gdbus emit` 模拟后收到 `(159, 'default')` |
| `TurnEndReason` 是 `{kind}` 对象联合 | `dsh-session/lib/types/types.d.ts:166` |

## 关键环境事实（实测）

| 事实 | 证据 |
|---|---|
| 桌面 KDE Plasma 6.6.6 / Wayland | `plasmashell --version`、`$XDG_SESSION_TYPE=wayland` |
| SNI 托盘宿主已就绪 | `IsStatusNotifierHostRegistered` → `true` |
| PyQt6 6.10.2 可用，`QSystemTrayIcon` 能注册进 Plasma 托盘 | 探针进程出现在 `RegisteredStatusNotifierItems` |
| 无 pystray / AppIndicator / `PyQt6.QtSvg` 绑定 | import 全部失败 |
| 但 SVG **图像格式插件**在（`libqt6svg6`） | `QIcon("*.svg")` 可用，`QImageReader.canRead()` 为真 |
| `dsh web` 默认端口 3080，支持 `--port/--no-open/--host` | `dsh web --help` |
| 裸访问 `http://127.0.0.1:3080` 返回 401 | curl 探测 |
| 访问令牌是**进程级** `randomBytes`，只出现在启动打印行 | `dsh-client-connection/lib/index.js:294` `processLaunchToken` |
| `--no-open` 不抑制 URL 打印（`printUrl` 默认 true） | `dsh-web-app/lib/index.js:162` |
| 冷启动到打印令牌行约 **13.1 s** | 实测（端口 3181） |
| SIGTERM 后 **0.53 s** 退出，无子进程残留，端口释放 | 实测 |
| DSH 的每次工具调用跑在独立 systemd scope `dsh-subprocess-<dshpid>-<hash>.scope` | `journalctl --user` 实测 |
| 托盘若在该 scope 内启动，scope 拆除时会被 SIGTERM+SIGKILL 连带杀掉 | 实测事故：托盘随一次 DSH 重启消失 |
| `systemd-run --user --scope` 下 `Popen.pid` 与命令自身 pid 一致，stdout 多一行 banner | 实测 |
| 父进程被 SIGKILL 后，独立 scope 内的子进程仍存活 | 实测 |

**承重结论**：令牌是进程级的，所以**只有自己拉起的实例才拿得到带令牌的 URL**。接管来的实例只能打开裸 URL，依赖浏览器里已有的 cookie（`cookieMaxAgeDays` 默认 30 天）。这个区别必须显式呈现给用户，否则用户会对着 401 猜。

## 状态机

```
STOPPED ──start()──▶ STARTING ──等到令牌行──▶ RUNNING(owned, 有 url+token)
   ▲                    │                        │
   │                    └─子进程早退─▶ FAILED     ├─外部出现 dsh──▶ RUNNING(adopted, 无令牌)
   │                                              │
   └────stop()────────────────────────────────────▶ STOPPING ──grace──▶ SIGKILL ──▶ STOPPED
```

`owned` / `adopted` 必须分开：决定「打开 Web UI」是用带令牌 URL 还是裸 URL，也决定 tooltip 文案。

## 竞态矩阵

| # | 竞态 | 检测 | 规避 |
|---|---|---|---|
| R1 | 并发 start（连点、autostart 撞手动） | 跨进程 `flock(op.lock)` + 进程内 `RLock` | 后到者拿到锁时状态已是 STARTING/RUNNING，直接返回，不重复 spawn |
| R2 | 端口被**非 dsh** 占用 | `/proc/net/tcp` 取 listening inode → 扫 `/proc/*/fd` 反查 pid → 校验 cmdline | 报错并列出占用者，不 spawn 也不 kill |
| R3 | 预检到 spawn 之间的 TOCTOU | spawn 后解析结果 | 不信任预检；子进程早退且端口已出现 dsh → 判为竞态败方，收拾自家子进程并接管胜出者 |
| R4 | 子进程启动即失败 | exit code + 日志尾部 | 进 FAILED，把日志摘要呈现给用户 |
| R5 | 等令牌行超时 | 令牌等待带超时（45 s，>实测 13 s 的 3×余量） | 超时 → SIGTERM 收尾 → FAILED |
| R6 | 并发 stop | 同一把 op 锁 + STOPPED 幂等 | 第二次调用在锁上等待，拿到锁时已是 STOPPED，返回 `already_stopped` |
| R7 | 停止超时 / 孤儿 | SIGTERM 后等 grace；杀前快照子进程 | 超时 SIGKILL；按快照清理孤儿（实测常态无残留，纯防御） |
| R8 | 外部启停 dsh | 2 s 轮询端口+进程 | 轮询结果驱动状态翻转，托盘不说谎 |
| R9 | 双托盘实例 | `flock(tray.lock)` 非阻塞独占 | 第二实例打印"已在运行"并 exit 0 |
| R10 | 停止期间外部又启动 | op 锁 + 停完重新探测 | 状态以探测结果为准，不假设 STOPPED |
| R12 | 托盘被它管理的 dsh 连带杀死 | 启动时读 `/proc/self/cgroup` 找 `dsh-subprocess-*` | 直接拒绝启动并提示改用应用菜单/自启；纯 CLI 子命令不受影响 |
| R11 | 重启时中间态被他人插入 | 停 + 起在同一把 op 锁内连续执行 | 中间态对外不可见；停止未达成目标时中止重启，不制造第二个实例 |

### 为什么固定 3080

鉴权 cookie 的 audience 绑定 `host:port`。换端口会让用户在所有浏览器里**静默掉登录**。所以生产路径端口固定 3080，只有自检用 `--port` 覆盖。

### R3 与 R2 的边界（自检时澄清的模糊点）

- 占端口的是**非 dsh 进程** → 报错，不接管，不 kill。（R2）
- 占端口的是 **dsh** → 视为已运行，接管。（R3 / 已有实例策略）

判据统一为：`/proc/<pid>/cmdline` 里有一个参数 basename 是 `dsh`，且含 `web`。

## 模块边界

| 文件 | 职责 | 依赖 Qt |
|---|---|---|
| `dsh_tray/probe.py` | /proc 探测：监听 inode、pid 反查、cmdline 判定、进程存活、子进程快照 | 否 |
| `dsh_tray/locks.py` | 文件锁原语（op 锁 / 托盘单实例锁） | 否 |
| `dsh_tray/lifecycle.py` | 状态机、start/adopt/stop、令牌捕获 | 否 |
| `dsh_tray/icons.py` | 两态 SVG → QIcon | 是 |
| `dsh_tray/ui.py` | QSystemTrayIcon、菜单（启停/重启）、轮询刷新、确认对话框 | 是 |
| `dsh_tray/selftest.py` | R1–R7 自检场景（用假 dsh，不碰 3080） | 否 |
| `dsh-tray.py` | 入口、参数、单实例、autostart 前检 | 是（延迟导入） |

`lifecycle.py` 不 import Qt 是硬约束：这样 `--status/--start/--stop/--selftest` 能在无图形环境下跑，竞态路径也能被验证。

## 错误处理

| 场景 | 行为 |
|---|---|
| 端口被非 dsh 占用 | 弹冲突详情，启动项禁用 |
| 等令牌超时 | FAILED + 日志尾部 20 行 |
| 子进程提前退出 | FAILED + exit code |
| 停止超时 | SIGKILL + 孤儿清理，如实报告强杀次数 |
| adopted 打开 Web UI | 打开裸 URL 并说明沿用已有登录态；若 401 引导手动重启一次拿新令牌 |
| 托盘不可用（autostart） | 打印原因，exit 1，不留看不见的常驻进程 |
| 在 DSH 工具会话内启动托盘 | 打印作用域名与正确做法，exit 2 |

## 自检时新增的约束

1. `--autostart` 先查 `QSystemTrayIcon.isSystemTrayAvailable()`，不可用则不常驻。
2. **用系统 `python3`，不用 venv**：PyQt6 来自 `/usr/lib/python3/dist-packages`，venv 化会丢 PyQt6。
3. 图标不加方形留白：实测 16 px 下原始 viewBox 更饱满清晰。

## 验证方案

不能拿当前会话的服务进程做停止测试（本设计的第一个实例就是它）。分三层：

1. **纯函数层**：`--selftest` 用假 dsh 在临时端口跑 R1/R2/R3/R5/R6/R7 + R9 锁，全程不碰 3080。
2. **命令行层**：`--status` 对真实环境只读探测。
3. **GUI 层**：托盘出现在 Plasma、菜单随状态变化、打开 Web UI 可进。
