# Quickstart: 托盘通知控制台

**Feature**: specs/001-notify-console | **Date**: 2026-11-06

从零到「看到第一条通知」的最短路径。所有命令在仓库根执行（路径含 `&`，必须加引号）。

## 0. 前置

```sh
cd "/home/firenzeclaw/Code/DSH-Tray&Notice"
./dsh-tray.py --status        # 确认现有托盘代码可用
```

## 1. 构建 DSH 插件

```sh
cd plugin && npm install --legacy-peer-deps && npm run build && cd ..
# 产物：plugin/dist/index.js（host 半）、plugin/dist/client.js（client 半）
npm --prefix plugin test       # 插件单测（node --test 自动发现 tests/*.test.ts）
npm --prefix plugin run typecheck
```

`--legacy-peer-deps` 是必需的：`@deepseek-ai/*` 之间互为 peer，不跳过会因版本求解失败。
这些包只作**类型**用（代码里全是 `import type`），运行时不加载。

⚠️ **不要**给 `plugin/node_modules` 建指向 DSH 全局安装的符号链接。`npm install`
会顺着链接进入目标目录，把 DSH 的 `@deepseek-ai/*` 判为 extraneous 并删除——实测
删掉 306 个包，`dsh` 命令当场失效。恢复：`npm i -g @deepseek-ai/dsh@0.2.1-rc.5`。

## 2. 装进 web profile

```sh
dsh plugin --profile web add "link:$PWD/plugin"

# 确认方式（注意：不会写进 cordis.patch.yml）
grep tray-notify ~/.dsh/profiles/web/package.json
#   "dsh-tray-notify": "link:…/plugin"           ← dependencies
#   "dsh-tray-notify"                            ← dsh.profile.bundles

dsh --profile web --dump-config | grep -A1 tray-notify
#   - id: tray-notify
#     name: dsh-tray-notify
```

机制说明（实测）：`dsh plugin add` 把包加进 `package.json` 的 `dsh.profile.bundles`，
插件的**自带 patch**（`plugin/dsh.bundle.patch`）在启动时作为 bundle 层叠加，所以
`cordis.patch.yml` 里看不到它。改完插件代码后需要重启 `dsh web` 才生效（客户端产物
尤其如此——浏览器缓存的是旧的 `dist/client.js`）。

## 3. 启动托盘并触发一条通知

```sh
./scripts/dsh-tray.sh &        # 从终端启动仅用于开发；日常用应用菜单/自启
sleep 2
tail -n 5 ~/.dsh/run/tray-notify/events.jsonl   # 插件开始写事件流
tail -n 5 ~/.local/state/dsh-tray/tray.log      # 托盘侧的消费日志
```

在 DSH 网页里让任意会话跑完一轮 → 桌面右上应出现系统通知；
点它 → 浏览器定位到那个会话。

**不想等真实事件**时，可以直接往 spool 里塞一条（托盘 200 ms 内会消费）：

```sh
cat >> ~/.dsh/run/tray-notify/events.jsonl <<'EOF'
{"v":1,"type":"notification","id":"manual-1","ts":"2026-11-06T12:00:00Z","kind":"done",
 "sessionId":"manual","sessionTitle":"手工测试","title":"已完成","body":"来自 quickstart 的手工事件",
 "urgency":"normal","openUrl":"http://127.0.0.1:3080/?session=manual","dedupeKey":"done:manual:1"}
EOF
```

注意 `id` 与 `dedupeKey` 要唯一，否则会被去重窗口吞掉。

## 4. 验证清单（对应 spec 的验收）

| 步骤 | 验证 | 对应 |
|---|---|---|
| 跑完一轮 | 出现「已完成」通知，正文含轮次信息 | US1.1 |
| 触发审批 | 出现「需要你审批」通知，critical 驻留 | US1.2 / FR-013 |
| 点通知 | 落到该会话，URL 中 `session` 参数被移除 | US2 / FR-016/017 |
| 左键托盘 | 面板出现，控制区显示运行中·自有 | US3 / FR-020 |
| 「工作中」 | 活动会话一行，时长每秒自增 | FR-028/029 |
| 「概览」 | 首次 CPU 显示待采样，2 秒后出数值 | FR-031 |
| 设置页 | 预设切「安静」后完成通知消失，审批照常 | US5 / FR-007 |
| 重启托盘 | 已查看历史保留，未查看徽标数字不变 | SC-004 |

## 5. 手工验证点击动作（需要人手）

```sh
export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus
gdbus call --session --dest org.freedesktop.Notifications \
  --object-path /org/freedesktop/Notifications \
  --method org.freedesktop.Notifications.Notify \
  "DSH-Tray" "uint32 0" "" "手工测试" "请点击「打开会话」按钮" \
  "['open', '打开会话']" "{}" "int32 0"
```

**参数格式是 `uint32 0`（空格），不是 `uint32:0`（冒号）**：gdbus 用 GVariant 文本
格式，冒号写法会报「解析 u 类型的第 2 个参数时发生错误」。这个错很隐蔽——托盘会
静默回退到 `notify-send`，通知照样弹出，只是**没有按钮**。

点击按钮后托盘应收到 ActionInvoked（托盘日志会打印「已打开会话」）。
libnotify 的 `notify-send --action` 在本机被拒（research.md D3），不要用它验证。

不点按钮也能验证回执通路（模拟守护进程发信号）：

```sh
gdbus emit --session --object-path /org/freedesktop/Notifications \
  --signal org.freedesktop.Notifications.ActionInvoked "uint32 1" default
```

生产环境的订阅带 sender 过滤（`org.freedesktop.Notifications`），所以上面的
`gdbus emit` 只有在监听器用 `service_filter=''` 时才会被收到——这条命令用于
测试，不是验收路径。

## 6. 权限（安全红线）

spool 与状态文件必须 0600、目录 0700——通知正文可能含命令与路径，`openUrl` 含会话 id。
插件与托盘在每次写入时都会 `chmod`，所以**手工 `cat >>` 塞过事件后权限会变宽**，
下一次正常写入会自动收紧。手工检查：

```sh
stat -c '%a %n' ~/.dsh/run/tray-notify ~/.dsh/run/tray-notify/events.jsonl
# 期望 700 与 600
stat -c '%a %n' ~/.local/state/dsh-tray
# 期望 700
```

## 7. 常见问题

- **没有通知**：先看 `events.jsonl` 有没有行——没有是插件侧问题（查 profile 是否装上、
  设置里开关是否全关）；有行但没弹窗是托盘侧投递问题（查 `gdbus` 是否在 PATH、
  托盘日志里 `deliver` 是否失败）。
- **通知重复**：检查是否装了别的 DSH 通知插件（`~/.dsh/profiles/web/package.json` 的
  bundles），与它们共存会双投。
- **托盘在 DSH 工具会话里启动被拒**：既有保护，改用应用菜单。
