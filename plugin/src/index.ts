/**
 * 插件入口：把宿主事件接到 spool。
 *
 * 三条硬约束（AGENTS.md 硬约束 5 + contracts C2）：
 * 1. **observe-only**：任何监听器抛错都只记日志，绝不影响 agent loop。这里是旁路，
 *    不是业务路径。
 * 2. **`user-questions/request` 必须先写后 `next()`**：Web 端在 `next()` 之后才会
 *    拿到请求并弹出卡片；如果先 `next()` 再写，用户可能已经答完，而通知才刚落地。
 * 3. **令牌不进插件**：`openUrl` 只写 `?session=`，令牌由托盘注入。
 *
 * 父子关系用 `session.header.parentSession` 判定，而不是查 agent 注册表：header 是
 * durable 数据，注册表只有 `id`，反查子会话要么枚举全部 agent（O(n) 且拿不到
 * Session），要么维护第二份账本。这里在事件流里顺带记账，代价是一次 Map 写入。
 * @module
 */

import { randomUUID } from 'node:crypto'
import { join } from 'node:path'

import type { Context } from '@deepseek-ai/cordis'
import type { Session, SessionEvent } from '@deepseek-ai/dsh-session'
// 激活 dsh-user-approval 对 SessionEventMap 的模块增强：没有这行，
// `approval/asked` 不在 SessionEventType 联合里，switch 分支会被判为不可达。
import type {} from '@deepseek-ai/dsh-user-approval'
import { dshHomePath } from '@deepseek-ai/dsh-home-paths'

import { createLogger } from './log.ts'
import { createSpoolWriter, type SpoolWriter } from './spool.ts'
import { bindSettings, type Policy, type SettingsReader } from './settings.ts'
import { createSessionTracker } from './sessionstate.ts'
import { createDeferrer } from './defer.ts'
import {
  intentFromApproval,
  intentFromGoal,
  intentFromJob,
  intentFromQuestion,
  intentFromTurnEnd,
  toEntry,
  type NotificationIntent,
  type QuestionPayload,
  type SessionView,
} from './events.ts'
import type { TurnEndReasonKind } from './kinds.ts'

/** 插件名；也是设置命名空间与 bundle patch 里的 id。 */
export const name = 'dsh-tray-notify'

/**
 * 不声明 `inject`：设置服务缺失时插件应当降级到默认策略继续工作，而不是让整个
 * 插件装载失败（用户装了通知插件却什么都收不到，比「用了默认档位」糟得多）。
 */
export const inject = [] as const

/** spool 相对 DSH home 的位置。 */
export const SPOOL_RELATIVE = join('run', 'tray-notify', 'events.jsonl')

/** 插件运行所需的最小宿主能力；测试用假对象即可满足。 */
export interface PluginHost {
  readonly settings?: SettingsReader
  readonly sessionTitle?: { get(session: Session): { readonly title: string } | undefined }
  /** 订阅宿主事件；`prepend` 用于「先写后 next」。 */
  on(event: string, listener: (...args: never[]) => unknown, options?: { prepend?: boolean }): () => boolean
}

/** 一个可释放的接线句柄。 */
export interface Wiring {
  /** 当前策略。 */
  policy(): Policy
  /** 会话跟踪器（测试与诊断用）。 */
  tracker(): ReturnType<typeof createSessionTracker>
  /** 挂起表（测试与诊断用）。 */
  deferrer(): ReturnType<typeof createDeferrer>
  /** 释放全部订阅。 */
  dispose(): void
}

/**
 * 把会话对象投影成通知需要的形状。
 *
 * 标题取标题服务的最新快照；服务不可用或还没有标题时退回 cwd 末段，再退回会话 id。
 * 这三种退化都真实发生过：刚创建的会话没有标题、无 cwd 的会话没有目录名。
 * @param session - 宿主会话
 * @param titleService - 标题服务
 * @returns 会话投影
 */
export function sessionView(
  session: Pick<Session, 'id' | 'header'>,
  titleService: PluginHost['sessionTitle'],
): SessionView {
  const cwd = session.header.cwd
  const fromService = titleService?.get(session as Session)?.title
  const fallback = cwd === undefined ? undefined : cwd.replace(/[/\\]+$/, '').split(/[/\\]/).pop()
  return {
    id: String(session.id),
    title: fromService ?? (fallback === undefined || fallback === '' ? String(session.id) : fallback),
    ...(cwd === undefined ? {} : { cwd }),
    ...(session.header.origin === 'subagent' ? { origin: 'subagent' as const } : {}),
  }
}

/**
 * 接线：订阅事件、写 spool。
 * @param host - 宿主能力
 * @param logger - 日志器
 * @param spool - spool 写入器
 * @param now - 取当前时刻
 * @returns 接线句柄
 */
