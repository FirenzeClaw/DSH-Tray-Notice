/**
 * 事件 → 通知意图。
 *
 * 这一层只做**纯决策**：给一个事件与当前策略，回答「要不要通知、文案是什么」。
 * 订阅、去重、写 spool 都在 `index.ts`。分开的理由是它必须能被穷举测试——通知
 * 文案与分类是用户唯一看得见的东西，靠「跑一遍试试」验证不够。
 *
 * 文案原则：标题说「发生了什么」，正文说「在哪、关于什么」。不写「点击查看」这类
 * 无信息量的话——按钮本身就是入口。
 * @module
 */

import type { NotificationKind, NotificationEntry, Urgency } from './types.ts'
import type { Policy } from './settings.ts'
import { NOTIFIABLE_REASONS, REASON_TO_KIND, type TurnEndReasonKind } from './kinds.ts'

/** 会话的展示投影；由调用方从 `Session` 与标题服务拼出。 */
export interface SessionView {
  /** 会话标识。 */
  readonly id: string
  /** 会话标题（标题服务不可用时退化为 cwd 短名）。 */
  readonly title: string
  /** 工作目录，用于生成 `workspace` 短名。 */
  readonly cwd?: string
  /** `subagent` 表示子会话；缺省视作根会话。 */
  readonly origin?: 'subagent'
}

/** 一条待写入 spool 的意图；`id` 与 `ts` 由调用方在写入前补齐。 */
export interface NotificationIntent {
  readonly kind: NotificationKind
  readonly sessionId: string
  readonly sessionTitle: string
  readonly workspace?: string
  readonly title: string
  readonly body: string
  readonly urgency: Urgency
  readonly openUrl: string
  readonly dedupeKey: string
}

/** 托盘地址；与既有 `DEFAULT_PORT` 一致。 */
export const TRAY_URL = 'http://127.0.0.1:3080'

/**
 * 生成会话定位链接。
 *
 * **不带令牌**：令牌只在托盘一侧（contracts C2 / AGENTS.md 安全红线）。托盘投递
 * 前会按 owned/adopted 补上 `&token=…`。
 * @param sessionId - 会话标识
 * @returns 裸链接
 */
export function openUrlFor(sessionId: string): string {
  return `${TRAY_URL}/?session=${encodeURIComponent(sessionId)}`
}

/**
 * 取工作目录短名。
 * @param cwd - 绝对路径
 * @returns 末段目录名；无 cwd 时 undefined
 */
export function workspaceOf(cwd: string | undefined): string | undefined {
  if (cwd === undefined) return undefined
  const trimmed = cwd.replace(/[/\\]+$/, '')
  const segment = trimmed.split(/[/\\]/).pop()
  return segment === undefined || segment === '' ? undefined : segment
}

/**
 * 按 `bodyLimit` 截断正文。
 *
 * 用 `…` 而不是 `...`：面板与通知都用比例字体，三点占的宽度比一个省略号多，
 * 而截断后多留一个字符更有用。
 * @param body - 原始正文
 * @param limit - 上限（字符数）
 * @returns 截断后的正文
 */
export function clip(body: string, limit: number): string {
  if (limit <= 0) return '…'
  if (body.length <= limit) return body
  return `${body.slice(0, Math.max(0, limit - 1))}…`
}

/** 各类结束原因的标题与正文模板。 */
const TURN_END_COPY: Readonly<Record<TurnEndReasonKind, { title: string; body: (session: SessionView) => string }>> = {
  completed: { title: '已完成', body: (session) => `${session.title} 的这一轮跑完了` },
  error: { title: '出错了', body: (session) => `${session.title} 的轮次以错误结束，回到会话查看原因` },
  blocked: { title: '被阻塞', body: (session) => `${session.title} 停在阻塞状态，需要你处理` },
  'max-tokens': { title: '达到上限', body: (session) => `${session.title} 用满了 token 上限` },
  aborted: { title: '已取消', body: (session) => `${session.title} 的这一轮被取消` },
  interrupted: { title: '已中断', body: (session) => `${session.title} 的这一轮被中断` },
  forked: { title: '已取消', body: (session) => `${session.title} 的这一轮被分叉取代` },
}

