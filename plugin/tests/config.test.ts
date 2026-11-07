/**
 * 预设与组开关的测试。
 *
 * 断言的重点是「包含关系」而不是逐个布尔值：三档预设的语义就是层层放大，
 * 一旦有人手改某档的某一项，包含关系会立刻失败，比逐项断言更早发现意图漂移。
 * @module
 */

import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import {
  CRITICAL_TIMEOUT_MAX_MS,
  CRITICAL_TIMEOUT_MIN_MS,
  DEFAULT_CONFIG,
  PRESET_GROUPS,
  detectPreset,
  isGroupEnabled,
  normalizeConfig,
  normalizeCriticalTimeout,
  presetGroups,
  resolveGroups,
  type GroupName,
  type GroupSwitches,
} from '../src/config.ts'

const GROUPS: GroupName[] = ['needs-you', 'done-error', 'notice', 'other']

/** 组 → 是否开启（needs-you 视作任一子项）。 */
function enabledMap(groups: GroupSwitches): Record<GroupName, boolean> {
  return {
    'needs-you': isGroupEnabled(groups, 'needs-you'),
    'done-error': groups['done-error'],
    notice: groups.notice,
    other: groups.other,
  }
}

describe('预设的包含关系', () => {
  it('quiet 只开 needs-you 与 notice', () => {
    assert.deepEqual(enabledMap(PRESET_GROUPS.quiet), {
      'needs-you': true,
      'done-error': false,
      notice: true,
      other: false,
    })
  })

  it('quiet ⊂ standard ⊂ verbose', () => {
    const quiet = enabledMap(PRESET_GROUPS.quiet)
    const standard = enabledMap(PRESET_GROUPS.standard)
    const verbose = enabledMap(PRESET_GROUPS.verbose)
    for (const group of GROUPS) {
      if (quiet[group]) assert.equal(standard[group], true, `standard 应包含 quiet 的 ${group}`)
      if (standard[group]) assert.equal(verbose[group], true, `verbose 应包含 standard 的 ${group}`)
    }
  })

  it('verbose 全开', () => {
    for (const group of GROUPS) assert.equal(isGroupEnabled(PRESET_GROUPS.verbose, group), true)
  })

  it('custom 以 standard 为中性基底', () => {
    assert.deepEqual(presetGroups('custom'), PRESET_GROUPS.standard)
  })
})

describe('组级覆盖', () => {
  it('单组覆盖优先于预设', () => {
    const resolved = resolveGroups('quiet', { 'done-error': true })
    assert.equal(resolved['done-error'], true)
    assert.equal(resolved.notice, true)
  })

  it('needs-you 的子项可单独关闭，另一个保持', () => {
    const resolved = resolveGroups('quiet', { 'needs-you': { approval: false } })
    assert.equal(resolved['needs-you'].approval, false)
    assert.equal(resolved['needs-you'].answer, true)
  })

  it('不修改共享的预设对象', () => {
    const resolved = resolveGroups('quiet', { notice: false })
    assert.equal(resolved.notice, false)
    assert.equal(PRESET_GROUPS.quiet.notice, true, '预设常量被就地修改了')
  })

  it('空覆盖等于预设', () => {
    assert.deepEqual(resolveGroups('verbose'), PRESET_GROUPS.verbose)
  })
})

describe('预设反查', () => {
  it('与预设一致时返回该预设', () => {
    assert.equal(detectPreset(PRESET_GROUPS.quiet), 'quiet')
    assert.equal(detectPreset(PRESET_GROUPS.standard), 'standard')
    assert.equal(detectPreset(PRESET_GROUPS.verbose), 'verbose')
  })

  it('改动任一项即为 custom', () => {
    assert.equal(detectPreset(resolveGroups('standard', { other: true })), 'verbose')
    assert.equal(detectPreset(resolveGroups('quiet', { 'done-error': true, notice: false })), 'custom')
  })

  it('只关 needs-you 的一个子项即为 custom', () => {
    assert.equal(detectPreset(resolveGroups('standard', { 'needs-you': { answer: false } })), 'custom')
  })
})

describe('配置规范化', () => {
  it('空输入退回默认配置', () => {
    assert.deepEqual(normalizeConfig(undefined), DEFAULT_CONFIG)
    assert.deepEqual(normalizeConfig(null), DEFAULT_CONFIG)
    assert.deepEqual(normalizeConfig('nonsense'), DEFAULT_CONFIG)
  })

  it('缺 groups 时按预设补齐', () => {
    const config = normalizeConfig({ preset: 'verbose' })
    assert.deepEqual(config.groups, PRESET_GROUPS.verbose)
    assert.equal(config.preset, 'verbose')
  })

  it('groups 与 preset 冲突时以 groups 为准并重算标签', () => {
    const config = normalizeConfig({ preset: 'quiet', groups: { other: true } })
    assert.equal(config.groups.other, true)
    assert.equal(config.preset, 'custom')
  })

  it('非法 bodyLimit 退回默认值', () => {
    assert.equal(normalizeConfig({ bodyLimit: -1 }).bodyLimit, DEFAULT_CONFIG.bodyLimit)
    assert.equal(normalizeConfig({ bodyLimit: Number.NaN }).bodyLimit, DEFAULT_CONFIG.bodyLimit)
    assert.equal(normalizeConfig({ bodyLimit: '300' }).bodyLimit, DEFAULT_CONFIG.bodyLimit)
    assert.equal(normalizeConfig({ bodyLimit: 120 }).bodyLimit, 120)
  })

  it('布尔字段类型不对时退回默认', () => {
    const config = normalizeConfig({ subagents: 'yes', deferWhileChildrenRun: 1 })
    assert.equal(config.subagents, DEFAULT_CONFIG.subagents)
    assert.equal(config.deferWhileChildrenRun, DEFAULT_CONFIG.deferWhileChildrenRun)
  })
})


describe('critical 横幅时限', () => {
  it('默认 5 分钟', () => {
    assert.equal(DEFAULT_CONFIG.criticalTimeoutMs, 300_000)
    assert.equal(normalizeCriticalTimeout(undefined), 300_000)
  })

  it('越界钳到边界而不是退回默认', () => {
    assert.equal(normalizeCriticalTimeout(100), CRITICAL_TIMEOUT_MIN_MS)
    assert.equal(normalizeCriticalTimeout(99_999_999), CRITICAL_TIMEOUT_MAX_MS)
  })

  it('非法值退回默认', () => {
    for (const bad of ['60000', null, Number.NaN, Number.POSITIVE_INFINITY]) {
      assert.equal(normalizeCriticalTimeout(bad), 300_000, String(bad))
    }
  })

  it('区间内的值原样保留', () => {
    assert.equal(normalizeCriticalTimeout(600_000), 600_000)
  })

  it('normalizeConfig 会带上它', () => {
    assert.equal(normalizeConfig({ criticalTimeoutMs: 60_000 }).criticalTimeoutMs, 60_000)
    assert.equal(normalizeConfig({}).criticalTimeoutMs, 300_000)
  })
})
