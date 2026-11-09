# 验收记录：托盘通知控制台（SC-001 ~ SC-008）

**规格**: `specs/001-notify-console/spec.md`
**日期**: 2026-11-06
**环境**: KDE Plasma 6.6.6 / Wayland；Python 3.14.4 + PyQt6 6.10.2（系统包，非 venv）；
DSH 0.2.1-rc.5；Node 24.22.1

## 自动化基线

| 项 | 命令 | 结果 |
|---|---|---|
| 托盘侧单测（含离屏 GUI） | `python3 -m unittest discover -s dsh_tray/tests -t .` | **179 tests OK** |
| 插件单测 | `cd plugin && npm test` | **116 tests, 116 pass** |
| 竞态自检 | `./dsh-tray.py --selftest` | **10/10 PASS** |
| 插件类型检查 | `cd plugin && npm run typecheck` | 双端通过 |
| 客户端产物 | `cd plugin && npm run build` | 18355 B 单文件，相对 import 0 |
| 插件装载 | `dsh --profile web --dump-config \| grep tray-notify` | `id: tray-notify / name: dsh-tray-notify` 可见 |

## 逐条核对

### SC-001 事件到通知 90% 在 2 秒内

**状态**: 部分验证（组件级）

- 消费间隔 200 ms（DSH 运行中），实测 `FAST_INTERVAL_MS = 200`。
- 单轮消费实测：179 条单测里 `Consumer.poll()` 平均 < 1 ms（`Ran 179 tests in 2.27s`，含 GUI 用例）。
- 端到端（插件写 → 托盘弹）未在真实 8 小时会话中统计，**未验证** 90% 分位数。
- 验证方法：`tail -f ~/.dsh/run/tray-notify/events.jsonl` 与托盘日志
  `~/.local/state/dsh-tray/tray.log` 的时间戳差值，采样 ≥ 100 条。

### SC-002 点击到会话可交互 90% 在 3 秒内

**状态**: 部分验证

- 点击链路已端到端验证：`ActionInvoked` 收到 `(159, 'default')`（`gdbus emit` 模拟）。
- 深链拼接单测 9 条通过（owned 带令牌 / adopted 无令牌 / pid 不符丢弃令牌 / 端口 / 编码）。
- 浏览器打开耗时未测（依赖浏览器冷启动），**未验证** 90% 分位数。

### SC-003 标准预设 8 小时通知数 ≤ 轮次数的 1.1 倍

**状态**: 未验证（需要真实 8 小时使用）

- 机制上可保证：去重键 `kind:session:turn` 让每轮最多一条；`test` 类别不计入。
- 单测覆盖：同 dedupeKey 10 秒内只接受一条；`test` 不进未读计数。
- 验证方法：跑一天后比对 `~/.dsh/run/tray-notify/events.jsonl` 里 `type=="notification"`
  的行数与 DSH 会话日志的 `turn/end` 数。

### SC-004 托盘重启后已查看历史保留率 100%

**状态**: 已验证（组件级）

- 历史写盘为原子写（临时文件 + `replace`，0600），重启后 `history.load()` 全量读回。
- 单测：`test_mark_read_keeps_entry`（标记已读不删除）、`test_append_then_load`、
  `test_duplicate_id_ignored`、`test_corrupt_file_reads_as_empty` 均通过。
- 上限 500 条 / 30 天，超出部分按设计淘汰（不属于「保留率」范围）。

### SC-005 面板首屏 ≤ 300 ms；概览首屏 ≤ 1 s（CPU 首样本除外）

**状态**: 部分验证

- 离屏实测：`Panel` 构造 + `show()` + 一次 `refresh()` 在 179 条测试的总耗时里不可分辨
  （整批 2.27 s，含 40+ 条 GUI 用例）。
- 概览首样本返回 `None` 并显示「待采样」，第二次采样（2 s 后）才出 CPU 值——符合
  「CPU 首样本除外」的表述。
- 真实桌面上的首帧耗时**未单独测量**。

### SC-006 面板关闭时后台 CPU < 1%

**状态**: 已验证（机制级）

- 「工作中」页 `hideEvent` 停计时器（单测 `test_hide_stops_timer` 断言 `isActive()` 为 False）。
- 「概览」页 `hideEvent` 停采样（单测 `test_hide_timer_stops` 同上）。
- 通知消费在 DSH 未运行时降到 1 s（单测 `test_interval_follows_dsh_state`）。
- 实际 CPU 占用未用 `top` 长时间测量。

### SC-007 不看文档就能从设置页切到「安静」并验证生效

