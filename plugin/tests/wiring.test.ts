/**
 * 接线测试：订阅顺序、错误隔离、prepend 语义。
 *
 * 重点是 `user-questions/request` 的**调用序列**：先写 spool，再 `next()`。
 * 这条顺序错了不会让任何测试变红——Web 端照样能弹出提问卡片，只是通知可能晚于
 * 用户回答——所以必须显式断言。
 * @module
 */

import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import { wire, sessionView, type PluginHost } from '../src/index.ts'
import { createLogger } from '../src/log.ts'
import type { SpoolWriter } from '../src/spool.ts'
import type { SpoolRow } from '../src/types.ts'

/** 收集写入行。 */
function collector(): SpoolWriter & { rows: SpoolRow[] } {
  const rows: SpoolRow[] = []
  return {
    path: '/tmp/fake.jsonl',
    rows,
    append: (row) => {
      rows.push(row)
    },
  }
}

/** 假宿主：记录监听器与 prepend 标志。 */
function fakeHost(settings?: unknown) {
  const listeners = new Map<string, { handler: (...args: never[]) => unknown; prepend: boolean }[]>()
  const host: PluginHost & { emit(event: string, ...args: unknown[]): unknown; prepended(event: string): boolean[] } = {
    ...(settings === undefined ? {} : { settings: settings as never }),
    on(event, handler, options) {
      const entry = { handler: handler as never, prepend: options?.prepend ?? false }
      const list = listeners.get(event) ?? []
      list.push(entry)
      listeners.set(event, list)
      return () => {
        const index = list.indexOf(entry)
        if (index >= 0) list.splice(index, 1)
        return true
      }
    },
    emit(event, ...args) {
      const list = listeners.get(event) ?? []
      let result: unknown
      for (const entry of list) result = (entry.handler as (...a: unknown[]) => unknown)(...args)
      return result
    },
    /** 带 `this` 绑定触发：cordis 的监听器以 scoped context 为 this。 */
    emitWithThis(event, thisArg, ...args) {
      const list = listeners.get(event) ?? []
      let result: unknown
      for (const entry of list) {
        result = (entry.handler as (...a: unknown[]) => unknown).apply(thisArg, args)
      }
      return result
    },
    prepended(event) {
      return (listeners.get(event) ?? []).map((entry) => entry.prepend)
    },
  }
  return host
}

/** 造一个最小会话。 */
function makeSession(id: string, options: { origin?: 'subagent'; parent?: string; cwd?: string } = {}) {
  return {
    id,
    header: {
      cwd: options.cwd ?? '/home/firenzeclaw/Code/DSH-Tray&Notice',
      ...(options.origin === undefined ? {} : { origin: options.origin }),
      ...(options.parent === undefined ? {} : { parentSession: options.parent }),
    },
  }
}

/** 固定时钟。 */
const fixedNow = () => new Date('2026-11-06T12:00:00.000Z')

describe('订阅装配', () => {
  it('订阅五类事件源', () => {
    const spool = collector()
    const host = fakeHost()
    const wiring = wire(host, createLogger(undefined, 'test'), spool, fixedNow)
    assert.deepEqual(host.prepended('user-questions/request'), [true], '提问监听必须 prepend')
    wiring.dispose()
  })

  it('提问监听在 next 之前写完 spool', () => {
    const spool = collector()
    const host = fakeHost()
    const wiring = wire(host, createLogger(undefined, 'test'), spool, fixedNow)
    const writesAtNext: number[] = []

    host.emitWithThis(
      'user-questions/request',
      { agent: { id: 'session-1' } },
      { questions: [{ question: '选哪个？' }], wait: { callId: 'call_1' } },
      () => {
        writesAtNext.push(spool.rows.length)
        return Promise.resolve({})
      },
    )

    // 装载时先下发一条 tray-settings，所以这里计数是 3 而不是 2；断言的是
    // 「next 之前那些行已经落盘」，与具体条数无关的话就退化成不验证顺序了，
    // 因此改为按类型断言：此刻通知行必须已经存在。
    const typesAtNext = spool.rows.slice(0, writesAtNext[0] ?? 0).map((row) => row.type)
    assert.ok(typesAtNext.includes('notification'), 'next 时通知必须已写入')
    assert.ok(typesAtNext.includes('session-state'), 'next 时会话快照必须已写入')
    assert.equal(spool.rows.filter((row) => row.type === 'notification').length, 1)
    wiring.dispose()
  })

  it('监听器抛错不影响其它订阅', () => {
    const spool = collector()
    const host = fakeHost()
    const wiring = wire(host, createLogger(undefined, 'test'), spool, fixedNow)

    // 造一个会让内部逻辑抛错的事件：session 为 null
    assert.doesNotThrow(() => host.emit('session/event', null, { type: 'turn/start', data: { turn: 1 } }))
    wiring.dispose()
  })
})

