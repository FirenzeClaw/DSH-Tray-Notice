/**
 * 事件分类的结构性测试。
 *
 * 断言的是**覆盖性**而非逐项对错：七个 reason 各有归属、每个 kind 都有组、
 * 宿主新增 reason 时这里必须先失败。逐项断言只会让人在加一个 reason 时
 * 顺手把测试也改绿，覆盖性断言则逼人回来想「新原因该不该通知」。
 * @module
 */

import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import { PRESET_GROUPS, resolveGroups } from '../src/config.ts'
import {
  KIND_TO_GROUP,
  NOTIFIABLE_REASONS,
  REASON_TO_KIND,
  TURN_END_REASONS,
  groupOfKind,
  isKindEnabled,
} from '../src/kinds.ts'
import type { NotificationKind } from '../src/types.ts'

describe('turn/end 原因覆盖', () => {
  it('七个 reason 全覆盖', () => {
    assert.equal(TURN_END_REASONS.length, 7)
    for (const reason of TURN_END_REASONS) {
      assert.ok(REASON_TO_KIND[reason], `reason ${reason} 没有分类`)
    }
  })

  it('六类语义齐全（FR-003）', () => {
    const kinds = new Set(TURN_END_REASONS.map((reason) => REASON_TO_KIND[reason]))
    for (const expected of ['done', 'error', 'blocked', 'max-tokens', 'cancelled', 'interrupted']) {
      assert.ok(kinds.has(expected as NotificationKind), `缺少类别 ${expected}`)
    }
  })

  it('默认打扰的 reason 只有四类', () => {
    assert.deepEqual(
      [...NOTIFIABLE_REASONS].sort(),
      ['blocked', 'completed', 'error', 'max-tokens'],
    )
  })

  it('取消与中断默认不通知（归 other 组）', () => {
    assert.equal(groupOfKind(REASON_TO_KIND.aborted), 'other')
    assert.equal(groupOfKind(REASON_TO_KIND.interrupted), 'other')
    assert.equal(isKindEnabled('cancelled', PRESET_GROUPS.standard), false)
    assert.equal(isKindEnabled('interrupted', PRESET_GROUPS.standard), false)
  })

  it('详细预设下取消与中断会通知', () => {
    assert.equal(isKindEnabled('cancelled', PRESET_GROUPS.verbose), true)
    assert.equal(isKindEnabled('interrupted', PRESET_GROUPS.verbose), true)
  })
})

describe('kind → 组', () => {
  it('每个非 test 的 kind 都有归属组', () => {
    const kinds: NotificationKind[] = [
      'needs-approval',
      'needs-answer',
      'done',
      'error',
      'blocked',
      'max-tokens',
      'cancelled',
      'interrupted',
      'job',
      'goal',
      'subagent',
      'tool-failure',
      'notice',
    ]
    for (const kind of kinds) {
      assert.ok(groupOfKind(kind), `kind ${kind} 没有归属组`)
      assert.ok(KIND_TO_GROUP[kind as Exclude<NotificationKind, 'test'>], `kind ${kind} 缺映射`)
    }
  })

  it('test 类别不受开关控制', () => {
    assert.equal(groupOfKind('test'), undefined)
    assert.equal(isKindEnabled('test', PRESET_GROUPS.quiet), true)
  })

  it('未知 kind 落到 other 组而不是丢弃', () => {
    assert.equal(groupOfKind('brand-new-kind' as NotificationKind), 'other')
  })
})

describe('needs-you 的子项开关', () => {
  it('只关审批时提问仍然通知', () => {
    const groups = resolveGroups('standard', { 'needs-you': { approval: false } })
    assert.equal(isKindEnabled('needs-approval', groups), false)
    assert.equal(isKindEnabled('needs-answer', groups), true)
  })

  it('两个子项都关后组内全静默', () => {
    const groups = resolveGroups('standard', { 'needs-you': { approval: false, answer: false } })
    assert.equal(isKindEnabled('needs-approval', groups), false)
    assert.equal(isKindEnabled('needs-answer', groups), false)
  })
})