**状态**: 部分验证

- 设置分区含三档预设按钮（安静/标准/详细）+ 四组开关 + 「发送测试通知」按钮，
  每个开关带一句说明（例如「提示：会话内的观察，例如「你可能卡住了」」）。
- 「发送测试通知」绕过组开关，用途正是「先确认链路，再决定开哪些」。
- **未在真实设置页里点过**（需要重启 DSH 让客户端产物生效后人工验证）。

### SC-008 投递失败丢失条目数 0

**状态**: 已验证

- `Consumer.poll()` 在投递失败时仍调用 `history_writer`（单测 `test_failure_still_stores`
  断言 `result.stored == 1` 且 `delivered == 0`）。
- 历史写失败单独捕获并记日志，不影响同批其它条目。
- 托盘 tooltip 在「有事件但一条都没投出去」时显示「通知不可用」，用户仍能在面板看到。

## 未验证项汇总

以下四项需要真实使用或人工点击，本轮**未验证**，不做「已验证」表述：

1. SC-001 / SC-002 的 90% 分位数（需 ≥100 次采样）。
2. SC-003 的 8 小时倍率（需一天真实使用）。
3. SC-005 的真实桌面首帧耗时。
4. SC-007 的设置页人工操作（需重启 DSH 装载客户端产物）。

## 走查发现的缺陷与修正（2026-11-07）

在真实桌面上走查时发现一个**只有实测才会暴露**的缺陷，已修复：

**症状**：21:16 发的一条 critical 通知在屏幕上停留 1 小时 40 分钟不消失；期间发出的
所有通知（含换 app 名、去掉 actions/hints、改各种 timeout）**一条横幅都没渲染**，
但 D-Bus 调用全部成功并返回了 id（164–172）。关掉那条旧通知后，横幅立刻恢复正常。

**根因**：`TIMEOUT_CRITICAL_MS = 0`。按 freedesktop 规范 0 =「由服务端决定」，而 Plasma
对 critical 的处理是**保留到用户手动关闭**。一条没人关的 critical 通知会占住弹窗位，
后续通知排队但不显示——看起来完全像通知功能坏了。这与 FR-013「需要你的通知驻留」的
**字面**一致，但和它想要的**效果**相反。

**修正（用户批准的 C+B 方案）**：

| 改动 | 内容 | 位置 |
|---|---|---|
| C 顶替 | 同一会话的新通知带 `replaces_id` 顶替旧横幅，不再排队 | `delivery.PopupRegistry` + `tray._deliver` |
| B 有限时限 | critical 兜底从 0 改为 5 分钟 | `delivery.TIMEOUT_CRITICAL_MS` |
| 可配置 | `criticalTimeoutMs` 进设置页（5 秒 ~ 1 小时，数字输入，回车/失焦提交） | `config.ts` / `client/index.ts` |
| 契约 | 通知条目新增可选 `timeoutMs`，由插件按设置下发 | `types.ts` / `types.py` |

**顺带修掉的测试缺陷**：`test_read_page_groups_by_day` 依赖真实时钟，11-06 写的用例在
11-07 早上把「今天」算成了「昨天」。已给 `NotificationListPage.refresh()` 加可注入的
`now`，用例传冻结时刻。

**测量错误订正（2026-11-07 21:10）**：我曾据此记录「Plasma 已不再渲染任何弹窗」，
**这个结论是错的**，源于我自己的测量缺陷：

- `spectacle` 抓的是物理分辨率（本机 2560×1600），而我按**预览坐标**（1463×915）写死了
  裁剪区域 `(1050, 20, 1463, 320)`。实际裁到的是图片中左部，横幅在右上角根本不在视野里
  ——所以无论有没有横幅都测出 `0.00%`。
- 用户提供的截图证明通知一直在正常显示（卡片上带「4 分钟前」「7 分钟前」的相对时间，
  其中包含不经本仓库代码的 `notify-send` 参照组）。

检测器已改为**比例坐标**（`DEFAULT_REGION_FRAC = (0.74, 0.02, 0.99, 0.50)`，对分辨率免疫），
并加 `--selftest` 先证明检测有效（同一对图 0%，模拟横幅 82%）。

### 真实缺陷：带 `actions` 的通知不显示横幅

修正检测器后，参数矩阵给出了确定结论（每格都是「清空通知中心 → 截图 → 发一条 → 截图 → 差分」）：

