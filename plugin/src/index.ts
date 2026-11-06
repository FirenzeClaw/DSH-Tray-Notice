/**
 * 插件入口骨架。
 *
 * 真正的接线在 T023 完成：订阅 session 事件、按策略生成意图、写入 spool。
 * 此刻只保留可编译的最小形状，让 `npm run typecheck` 能在骨架阶段通过。
 * @module
 */
import type { Context } from '@deepseek-ai/cordis'

export const name = 'dsh-tray-notify'

/** 依赖的宿主服务；缺失时 cordis 拒绝启动（fail loud）。 */
export const inject = [] as const

/**
 * 插件装载点。
 * @param _ctx - cordis 上下文
 */
export function apply(_ctx: Context): void {
  // T023 接入事件订阅
}
