/**
 * 通知策略配置：四组开关、三档预设、自定义标记。
 *
 * 为什么开关粒度是「组」而不是「每个事件」：12 个 kind 两两组合会让设置页变成
 * 勾选矩阵，而用户真正想说的是「安静点 / 正常 / 全都告诉我」。组内只在「需要你」
 * 这一组保留两个子开关——审批与提问的打扰成本不同，值得分开。
 *
 * 权威性约定：`groups` 是唯一生效的值，`preset` 只是界面标签。用户逐组改动后
 * 由 `detectPreset` 重新判定标签——这样「把值改回与某预设一致时自动显示为该预设」
 * 不需要额外的状态机。
 * @module
 */

/** 持久化的预设值；界面只做标签映射。 */
export type Preset = 'quiet' | 'standard' | 'verbose' | 'custom'

/** 四组开关。 */
export interface GroupSwitches {
  /** 需要你：审批与提问。两个子项可分别关掉。 */
  readonly 'needs-you': {
    readonly approval: boolean
    readonly answer: boolean
  }
  /** 完成与出错。 */
  readonly 'done-error': boolean
  /** 提示（含「你可能卡住了」这类观察）。 */
  readonly notice: boolean
  /** 其它信息性：job / goal / subagent / tool-failure 等。 */
  readonly other: boolean
}

/** 组名。 */
export type GroupName = keyof GroupSwitches

/** 插件配置。 */
export interface TrayNotifyConfig {
  readonly preset: Preset
  readonly groups: GroupSwitches
  /** 子会话轮次结束是否通知；默认 false——子会话的完成通常不是用户关心的事。 */
  readonly subagents: boolean
  /** 父会话结束时等子会话跑完再通知；默认 true。 */
  readonly deferWhileChildrenRun: boolean
  /** 正文截断长度；默认 200。 */
  readonly bodyLimit: number
  /**
   * 设置页「发送测试通知」的触发标记。
   *
   * 为什么用计数器而不是布尔：布尔改成 true 后必须改回 false 才能再触发一次，
   * 而设置页写完就忘；计数器每次 +1，插件据此判断「用户又点了一次」。
   */
  readonly testNonce: number
}

/** 全关。 */
const ALL_OFF: GroupSwitches = {
  'needs-you': { approval: false, answer: false },
  'done-error': false,
  notice: false,
  other: false,
}

/** 三档预设各自的开关集合。`custom` 不在表里：它表示「以 groups 为准」。 */
export const PRESET_GROUPS: Readonly<Record<Exclude<Preset, 'custom'>, GroupSwitches>> = {
  // 安静：只留真正要人动手的事，外加「提示」——后者承载「你可能卡住了」这类
  // 观察，是安静模式下仍值得打扰的唯一信息（用户已确认保留）。
  quiet: { ...ALL_OFF, 'needs-you': { approval: true, answer: true }, notice: true },
  // 标准：再加完成与出错。
  standard: {
    'needs-you': { approval: true, answer: true },
    'done-error': true,
    notice: true,
    other: false,
  },
  // 详细：全开。
  verbose: {
    'needs-you': { approval: true, answer: true },
    'done-error': true,
    notice: true,
    other: true,
  },
}

/** 默认配置：标准预设。 */
export const DEFAULT_CONFIG: TrayNotifyConfig = {
  preset: 'standard',
  groups: PRESET_GROUPS.standard,
  subagents: false,
  deferWhileChildrenRun: true,
  bodyLimit: 200,
  testNonce: 0,
}

/** 组级覆盖：允许只给一个组、或只给 needs-you 的一个子项。 */
export interface GroupOverrides {
  readonly 'needs-you'?: { readonly approval?: boolean; readonly answer?: boolean }
  readonly 'done-error'?: boolean
  readonly notice?: boolean
  readonly other?: boolean
}

/**
 * 取某预设的开关集合。
 * @param preset - 预设值；`custom` 退回 `standard` 作为中性基底
 * @returns 开关集合（冻结的共享对象，调用方不应修改）
 */
export function presetGroups(preset: Preset): GroupSwitches {
  if (preset === 'custom') return PRESET_GROUPS.standard
  return PRESET_GROUPS[preset]
}

/**
 * 由预设叠加组级覆盖，得到最终开关集合。
 *
 * 纯函数：不读环境、不写文件，因此可以直接在测试里穷举三档预设与覆盖的组合。
 * @param preset - 基底预设
 * @param overrides - 组级覆盖；未给出的项沿用预设值
 * @returns 新的开关集合（不与入参共享引用）
 */
