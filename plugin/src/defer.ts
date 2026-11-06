/**
 * 挂起完成：父会话跑完时等子会话收尾。
 *
 * 要解决的问题：一个父会话派出三个子代理并行干活，父轮次先结束。如果立刻发
 * 「已完成」，用户回到电脑前看到的是三个还在跑的子代理——通知说了谎。等子会话
 * 全部收尾再发，才符合「跑完了」的语义。
 *
 * 但等待不能无限：宽限 2 秒覆盖「子会话在同一批里陆续结束」的正常情形；超过
 * 15 分钟说明这个父会话已经不该再被当作「刚跑完」，丢弃比误报好。
 *
 * 时钟通过构造参数注入，测试才能在不真等 2 秒的情况下验证边界。
 * @module
 */

import type { NotificationKind } from './types.ts'

/** 最后一个子会话结束后的宽限：2 秒。 */
export const GRACE_MS = 2000

/** 挂起上限：15 分钟。超过即丢弃，避免用户几小时后收到一条过时的「已完成」。 */
export const MAX_DEFER_MS = 15 * 60 * 1000

/** 挂起产出的结果：交给调用方补齐会话投影与文案。 */
export interface DeferOutcome {
  readonly kind: NotificationKind
  /** 父会话 id。 */
  readonly parentId: string
  /** 挂起开始到产出的实际等待时长（毫秒），仅用于日志。 */
  readonly waitedMs: number
}

/** 一条挂起记录。 */
interface Pending {
  readonly children: Set<string>
  readonly startedAt: number
  /** 最后一个子会话结束的时刻；未全部结束前为 undefined。 */
  lastChildFinishedAt?: number
}

/** 挂起表。 */
export interface Deferrer {
  /**
   * 登记一次挂起。
   * @param parentId - 父会话 id
   * @param children - 仍在跑的子会话 id 列表
   */
  register(parentId: string, children: readonly string[]): void
  /**
   * 标记一个子会话结束。
   * @param parentId - 父会话 id
   * @param childId - 结束的子会话 id
   */
  childFinished(parentId: string, childId: string): void
  /**
   * 取消挂起（父会话恢复了新一轮，或会话被销毁）。
   * @param parentId - 父会话 id
   */
  cancel(parentId: string): void
  /**
   * 判定某父会话是否该产出通知。
   *
   * 会顺带清理：产出、超时、取消都从表里移除，所以调用方可以反复调用。
   * @param parentId - 父会话 id
   * @returns 该产出时的结果；否则 undefined
   */
  resolve(parentId: string): DeferOutcome | undefined
  /** 当前挂起数（诊断与测试用）。 */
  readonly pendingCount: number
}

/**
 * 创建挂起表。
 * @param now - 取当前毫秒时刻的函数；测试注入假时钟
 * @param log - 记一条诊断日志（超时丢弃时用）
 * @returns 挂起表
 */
export function createDeferrer(now: () => number, log: (message: string) => void = () => {}): Deferrer {
  const pending = new Map<string, Pending>()

  return {
    register(parentId, children) {
      if (pending.has(parentId)) return
      pending.set(parentId, { children: new Set(children), startedAt: now() })
    },

    childFinished(parentId, childId) {
      const entry = pending.get(parentId)
      if (entry === undefined) return
      // 未知子 id 不改变状态：它可能是另一棵子树的会话，误删会让等待提前结束。
      if (!entry.children.delete(childId)) return
      if (entry.children.size === 0 && entry.lastChildFinishedAt === undefined) {
        entry.lastChildFinishedAt = now()
      }
    },

    cancel(parentId) {
      pending.delete(parentId)
    },

    resolve(parentId) {
      const entry = pending.get(parentId)
      if (entry === undefined) return undefined
      const current = now()

      if (current - entry.startedAt > MAX_DEFER_MS) {
        pending.delete(parentId)
        log(`挂起超过 15 分钟，丢弃：${parentId}`)
        return undefined
      }
      if (entry.children.size > 0) return undefined
      const finishedAt = entry.lastChildFinishedAt ?? entry.startedAt
      if (current - finishedAt < GRACE_MS) return undefined

      pending.delete(parentId)
      return { kind: 'done', parentId, waitedMs: current - entry.startedAt }
    },

    get pendingCount() {
      return pending.size
    },
  }
}
