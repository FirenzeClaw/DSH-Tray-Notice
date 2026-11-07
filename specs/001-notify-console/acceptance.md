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
并加 `--selftest` 先证明检测有效（同一对图 0%，模拟横幅 82%）。修正后同一场景测出 1.51%：
说明该区域当时呈现的是通知中心里的常驻卡片，而非瞬时横幅——两者在像素上量级不同，
脚本对此不做区分，判读时需人工确认。

**教训**：像素差分这类断言必须先自检检测器本身。`0.00%` 这个数字当时被当成了
「系统不渲染」的证据，而它其实只是「我裁错了地方」。

## 已知限制

- **Windows 未实现**：`dsh_tray/platform/__init__.py` 对非 Linux 平台抛
  `NotImplementedError` 并指向多平台规格（S3）。没有 Windows 机器，不做任何「支持」表述。
- **macOS 未实现**：同上，按用户决定只留接口。
- 托盘图标在 Wayland 下无法定位（`geometry()` 返回 0×0），面板固定出现在屏幕右上角。
