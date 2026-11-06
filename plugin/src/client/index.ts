/**
 * 客户端半：深链跳转与设置页。
 *
 * 受宿主约束：客户端产物必须是**单文件、无相对 require**（依赖只能经 `require("裸模块名")`
 * 从宿主模块表取）。因此本文件不 import 项目内其他模块，需要的东西由
 * `scripts/build-client.mjs` 注入或就地实现。
 *
 * 当前实现深链跳转；设置页分区在 T059/T060 补齐。
 * @module
 */

/** 宿主提供的客户端上下文（只声明用到的部分）。 */
export interface ClientContext {
  readonly remote: unknown
  /** 工作区导航；`openSession` 是深链的落点。 */
  readonly uiWorkspace?: {
    openSession(sessionId: string): void
  }
  /** 事件总线。 */
  readonly on?: (event: string, listener: (...args: unknown[]) => void) => () => void
}

/** 深链执行所需的浏览器环境（可注入，便于测试）。 */
export interface DeepLinkEnv {
  readonly search: string
  readonly pathname: string
  openSession(sessionId: string): void
  replaceState(state: unknown, title: string, url: string): void
}

/**
 * 从查询串里取出 `session`。
 *
 * 用 `URLSearchParams` 而不是手写正则：它会处理百分号解码与 `+`，手写版本在这两处
 * 都容易出错（会话 id 里出现过空格与 `&`）。
 * @param search - `location.search`（含前导 `?`）
 * @returns 会话 id；缺失或为空时 undefined
 */
export function parseSessionParam(search: string): string | undefined {
  const params = new URLSearchParams(search)
  const raw = params.get('session')
  if (raw === null) return undefined
  const trimmed = raw.trim()
  return trimmed === '' ? undefined : trimmed
}

/**
 * 去掉 `session` 参数，保留其它查询项。
 * @param search - 原查询串
 * @param pathname - 当前路径
 * @returns 新的相对 URL
 */
export function stripSessionParam(search: string, pathname: string): string {
  const params = new URLSearchParams(search)
  params.delete('session')
  const rest = params.toString()
  return rest === '' ? pathname : `${pathname}?${rest}`
}

/**
 * 执行一次深链跳转。
 *
 * 顺序：先 `openSession`，成功后才清参数。反过来会让「跳转失败但参数已清」变成
 * 刷新也无法重试的状态。
 * @param env - 浏览器环境
 * @returns 是否执行了跳转
 */
export function applyDeepLink(env: DeepLinkEnv): boolean {
  const sessionId = parseSessionParam(env.search)
  if (sessionId === undefined) return false
  try {
    env.openSession(sessionId)
  } catch {
    // 会话不存在（已被删除、或链接来自另一台机器）：静默留在首页。
    // 不清参数，刷新时会再试一次——用户可能刚打开了正确的 profile。
    return false
  }
  env.replaceState({}, '', stripSessionParam(env.search, env.pathname))
  return true
}

/**
 * 客户端插件装载点。
 * @param ctx - 客户端上下文
 */
export function apply(ctx: ClientContext): void {
  // 深链只在真实浏览器里执行；测试直接调 applyDeepLink。
  const globalLocation = (globalThis as { location?: { search: string; pathname: string } }).location
  const history = (globalThis as { history?: { replaceState(s: unknown, t: string, u: string): void } }).history
  const workspace = ctx.uiWorkspace
  if (globalLocation === undefined || history === undefined || workspace === undefined) return

  applyDeepLink({
    search: globalLocation.search,
    pathname: globalLocation.pathname,
    openSession: (sessionId) => workspace.openSession(sessionId),
    replaceState: (state, title, url) => history.replaceState(state, title, url),
  })
}
