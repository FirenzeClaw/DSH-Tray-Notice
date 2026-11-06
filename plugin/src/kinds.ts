/**
 * 事件分类：`kind` → 组归属、`turn/end` 原因 → `kind`。
 *
 * 为什么单独成模块：分类是**策略的核心**，而策略必须能被穷举测试。把映射写进
 * 事件处理逻辑里，就只能靠「跑一遍看看」验证；抽成常量表后，测试可以断言
 * 「七个 reason 全覆盖」「每个 kind 都有归属组」这类结构性质。
 * @module
 */

import type { GroupName } from './config.ts'
import type { NotificationKind } from './types.ts'

/**
 * `turn/end` 的结束原因。
 *
 * 七个值来自 `dsh-session/lib/types/types.d.ts` 的 `TurnEndReasonMap`
 * （本机 0.2.1-rc.5 实测）。新增值会让本文件的穷举测试失败——这是刻意的：
 * 宿主加了原因而插件没分类，用户会看到「未知」通知。
 */
export const TURN_END_REASONS = [
  'completed',
  'aborted',
  'blocked',
  'error',
  'max-tokens',
  'interrupted',
  'forked',
] as const

/** `turn/end` 结束原因。 */
export type TurnEndReason = (typeof TURN_END_REASONS)[number]

/**
 * 结束原因 → 通知类别。
 *
 * 覆盖 FR-003 的六类（完成/出错/阻塞/超限/取消/中断）。第七个原因 `forked` 没有
 * 对应的人类语义——它表示「这一轮被分叉取代」，用户视角上等同取消，故并入
 * `cancelled`，避免出现一个没人认识的类别。
 *
 * 是否真的通知还要看开关：`cancelled`/`interrupted` 归 `other` 组，该组在安静与
 * 标准预设下关闭，因此「取消与中断默认不通知」（FR-003）。
 */
export const REASON_TO_KIND: Readonly<Record<TurnEndReason, NotificationKind>> = {
  completed: 'done',
  error: 'error',
  blocked: 'blocked',
  'max-tokens': 'max-tokens',
  aborted: 'cancelled',
  interrupted: 'interrupted',
  forked: 'cancelled',
}

/**
 * 默认需要打扰的 reason 集合。
 *
 * 只列四类「有事发生」的结束；取消与中断默认静默（FR-003），但用户可以在详细
 * 预设里通过 `other` 组打开它们。
 */
export const NOTIFIABLE_REASONS: ReadonlySet<TurnEndReason> = new Set<TurnEndReason>([
  'completed',
  'error',
  'blocked',
  'max-tokens',
])

/**
 * `kind` → 所属组。
 *
 * `kind:"test"` 不在这里：它是设置页「发送测试通知」的内部验证类别，不受开关
 * 控制、不计入统计（data-model.md 的注）。查不到归属的 kind 按 `other` 处理，
 * 这样插件先升级也不会让事件静默消失。
 */
export const KIND_TO_GROUP: Readonly<Record<Exclude<NotificationKind, 'test'>, GroupName>> = {
  'needs-approval': 'needs-you',
  'needs-answer': 'needs-you',
  done: 'done-error',
  error: 'done-error',
  blocked: 'done-error',
  'max-tokens': 'done-error',
  notice: 'notice',
  cancelled: 'other',
  interrupted: 'other',
  job: 'other',
  goal: 'other',
  subagent: 'other',
  'tool-failure': 'other',
}

/**
 * 查一个 kind 的归属组。
 * @param kind - 通知类别
 * @returns 组名；`test` 与未知 kind 返回 undefined（`test` 不受开关控制）
 */
export function groupOfKind(kind: NotificationKind): GroupName | undefined {
  if (kind === 'test') return undefined
  return KIND_TO_GROUP[kind] ?? 'other'
}

/**
 * 判断某个 kind 在当前开关下是否应当通知。
 *
 * `needs-you` 组内还要再看子项：审批与提问的打扰成本不同。
 * @param kind - 通知类别
 * @param groups - 开关集合
 * @returns 是否通知
 */
export function isKindEnabled(
  kind: NotificationKind,
  groups: {
    readonly 'needs-you': { readonly approval: boolean; readonly answer: boolean }
    readonly 'done-error': boolean
    readonly notice: boolean
    readonly other: boolean
  },
): boolean {
  if (kind === 'test') return true
  if (kind === 'needs-approval') return groups['needs-you'].approval
  if (kind === 'needs-answer') return groups['needs-you'].answer
  const group = groupOfKind(kind)
  if (group === undefined || group === 'needs-you') return false
  return groups[group]
}
