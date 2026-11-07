/**
 * 客户端半：深链跳转 + 设置分区。
 *
 * 受宿主约束：客户端产物必须是**单文件、无相对 require**（依赖只能经 `require("裸模块名")`
 * 从宿主模块表取）。React、`react/jsx-runtime` 与 `@deepseek-ai/dsh-client-ui-primitives`
 * 都由宿主提供；本文件不 import 任何项目内模块，因此拆文件会直接导致构建失败——
 * 这也是本文件超过 AGENTS.md 400 行建议上限的既有例外，不是遗漏。
 *
 * 两个功能：
 * 1. **深链**：`?session=<id>` → `uiWorkspace.openSession`，成功后清掉参数。
 * 2. **设置分区**：三档预设 + 四组开关 + 需要你的两个子项 + 发送测试通知。
 * @module
 */

import { jsx, jsxs } from 'react/jsx-runtime'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ReactElement } from 'react'

/** 宿主提供的设置远程接口（只声明用到的部分）。 */
interface RemoteResult<T> {
  readonly ok: boolean
  readonly value?: T
  readonly error?: { readonly code?: string; readonly message?: string }
}

interface SettingsNamespaceView {
  readonly ns: string
  readonly value: unknown
  readonly revision: number
}

interface SettingsDescribeValue {
  readonly writable: boolean
  readonly namespaces: readonly SettingsNamespaceView[]
}

interface SettingsRemote {
  describe(): Promise<RemoteResult<SettingsDescribeValue>>
  update(
    ns: string,
    patch: Record<string, unknown>,
    expectedRevision: number | undefined,
  ): Promise<RemoteResult<SettingsNamespaceView>>
}

/** 宿主提供的槽位注册器。 */
interface Slots {
  inject(name: string, register: () => () => void): void
  register(options: Record<string, unknown>, component: (props: Record<string, unknown>) => ReactElement): () => void
}

/** 宿主提供的原语（只声明用到的）。 */
interface Primitives {
  Button: (props: Record<string, unknown>) => ReactElement
  Switch: (props: Record<string, unknown>) => ReactElement
}

/** 客户端上下文。 */
export interface ClientContext {
  readonly remote?: { readonly settings?: SettingsRemote }
  readonly uiWorkspace?: { openSession(sessionId: string): void }
  readonly slots?: Slots
  /** 按名探测其它宿主服务（可选）。 */
  get?(name: string): unknown
}

/**
 * 客户端依赖。
 *
 * `remote.settings` 必须**单独列出**：`ctx.remote` 是远程代理，每个属性有独立的访问门；
 * 只注入 `remote` 时读 `ctx.remote.settings` 会抛 `cannot get property … without inject`，
 * 而抛出点在渲染期，宿主会把整条 section 判为崩溃并撤下。类型检查发现不了，故留注释。
 */
export const inject = ['remote', 'remote.settings', 'slots']

/** 设置命名空间 = profile 插件条目 id。 */
const NAMESPACE_ID = 'tray-notify'

/** 分区标题。 */
const SECTION_TITLE = 'DSH 通知'

/** 预设的界面标签。 */
const PRESET_LABELS: ReadonlyArray<{ readonly value: string; readonly label: string }> = [
  { value: 'quiet', label: '安静' },
  { value: 'standard', label: '标准' },
  { value: 'verbose', label: '详细' },
]

/** 预设对应的开关集合；与服务端 `config.ts` 的 PRESET_GROUPS 必须一致。 */
const PRESET_GROUPS: Record<string, Groups> = {
  quiet: { 'needs-you': { approval: true, answer: true }, 'done-error': false, notice: true, other: false },
  standard: { 'needs-you': { approval: true, answer: true }, 'done-error': true, notice: true, other: false },
  verbose: { 'needs-you': { approval: true, answer: true }, 'done-error': true, notice: true, other: true },
}

/** 四组开关。 */
interface Groups {
  readonly 'needs-you': { readonly approval: boolean; readonly answer: boolean }
  readonly 'done-error': boolean
  readonly notice: boolean
  readonly other: boolean
}

