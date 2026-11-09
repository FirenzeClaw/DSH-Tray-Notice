/**
 * 新增外观设置项：规范化与 spool 下发。
 *
 * 为什么单独测：rowsVisible 有 3–12 的钳制，bannerClick / notificationActions
 * 是枚举，任一项写错都会让托盘侧拿到非法值——而托盘不校验，只会画出奇怪的高度。
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'

import { DEFAULT_CONFIG, normalizeConfig, normalizeRowsVisible } from '../src/config.ts'

test('rowsVisible 越界被钳制', () => {
  assert.equal(normalizeRowsVisible(99), 12)
  assert.equal(normalizeRowsVisible(0), 3)
  assert.equal(normalizeRowsVisible(-5), 3)
})

test('rowsVisible 非数字退回默认', () => {
  assert.equal(normalizeRowsVisible('5'), DEFAULT_CONFIG.rowsVisible)
  assert.equal(normalizeRowsVisible(undefined), DEFAULT_CONFIG.rowsVisible)
  assert.equal(normalizeRowsVisible(Number.NaN), DEFAULT_CONFIG.rowsVisible)
})

test('rowsVisible 小数向下取整', () => {
  assert.equal(normalizeRowsVisible(7.9), 7)
})

test('bannerClick 未知值退回 panel', () => {
  assert.equal(normalizeConfig({ bannerClick: 'nonsense' }).bannerClick, 'panel')
  assert.equal(normalizeConfig({ bannerClick: 'session' }).bannerClick, 'session')
})

test('notificationActions 未知值退回 auto', () => {
  assert.equal(normalizeConfig({ notificationActions: 'nonsense' }).notificationActions, 'auto')
  assert.equal(normalizeConfig({ notificationActions: 'on' }).notificationActions, 'on')
  assert.equal(normalizeConfig({ notificationActions: 'off' }).notificationActions, 'off')
})

test('默认值：5 条、panel、auto', () => {
  const config = normalizeConfig({})
  assert.equal(config.rowsVisible, 5)
  assert.equal(config.bannerClick, 'panel')
  assert.equal(config.notificationActions, 'auto')
})