export function resolveGroups(preset: Preset, overrides: GroupOverrides = {}): GroupSwitches {
  const base = presetGroups(preset)
  const needsYou = overrides['needs-you']
  return {
    'needs-you': {
      approval: needsYou?.approval ?? base['needs-you'].approval,
      answer: needsYou?.answer ?? base['needs-you'].answer,
    },
    'done-error': overrides['done-error'] ?? base['done-error'],
    notice: overrides.notice ?? base.notice,
    other: overrides.other ?? base.other,
  }
}

/**
 * 判断一组开关与哪个预设完全一致。
 *
 * 用于「用户逐组改回预设值时，标签自动回到该预设」——不需要额外状态机。
 * @param groups - 当前开关
 * @returns 匹配的预设名；都不匹配时 `custom`
 */
export function detectPreset(groups: GroupSwitches): Preset {
  const candidates: Exclude<Preset, 'custom'>[] = ['quiet', 'standard', 'verbose']
  for (const candidate of candidates) {
    if (sameGroups(groups, PRESET_GROUPS[candidate])) return candidate
  }
  return 'custom'
}

/**
 * 两组开关是否完全相同。
 * @param left - 左
 * @param right - 右
 * @returns 完全相同为 true
 */
function sameGroups(left: GroupSwitches, right: GroupSwitches): boolean {
  return (
    left['needs-you'].approval === right['needs-you'].approval &&
    left['needs-you'].answer === right['needs-you'].answer &&
    left['done-error'] === right['done-error'] &&
    left.notice === right.notice &&
    left.other === right.other
  )
}

/**
 * 判断某个组是否开启。
 * @param groups - 开关集合
 * @param group - 组名
 * @returns 是否开启；`needs-you` 只要任一子项开启即为开启
 */
export function isGroupEnabled(groups: GroupSwitches, group: GroupName): boolean {
  if (group === 'needs-you') return groups['needs-you'].approval || groups['needs-you'].answer
  return groups[group]
}

/**
 * 把可能残缺的配置规范化成完整配置。
 *
 * 读设置失败或用户手工改过配置文件时，字段可能缺失或类型不对；这里一次性收敛，
 * 后续代码不必到处判空。
 * @param raw - 任意输入
 * @returns 完整配置
 */
export function normalizeConfig(raw: unknown): TrayNotifyConfig {
  if (typeof raw !== 'object' || raw === null) return DEFAULT_CONFIG
  const source = raw as Partial<TrayNotifyConfig>
  const preset: Preset =
    source.preset === 'quiet' || source.preset === 'standard' || source.preset === 'verbose' || source.preset === 'custom'
      ? source.preset
      : DEFAULT_CONFIG.preset
  const groups = normalizeGroups(source.groups, preset)
  return {
    preset: detectPreset(groups),
    groups,
    subagents: typeof source.subagents === 'boolean' ? source.subagents : DEFAULT_CONFIG.subagents,
    deferWhileChildrenRun:
      typeof source.deferWhileChildrenRun === 'boolean'
        ? source.deferWhileChildrenRun
        : DEFAULT_CONFIG.deferWhileChildrenRun,
    bodyLimit:
      typeof source.bodyLimit === 'number' && Number.isFinite(source.bodyLimit) && source.bodyLimit > 0
        ? Math.floor(source.bodyLimit)
        : DEFAULT_CONFIG.bodyLimit,
    testNonce:
      typeof source.testNonce === 'number' && Number.isFinite(source.testNonce) && source.testNonce >= 0
        ? Math.floor(source.testNonce)
        : DEFAULT_CONFIG.testNonce,
  }
}

/**
 * 规范化开关集合：缺项按预设补齐，类型不对按预设补齐。
 * @param raw - 任意输入
 * @param preset - 用于补齐的预设
 * @returns 完整开关集合
 */
function normalizeGroups(raw: unknown, preset: Preset): GroupSwitches {
  const base = presetGroups(preset)
  if (typeof raw !== 'object' || raw === null) return base
  const source = raw as GroupOverrides
  const needsYou = typeof source['needs-you'] === 'object' && source['needs-you'] !== null ? source['needs-you'] : {}
  return {
    'needs-you': {
      approval: typeof needsYou.approval === 'boolean' ? needsYou.approval : base['needs-you'].approval,
      answer: typeof needsYou.answer === 'boolean' ? needsYou.answer : base['needs-you'].answer,
    },
    'done-error': typeof source['done-error'] === 'boolean' ? source['done-error'] : base['done-error'],
    notice: typeof source.notice === 'boolean' ? source.notice : base.notice,
    other: typeof source.other === 'boolean' ? source.other : base.other,
  }
}
