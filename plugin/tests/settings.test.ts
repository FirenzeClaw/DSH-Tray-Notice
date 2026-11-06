/**
 * 设置读取与热更新的测试。
 *
 * 用假设置服务与假上下文：`bindSettings` 只要求 `on` 与 `describe` 两个方法，
 * 结构类型让这条测试不必造 cordis 运行时。
 * @module
 */

import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import { DEFAULT_CONFIG, PRESET_GROUPS } from '../src/config.ts'
import type { Logger } from '../src/log.ts'
import { SETTINGS_NAMESPACE, bindSettings, createPolicy, readConfig } from '../src/settings.ts'

/** 收集日志的假 logger。 */
function fakeLogger(): Logger & { lines: string[] } {
  const lines: string[] = []
  return {
    lines,
    debug: (message) => lines.push(`debug ${message}`),
    info: (message) => lines.push(`info ${message}`),
    warn: (message) => lines.push(`warn ${message}`),
    error: (message) => lines.push(`error ${message}`),
  }
}

/** 假设置服务：`value` 可随时替换，`fail` 控制是否抛错。 */
function fakeSettings(initial: unknown, options: { fail?: boolean; ns?: string } = {}) {
  const state = { value: initial, fail: options.fail ?? false, ns: options.ns ?? SETTINGS_NAMESPACE }
  return {
    state,
    describe() {
      if (state.fail) throw new Error('settings backend down')
      return [{ ns: state.ns, value: state.value }]
    },
  }
}

/** 假上下文：记录监听器，`emit` 触发。 */
function fakeContext() {
  const listeners: ((ns: string) => void)[] = []
  return {
    on(event: string, listener: (ns: string) => void) {
      assert.equal(event, 'settings/document-updated')
      listeners.push(listener)
      return () => {
        const index = listeners.indexOf(listener)
        if (index >= 0) listeners.splice(index, 1)
      }
    },
    emit(ns: string) {
      for (const listener of [...listeners]) listener(ns)
    },
    get listenerCount() {
      return listeners.length
    },
  }
}

describe('读配置', () => {
  it('读到预设时按其开关生效', () => {
    const logger = fakeLogger()
    const config = readConfig(fakeSettings({ preset: 'verbose' }), logger)
    assert.equal(config.preset, 'verbose')
    assert.equal(config.groups.other, true)
  })

  it('缺条目时用默认配置并记 info', () => {
    const logger = fakeLogger()
    const config = readConfig(fakeSettings(undefined, { ns: 'other-plugin' }), logger)
    assert.deepEqual(config, DEFAULT_CONFIG)
    assert.ok(logger.lines.some((line) => line.startsWith('info')))
  })

  it('读抛错时回退标准预设并记 warn', () => {
    const logger = fakeLogger()
    const config = readConfig(fakeSettings({}, { fail: true }), logger)
    assert.deepEqual(config, DEFAULT_CONFIG)
    assert.ok(logger.lines.some((line) => line.startsWith('warn') && line.includes('回退')))
  })

  it('没有 settings 服务时回退默认并记 warn', () => {
    const logger = fakeLogger()
    const config = readConfig(undefined, logger)
    assert.deepEqual(config, DEFAULT_CONFIG)
    assert.ok(logger.lines.some((line) => line.startsWith('warn')))
  })
})

describe('策略对象', () => {
  it('wants 反映组开关', () => {
    const policy = createPolicy({ ...DEFAULT_CONFIG, groups: PRESET_GROUPS.quiet })
    assert.equal(policy.wants('needs-approval'), true)
    assert.equal(policy.wants('done'), false)
    assert.equal(policy.wants('notice'), true)
    assert.equal(policy.wants('job'), false)
  })

  it('test 类别始终放行', () => {
    const policy = createPolicy({ ...DEFAULT_CONFIG, groups: PRESET_GROUPS.quiet })
    assert.equal(policy.wants('test'), true)
  })
})

describe('热更新', () => {
  it('设置变更后策略更新', () => {
    const logger = fakeLogger()
    const settings = fakeSettings({ preset: 'quiet' })
    const ctx = fakeContext()
    const binding = bindSettings(ctx, settings, logger)
    assert.equal(binding.current().config.preset, 'quiet')
    assert.equal(binding.current().wants('done'), false)

    settings.state.value = { preset: 'verbose' }
    ctx.emit(SETTINGS_NAMESPACE)

    assert.equal(binding.current().config.preset, 'verbose')
    assert.equal(binding.current().wants('done'), true)
  })

  it('其它命名空间的变更不触发重读', () => {
    const logger = fakeLogger()
    const settings = fakeSettings({ preset: 'quiet' })
    const ctx = fakeContext()
    const binding = bindSettings(ctx, settings, logger)

    settings.state.value = { preset: 'verbose' }
    ctx.emit('some-other-plugin')

    assert.equal(binding.current().config.preset, 'quiet')
  })

  it('dispose 后不再重读', () => {
    const logger = fakeLogger()
    const settings = fakeSettings({ preset: 'quiet' })
    const ctx = fakeContext()
    const binding = bindSettings(ctx, settings, logger)
    binding.dispose()
    assert.equal(ctx.listenerCount, 0)

    settings.state.value = { preset: 'verbose' }
    ctx.emit(SETTINGS_NAMESPACE)
    assert.equal(binding.current().config.preset, 'quiet')
  })

  it('变更后读失败时退回标准预设而不是保留旧值', () => {
    const logger = fakeLogger()
    const settings = fakeSettings({ preset: 'verbose' })
    const ctx = fakeContext()
    const binding = bindSettings(ctx, settings, logger)
    assert.equal(binding.current().config.preset, 'verbose')

    settings.state.fail = true
    ctx.emit(SETTINGS_NAMESPACE)
    assert.equal(binding.current().config.preset, DEFAULT_CONFIG.preset)
  })
})