/** 组开关的界面元信息。 */
const GROUP_ROWS: ReadonlyArray<{ readonly key: keyof Groups; readonly label: string; readonly hint: string }> = [
  { key: 'needs-you', label: '需要你', hint: '审批请求与提问' },
  { key: 'done-error', label: '完成与出错', hint: '轮次跑完、出错、阻塞、超限' },
  { key: 'notice', label: '提示', hint: '会话内的观察，例如「你可能卡住了」' },
  { key: 'other', label: '其它信息性', hint: '后台任务、目标变更、取消与中断' },
]

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
    // 会话不存在（已被删除、或链接来自另一台机器）：静默留在首页，不清参数，
    // 刷新时会再试一次。
    return false
  }
  env.replaceState({}, '', stripSessionParam(env.search, env.pathname))
  return true
}

/**
 * 把设置值规范化成组开关。
 *
 * 服务端已经做过一次规范化，这里再兜一次是因为客户端拿到的可能是旧版本文档
 * （用户刚升级插件、设置还没被重写）。
 * @param raw - 设置值
 * @returns 组开关
 */
export function groupsOf(raw: unknown): Groups {
  const value = typeof raw === 'object' && raw !== null ? (raw as { groups?: unknown }) : {}
  const source = typeof value.groups === 'object' && value.groups !== null ? (value.groups as Record<string, unknown>) : {}
  const needsYou = typeof source['needs-you'] === 'object' && source['needs-you'] !== null
    ? (source['needs-you'] as Record<string, unknown>)
    : {}
  return {
    'needs-you': {
      approval: typeof needsYou.approval === 'boolean' ? needsYou.approval : true,
      answer: typeof needsYou.answer === 'boolean' ? needsYou.answer : true,
    },
    'done-error': typeof source['done-error'] === 'boolean' ? source['done-error'] : true,
    notice: typeof source.notice === 'boolean' ? source.notice : true,
    other: typeof source.other === 'boolean' ? source.other : false,
  }
}

/**
 * 从设置值里取 critical 横幅时限（毫秒）。
 *
 * 服务端会规范化（钳到 5 秒 ~ 1 小时），这里只做界面兜底：拿到的可能是旧版本文档。
 * @param raw - 设置值
 * @returns 毫秒数
 */
export function criticalTimeoutOf(raw: unknown): number {
  const value = typeof raw === 'object' && raw !== null ? (raw as { criticalTimeoutMs?: unknown }) : {}
  const ms = value.criticalTimeoutMs
  if (typeof ms !== 'number' || !Number.isFinite(ms)) return DEFAULT_CRITICAL_TIMEOUT_MS
  return Math.min(CRITICAL_TIMEOUT_MAX_MS, Math.max(CRITICAL_TIMEOUT_MIN_MS, Math.floor(ms)))
}

/** 与服务端 `config.ts` 保持一致的下限、上限与默认值。 */
export const CRITICAL_TIMEOUT_MIN_MS = 5_000
export const CRITICAL_TIMEOUT_MAX_MS = 3_600_000
export const DEFAULT_CRITICAL_TIMEOUT_MS = 300_000

/**
 * 判断当前开关与哪个预设一致。
 * @param groups - 开关
 * @returns 预设名；都不匹配时 `custom`
 */
export function presetOf(groups: Groups): string {
  for (const [preset, expected] of Object.entries(PRESET_GROUPS)) {
    if (
      groups['needs-you'].approval === expected['needs-you'].approval &&
      groups['needs-you'].answer === expected['needs-you'].answer &&
      groups['done-error'] === expected['done-error'] &&
      groups.notice === expected.notice &&
      groups.other === expected.other
    ) {
      return preset
    }
  }
  return 'custom'
}

/** 当前客户端上下文；`apply` 里赋值，供组件使用。 */
let currentContext: ClientContext | undefined

