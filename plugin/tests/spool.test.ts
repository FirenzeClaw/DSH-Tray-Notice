/**
 * spool 写入与日志脱敏的测试。
 *
 * 用 Node 内置 test runner（Node 24 可直接跑 `.ts`，无需预编译）。
 * 所有用例都在临时目录里跑，不碰真实的 `~/.dsh`。
 * @module
 */

import assert from 'node:assert/strict'
import { mkdtempSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, beforeEach, describe, it } from 'node:test'

import { createLogger, redact } from '../src/log.ts'
import {
  ARCHIVE_SUFFIX,
  MAX_FILE_BYTES,
  MAX_LINE_BYTES,
  createSpoolWriter,
  truncateBody,
} from '../src/spool.ts'
import type { NotificationEntry } from '../src/types.ts'

/** 造一条最小可用通知。 */
function makeEntry(overrides: Partial<NotificationEntry> = {}): NotificationEntry {
  return {
    v: 1,
    type: 'notification',
    id: 'id-1',
    ts: '2026-11-06T11:40:00.000Z',
    kind: 'done',
    sessionId: 'session-1',
    sessionTitle: '标题',
    title: '已完成',
    body: '正文',
    urgency: 'normal',
    openUrl: 'http://127.0.0.1:3080/?session=session-1',
    dedupeKey: 'done:session-1:1',
    ...overrides,
  }
}

describe('spool 写入', () => {
  let dir = ''
  let logPath = ''

  beforeEach(() => {
    dir = mkdtempSync(join(tmpdir(), 'tray-notify-spool-'))
    logPath = join(dir, 'plugin.log')
  })

  afterEach(() => {
    rmSync(dir, { recursive: true, force: true })
  })

  it('追加单行 JSON 并带换行', () => {
    const spoolPath = join(dir, 'events.jsonl')
    const writer = createSpoolWriter(spoolPath, createLogger(logPath, 'test'))
    writer.append(makeEntry())
    writer.append(makeEntry({ id: 'id-2' }))

    const lines = readFileSync(spoolPath, 'utf8').trimEnd().split('\n')
    assert.equal(lines.length, 2)
    assert.equal(JSON.parse(lines[0] ?? '{}').id, 'id-1')
    assert.equal(JSON.parse(lines[1] ?? '{}').id, 'id-2')
  })

  it('文件超过 1 MiB 时轮转成 .1 并重开', () => {
    const spoolPath = join(dir, 'events.jsonl')
    const writer = createSpoolWriter(spoolPath, createLogger(logPath, 'test'))
    writeFileSync(spoolPath, 'x'.repeat(MAX_FILE_BYTES + 1), 'utf8')

    writer.append(makeEntry())

    const archive = `${spoolPath}${ARCHIVE_SUFFIX}`
    assert.equal(statSync(archive).size, MAX_FILE_BYTES + 1)
    assert.equal(readFileSync(spoolPath, 'utf8').trimEnd().split('\n').length, 1)
  })

  it('写失败只记日志、不抛出', () => {
    // 让父路径是个普通文件，mkdir 必然失败。
    const blocker = join(dir, 'blocker')
    writeFileSync(blocker, 'x', 'utf8')
    const writer = createSpoolWriter(join(blocker, 'events.jsonl'), createLogger(logPath, 'test'))

    assert.doesNotThrow(() => writer.append(makeEntry()))
    assert.match(readFileSync(logPath, 'utf8'), /spool 写入失败/)
  })
})

describe('超长行截断', () => {
  it('截断 body 而保留整行合法 JSON', () => {
    const huge = makeEntry({ body: 'x'.repeat(MAX_LINE_BYTES) })
    const truncated = truncateBody(huge)

    const line = JSON.stringify(truncated)
    assert.ok(Buffer.byteLength(`${line}\n`, 'utf8') <= MAX_LINE_BYTES)
    assert.equal(JSON.parse(line).id, 'id-1')
    assert.ok((JSON.parse(line).body as string).endsWith('…'))
  })

  it('未超限时原样返回', () => {
    const entry = makeEntry()
    assert.deepEqual(truncateBody(entry), entry)
  })

  it('会话快照行不受 body 截断影响', () => {
    const state = {
      v: 1 as const,
      type: 'session-state' as const,
      ts: '2026-11-06T11:40:05.000Z',
      sessions: [],
    }
    assert.deepEqual(truncateBody(state), state)
  })
})

describe('日志脱敏', () => {
  it('把 token= 的值替换成 ***', () => {
    assert.equal(redact('打开 http://127.0.0.1:3080/?token=abc&session=x'), '打开 http://127.0.0.1:3080/?token=***&session=x')
  })

  it('处理 JSON 形态的键值', () => {
    assert.equal(redact('{"token":"abc"}'), '{"token":"***"}')
    assert.equal(redact('apiKey: sk-123'), 'apiKey: ***')
  })

  it('不误伤普通单词', () => {
    assert.equal(redact('token 已过期'), 'token 已过期')
  })
})
