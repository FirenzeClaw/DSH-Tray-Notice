/**
 * 会话状态快照：谁在跑、跑到哪。
 *
 * 托盘「工作中」页与「概览」页的数据来源。设计要点是**变了才写**：快照是全量
 * 替换（托盘不做合并），所以任何一次写都覆盖全部会话；如果每次工具结果都写一行，
 * spool 会被心跳塞满。这里用「序列化后比较」做变更检测——字段少、结构浅，比逐字段
 * 比较更不容易漏。
 * @module
 */

import type { SessionView } from './events.ts'
import type { SessionRow, SessionStateEntry } from './types.ts'

/** `currentTool` 里参数摘要的最大长度。太长会把通知与面板撑开。 */
export const TOOL_LABEL_LIMIT = 60

/** 会话跟踪器。 */
export interface SessionTracker {
  /**
   * 轮次开始：置 working 并记录起始时刻。
   * @param session - 会话投影
   * @param turn - 轮次号
   */
  turnStart(session: SessionView, turn: number): void
  /**
   * 工具调用：更新 `currentTool`。
   * @param session - 会话投影
   * @param name - 工具名
   * @param args - 原始参数串（只取摘要）
   */
  toolCall(session: SessionView, name: string, args: string): void
  /**
   * 等待用户输入：置 waiting-user。
   * @param session - 会话投影
   * @param turn - 轮次号
   */
  waitingUser(session: SessionView, turn: number): void
  /**
   * 轮次结束：移出快照。
   * @param session - 会话投影
   * @param turn - 轮次号
   */
  turnEnd(session: SessionView, turn: number): void
  /** 当前快照（不触发写入）。 */
  current(): SessionStateEntry
}

/**
 * 从工具参数里取一段可读摘要。
 *
 * 只取第一个字符串值：参数的 JSON 结构各异，把整串塞进通知既难看又可能泄露路径。
 * @param args - 模型产出的原始 JSON 字符串
 * @returns 摘要；无法解析时用原串开头
 */
export function toolArgsSummary(args: string): string {
  const trimmed = args.trim()
  if (trimmed === '') return ''
  try {
    const parsed: unknown = JSON.parse(trimmed)
    if (typeof parsed === 'object' && parsed !== null) {
      for (const value of Object.values(parsed as Record<string, unknown>)) {
        if (typeof value === 'string' && value !== '') return value
      }
    }
  } catch {
    // 参数不是合法 JSON（模型可能截断），退化为原串摘要。
  }
  return trimmed
}

/**
 * 拼 `currentTool` 展示串。
 * @param name - 工具名
 * @param args - 原始参数
 * @returns 形如 `Bash · pnpm build`；参数为空时只有工具名
 */
export function toolLabel(name: string, args: string): string {
  const summary = toolArgsSummary(args)
  if (summary === '') return name
  const clipped = summary.length > TOOL_LABEL_LIMIT ? `${summary.slice(0, TOOL_LABEL_LIMIT - 1)}…` : summary
  return `${name} · ${clipped}`
}

/**
 * 创建会话跟踪器。
 * @param write - 快照写出回调（内容变化时才调用）
 * @param now - 取当前毫秒时刻
 * @returns 跟踪器
 */
export function createSessionTracker(write: (state: SessionStateEntry) => void, now: () => number): SessionTracker {
  /** 会话 id → 行。 */
  const rows = new Map<string, SessionRow>()
  /** 上次写出的内容指纹，用于抑制无变化的写。 */
  let lastFingerprint = ''

  const fingerprint = (): string => JSON.stringify([...rows.values()])

  const flush = (): void => {
    const next = fingerprint()
    if (next === lastFingerprint) return
    lastFingerprint = next
    write({
      v: 1,
      type: 'session-state',
      ts: new Date(now()).toISOString(),
      sessions: [...rows.values()],
    })
  }

  const upsert = (session: SessionView, patch: Partial<SessionRow> & Pick<SessionRow, 'state' | 'turn'>): void => {
    const previous = rows.get(session.id)
    rows.set(session.id, {
      id: session.id,
      title: session.title,
      origin: session.origin === 'subagent' ? 'subagent' : 'root',
      ...(previous ?? {}),
      ...patch,
    })
    flush()
  }

  return {
    turnStart(session, turn) {
      upsert(session, {
        state: 'working',
        turn,
        turnStartedAt: new Date(now()).toISOString(),
      })
    },

    toolCall(session, name, args) {
      const previous = rows.get(session.id)
      // 没在跟踪的会话（例如插件刚装载、轮次已开始）不凭空造行：那会让「工作中」
      // 页出现一个没有起始时刻的条目，时长算不出来。
      if (previous === undefined) return
      upsert(session, { state: previous.state === 'idle' ? 'working' : previous.state, turn: previous.turn, currentTool: toolLabel(name, args) })
    },

    waitingUser(session, turn) {
      upsert(session, { state: 'waiting-user', turn })
    },

    turnEnd(session, turn) {
      if (!rows.delete(session.id)) return
      flush()
    },

    current() {
      return {
        v: 1,
        type: 'session-state',
        ts: new Date(now()).toISOString(),
        sessions: [...rows.values()],
      }
    },
  }
}