/**
 * 由 `turn/end` 生成意图。
 *
 * @param policy - 当前策略
 * @param session - 会话投影
 * @param data - `turn/end` 载荷
 * @returns 意图；不该通知时 undefined
 */
export function intentFromTurnEnd(
  policy: Policy,
  session: SessionView,
  data: { readonly turn: number; readonly reason: TurnEndReasonKind },
): NotificationIntent | undefined {
  const isSubagent = session.origin === 'subagent'
  if (isSubagent && !policy.subagents) return undefined

  const kind = REASON_TO_KIND[data.reason]
  if (!policy.wants(kind)) return undefined
  // 非子会话时，取消/中断这类「默认不打扰」的原因只在 other 组开启后才走到这里；
  // NOTIFIABLE_REASONS 只是语义标注，真正的门是 policy.wants。
  void NOTIFIABLE_REASONS

  const copy = TURN_END_COPY[data.reason]
  return {
    kind: isSubagent ? 'subagent' : kind,
    sessionId: session.id,
    sessionTitle: session.title,
    workspace: workspaceOf(session.cwd),
    title: isSubagent ? `子会话${copy.title}` : copy.title,
    body: clip(copy.body(session), policy.bodyLimit),
    urgency: 'normal',
    openUrl: openUrlFor(session.id),
    dedupeKey: `${isSubagent ? 'subagent' : kind}:${session.id}:${data.turn}`,
  }
}

/**
 * 由 `approval/asked` 生成意图。
 *
 * @param policy - 当前策略
 * @param session - 会话投影
 * @param data - 审批载荷
 * @returns 意图；不该通知时 undefined
 */
export function intentFromApproval(
  policy: Policy,
  session: SessionView,
  data: { readonly id: string; readonly toolName: string; readonly reason?: string },
): NotificationIntent | undefined {
  if (!policy.wants('needs-approval')) return undefined
  const detail = data.reason === undefined || data.reason === '' ? data.toolName : `${data.toolName} · ${data.reason}`
  return {
    kind: 'needs-approval',
    sessionId: session.id,
    sessionTitle: session.title,
    workspace: workspaceOf(session.cwd),
    title: '需要你审批',
    body: clip(detail, policy.bodyLimit),
    urgency: 'critical',
    openUrl: openUrlFor(session.id),
    dedupeKey: `approval:${data.id}`,
  }
}

/** 提问载荷的最小形状：只用到问题文本与 callId。 */
export interface QuestionPayload {
  readonly questions: readonly { readonly question: string; readonly options?: readonly { readonly label: string }[] }[]
  readonly wait?: { readonly callId: string }
}

/**
 * 由 `user-questions/request` 生成意图。
 *
 * 去重键优先用 `callId`——它是宿主侧唯一稳定的请求标识（`AskUserQuestionRequestEvent`
 * 没有 requestId 字段）。没有 callId 时用问题文本拼一个稳定键：同一问题重复弹出时
 * 用户看到的本来就是同一件事，10 秒内合并掉是对的。
 * @param policy - 当前策略
 * @param session - 会话投影
 * @param payload - 提问载荷
 * @returns 意图；不该通知时 undefined
 */
export function intentFromQuestion(
  policy: Policy,
  session: SessionView,
  payload: QuestionPayload,
): NotificationIntent | undefined {
  if (!policy.wants('needs-answer')) return undefined
  const first = payload.questions[0]
  const text = first?.question ?? '有新的提问'
  const options = first?.options?.map((option) => option.label).slice(0, 4).join(' / ')
  const body = options === undefined || options === '' ? text : `${text}（${options}）`
  const key = payload.wait?.callId ?? `text:${text}`
  return {
    kind: 'needs-answer',
    sessionId: session.id,
    sessionTitle: session.title,
    workspace: workspaceOf(session.cwd),
    title: '需要你回答',
    body: clip(body, policy.bodyLimit),
    urgency: 'critical',
    openUrl: openUrlFor(session.id),
    dedupeKey: `question:${key}`,
  }
}

