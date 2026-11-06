/**
 * 挂起完成的测试。
 *
 * 全部用注入的假时钟：真实等待 2 秒会让测试变慢且不稳定，而这里要验证的恰恰是
 * 「2 秒」这个边界。时钟注入也让 15 分钟上限能在毫秒内验证。
 * @module
 */

import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import { GRACE_MS, MAX_DEFER_MS, createDeferrer } from '../src/defer.ts'

/** 假时钟：手动推进。 */
function fakeClock(start = 1_700_000_000_000) {
  let now = start
  return {
    now: () => now,
    advance: (ms: number) => {
      now += ms
    },
  }
}

describe('挂起完成的判定', () => {
  it('子会话仍在跑时不产出通知', () => {
    const clock = fakeClock()
    const deferrer = createDeferrer(clock.now)
    deferrer.register('parent', ['child-1'])

    assert.equal(deferrer.resolve('parent'), undefined)
    assert.equal(deferrer.pendingCount, 1)
  })

  it('最后一个子会话结束后进入宽限，宽限内不产出', () => {
    const clock = fakeClock()
    const deferrer = createDeferrer(clock.now)
    deferrer.register('parent', ['child-1', 'child-2'])

    deferrer.childFinished('parent', 'child-1')
    assert.equal(deferrer.resolve('parent'), undefined)

    deferrer.childFinished('parent', 'child-2')
    clock.advance(GRACE_MS - 1)
    assert.equal(deferrer.resolve('parent'), undefined)
  })

  it('宽限到期后产出通知', () => {
    const clock = fakeClock()
    const deferrer = createDeferrer(clock.now)
    deferrer.register('parent', ['child-1'])
    deferrer.childFinished('parent', 'child-1')

    clock.advance(GRACE_MS)
    const outcome = deferrer.resolve('parent')
    assert.ok(outcome)
    assert.equal(outcome.kind, 'done')
    assert.equal(deferrer.pendingCount, 0, '产出后应移出挂起表')
  })

  it('父会话在宽限内恢复则取消挂起', () => {
    const clock = fakeClock()
    const deferrer = createDeferrer(clock.now)
    deferrer.register('parent', ['child-1'])
    deferrer.childFinished('parent', 'child-1')
    clock.advance(GRACE_MS - 100)

    deferrer.cancel('parent')
    clock.advance(GRACE_MS)
    assert.equal(deferrer.resolve('parent'), undefined)
    assert.equal(deferrer.pendingCount, 0)
  })

  it('超过 15 分钟上限后丢弃且不产出', () => {
    const clock = fakeClock()
    const logged: string[] = []
    const deferrer = createDeferrer(clock.now, (message) => logged.push(message))
    deferrer.register('parent', ['child-1'])
    deferrer.childFinished('parent', 'child-1')

    clock.advance(MAX_DEFER_MS + 1)
    assert.equal(deferrer.resolve('parent'), undefined)
    assert.equal(deferrer.pendingCount, 0)
    assert.ok(logged.some((line) => line.includes('15')))
  })

  it('上限内产出（边界值）', () => {
    const clock = fakeClock()
    const deferrer = createDeferrer(clock.now)
    deferrer.register('parent', ['child-1'])
    deferrer.childFinished('parent', 'child-1')

    clock.advance(MAX_DEFER_MS - 1)
    assert.ok(deferrer.resolve('parent'))
  })

  it('未登记的会话 resolve 返回 undefined', () => {
    const deferrer = createDeferrer(fakeClock().now)
    assert.equal(deferrer.resolve('nobody'), undefined)
  })

  it('重复登记同一父会话不叠加', () => {
    const deferrer = createDeferrer(fakeClock().now)
    deferrer.register('parent', ['child-1'])
    deferrer.register('parent', ['child-1'])
    assert.equal(deferrer.pendingCount, 1)
  })

  it('子会话结束时未知子 id 不影响判定', () => {
    const clock = fakeClock()
    const deferrer = createDeferrer(clock.now)
    deferrer.register('parent', ['child-1'])
    deferrer.childFinished('parent', 'unknown-child')
    clock.advance(GRACE_MS)
    assert.equal(deferrer.resolve('parent'), undefined, '已知子会话仍在跑')
  })
})