| actions | urgency / 超时 | 横幅区变化 | 结论 |
|---|---|---|---|
| `[]` | normal / 60s | 9.12% | 有横幅 |
| `['default', '打开']` | normal / 60s | 0.00% | **无横幅** |
| `['default', '打开']` | critical / 永驻 | 0.00% | **无横幅** |
| `['default', '打开']` | 无 urgency / 永驻 | 0.00% | **无横幅** |
| `[]` | 无 urgency / 永驻 | 9.14% | 有横幅 |

补充排除项（全部 0.00%）：换动作键名（`open`）、空标签、两个动作、四种 hints
（`desktop-entry` / `urgency` / `x-kde-urls` / 空）。**全屏 OCR 也确认它没有渲染在任何位置**。

也就是说：**只要 `actions` 非空，本机 Plasma 6.6.6 就接受通知（返回 id）但不弹横幅**。
`notify-send --action` 报「Actions are not supported by this notifications server」
（research.md D3）与此互为印证——能力列表里有 `actions`，但弹窗路径处理不了它。

**后果**：FR-016/017「点通知跳到会话」与「通知要弹出来」在本机无法同时满足。
取舍见「待决策」一节。

**教训**：像素差分这类断言必须先自检检测器本身。`0.00%` 这个数字当初被当成了
「系统不渲染」的证据，而它其实只是「我裁错了地方」——但订正之后，同一个 0.00%
在正确的区域上反而指向了一个**真实**的缺陷。

#### 源码复核（2026-11-09）：上面的归因站不住

读 `plasma-workspace` 6.6 源码后，这条结论**没有被源码支持**：

- `libnotificationmanager/notificationfilterproxymodel.cpp:150-227` 是弹窗模型的过滤器，
  全部条件只有五类：`expired` → `dismissed` → 应用黑名单 → 白名单（仅免打扰时生效）
  → `urgency` 不在允许集合 → 因抑制期加入。**没有任何一条与 `actions` 相关**。
- `applets/notifications/global/Globals.qml:429-465` 构造弹窗模型时同样只设了
  `blacklistedDesktopEntries` / `blacklistedNotifyRcNames` / `urgencies` /
  `showExpired` / `showDismissed` / `showAddedDuringInhibition` / `limit` / `groupMode`。

也就是说，「actions 非空导致不弹横幅」在实现层找不到支点。表格里的 `0.00%` 更可能
来自三个未控变量：

1. **1 秒去重**：`libnotificationmanager/server_p.cpp:136-250` 会丢弃 1 秒内
   `applicationName`+`summary`+`body`+`desktopEntry`+`eventId`+`actionNames`+`icon`+`urls`
   完全相同的请求（回 `ExcessNotificationGeneration`，返回 id 0）。当时的对照实验
   summary/body 区分度不足。
2. **通知中心未真正清空**：清空与发送之间若有残留卡片，差分基线就不可比。
3. **`plasmanotifyrc` 状态**：测试期间注册了 `[Applications][dsh-tray] Seen=true`，
   需确认无 `ShowPopups=false`（已复查：托盘与应用本身都不在黑名单，仅两个 waydroid
   应用是 `ShowPopups=false`）。

**处置**：已按受控条件复核，**现象属实且稳定复现，不是去重、也不是测量误差**。
复核细节见
[`research/linux-notification-actions.md`](../../research/linux-notification-actions.md) 第五节。
要点：

- 两臂各 5 轮交错、唯一文案、清空后静置 1.6 s：`actions=[]` 均值 13.20%（25.21/12.10/
  9.56/9.58/9.56），`actions=['default','打开会话']` **五轮全 0.00%**；
- 返回 id 全部非零（68–77），**排除 1 秒去重**；
- 全屏 OCR 搜索唯一标记词：无 actions 找得到，有 actions **找不到** —— 屏幕上根本
  没有这段文字；
- `plasmashell` 默认日志级别下无相关报错，根因需开 debug 日志并重启 plasmashell 才能
  定位，属侵入性操作，未执行。

**结论**：本机 Plasma 6.6.6 上，`actions` 非空的通知被接受但不渲染。因此 KDE 下
**横幅可见与横幅可点互斥**，「点横幅」不可实现，交互必须放在托盘侧。

### 交互路径实测：系统通知上没有任何可点区域

用户要求「点击横幅跳面板」与「点击横幅跳会话」两种模式可配置。为确定可行路径，
在真实桌面上逐项实测（每次都用 tesseract TSV 定位精确像素框再点，避免坐标误差）：

