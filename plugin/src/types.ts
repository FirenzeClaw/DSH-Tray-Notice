/**
 * 跨进程契约类型：spool 行的两种形态。
 *
 * 这些形状是插件与托盘之间**唯一**的耦合面（data-model.md）。改字段必须同时改
 * 托盘侧 `dsh_tray/notify/types.py` 并把 `SCHEMA_VERSION` 加一——两侧各写一份是
 * 刻意的：双语言仓库里共享代码的成本高于共享契约。
 *
 * 约定：
 * - 字段名一律 camelCase（JSON 侧）；Python 侧在 `from_json` 里映射到 snake_case。
 * - 时间一律 ISO-8601 UTC 字符串，不传 epoch 数字：托盘要按本地时区分组显示，
 *   带时区的字符串比裸数字少一次猜。
 * @module
 */

/** spool 协议版本。任何字段变更都要递增，托盘据此丢弃不认识的旧行。 */
export const SCHEMA_VERSION = 1

/**
 * 通知类别。
 *
 * 字面量联合而非 enum：编译期就能挡住拼错，产物里也不留运行时对象。
 */
export type NotificationKind =
  | 'needs-approval'
  | 'needs-answer'
  | 'done'
  | 'error'
  | 'blocked'
  | 'max-tokens'
  | 'job'
  | 'goal'
  | 'subagent'
  | 'tool-failure'
  | 'notice'
  | 'test'

/** 紧急度。`critical` 对应 freedesktop urgency=2，托盘据此决定是否弹出横幅。 */
export type Urgency = 'critical' | 'normal'

/** 一条通知。托盘侧主键是 `id`（幂等消费）。 */
export interface NotificationEntry {
  readonly v: typeof SCHEMA_VERSION
  readonly type: 'notification'
  /** UUID，托盘侧主键；重复 id 直接丢弃。 */
  readonly id: string
  /** ISO-8601 UTC。 */
  readonly ts: string
  readonly kind: NotificationKind
  readonly sessionId: string
  readonly sessionTitle: string
  /** 工作目录短名，次要信息，可缺省。 */
  readonly workspace?: string
  readonly title: string
  /** 正文；超过 `bodyLimit` 时由插件截断并加省略号。 */
  readonly body: string
  readonly urgency: Urgency
  /**
   * 会话定位链接，**不含令牌**（`http://127.0.0.1:3080/?session=<id>`）。
   *
   * 令牌只存在于托盘一侧：插件拿不到也不该拿（AGENTS.md 安全红线）。托盘投递前
   * 按 owned/adopted 注入 `&token=…`。
   */
  readonly openUrl: string
  /** 去重键；托盘对同键且 10 秒内的第二条直接丢弃。 */
  readonly dedupeKey: string
}

/** 会话运行态。 */
export type SessionRunState = 'working' | 'waiting-user' | 'idle'

/** 会话来源；子会话默认不通知、不在「工作中」页显示。 */
export type SessionOrigin = 'root' | 'subagent'

/** 一个会话的当前状态。 */
export interface SessionRow {
  readonly id: string
  readonly title: string
  readonly state: SessionRunState
  /** 当前轮次号。 */
  readonly turn: number
  /** 本轮开始时刻（ISO-8601）；`idle` 时缺省。 */
  readonly turnStartedAt?: string
  /** 正在执行的工具名 + 参数摘要，如 `Bash · pnpm build`。 */
  readonly currentTool?: string
  readonly origin: SessionOrigin
}

/**
 * 会话状态快照。
 *
 * `sessions` 是**全量替换**而非增量：托盘不做合并逻辑，收到就整体换掉
 * （data-model.md 不变量 4）。这样插件侧不必维护「哪些会话已下线」的账本。
 */
export interface SessionStateEntry {
  readonly v: typeof SCHEMA_VERSION
  readonly type: 'session-state'
  readonly ts: string
  readonly sessions: readonly SessionRow[]
}

/** spool 行。 */
export type SpoolRow = NotificationEntry | SessionStateEntry
