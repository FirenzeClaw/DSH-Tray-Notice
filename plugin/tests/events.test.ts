/**
 * 通知意图生成的测试。
 *
 * 只测纯函数 `intentFromEvent`：把「宿主事件 → 该不该通知、文案是什么」这段决策
 * 从订阅代码里剥出来，才能在没有任何 cordis 运行时的情况下穷举验证。
 * @module
 */

import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import { PRESET_GROUPS } from '../src/config.ts'
import { createPolicy } from '../src/settings.ts'
import type { TrayNotifyConfig } from '../src/config.ts'
import { intentFromTurnEnd, intentFromApproval, intentFromQuestion } from '../src/events.ts'

/** 造一个策略：verbose 全开，方便观察分类而不被开关挡住。 */
function verbosePolicy(bodyLimit = 200) {
  const config: TrayNotifyConfig = {
    preset: 'verbose',
    groups: PRESET_GROUPS.verbose,
    subagents: false,
    deferWhileChildrenRun: true,
    bodyLimit,
  }
  return createPolicy(config)
}

/** 会话的最小投影。 */
const SESSION = {
  id: 'session-1dc80bc4' as never,
  title: '通知面板设计',
  cwd: '/home/firenzeclaw/Code/DSH-Tray&Notice',
}

describe('turn/end → 意图', () => {
  it('completed 产出 done，urgent=normal，去重键带轮次', () => {
    const intent = intentFromTurnEnd(verbosePolicy(), SESSION, { turn: 4, reason: 'completed' })
    assert.ok(intent)
    assert.equal(intent.kind, 'done')
    assert.equal(intent.urgency, 'normal')
    assert.equal(intent.dedupeKey, 'done:session-1dc80bc4:4')
    assert.equal(intent.sessionId, 'session-1dc80bc4')
    assert.equal(intent.sessionTitle, '通知面板设计')
  })

  it('error 产出 error 且正文含原因', () => {
    const intent = intentFromTurnEnd(verbosePolicy(), SESSION, { turn: 5, reason: 'error' })
    assert.ok(intent)
    assert.equal(intent.kind, 'error')
    assert.match(intent.body, /出错|错误/)
  })

  it('blocked 与 max-tokens 各有对应类别', () => {
    const blocked = intentFromTurnEnd(verbosePolicy(), SESSION, { turn: 6, reason: 'blocked' })
    const tokens = intentFromTurnEnd(verbosePolicy(), SESSION, { turn: 7, reason: 'max-tokens' })
    assert.equal(blocked?.kind, 'blocked')
    assert.equal(tokens?.kind, 'max-tokens')
  })

  it('aborted 在标准预设下不产出意图', () => {
    const config: TrayNotifyConfig = {
      preset: 'standard',
      groups: PRESET_GROUPS.standard,
      subagents: false,
      deferWhileChildrenRun: true,
      bodyLimit: 200,
    }
    assert.equal(intentFromTurnEnd(createPolicy(config), SESSION, { turn: 8, reason: 'aborted' }), undefined)
  })

  it('子会话默认不产出意图', () => {
    const intent = intentFromTurnEnd(verbosePolicy(), { ...SESSION, origin: 'subagent' }, {
      turn: 1,
      reason: 'completed',
    })
    assert.equal(intent, undefined)
  })

  it('子会话开关打开后产出意图', () => {
    const config: TrayNotifyConfig = {
      preset: 'verbose',
      groups: PRESET_GROUPS.verbose,
      subagents: true,
      deferWhileChildrenRun: true,
      bodyLimit: 200,
    }
    const intent = intentFromTurnEnd(createPolicy(config), { ...SESSION, origin: 'subagent' }, {
      turn: 1,
      reason: 'completed',
    })
    assert.ok(intent)
    assert.equal(intent.kind, 'subagent')
  })

  it('正文超 bodyLimit 时截断并加省略号', () => {
    const intent = intentFromTurnEnd(verbosePolicy(20), SESSION, { turn: 9, reason: 'error' })
    assert.ok(intent)
    assert.ok(intent.body.length <= 21, `实际长度 ${intent.body.length}`)
    assert.ok(intent.body.endsWith('…'))
  })

  it('openUrl 不含令牌', () => {
    const intent = intentFromTurnEnd(verbosePolicy(), SESSION, { turn: 1, reason: 'completed' })
    assert.ok(intent)
    assert.equal(intent.openUrl, 'http://127.0.0.1:3080/?session=session-1dc80bc4')
    assert.ok(!intent.openUrl.includes('token'))
  })
})

describe('approval/asked → 意图', () => {
  it('产出 critical 的 needs-approval，去重键按审批 id', () => {
    const intent = intentFromApproval(verbosePolicy(), SESSION, {
      id: 'appr_01' as never,
      toolName: 'Bash',
      reason: 'rm -rf dist',
    })
    assert.ok(intent)
    assert.equal(intent.kind, 'needs-approval')
    assert.equal(intent.urgency, 'critical')
    assert.equal(intent.dedupeKey, 'approval:appr_01')
    assert.match(intent.body, /Bash/)
  })

  it('审批子项关闭时不产出意图', () => {
    const config: TrayNotifyConfig = {
      preset: 'standard',
      groups: { ...PRESET_GROUPS.standard, 'needs-you': { approval: false, answer: true } },
      subagents: false,
      deferWhileChildrenRun: true,
      bodyLimit: 200,
    }
    const intent = intentFromApproval(createPolicy(config), SESSION, {
      id: 'appr_02' as never,
      toolName: 'Bash',
    })
    assert.equal(intent, undefined)
  })
})

describe('user-questions/request → 意图', () => {
  it('产出 critical 的 needs-answer', () => {
    const intent = intentFromQuestion(verbosePolicy(), SESSION, {
      questions: [{ question: '选哪个方案？', options: [{ label: 'A' }, { label: 'B' }] }],
      wait: { callId: 'call_01' as never },
    })
    assert.ok(intent)
    assert.equal(intent.kind, 'needs-answer')
    assert.equal(intent.urgency, 'critical')
    assert.equal(intent.dedupeKey, 'question:call_01')
    assert.match(intent.body, /选哪个方案/)
  })

  it('没有 callId 时用问题文本生成稳定去重键', () => {
    const first = intentFromQuestion(verbosePolicy(), SESSION, {
      questions: [{ question: '继续吗？' }],
    })
    const second = intentFromQuestion(verbosePolicy(), SESSION, {
      questions: [{ question: '继续吗？' }],
    })
    assert.ok(first && second)
    assert.equal(first.dedupeKey, second.dedupeKey)
    assert.ok(first.dedupeKey.startsWith('question:'))
  })

  it('提问子项关闭时不产出意图', () => {
    const config: TrayNotifyConfig = {
      preset: 'standard',
      groups: { ...PRESET_GROUPS.standard, 'needs-you': { approval: true, answer: false } },
      subagents: false,
      deferWhileChildrenRun: true,
      bodyLimit: 200,
    }
    assert.equal(
      intentFromQuestion(createPolicy(config), SESSION, { questions: [{ question: 'x' }] }),
      undefined,
    )
  })
})
