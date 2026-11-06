/**
 * 会话内 notice → 桌面通知。
 *
 * `target-monitor` 这类插件会把「你可能卡住了」作为 **notice 形态的 user/message**
 * 注入会话（`source = { kind: 'target-monitor', form: 'notice', summary }`）。用户
 * 不在屏幕前时看不到它，所以要抬成桌面通知。
 *
 * 为什么只认白名单 + `form === 'notice'`，不匹配文案：文案会随版本改，匹配文案等于
 * 把两个插件的字符串耦死。`kind` 是生产者声明的身份，`form` 是宿主定义的形态，
 * 这两个字段才稳定。
 *
 * 反向约束（FR-040）：本模块只**读**会话事件，绝不写会话——托盘通知插件不参与
 * agent loop，也不该影响会话内容。
 * @module
 */

/** 默认白名单：已知会用 notice 形态提醒用户的插件。 */
export const DEFAULT_NOTICE_SOURCES: readonly string[] = ['target-monitor']

/** 消息来源的最小形状。 */
export interface NoticeSourceLike {
  readonly kind?: unknown
  readonly form?: unknown
  readonly summary?: unknown
}

/**
 * 判断一条消息来源是否是应当抬成通知的 notice。
 * @param source - 消息的 `source` 字段
 * @param allowed - 允许的 `kind` 集合
 * @returns notice 正文；不是 notice 或不在白名单时 undefined
 */
export function matchNotice(source: unknown, allowed: ReadonlySet<string> = new Set(DEFAULT_NOTICE_SOURCES)): string | undefined {
  if (typeof source !== 'object' || source === null) return undefined
  const candidate = source as NoticeSourceLike
  if (candidate.form !== 'notice') return undefined
  if (typeof candidate.kind !== 'string' || !allowed.has(candidate.kind)) return undefined
  const summary = typeof candidate.summary === 'string' ? candidate.summary.trim() : ''
  // summary 是宿主 bound 过的一行说明；为空时给一句兜底，避免弹出空通知。
  return summary === '' ? '会话里有一条提示' : summary
}

/**
 * 由白名单配置构造集合。
 * @param configured - 配置里的白名单；undefined 时用默认值
 * @returns 集合
 */
export function noticeSourceSet(configured: readonly string[] | undefined): Set<string> {
  return new Set(configured === undefined || configured.length === 0 ? DEFAULT_NOTICE_SOURCES : configured)
}
