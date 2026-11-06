/**
 * 会话状态快照的测试。
 *
 * 核心断言是「变了才写」：托盘每 500 ms 读一次 spool，如果每次 `tool/result` 都
 * 写一行全量快照，spool 会被无意义的心跳塞满。所以这里既验证状态正确，也验证
 * 写入次数。
 * @module
 */

import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import { createSessionTracker } from '../src/sessionstate.ts'
import type { SessionView } from '../src/events.ts'

/** 造一个会话投影。 */
function session(overrides: Partial<SessionView> = {}): SessionView {
  return {
    id: 'session-1',
    title: '通知面板设计',
    cwd: '/home/firenzeclaw/Code/DSH-Tray&Notice',
    ...overrides,
  }
}

/** 收集写出的快照。 */
function collector() {
  const writes: { sessions: readonly { id: string; state: string; currentTool?: string }[] }[] = []
  return {
    writes,
    write: (state: { sessions: readonly { id: string; state: string; currentTool?: string }[] }) => {
      writes.push(state)
    },
  }
}

describe('会话快照的写入时机', () => {
  it('turn/start + tool/call + turn/end 共写 3 行', () => {
    const sink = collector()
    const tracker = createSessionTracker(sink.write, () => 1_700_000_000_000)

    tracker.turnStart(session(), 4)
    tracker.toolCall(session(), 'Bash', 'pnpm build')
    tracker.turnEnd(session(), 4)

    assert.equal(sink.writes.length, 3)
    assert.equal(sink.writes[0]?.sessions[0]?.state, 'working')
    assert.equal(sink.writes[1]?.sessions[0]?.currentTool, 'Bash · pnpm build')
    assert.equal(sink.writes[2]?.sessions.length, 0)
  })

  it('内容未变时不写新行', () => {
    const sink = collector()
    const tracker = createSessionTracker(sink.write, () => 1_700_000_000_000)

    tracker.turnStart(session(), 4)
    tracker.toolCall(session(), 'Bash', 'pnpm build')
    tracker.toolCall(session(), 'Bash', 'pnpm build')

    assert.equal(sink.writes.length, 2, '重复的 tool/call 不该再写')
  })

  it('turn/end 对未知会话不写', () => {
    const sink = collector()
    const tracker = createSessionTracker(sink.write, () => 1_700_000_000_000)
    tracker.turnEnd(session({ id: 'never-started' }), 1)
    assert.equal(sink.writes.length, 0)
  })
})

describe('会话快照的内容', () => {
  it('turn/start 记录 turnStartedAt 与轮次', () => {
    const sink = collector()
    const tracker = createSessionTracker(sink.write, () => 1_700_000_000_000)
    tracker.turnStart(session(), 7)

    const row = sink.writes[0]?.sessions[0] as unknown as { turn: number; turnStartedAt: string; origin: string }
    assert.equal(row.turn, 7)
    assert.equal(row.turnStartedAt, new Date(1_700_000_000_000).toISOString())
    assert.equal(row.origin, 'root')
  })

  it('子会话标记 origin=subagent', () => {
    const sink = collector()
    const tracker = createSessionTracker(sink.write, () => 1_700_000_000_000)
    tracker.turnStart(session({ origin: 'subagent' }), 1)
    const row = sink.writes[0]?.sessions[0] as unknown as { origin: string }
    assert.equal(row.origin, 'subagent')
  })

  it('waitingUser 置 waiting-user 并保留 currentTool', () => {
    const sink = collector()
    const tracker = createSessionTracker(sink.write, () => 1_700_000_000_000)
    tracker.turnStart(session(), 2)
    tracker.toolCall(session(), 'Bash', 'ls')
    tracker.waitingUser(session(), 2)

    const row = sink.writes.at(-1)?.sessions[0] as unknown as { state: string; currentTool: string }
    assert.equal(row.state, 'waiting-user')
    assert.equal(row.currentTool, 'Bash · ls')
  })

  it('多会话共存，各自独立', () => {
    const sink = collector()
    const tracker = createSessionTracker(sink.write, () => 1_700_000_000_000)
    tracker.turnStart(session({ id: 'a' }), 1)
    tracker.turnStart(session({ id: 'b' }), 1)

    const ids = (sink.writes.at(-1)?.sessions ?? []).map((row) => row.id).sort()
    assert.deepEqual(ids, ['a', 'b'])
  })

  it('快照是全量替换：turn/end 后该会话消失但其它保留', () => {
    const sink = collector()
    const tracker = createSessionTracker(sink.write, () => 1_700_000_000_000)
    tracker.turnStart(session({ id: 'a' }), 1)
    tracker.turnStart(session({ id: 'b' }), 1)
    tracker.turnEnd(session({ id: 'a' }), 1)

    const ids = (sink.writes.at(-1)?.sessions ?? []).map((row) => row.id)
    assert.deepEqual(ids, ['b'])
  })

  it('工具名与参数用 · 连接，参数过长截断', () => {
    const sink = collector()
    const tracker = createSessionTracker(sink.write, () => 1_700_000_000_000)
    tracker.turnStart(session(), 1)
    tracker.toolCall(session(), 'Bash', 'x'.repeat(200))

    const row = sink.writes.at(-1)?.sessions[0] as unknown as { currentTool: string }
    assert.ok(row.currentTool.startsWith('Bash · '))
    assert.ok(row.currentTool.length < 100, `实际 ${row.currentTool.length}`)
  })

  it('快照带 v 与 type', () => {
    const sink = collector()
    const tracker = createSessionTracker(sink.write, () => 1_700_000_000_000)
    tracker.turnStart(session(), 1)

    const state = sink.writes[0] as unknown as { v: number; type: string; ts: string }
    assert.equal(state.v, 1)
    assert.equal(state.type, 'session-state')
    assert.equal(state.ts, new Date(1_700_000_000_000).toISOString())
  })
})