export function wire(
  host: PluginHost,
  logger: ReturnType<typeof createLogger>,
  spool: SpoolWriter,
  now: () => Date = () => new Date(),
): Wiring {
  const settingsBinding = bindSettings(
    host as unknown as Pick<Context, 'on'>,
    host.settings,
    logger,
    () => emitTestNotification(),
  )
  const tracker = createSessionTracker((state) => spool.append(state), () => now().getTime())
  const deferrer = createDeferrer(() => now().getTime(), (message) => logger.info(message))
  const disposers: (() => boolean)[] = []

  /** 见过的会话对象；用于按 id 取标题与 cwd。 */
  const seen = new Map<string, Session>()
  /** 父会话 id → 仍在跑的根子会话 id 集合。 */
  const liveChildren = new Map<string, Set<string>>()

  /**
   * 写一条测试通知。
   *
   * 绕过组开关（`policy.wants('test')` 恒为 true），也不进未读统计——它的用途是
   * 让用户确认「链路通不通」，不是一条真事件。
   */
  const emitTestNotification = (): void => {
    const session = [...seen.values()][0]
    const view = session === undefined ? { id: 'test', title: '测试通知' } : sessionView(session, host.sessionTitle)
    emit({
      kind: 'test',
      sessionId: view.id,
      sessionTitle: view.title,
      title: '测试通知',
      body: '看到这条说明通知链路是通的',
      urgency: 'normal',
      openUrl: '',
      dedupeKey: `test:${Date.now()}`,
    })
  }

  /** 统一的「写一条通知」路径：补 id 与时间戳。 */
  const emit = (intent: NotificationIntent | undefined): void => {
    if (intent === undefined) return
    spool.append(toEntry(intent, randomUUID(), now()))
    logger.debug(`写入通知 ${intent.kind} ${intent.sessionId}`)
  }

  /**
   * 包一层 try/catch：监听器失败只记日志。
   *
   * 必须用普通函数而不是箭头函数：cordis 把 scoped context 作为 `this` 传给监听器
   * （`user-questions/request` 靠它拿 agent），箭头函数会丢掉这层绑定。
   */
  const guard = <A extends unknown[]>(label: string, handler: (...args: A) => unknown): ((...args: A) => void) => {
    return function (this: unknown, ...args: A): void {
      try {
        void handler.apply(this, args)
      } catch (error) {
        logger.error(`${label} 处理失败：${error instanceof Error ? (error.stack ?? error.message) : String(error)}`)
      }
    }
  }

  /** 取会话投影；未见过的会话退化为「只有 id」。 */
  const viewOf = (sessionId: string): SessionView => {
    const session = seen.get(sessionId)
    if (session === undefined) return { id: sessionId, title: sessionId }
    return sessionView(session, host.sessionTitle)
  }

  /** 记一次子会话出现。 */
  const markChild = (parentId: string | undefined, childId: string): void => {
    if (parentId === undefined) return
    const set = liveChildren.get(parentId) ?? new Set<string>()
    set.add(childId)
    liveChildren.set(parentId, set)
  }

  /** 记一次子会话结束。 */
  const unmarkChild = (parentId: string | undefined, childId: string): void => {
    if (parentId === undefined) return
    liveChildren.get(parentId)?.delete(childId)
  }

  /** 取父会话 id（来自 durable header）。 */
  const parentOf = (session: Session): string | undefined => {
    const parent = session.header.parentSession
    return parent === undefined ? undefined : String(parent)
  }

  /**
   * 处理轮次结束：可能立即通知，也可能挂起等子会话。
   * @param session - 宿主会话
   * @param turn - 轮次号
   * @param reason - 结束原因
   * @param policy - 当前策略
   */
  const handleTurnEnd = (session: Session, turn: number, reason: TurnEndReasonKind, policy: Policy): void => {
    const parentId = parentOf(session)
    const children = [...(liveChildren.get(String(session.id)) ?? [])]
    const isRoot = session.header.origin !== 'subagent'
    if (policy.deferWhileChildrenRun && isRoot && reason === 'completed' && children.length > 0) {
      deferrer.register(String(session.id), children)
      logger.debug(`挂起完成通知：${session.id} 等 ${children.length} 个子会话`)
    } else {
      emit(intentFromTurnEnd(policy, viewOf(String(session.id)), { turn, reason }))
    }

    if (parentId !== undefined) {
      unmarkChild(parentId, String(session.id))
      deferrer.childFinished(parentId, String(session.id))
      const outcome = deferrer.resolve(parentId)
      if (outcome !== undefined) {
        emit(intentFromTurnEnd(policy, viewOf(parentId), { turn: lastTurnOf(parentId), reason: 'completed' }))
      }
    }
  }

  /** 取会话当前轮次号（用于挂起产出时的去重键）。 */
  const lastTurnOf = (sessionId: string): number => {
    const row = tracker.current().sessions.find((entry) => entry.id === sessionId)
    return row?.turn ?? 0
  }

  // ── 会话事件（含 turn/*、tool/*、approval/*） ─────────────────────────────
  disposers.push(
    host.on(
      'session/event',
      guard('session/event', (session: Session, event: SessionEvent) => {
        const sessionId = String(session.id)
        seen.set(sessionId, session)
        if (session.header.origin === 'subagent' && event.type === 'turn/start') {
          markChild(parentOf(session), sessionId)
        }

        const policy = settingsBinding.current()
        switch (event.type) {
          case 'turn/start': {
            tracker.turnStart(sessionView(session, host.sessionTitle), event.data.turn)
            deferrer.cancel(sessionId)
            break
          }
          case 'turn/end': {
            tracker.turnEnd(sessionView(session, host.sessionTitle), event.data.turn)
            // 宿主的 reason 是 { kind } 对象联合（TurnEndReasonMap），取 kind 才是字符串。
            handleTurnEnd(session, event.data.turn, event.data.reason.kind, policy)
            break
          }
          case 'tool/call': {
            tracker.toolCall(sessionView(session, host.sessionTitle), event.data.name, event.data.arguments)
            break
          }
          case 'approval/asked': {
            tracker.waitingUser(sessionView(session, host.sessionTitle), lastTurnOf(sessionId))
            emit(
              intentFromApproval(policy, viewOf(sessionId), {
                id: String(event.data.id),
                toolName: event.data.toolName,
                ...(event.data.reason === undefined ? {} : { reason: event.data.reason }),
              }),
            )
            break
          }
          default:
            break
        }
      }),
    ),
  )

  // ── 提问：必须先写后 next ──────────────────────────────────────────────────
  disposers.push(
    host.on(
      'user-questions/request',
      guard(
        'user-questions/request',
        function (this: { agent?: { id: string } }, request: QuestionPayload, next: () => Promise<unknown>) {
          const policy = settingsBinding.current()
          const sessionId = this?.agent?.id
          if (sessionId !== undefined) {
            tracker.waitingUser(viewOf(sessionId), lastTurnOf(sessionId))
            emit(intentFromQuestion(policy, viewOf(sessionId), request))
          }
          // 顺序是契约的一部分：写盘完成之后才把请求交给下游，否则 Web 端可能先弹卡片。
          return next()
        },
      ),
      { prepend: true },
    ),
  )

  // ── 后台作业与目标 ────────────────────────────────────────────────────────
  disposers.push(
    host.on(
      'job/settled',
      guard(
        'job/settled',
        (payload: {
          jobId: string
          label: string
          owner: string
          status: 'completed' | 'killed' | 'failed'
          detail?: string
        }) => {
          emit(
            intentFromJob(settingsBinding.current(), viewOf(String(payload.owner)), {
              jobId: String(payload.jobId),
              label: payload.label,
              status: payload.status,
              ...(payload.detail === undefined ? {} : { detail: payload.detail }),
            }),
          )
        },
      ),
    ),
  )

  disposers.push(
    host.on(
      'goal/changed',
      guard(
        'goal/changed',
        (payload: { agent: { id: string }; change: { operation: string; goal?: { objective?: string } } }) => {
          emit(
            intentFromGoal(settingsBinding.current(), viewOf(String(payload.agent.id)), payload.change),
          )
        },
      ),
    ),
  )

  return {
    policy: () => settingsBinding.current(),
    tracker: () => tracker,
    deferrer: () => deferrer,
    dispose: () => {
      for (const off of disposers) off()
      settingsBinding.dispose()
    },
  }
}

/**
 * cordis 插件装载点。
 * @param ctx - 宿主上下文
 */
export function apply(ctx: Context): void {
  const logPath = process.env['DSH_TRAY_NOTIFY_LOG'] ?? dshHomePath('run', 'tray-notify', 'plugin.log')
  const logger = createLogger(logPath, 'plugin')
  const spoolPath = dshHomePath(SPOOL_RELATIVE)
  const spool = createSpoolWriter(spoolPath, logger)

  // 设置服务是可选能力：没有它就用默认策略，而不是让插件装载失败。
  const settings = (ctx as unknown as { settings?: SettingsReader }).settings
  const wiring = wire({ on: ctx.on.bind(ctx), settings, ...(ctx as unknown as { sessionTitle?: PluginHost['sessionTitle'] }) }, logger, spool)

  ctx.effect(() => () => wiring.dispose(), 'tray-notify wiring')
  logger.info(`已装载，spool=${spoolPath}`)
}