/** 一行开关。 */
function SwitchRow(props: {
  readonly primitives: Primitives | undefined
  readonly label: string
  readonly hint: string
  readonly checked: boolean
  readonly disabled: boolean
  readonly onChange: (next: boolean) => void
}): ReactElement {
  const Switch = props.primitives?.Switch
  return jsxs('div', {
    style: { display: 'flex', alignItems: 'center', gap: '12px', padding: '10px 0' },
    children: [
      jsxs('div', {
        style: { flex: '1', minWidth: '0' },
        children: [
          jsx('div', { style: { fontSize: '14px' }, children: props.label }),
          jsx('div', {
            style: { fontSize: '12px', opacity: 0.65, marginTop: '2px' },
            children: props.hint,
          }),
        ],
      }),
      Switch === undefined
        ? jsx('input', {
            type: 'checkbox',
            checked: props.checked,
            disabled: props.disabled,
            onChange: (event: { target: { checked: boolean } }) => props.onChange(event.target.checked),
          })
        : jsx(Switch, {
            checked: props.checked,
            disabled: props.disabled,
            onChange: (next: boolean) => props.onChange(next),
          }),
    ],
  })
}

/** 设置分区组件。 */
function TrayNotifySection(): ReactElement {
  const [value, setValue] = useState<unknown>(undefined)
  const [revision, setRevision] = useState<number | undefined>(undefined)
  const [writable, setWritable] = useState(false)
  const [error, setError] = useState<string | undefined>(undefined)
  const [busy, setBusy] = useState(false)
  /** 最新 revision 的同步副本：闭包里读到的可能是几帧之前的，写入会撞冲突。 */
  const revisionRef = useRef<number | undefined>(undefined)

  const settings = currentContext?.remote?.settings
  const primitives = currentContext?.get?.('ui-primitives') as Primitives | undefined

  const groups = useMemo(() => groupsOf(value), [value])
  const preset = useMemo(() => presetOf(groups), [groups])
  const criticalTimeoutMs = useMemo(() => criticalTimeoutOf(value), [value])
  /**
   * 输入框里的草稿（秒）。
   *
   * 独立于 value 保存：用户正在输入时 `1`、`12`、`120` 都是中间态，若每次都写回
   * 服务端，会连着提交三个值并互相踩 revision。只在回车/失焦时提交一次。
   */
  const [criticalSecondsDraft, setCriticalSecondsDraft] = useState<string | undefined>(undefined)

  const load = useCallback(async () => {
    if (settings === undefined) return
    const result = await settings.describe()
    if (!result.ok || result.value === undefined) {
      setError(result.error?.message ?? '读取设置失败')
      return
    }
    const namespace = result.value.namespaces.find((entry) => entry.ns === NAMESPACE_ID)
    if (namespace === undefined) {
      setError('设置里没有 tray-notify 条目，请确认插件已装载')
      return
    }
    setWritable(result.value.writable)
    setValue(namespace.value)
    setRevision(namespace.revision)
    revisionRef.current = namespace.revision
    setError(undefined)
  }, [settings])

  useEffect(() => {
    void load()
  }, [load])

  /**
   * 写入一个补丁。
   *
   * 用最新 revision，并在成功后用它返回的新 revision 更新本地——否则连续改两项时
   * 第二项必然撞冲突（服务端会拒绝过期的 revision）。
   */
  const write = useCallback(
    async (patch: Record<string, unknown>) => {
      if (settings === undefined || busy) return
      setBusy(true)
      try {
        const result = await settings.update(NAMESPACE_ID, patch, revisionRef.current)
        if (!result.ok) {
          const code = result.error?.code ?? ''
          // 实测宿主返回的码是 `settings/conflict`（带前缀），不是文档里的 `conflict`。
          setError(
            code.includes('conflict')
              ? '设置已被其他窗口修改，请刷新后重试'
              : (result.error?.message ?? '保存失败'),
          )
          return
        }
        if (result.value !== undefined) {
          setValue(result.value.value)
          setRevision(result.value.revision)
          revisionRef.current = result.value.revision
        }
        setError(undefined)
      } finally {
        setBusy(false)
      }
    },
    [busy, settings],
  )

  const applyPreset = useCallback(
    (next: string) => {
      const target = PRESET_GROUPS[next]
      if (target === undefined) return
      void write({ preset: next, groups: target })
    },
    [write],
  )

  const setGroup = useCallback(
    (key: keyof Groups, next: boolean) => {
      const merged: Groups = { ...groups, [key]: next }
      void write({ preset: presetOf(merged), groups: merged })
    },
    [groups, write],
  )

  const setNeedsYou = useCallback(
    (key: 'approval' | 'answer', next: boolean) => {
      const merged: Groups = { ...groups, 'needs-you': { ...groups['needs-you'], [key]: next } }
      void write({ preset: presetOf(merged), groups: merged })
    },
    [groups, write],
  )

  /** 把输入框的草稿提交上去；非法或没改就丢弃草稿、回到服务端的值。 */
  const commitCriticalTimeout = useCallback(() => {
    if (criticalSecondsDraft === undefined) return
    const seconds = Number(criticalSecondsDraft.trim())
    setCriticalSecondsDraft(undefined)
    if (!Number.isFinite(seconds)) return
    const ms = Math.round(seconds * 1000)
    if (ms === criticalTimeoutMs) return
    void write({ criticalTimeoutMs: ms })
  }, [criticalSecondsDraft, criticalTimeoutMs, write])

  const sendTest = useCallback(() => {
    // 计数器 +1：布尔改成 true 后必须改回才能再触发，而设置页写完就忘。
    const current = typeof (value as { testNonce?: unknown } | undefined)?.testNonce === 'number'
      ? ((value as { testNonce: number }).testNonce)
      : 0
    void write({ testNonce: current + 1 })
  }, [value, write])

  const disabled = !writable || busy

  return jsxs('div', {
    style: { display: 'flex', flexDirection: 'column', gap: '12px', padding: '16px 0' },
    children: [
      jsx('div', { style: { fontSize: '18px', fontWeight: 600 }, children: SECTION_TITLE }),
      jsx('div', {
        style: { fontSize: '13px', opacity: 0.7 },
        children: '决定哪些 DSH 事件会变成桌面通知。改完即时生效，不需要重启。',
      }),
      error === undefined
        ? null
        : jsx('div', {
            style: {
              fontSize: '12px',
              color: '#da4453',
              border: '1px solid rgba(218,68,83,.4)',
              borderRadius: '6px',
              padding: '8px 10px',
            },
            children: error,
          }),
      jsxs('div', {
        style: { display: 'flex', gap: '6px', alignItems: 'center' },
        children: [
          ...PRESET_LABELS.map((entry) =>
            jsx(
              'button',
              {
                type: 'button',
                disabled,
                onClick: () => applyPreset(entry.value),
                style: {
                  fontSize: '12.5px',
                  padding: '5px 12px',
                  borderRadius: '6px',
                  border: '1px solid rgba(255,255,255,.14)',
                  background: preset === entry.value ? 'rgba(61,174,233,.18)' : 'transparent',
                  color: preset === entry.value ? '#9fd8f5' : 'inherit',
                  cursor: disabled ? 'default' : 'pointer',
                },
                children: entry.label,
              },
              entry.value,
            ),
          ),
          preset === 'custom'
            ? jsx('span', { style: { fontSize: '12px', opacity: 0.6 }, children: '自定义' })
            : null,
        ],
      }),
      ...GROUP_ROWS.map((row) =>
        row.key === 'needs-you'
          ? jsxs(
              'div',
              {
                children: [
                  jsx(SwitchRow, {
                    primitives,
                    label: row.label,
                    hint: row.hint,
                    checked: groups['needs-you'].approval || groups['needs-you'].answer,
                    disabled,
                    onChange: (next: boolean) => {
                      // 组级开关同时改两个子项：关掉整组比让用户点两次更符合直觉。
                      setNeedsYou('approval', next)
                      setNeedsYou('answer', next)
                    },
                  }),
                  jsx('div', {
                    style: { paddingLeft: '18px' },
                    children: jsx(SwitchRow, {
                      primitives,
                      label: '审批请求',
                      hint: '工具执行前的确认',
                      checked: groups['needs-you'].approval,
                      disabled,
                      onChange: (next: boolean) => setNeedsYou('approval', next),
                    }),
                  }),
                  jsx('div', {
                    style: { paddingLeft: '18px' },
                    children: jsx(SwitchRow, {
                      primitives,
                      label: '提问',
                      hint: '需要你选择的选项',
                      checked: groups['needs-you'].answer,
                      disabled,
                      onChange: (next: boolean) => setNeedsYou('answer', next),
                    }),
                  }),
                ],
              },
              row.key,
            )
          : jsx(
              SwitchRow,
              {
                primitives,
                label: row.label,
                hint: row.hint,
                checked: groups[row.key] as boolean,
                disabled,
                onChange: (next: boolean) => setGroup(row.key, next),
              },
              row.key,
            ),
      ),
      jsxs('div', {
        style: { display: 'flex', alignItems: 'center', gap: '12px', padding: '10px 0' },
        children: [
          jsxs('div', {
            style: { flex: '1', minWidth: '0' },
            children: [
              jsx('div', { style: { fontSize: '14px' }, children: '审批通知停留时间' }),
              jsx('div', {
                style: { fontSize: '12px', opacity: 0.65, marginTop: '2px' },
                children: '需要你处理的通知在屏幕上停留多久（秒）。不设「永不消失」——实测那样会占住弹窗位，后续通知全被挡住。',
              }),
            ],
          }),
          jsx('input', {
            type: 'number',
            min: CRITICAL_TIMEOUT_MIN_MS / 1000,
            max: CRITICAL_TIMEOUT_MAX_MS / 1000,
            step: 30,
            disabled,
            // 草稿优先：编辑期间不能被服务端回写顶掉，否则用户打不完整。
            value: criticalSecondsDraft ?? String(Math.round(criticalTimeoutMs / 1000)),
            onChange: (event: { target: { value: string } }) => setCriticalSecondsDraft(event.target.value),
            onBlur: commitCriticalTimeout,
            onKeyDown: (event: { key: string }) => {
              if (event.key === 'Enter') commitCriticalTimeout()
            },
            style: {
              width: '90px',
              fontSize: '13px',
              padding: '5px 8px',
              borderRadius: '6px',
              border: '1px solid rgba(255,255,255,.14)',
              background: 'transparent',
              color: 'inherit',
            },
          }),
          jsx('span', { style: { fontSize: '12px', opacity: 0.6 }, children: '秒' }),
        ],
      }),
      jsxs('div', {
        style: { display: 'flex', alignItems: 'center', gap: '10px', paddingTop: '6px' },
        children: [
          jsx('button', {
            type: 'button',
            disabled,
            onClick: sendTest,
            style: {
              fontSize: '12.5px',
              padding: '6px 12px',
              borderRadius: '6px',
              border: '1px solid rgba(255,255,255,.14)',
              background: 'transparent',
              cursor: disabled ? 'default' : 'pointer',
            },
            children: '发送测试通知',
          }),
          jsx('span', {
            style: { fontSize: '12px', opacity: 0.6 },
            children: '用它确认通知链路通不通，不受上面的开关影响。',
          }),
        ],
      }),
    ],
  })
}

/**
 * 客户端插件装载点。
 * @param ctx - 客户端上下文
 */
export function apply(ctx: ClientContext): void {
  currentContext = ctx

  const globalLocation = (globalThis as { location?: { search: string; pathname: string } }).location
  const history = (globalThis as { history?: { replaceState(s: unknown, t: string, u: string): void } }).history
  const workspace = ctx.uiWorkspace
  if (globalLocation !== undefined && history !== undefined && workspace !== undefined) {
    applyDeepLink({
      search: globalLocation.search,
      pathname: globalLocation.pathname,
      openSession: (sessionId) => workspace.openSession(sessionId),
      replaceState: (state, title, url) => history.replaceState(state, title, url),
    })
  }

  const slots = ctx.slots
  if (slots !== undefined) {
    slots.inject('settings.section', () =>
      slots.register(
        { name: 'settings.section', id: NAMESPACE_ID, order: 60, label: () => SECTION_TITLE },
        TrayNotifySection,
      ),
    )
  }
}