| 尝试 | 结果 |
|---|---|
| 带 `actions` + 点通知本体 | 通知根本不渲染（见上），无从点起 |
| 无 `actions` + 点通知本体 | 卡片无变化、无窗口打开（截图差分 < 1.1%） |
| 无 `actions` + 正文 `<a href>`（`body-markup`）+ 点链接文字 | 链接文字**能渲染**（OCR 可读），但点击两次都不触发导航：地址栏无变化（差分 3.31%，仅为聚焦）、卡片仍在 |

**结论**：本机 Plasma 6.6.6 上，系统通知**没有任何可交互区域**——
要么带 `actions` 导致整条通知不可见，要么可见但点哪里都没反应（包括富文本链接）。

#### 源码复核（2026-11-09）：为什么点正文没反应

`applets/notifications/delegates/DelegatePopup.qml:135` 是正文的点击处理器：

```qml
onClicked: {
    if (delegateRoot.modelInterface.hasDefaultAction && !delegateRoot.hoveredLink) {
        delegateRoot.modelInterface.defaultActionInvoked();
    }
}
```

没有 `hasDefaultAction` 时，**点正文不进入任何分支**——不发 `ActionInvoked`、不关闭、
不做任何事。标题区（`DelegatePopup.qml:106`）同理，且要求 `!hasBodyText`。

`hasDefaultAction` 有两个来源（`Globals.qml:701-715`）：

1. 通知自己声明了键名为 `default` 的动作；
2. Plasma 在任务栏模型里找到 `AppId === desktopEntry + ".desktop"` 的窗口，
   把「点击 = 激活该窗口」当作默认动作。

托盘应用没有窗口，任务栏里也没有它的条目，**来源 2 永远不成立**。而当时的通知既没有
声明 `default` 动作（无 `actions`），发送方也不是带窗口的应用 —— 所以点击必然无反应。
富文本链接不触发导航同理：`hoveredLink` 为真时反而会跳过默认动作分支。

**这不是 Plasma 的缺陷，而是我们没用对协议。** 规范（1.3 §ActionInvoked）明确
「点通知本体」属于全局 invoking，对应动作键就是 `default`；要吃到这个交互，
**通知必须声明 `default` 动作**。

因此上一节的「点横幅这个前提不成立」需要修正：**在声明 `default` 动作之后，前提可能成立**，
而这正好与「带 actions 不弹横幅」的待复核异常撞在一起 —— 两者必须一起复核。

## 待决策：交互该放在哪（需用户定）

用户要求「点横幅跳面板」与「点横幅跳会话」两种模式可配置。当前证据分两层：

- **协议层**（`research/linux-notification-actions.md`）：声明 `default` 动作是让 KDE
  本体点击生效的唯一途径；显式动作按钮是四家桌面环境唯一一致的可见交互；
  但规范允许服务器忽略 actions，**不能把通知当可靠通道**。
- **本机实测层**：带 actions 的通知是否真不弹横幅，尚未在受控条件下复核。

因此方案表更新为：

| 方案 | 横幅 | 一次点击能到哪 | 代价 |
|---|---|---|---|
| A. 去 `actions`，交互全走托盘 | ✅ 有（已验） | 托盘左键 → 面板 → 点行 → 会话（两步） | 与原型「点通知跳会话」不同；**确定可行** |
| B. 保留 `actions` | ❌ 无（待复核） | — | 若复核证伪则完全不可接受 |
| C. 去 `actions`，托盘左键**直接打开最新未读会话** | ✅ 有 | 一次点击直达会话；看列表用右键菜单 | 牺牲「先看列表」的默认行为 |
| D. A 与 C 做成设置项 | ✅ 有 | 由设置决定 | 需要多一套状态与测试 |
| **E. 声明 `default` 动作 + 显式按钮** | 取决于 B 的复核结果 | 点横幅 = 默认动作（跳会话或开面板） | 若 B 成立则整条通知不可见，E 随之作废 |

**推荐路径**：先做受控复核（第五节方案）。若 actions 不影响横幅 → 选 **E + D**
（既满足用户「两种模式可选」的原意，又保持跨桌面可移植）；若 actions 确实压掉横幅 →
退到 **D**（把切换载体从「点哪条通知」变成「点托盘时做什么」）。B 在任何情况下都排除。

## 已知限制

- **Windows 未实现**：`dsh_tray/platform/__init__.py` 对非 Linux 平台抛
  `NotImplementedError` 并指向多平台规格（S3）。没有 Windows 机器，不做任何「支持」表述。
- **macOS 未实现**：同上，按用户决定只留接口。
- 托盘图标在 Wayland 下无法定位（`geometry()` 返回 0×0），面板固定出现在屏幕右上角。