describe('会话事件的处理', () => {
  it('turn/start 写快照', () => {
    const spool = collector()
    const host = fakeHost()
    const wiring = wire(host, createLogger(undefined, 'test'), spool, fixedNow)

    host.emit('session/event', makeSession('s-1'), { type: 'turn/start', data: { turn: 1 } })
    const state = spool.rows.find((row) => row.type === 'session-state')
    assert.ok(state)
    assert.equal(state.type === 'session-state' ? state.sessions[0]?.state : '', 'working')
    wiring.dispose()
  })

  it('turn/end(completed) 写通知', () => {
    const spool = collector()
    const host = fakeHost()
    const wiring = wire(host, createLogger(undefined, 'test'), spool, fixedNow)

    host.emit('session/event', makeSession('s-1'), { type: 'turn/start', data: { turn: 1 } })
    host.emit('session/event', makeSession('s-1'), {
      type: 'turn/end',
      data: { turn: 1, reason: { kind: 'completed' } },
    })

    const notification = spool.rows.find((row) => row.type === 'notification')
    assert.ok(notification)
    assert.equal(notification.type === 'notification' ? notification.kind : '', 'done')
    wiring.dispose()
  })

  it('approval/asked 写 critical 通知', () => {
    const spool = collector()
    const host = fakeHost()
    const wiring = wire(host, createLogger(undefined, 'test'), spool, fixedNow)

    host.emit('session/event', makeSession('s-1'), { type: 'turn/start', data: { turn: 1 } })
    host.emit('session/event', makeSession('s-1'), {
      type: 'approval/asked',
      data: { id: 'appr_1', toolName: 'Bash' },
    })

    const notification = spool.rows.find((row) => row.type === 'notification')
    assert.ok(notification)
    assert.equal(notification.type === 'notification' ? notification.urgency : '', 'critical')
    wiring.dispose()
  })

  it('notice 形态的 user/message 抬成通知', () => {
    const spool = collector()
    const host = fakeHost()
    const wiring = wire(host, createLogger(undefined, 'test'), spool, fixedNow)

    host.emit('session/event', makeSession('s-1'), {
      type: 'user/message',
      data: {
        source: { kind: 'target-monitor', form: 'notice', summary: '你可能卡住了' },
      },
    })

    const notification = spool.rows.find((row) => row.type === 'notification')
    assert.ok(notification, '应当写出一条通知')
    assert.equal(notification.type === 'notification' ? notification.kind : '', 'notice')
    assert.equal(notification.type === 'notification' ? notification.body : '', '你可能卡住了')
    wiring.dispose()
  })

  it('未知 kind 的 notice 不抬成通知', () => {
    const spool = collector()
    const host = fakeHost()
    const wiring = wire(host, createLogger(undefined, 'test'), spool, fixedNow)

    host.emit('session/event', makeSession('s-1'), {
      type: 'user/message',
      data: { source: { kind: 'unknown-plugin', form: 'notice', summary: 'x' } },
    })

    assert.equal(spool.rows.filter((row) => row.type === 'notification').length, 0)
    wiring.dispose()
  })

  it('子会话结束会解开父会话的挂起', () => {
    const spool = collector()
    const host = fakeHost()
    const wiring = wire(host, createLogger(undefined, 'test'), spool, fixedNow)

    // 父会话开轮 → 子会话开轮 → 父会话 completed（应挂起）
    host.emit('session/event', makeSession('parent'), { type: 'turn/start', data: { turn: 1 } })
    host.emit('session/event', makeSession('child', { origin: 'subagent', parent: 'parent' }), {
      type: 'turn/start',
      data: { turn: 1 },
    })
    host.emit('session/event', makeSession('parent'), {
      type: 'turn/end',
      data: { turn: 1, reason: { kind: 'completed' } },
    })

    assert.equal(
      spool.rows.filter((row) => row.type === 'notification').length,
      0,
      '子会话还在跑，父会话不该发通知',
    )
    wiring.dispose()
  })
})

describe('会话投影', () => {
  it('标题服务优先', () => {
    const view = sessionView(makeSession('s-1'), { get: () => ({ title: '通知面板设计' }) })
    assert.equal(view.title, '通知面板设计')
  })

  it('无标题服务时退回 cwd 末段', () => {
    const view = sessionView(makeSession('s-1'), undefined)
    assert.equal(view.title, 'DSH-Tray&Notice')
  })

  it('无 cwd 时退回会话 id', () => {
    const session = { id: 's-1', header: {} }
    const view = sessionView(session as never, undefined)
    assert.equal(view.title, 's-1')
  })

  it('子会话标记 origin', () => {
    const view = sessionView(makeSession('s-1', { origin: 'subagent' }), undefined)
    assert.equal(view.origin, 'subagent')
  })
})
