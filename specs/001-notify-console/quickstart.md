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
cd plugin && npm install && npm run build && cd ..
# 产物：plugin/dist/index.js（host 半）、plugin/dist/client.js（client 半）
npm --prefix plugin test       # 插件单测
```

## 2. 装进 web profile

```sh
dsh plugin --profile web add "link:$PWD/plugin"
# 然后确认 ~/.dsh/profiles/web/cordis.patch.yml 出现了
#   - insert:
#       - id: tray-notify
#         name: tray-notify
# profile 的 HMR 会热加载；`dsh web` 不必重启
```

## 3. 启动托盘并触发一条通知

```sh
./scripts/dsh-tray.sh &        # 从终端启动仅用于开发；日常用应用菜单/自启
sleep 2
tail -n 5 ~/.dsh/run/tray-notify/events.jsonl   # 插件开始写事件流
```

在 DSH 网页里让任意会话跑完一轮 → 桌面右上应出现系统通知；
点它 → 浏览器定位到那个会话。

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
  "DSH-Tray" 0 "" "手工测试" "请点击「打开会话」按钮" \
  "['open', '打开会话']" "{}" 0
```

点击按钮后托盘应收到 ActionInvoked（托盘日志会打印）。
libnotify 的 `notify-send --action` 在本机被拒（research.md D3），不要用它验证。

## 6. 常见问题

- **没有通知**：先看 `events.jsonl` 有没有行——没有是插件侧问题（查 profile 是否装上、
  设置里开关是否全关）；有行但没弹窗是托盘侧投递问题（查 `gdbus` 是否在 PATH、
  托盘日志里 `deliver` 是否失败）。
- **通知重复**：检查是否装了别的 DSH 通知插件（`~/.dsh/profiles/web/package.json` 的
  bundles），与它们共存会双投。
- **托盘在 DSH 工具会话里启动被拒**：既有保护，改用应用菜单。
