/**
 * 插件侧 spool 写入：追加 NDJSON，轮转，超长截断。
 *
 * 为什么用文件而不是 socket/IPC：托盘可能比 DSH 晚启动、早退出、被用户杀掉重启。
 * 文件 spool 让「写入方」与「投递方」完全解耦——插件写完就走，托盘下次启动照样
 * 能补投（FR-034）。代价是要处理轮转与半行，见下。
 *
 * 三条不变量（contracts C1）：
 * 1. 单写者：只有插件追加，托盘只读。
 * 2. 单行 ≤ 64 KiB：超长时**截断 body 字段**而不是丢弃整行——丢整行等于丢事件。
 * 3. 写失败静默：spool 是旁路，不能因为它让 agent loop 失败。
 * @module
 */

import { appendFileSync, existsSync, mkdirSync, renameSync, statSync } from 'node:fs'
import { dirname, join } from 'node:path'

import type { Logger } from './log.ts'
import type { SpoolRow } from './types.ts'

/** 单行上限（字节）。超过就截断 body。 */
export const MAX_LINE_BYTES = 64 * 1024

/** 轮转阈值；超过就把当前文件改名成 `.1`。 */
export const MAX_FILE_BYTES = 1024 * 1024

/** 轮转保留的代数（`.1` 一代）。 */
export const ARCHIVE_SUFFIX = '.1'

/**
 * 构造一条 spool 行的字节长度（UTF-8）。
 * @param row - 待测量行
 * @returns 字节数
 */
function lineBytes(row: SpoolRow): number {
  return Buffer.byteLength(`${JSON.stringify(row)}\n`, 'utf8')
}

/**
 * 把超长的 body 截断到整行不超过上限。
 *
 * 二分而不是「减去超出量」：`JSON.stringify` 会给引号、换行、非 ASCII 字符做转义，
 * 字符数与字节数不成比例，按字符差估算会来回偏。二分最多 log2(body.length) 次序列化，
 * 在 64 KiB 量级上不过十几次，足够便宜。
 * @param row - 原行
 * @param limit - 整行字节上限
 * @returns 截断后的行；body 已经为空仍超限时原样返回（由调用方丢弃）
 */
export function truncateBody(row: SpoolRow, limit: number = MAX_LINE_BYTES): SpoolRow {
  if (row.type !== 'notification') return row
  if (lineBytes(row) <= limit) return row

  const original = row.body
  let low = 0
  let high = original.length
  let best = ''
  while (low <= high) {
    const middle = Math.floor((low + high) / 2)
    const candidate = `${original.slice(0, middle)}…`
    if (lineBytes({ ...row, body: candidate }) <= limit) {
      best = candidate
      low = middle + 1
    } else {
      high = middle - 1
    }
  }
  return { ...row, body: best }
}

/** spool 写入器。 */
export interface SpoolWriter {
  /** spool 文件绝对路径（测试与诊断用）。 */
  readonly path: string
  /**
   * 追加一行。
   * @param row - 契约行
   */
  append(row: SpoolRow): void
}

/**
 * 创建 spool 写入器。
 * @param filePath - `events.jsonl` 的绝对路径
 * @param logger - 日志器；写失败只记一条
 * @returns 写入器
 */
export function createSpoolWriter(filePath: string, logger: Logger): SpoolWriter {
  const append = (row: SpoolRow): void => {
    try {
      mkdirSync(dirname(filePath), { recursive: true })
      // 轮转检查放在写前：写完再查会让单次写入可能超出上限一倍。
      if (existsSync(filePath) && statSync(filePath).size > MAX_FILE_BYTES) {
        try {
          renameSync(filePath, join(dirname(filePath), `${filePath.split('/').pop()}${ARCHIVE_SUFFIX}`))
        } catch {
          // 改名失败（权限、占用）不阻断：继续追加，托盘侧会读到更长的文件。
        }
      }
      const line = `${JSON.stringify(truncateBody(row))}\n`
      appendFileSync(filePath, line, 'utf8')
    } catch (error) {
      logger.warn(`spool 写入失败（${filePath}）：${error instanceof Error ? error.message : String(error)}`)
    }
  }
  return { path: filePath, append }
}
