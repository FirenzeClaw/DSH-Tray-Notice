/**
 * 设置分区逻辑的测试。
 *
 * 只测纯函数（`groupsOf` / `presetOf`）：React 组件本身要靠真实宿主渲染才能验证，
 * 而「预设与组开关的映射」「改一组后变成自定义」这类规则是纯数据变换，值得直接断言。
 * @module
 */

import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import { groupsOf, presetOf } from '../src/client/index.ts'

describe('设置值规范化', () => {
  it('完整值原样保留', () => {
    const groups = groupsOf({
      groups: {
        'needs-you': { approval: false, answer: true },
        'done-error': true,
        notice: false,
        other: true,
      },
    })
    assert.deepEqual(groups, {
      'needs-you': { approval: false, answer: true },
      'done-error': true,
      notice: false,
      other: true,
    })
  })

  it('缺字段时用服务端默认值补齐', () => {
    const groups = groupsOf({})
    assert.deepEqual(groups, {
      'needs-you': { approval: true, answer: true },
      'done-error': true,
      notice: true,
      other: false,
    })
  })

  it('类型不对时退回默认', () => {
    const groups = groupsOf({ groups: { 'done-error': 'yes', notice: 1 } })
    assert.equal(groups['done-error'], true)
    assert.equal(groups.notice, true)
  })

  it('非对象输入不抛错', () => {
    assert.doesNotThrow(() => groupsOf(undefined))
    assert.doesNotThrow(() => groupsOf(null))
    assert.doesNotThrow(() => groupsOf('nonsense'))
  })
})

describe('预设反查', () => {
  it('三档预设各自可识别', () => {
    assert.equal(presetOf(groupsOf({ groups: { 'needs-you': { approval: true, answer: true }, 'done-error': false, notice: true, other: false } })), 'quiet')
    assert.equal(presetOf(groupsOf({ groups: { 'needs-you': { approval: true, answer: true }, 'done-error': true, notice: true, other: false } })), 'standard')
    assert.equal(presetOf(groupsOf({ groups: { 'needs-you': { approval: true, answer: true }, 'done-error': true, notice: true, other: true } })), 'verbose')
  })

  it('改动任一项即为自定义', () => {
    const groups = groupsOf({ groups: { 'needs-you': { approval: true, answer: false }, 'done-error': true, notice: true, other: false } })
    assert.equal(presetOf(groups), 'custom')
  })
})
