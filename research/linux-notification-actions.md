# 调研：Linux 桌面通知的可交互性（actions / 点击跳转）

调研日期：2026-11-09
目的：回答「点击系统通知横幅能否跳回 DSH 会话」这个设计前提，确定可实现、可移植的交互载体，避免继续用试错法碰运气。
方法：一手来源优先——freedesktop 规范原文、本机 plasma-workspace 6.6 源码、各桌面环境官方文档/开发者博客。二手来源已标注。
被测环境：Plasma 6.6.6 / KDE Frameworks / Wayland，`GetServerInformation` 返回 `('Plasma','KDE','6.6.6','1.2')`。

---

## 一、规范怎么说（freedesktop Desktop Notifications 1.3，2024-08-18）

**actions 是可选的，服务端可以完全忽略。** 原文（[spec](https://specifications.freedesktop.org/notification/latest-single)）：

> This functionality **may not be implemented** by the notification server, conforming clients should check if it is available before using it… An implementation is **free to ignore** any requested by the client.

规范的立场很明确：把 actions 当「尽力而为的增强」，不能当作可靠通道。

**`default` 是约定键名，不是保证：**

> The default action (usually invoked by clicking the notification) should have a key named `"default"`. The name can be anything, though implementations are free not to display it.

**`ActionInvoked` 有两个触发来源**，且客户端不得假设它一定会来：

> This signal is emitted when one of the following occurs: The user performs some global "invoking" action upon a notification. For instance, **clicking somewhere on the notification itself**. / The user invokes a specific action as specified in the original Notify request.
>
> Clients should not assume the server will generate this signal. Some servers may not support user interaction at all.

**`expire_timeout` 的取值容易记反：**

| 值 | 含义 |
|---|---|
| `-1` | 由服务端按自己的策略决定（会随 urgency 变化） |
| `0` | **永不过期**，只能由用户关闭或发送方 `CloseNotification` |
| `>0` | 该毫秒数后自动关闭 |

> Critical notifications should not automatically expire… They should only be closed when the user dismisses them.

**capabilities 只能说明「支持」，不承诺渲染方式。** 本机返回含 `actions`、`body-hyperlinks`、`body-markup`、`persistence`、`inline-reply`、`sound`、`x-kde-urls`、`x-kde-origin-name`、`inhibitions`，但下面会看到，声称支持 actions 的服务器对「点正文」的处理仍然各不相同。

---

## 二、KDE Plasma 6.6.6：源码级结论

源码位置：`plasma-workspace` 6.6 检出，`applets/notifications/`、`libnotificationmanager/`。

### 2.1 点通知本体，只在「有默认动作」时才发出信号

`applets/notifications/delegates/DelegatePopup.qml:135`：

```qml
onClicked: {
    if (delegateRoot.modelInterface.hasDefaultAction && !delegateRoot.hoveredLink) {
        delegateRoot.modelInterface.defaultActionInvoked();
    }
}
```

标题区（`DelegatePopup.qml:106`）逻辑相同，`visible: modelInterface.hasDefaultAction && !hasBodyText`。

**结论：没有 `hasDefaultAction` 的通知，点正文什么都不发生**——不发 `ActionInvoked`、不关闭、不做任何事。

### 2.2 `hasDefaultAction` 有两个来源，第二个对托盘应用永远不成立

`applets/notifications/global/Globals.qml:701-715`：

```qml
// If there is no default action, check if there is a window we could activate instead
if (!popup.hasDefaultAction) {
    for (let i = 0; i < globals.tasksModel.rowCount(); ++i) {
        const appId = globals.tasksModel.data(idx, TaskManager.AbstractTasksModel.AppId);
        if (appId === desktopEntry + ".desktop") {
            defaultActionFallbackWindowIdx = globals.tasksModel.makePersistentModelIndex(i);
            model.hasDefaultAction = true;
            break;
        }
    }
}
```

来源一：通知自己声明了 `default` 动作。
来源二：Plasma 在任务栏模型里找到一个 `AppId` 等于 `desktopEntry + ".desktop"` 的窗口，于是把「点击 = 激活那个窗口」当作默认动作。

托盘应用没有窗口，任务栏里也不会有它的条目，**所以第二个来源永远不成立**。这解释了本项目为什么点了毫无反应：我们既没声明 `default` 动作，又没有窗口可以兜底。

### 2.3 动作按钮走另一条链路

`Globals.qml:594-654`：

- `onDefaultActionInvoked` → `popupNotificationsModel.invokeDefaultAction(index, behavior)`
- `onActionInvoked: actionName` → `popupNotificationsModel.invokeAction(index, actionName)`
- `onOpenUrl` → `Qt.openUrlExternally(url)`

只有**声明显式动作按钮**时，才会渲染按钮并在这条链路上发出 `ActionInvoked`。

### 2.4 弹窗显示与否，与 actions 无关

`Globals.qml:429-465` 定义弹窗模型，`libnotificationmanager/notificationfilterproxymodel.cpp:150-227` 是它背后的过滤器。全部过滤条件只有五类：

1. `expired` 且不允许显示 → 排除
2. `dismissed` 且不允许显示 → 排除
3. 应用黑名单（`popupBlacklistedApplications` / `popupBlacklistedServices`，即设置里的「不显示弹出窗口」）
4. 白名单只在免打扰模式下生效
5. `urgency` 不在允许集合内 → 排除；免打扰期间加入的普通通知也排除

**源码中没有任何依据表明「actions 非空会导致不弹横幅」。** 这一点与本仓库 `specs/001-notify-console/acceptance.md` 里记录的实测现象（actions 非空 → 横幅区 0.00% 变化）矛盾，见第六节。

### 2.5 服务端会静默丢弃 1 秒内的完全重复通知

`libnotificationmanager/server_p.cpp:136-250`：若同一应用在 1 秒内发来 `applicationName`、`summary`、`body`、`desktopEntry`、`eventId`、`actionNames`、`icon`、`urls` 全部相同的请求，服务端回 `ExcessNotificationGeneration` 错误并返回 id 0。

做连续对照实验时必须让每条的 summary/body 都不同，否则测到的是去重而不是渲染。

---

## 三、其他桌面环境

| 桌面 / 服务器 | 动作按钮 | 点通知本体 | 官方依据 |
|---|---|---|---|
| **KDE Plasma 6** | 支持，渲染为按钮，发 `ActionInvoked` | 仅当声明 `default` 动作，或存在 AppId 匹配的窗口 | 上述源码 |
| **GNOME Shell 46+** | 支持；46 起重构为「抽屉里显示完整正文与按钮」 | 触发默认动作（打开对应应用） | [GNOME Shell 开发者博客 2024-04-23](https://blogs.gnome.org/shell-dev/2024/04/23/notifications-46-and-beyond/) |
| **XFCE (xfce4-notifyd)** | 支持，渲染为气泡内的按钮 | **明确不实现**：点击气泡只是关闭它 | [xfce4-notifyd 官方规范页](https://docs.xfce.org/apps/xfce4-notifyd/spec) |
| **Dunst** | 支持 | 单个动作或键名为 `default` 的动作可用中键触发（可配置） | [ArchWiki: Dunst](https://wiki.archlinux.org/title/Dunst) |

**XFCE 的原文值得单独引用**，因为它直接否掉了「点横幅跳转」这个载体：

> Please note that the "default action", which is usually triggered by clicking a notification bubble **is not implemented** in xfce4-notifyd. Clicking a notification instead closes it. If applications want to provide actions they have to specify the tuple of action-id and action for a button to be shown in the bubble.

**GNOME 的 API 分裂是另一个坑**：非 GTK 应用走 XDG Notification，GTK 应用走 `Gio.Notification`（最终落到 GNOME Shell 私有 D-Bus 接口），沙箱应用走 XDG Portal。三条路径的能力集不同，同一个动作在三条路径上的表现可能不一致。据 GNOME 博客，官方方向是收敛到 Portal，但那是后续版本的事。

**跨桌面唯一稳定的交集是「显式动作按钮」**：规范要求动作以「偶数位=id、奇数位=显示文本」的成对列表传递，四家都按这个格式渲染成按钮。而「点本体」的语义在四家各不相同（KDE 有条件触发、XFCE 关闭、GNOME 打开应用、Dunst 中键），不能作为唯一交互。

---

## 四、对本项目的结论

结论按平台分两层：**协议层（规范允许什么）** 与 **本机实现层（KDE 实际能做到什么）**。
两者在 actions 这一点上冲突，以更保守的一方为准。

**协议层（适用于 GNOME / XFCE / Dunst 等）**

1. **要让「点通知本体」生效，必须声明键名为 `default` 的动作**。规范把它定义为全局
   invoking 动作；KDE 的窗口兜底路径对无窗口的托盘应用永远不成立，声明 `default`
   是唯一途径。
2. **同时声明显式动作按钮**（如 `open` =「打开会话」），这是跨桌面唯一一致的可见交互。
3. **不能把通知当可靠通道**。规范允许服务器忽略 actions；XFCE 明确不实现默认动作。
   托盘面板必须保留完整等价入口。

**本机实现层（KDE Plasma 6.6.6，第五节实测）**

4. **KDE 上不能用 actions**。声明动作会让通知完全不渲染 —— 横幅可见与横幅可点在本机
   互斥。因此 KDE 下的通知一律**不带 actions**，交互全部走托盘。
5. **`expire_timeout` 用正数**，不要用 `0`（永不过期会占住弹窗位，本项目已因此踩坑，
   见 `acceptance.md`）。
6. **带上 `desktop-entry` 提示**，让桌面环境正确归因应用（影响 KDE 的应用级设置与图标）。

**落到设计上**：「点横幅跳转」应做成**按平台能力启用的可选能力**，
检测到 KDE（或用户实测横幅不可见）时关闭，默认走托盘交互。这正是用户要的
「双方案可选」，只是默认值由平台能力决定，而不是让用户去猜。

---

## 五、受控复核结果（2026-11-09）：异常确认为真

`acceptance.md` 曾记录「actions 非空 → 横幅不出现」，但第二节的源码里找不到任何
actions 相关过滤，因此列为待复核。已按受控条件重测，**结论：现象真实且稳定复现，
且不是此前怀疑的去重或测量误差**。

### 5.1 受控 A/B（两臂交错、各 5 轮）

条件：每轮先 `CloseNotification` 清空 id 1–499、静置 1.6 s、截图取基线 → 发通知
（summary/body 各带唯一毫秒戳）→ 静置 2.0 s → 截图 → 按 `DEFAULT_REGION_FRAC`
差分。两臂仅 `actions` 不同，`desktop-entry` 提示相同。

| 臂 | 各轮横幅区变化 | 均值 | 返回 id |
|---|---|---|---|
| A：`actions=[]` | 25.21 / 12.10 / 9.56 / 9.58 / 9.56 % | 13.20% | 68,70,72,74,76 |
| B：`actions=['default','打开会话']` | 0.00 / 0.00 / 0.00 / 0.00 / 0.00 % | **0.00%** | 69,71,73,75,77 |

**5/5 完全分离，且返回 id 全部非零** —— 排除 2.5 节的 1 秒去重（该路径返回 id 0）。

### 5.2 排除「渲染在别处」

全图差分（区域取 `(0,0,1,1)`）三轮：2.45% / 0.11% / 21.41%，而同一批图在横幅区恒为
0.00% —— 变化来自时钟、光标等桌面噪声，不在通知区。

### 5.3 全屏 OCR 判定（决定性）

发送带唯一 ASCII 标记的通知，等 2 s 后全屏截图，用 `tesseract -l eng --psm 11`
搜索标记词：

| 臂 | 标记 | 全屏能否找到 |
|---|---|---|
| `actions=[]` | `MKZQ7A` | **True** |
| `actions=['default','打开会话']` | `MKZQ7B` | **False** |

**屏幕上根本不存在这段文字。**

### 5.4 结论与影响

在本机 Plasma 6.6.6 上，**`actions` 非空的 D-Bus 通知会被接受（返回有效 id），但不会
渲染在任何位置**。源码层面未见对应过滤，`plasmashell` 默认日志级别下也没有相关报错
（仅一条无关的 Seedvault 记录），因此根因需开启 `org.kde.plasma.notifications.debug`
并重启 plasmashell 才能进一步定位 —— 属于侵入性操作，未执行。

对本项目的直接影响：

- **KDE 上「点横幅跳转」不可实现。** 要让横幅可点，必须声明 `default` 动作；而声明动作
  又会让整条通知消失 —— 两者在当前 Plasma 版本下互斥。
- 因此第二节 2.2 给出的「声明 `default` 动作」方案，**在本机 Plasma 上不适用**，
  仅对 GNOME / XFCE / Dunst 有意义。
- 可行的通知形态只有一种：**不带 actions 的通知**（横幅可见，但点它没有任何反应）。
- 交互必须放在托盘侧；「点横幅」作为可选能力，按平台能力决定是否启用。

### 5.5 复现脚本

`/tmp/ab-actions-probe.py`（本次使用，未入库）：复用 `scripts/check-banner.py` 的
`capture` / `changed_percent` / `close_notification`，两臂交错各 5 轮。

---

## 六、来源清单

| 来源 | 类型 | 日期 / 版本 |
|---|---|---|
| [Desktop Notifications Specification 1.3](https://specifications.freedesktop.org/notification/latest-single) | 一手规范 | 发布 2024-08-18 |
| 本机 `plasma-workspace` 6.6 源码（`DelegatePopup.qml`、`Globals.qml`、`notificationfilterproxymodel.cpp`、`server_p.cpp`） | 一手源码 | 6.6 分支检出 |
| [Notifications in 46 and beyond（GNOME Shell 开发者博客）](https://blogs.gnome.org/shell-dev/2024/04/23/notifications-46-and-beyond/) | 一手（开发者博文） | 2024-04-23 |
| [xfce4-notifyd 规范支持表](https://docs.xfce.org/apps/xfce4-notifyd/spec) | 一手（官方文档） | 页面最后修改 2025-12-30 |
| [ArchWiki: Dunst](https://wiki.archlinux.org/title/Dunst) | 二手（社区文档） | 抓取 2026-11-09 |
| [GNOME/GSConnect #1788](https://github.com/GSConnect/gnome-shell-extension-gsconnect/issues/1788) | 二手（issue 讨论，佐证 GNOME 46 抽屉内的动作按钮） | 抓取 2026-11-09 |
