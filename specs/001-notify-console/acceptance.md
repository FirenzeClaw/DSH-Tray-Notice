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

## 已知限制

- **Windows 未实现**：`dsh_tray/platform/__init__.py` 对非 Linux 平台抛
  `NotImplementedError` 并指向多平台规格（S3）。没有 Windows 机器，不做任何「支持」表述。
- **macOS 未实现**：同上，按用户决定只留接口。
- 托盘图标在 Wayland 下无法定位（`geometry()` 返回 0×0），面板固定出现在屏幕右上角。