/**
 * 由 `job/settled` 生成意图。
 * @param policy - 当前策略
 * @param session - 会话投影
 * @param data - 作业载荷
 * @returns 意图；不该通知时 undefined
 */
export function intentFromJob(
  policy: Policy,
  session: SessionView,
  data: { readonly jobId: string; readonly label: string; readonly status: 'completed' | 'killed' | 'failed'; readonly detail?: string },
): NotificationIntent | undefined {
  if (!policy.wants('job')) return undefined
  const statusText = data.status === 'completed' ? '完成' : data.status === 'killed' ? '被终止' : '失败'
  const detail = data.detail === undefined ? '' : ` · ${data.detail}`
  return {
    kind: 'job',
    sessionId: session.id,
    sessionTitle: session.title,
    workspace: workspaceOf(session.cwd),
    title: `后台任务${statusText}`,
    body: clip(`${data.label}${detail}`, policy.bodyLimit),
    urgency: 'normal',
    openUrl: openUrlFor(session.id),
    dedupeKey: `job:${data.jobId}`,
  }
}

/**
 * 由 `goal/changed` 生成意图。
 * @param policy - 当前策略
 * @param session - 会话投影
 * @param change - 目标变更
 * @returns 意图；不该通知时 undefined
 */
export function intentFromGoal(
  policy: Policy,
  session: SessionView,
  change: { readonly operation: string; readonly goal?: { readonly objective?: string } },
): NotificationIntent | undefined {
  if (!policy.wants('goal')) return undefined
  const objective = change.goal?.objective ?? ''
  return {
    kind: 'goal',
    sessionId: session.id,
    sessionTitle: session.title,
    workspace: workspaceOf(session.cwd),
    title: `目标${goalOperationText(change.operation)}`,
    body: clip(objective === '' ? session.title : objective, policy.bodyLimit),
    urgency: 'normal',
    openUrl: openUrlFor(session.id),
    dedupeKey: `goal:${session.id}:${change.operation}`,
  }
}

/**
 * 目标操作的中文标签。
 * @param operation - 宿主操作名
 * @returns 中文标签；未知操作原样返回
 */
function goalOperationText(operation: string): string {
  const table: Readonly<Record<string, string>> = {
    create: '已创建',
    edit: '已修改',
    pause: '已暂停',
    resume: '已恢复',
    complete: '已完成',
    block: '受阻',
    clear: '已清除',
  }
  return table[operation] ?? operation
}

/**
 * 把意图补全成可写入 spool 的条目。
 * @param intent - 意图
 * @param id - 新生成的 UUID
 * @param now - 当前时刻
 * @returns 契约条目
 */
/** normal 通知的横幅停留毫秒数（固定 5 秒，不进设置）。 */
export const DEFAULT_NORMAL_TIMEOUT_MS = 5000

/**
 * 按紧急度决定横幅停留时间。
 * @param urgency - 紧急度
 * @param criticalTimeoutMs - critical 的时限，来自设置
 * @returns 毫秒数
 */
export function timeoutFor(urgency: Urgency, criticalTimeoutMs: number): number {
  return urgency === 'critical' ? criticalTimeoutMs : DEFAULT_NORMAL_TIMEOUT_MS
}

export function toEntry(
  intent: NotificationIntent,
  id: string,
  now: Date,
  timeoutMs?: number,
): NotificationEntry {
  return {
    v: 1,
    type: 'notification',
    id,
    ts: now.toISOString(),
    kind: intent.kind,
    sessionId: intent.sessionId,
    sessionTitle: intent.sessionTitle,
    ...(intent.workspace === undefined ? {} : { workspace: intent.workspace }),
    title: intent.title,
    body: intent.body,
    urgency: intent.urgency,
    openUrl: intent.openUrl,
    dedupeKey: intent.dedupeKey,
    ...(timeoutMs === undefined ? {} : { timeoutMs }),
  }
}
