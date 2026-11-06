/**
 * 客户端深链解析的测试。
 *
 * 客户端受「单文件、无相对 require」约束，所以解析逻辑必须能脱离宿主独立测试：
 * 这里用假的 `uiWorkspace` 与假 `location` 驱动，不引入 jsdom。
 * @module
 */

import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import { parseSessionParam, applyDeepLink } from '../src/client/index.ts'

describe('查询串解析', () => {
  it('取出 session', () => {
    assert.equal(parseSessionParam('?session=abc'), 'abc')
  })

  it('多个参数时只取 session', () => {
    assert.equal(parseSessionParam('?token=t&session=abc'), 'abc')
  })

  it('无参数返回 undefined', () => {
    assert.equal(parseSessionParam(''), undefined)
    assert.equal(parseSessionParam('?foo=1'), undefined)
  })

  it('空值返回 undefined', () => {
    assert.equal(parseSessionParam('?session='), undefined)
    assert.equal(parseSessionParam('?session=%20'), undefined)
  })

  it('做百分号解码', () => {
    assert.equal(parseSessionParam('?session=a%20b'), 'a b')
  })
})

describe('深链应用', () => {
  it('调用 openSession 一次并清掉参数', () => {
    const opened: string[] = []
    const replaced: string[] = []
    const applied = applyDeepLink({
      search: '?session=abc',
      pathname: '/',
      openSession: (id) => {
        opened.push(id)
      },
      replaceState: (_state, _title, url) => {
        replaced.push(url)
      },
    })

    assert.equal(applied, true)
    assert.deepEqual(opened, ['abc'])
    assert.equal(replaced.length, 1)
    assert.ok(!String(replaced[0]).includes('session='))
  })

  it('无 session 参数时不动作', () => {
    const opened: string[] = []
    const applied = applyDeepLink({
      search: '?foo=1',
      pathname: '/',
      openSession: (id) => {
        opened.push(id)
      },
      replaceState: () => {},
    })
    assert.equal(applied, false)
    assert.deepEqual(opened, [])
  })

  it('openSession 抛错时不外抛', () => {
    assert.doesNotThrow(() =>
      applyDeepLink({
        search: '?session=missing',
        pathname: '/',
        openSession: () => {
          throw new Error('session not found')
        },
        replaceState: () => {},
      }),
    )
  })

  it('openSession 抛错时不清理参数（便于刷新重试）', () => {
    let replaced = 0
    applyDeepLink({
      search: '?session=missing',
      pathname: '/',
      openSession: () => {
        throw new Error('nope')
      },
      replaceState: () => {
        replaced += 1
      },
    })
    assert.equal(replaced, 0)
  })

  it('清参数保留其它查询项', () => {
    const replaced: string[] = []
    applyDeepLink({
      search: '?token=t&session=abc&x=1',
      pathname: '/chat',
      openSession: () => {},
      replaceState: (_state, _title, url) => {
        replaced.push(url)
      },
    })
    assert.equal(replaced[0], '/chat?token=t&x=1')
  })
})
