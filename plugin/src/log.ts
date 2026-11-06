/**
 * 插件侧日志：写文件、失败静默、令牌脱敏。
 *
 * 三条约束都来自事故而不是洁癖：
 * 1. **写日志失败必须静默**——日志是诊断手段，不是业务路径。磁盘满时让插件崩掉，
 *    等于用诊断工具制造故障。
 * 2. **令牌脱敏**——`openUrl` 与 `dsh web` 的访问令牌都会经过这里；AGENTS.md 安全
 *    红线要求令牌不得进日志。
 * 3. **1 MiB 轮转**——插件长期驻留，日志不轮转会吃满 home 分区。
 *
 * 与托盘侧 `dsh_tray/notify/log.py` 共用行格式 `<iso> <level> <component> <msg>`，
 * 便于两侧日志直接 `cat` 在一起看。
 * @module
 */

import { appendFileSync, existsSync, mkdirSync, renameSync, statSync } from 'node:fs'
import { dirname } from 'node:path'

/** 单个日志文件的上限；超过就改名成 `.1` 并重开。 */
export const LOG_MAX_BYTES = 1024 * 1024

/** 日志级别。 */
export type LogLevel = 'debug' | 'info' | 'warn' | 'error'

/**
 * 把 `token=…` 之类的值替换成 `***`。
 *
 * 只处理「键=值」与「键: 值」两种形态：URL 查询串是前者，JSON 片段是后者。
 * 不追求覆盖所有编码形式——覆盖到真实出现过的形态即可，过度正则反而会误伤
 * 正文里的普通单词。
 * @param text - 原始文本
 * @returns 脱敏后的文本
 */
export function redact(text: string): string {
  return (
    text
      // URL 查询串：?token=abc&session=x —— 值到 & 或空白为止
      .replace(/(\b(?:token|apiKey|api_key|password|secret)=)(?!\*\*\*)[^&\s"'#]+/gi, '$1***')
      // JSON / 赋值形态："token":"abc"、token: abc、apiKey: sk-123
      .replace(
        /("?(?:token|apiKey|api_key|password|secret)"?\s*[:=]\s*)("?)(?!\*\*\*)([^\s,"'}]+)/gi,
        '$1$2***',
      )
  )
}

/**
 * 按大小轮转日志文件。
 *
 * 只保留一代（`.1`）：日志的用途是「最近发生了什么」，两代已经足够覆盖一次重启。
 * @param path - 日志文件路径
 */
function rotateIfNeeded(path: string): void {
  if (!existsSync(path)) return
  try {
    if (statSync(path).size <= LOG_MAX_BYTES) return
  } catch {
    return
  }
  try {
    renameSync(path, `${path}.1`)
  } catch {
    // 轮转失败不该阻断写入：继续往原文件追加，最多是文件更大一点。
  }
}

/** 一个组件的日志器。 */
export interface Logger {
  debug(message: string): void
  info(message: string): void
  warn(message: string): void
  error(message: string): void
}

/**
 * 创建日志器。
 * @param path - 日志文件绝对路径；为 undefined 时只写内存（测试用）
 * @param component - 组件名，出现在每行第三列
 * @returns 日志器
 */
export function createLogger(path: string | undefined, component: string): Logger {
  const write = (level: LogLevel, message: string): void => {
    const line = `${new Date().toISOString()} ${level} ${component} ${redact(message)}\n`
    if (path === undefined) return
    try {
      mkdirSync(dirname(path), { recursive: true })
      rotateIfNeeded(path)
      appendFileSync(path, line, 'utf8')
    } catch {
      // 刻意静默：见模块头注释第 1 条。
    }
  }
  return {
    debug: (message) => write('debug', message),
    info: (message) => write('info', message),
    warn: (message) => write('warn', message),
    error: (message) => write('error', message),
  }
}
