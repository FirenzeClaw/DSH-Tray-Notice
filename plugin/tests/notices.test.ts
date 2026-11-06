/**
 * notice 识别的测试。
 *
 * 识别只依赖 `kind` 与 `form` 两个字段：文案随版本改，匹配文案会把两个插件的
 * 字符串耦死。这里用不同文案验证同一条 notice 仍被识别。
 * @module
 */

import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import { DEFAULT_NOTICE_SOURCES, matchNotice, noticeSourceSet } from '../src/notices.ts'

describe('notice 识别', () => {
  it('target-monitor 的 notice 被识别', () => {
    const summary = matchNotice({ kind: 'target-monitor', form: 'notice', summary: '你可能卡住了' })
    assert.equal(summary, '你可能卡住了')
  })

  it('文案任意变化仍识别', () => {
    const first = matchNotice({ kind: 'target-monitor', form: 'notice', summary: 'A' })
    const second = matchNotice({ kind: 'target-monitor', form: 'notice', summary: '完全不同的文案' })
    assert.equal(first, 'A')
    assert.equal(second, '完全不同的文案')
  })

  it('未知 kind 不识别（白名单）', () => {
    assert.equal(matchNotice({ kind: 'some-other-plugin', form: 'notice', summary: 'x' }), undefined)
  })

  it('form 不是 notice 不识别', () => {
    assert.equal(matchNotice({ kind: 'target-monitor', form: 'snapshot', summary: 'x' }), undefined)
    assert.equal(matchNotice({ kind: 'target-monitor', summary: 'x' }), undefined)
  })

  it('source 缺失或非对象不识别', () => {
    assert.equal(matchNotice(undefined), undefined)
    assert.equal(matchNotice(null), undefined)
    assert.equal(matchNotice('notice'), undefined)
  })

  it('summary 缺失时给兜底文案', () => {
    assert.equal(matchNotice({ kind: 'target-monitor', form: 'notice' }), '会话里有一条提示')
    assert.equal(matchNotice({ kind: 'target-monitor', form: 'notice', summary: '  ' }), '会话里有一条提示')
  })

  it('可自定义白名单', () => {
    const allowed = noticeSourceSet(['another-plugin'])
    assert.equal(matchNotice({ kind: 'target-monitor', form: 'notice', summary: 'x' }, allowed), undefined)
    assert.equal(matchNotice({ kind: 'another-plugin', form: 'notice', summary: 'y' }, allowed), 'y')
  })

  it('空配置退回默认白名单', () => {
    assert.deepEqual([...noticeSourceSet(undefined)], [...DEFAULT_NOTICE_SOURCES])
    assert.deepEqual([...noticeSourceSet([])], [...DEFAULT_NOTICE_SOURCES])
  })
})
