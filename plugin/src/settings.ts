/**
 * 设置读取与热更新。
 *
 * 为什么读失败要回退「标准」而不是不工作：插件是旁路，用户装了它就该收到通知。
 * 一份读不出来的配置只能说明「用户还没配过」，默认档位是最合理的猜测；因为配置
 * 读失败而彻底静默，用户只会以为插件坏了。
 *
 * 热更新走宿主的 `settings/document-updated` 事件：设置页保存后宿主重新装配该条目，
 * 插件在这里重读并重建策略对象，不必重启 DSH。
 * @module
 */

import type { Context } from '@deepseek-ai/cordis'
// 这个 type-only import 同时起两个作用：拿到品牌化的命名空间类型，并让
// `dsh-settings` 的 `declare module '@deepseek-ai/cordis'` 增强生效——
// 否则 `settings/document-updated` 不在 Events 里，`ctx.on` 会拒绝该事件名。
import type { SettingsNamespace } from '@deepseek-ai/dsh-settings'

import {
  DEFAULT_CONFIG,
  normalizeConfig,
  type GroupSwitches,
  type TrayNotifyConfig,
} from './config.ts'
import { isKindEnabled } from './kinds.ts'
import type { Logger } from './log.ts'
import type { NotificationKind } from './types.ts'

/** 设置命名空间 = profile 插件条目 id（= bundle patch 里的 `id`）。 */
export const SETTINGS_NAMESPACE = 'tray-notify'

/**
 * 宿主设置服务的**最小结构**。
 *
 * 刻意不 import `SettingsForms` 类：插件只需要两个方法，绑定到具体类会让测试必须
 * 造出整个 cordis 服务。结构类型在这里比名义类型更合适。
 */
export interface SettingsReader {
  /**
   * 读当前所有条目的表单值。
   * @returns 每项含 `ns` 与解析后的 `value`
   */
  describe(): readonly { readonly ns: string; readonly value: unknown }[]
}

/** 策略对象：由配置派生的、热路径上要用的判定。 */
export interface Policy {
  /** 配置快照。 */
  readonly config: TrayNotifyConfig
  /** 该 kind 在当前开关下是否通知。 */
  wants(kind: NotificationKind): boolean
  /** 组开关（供 `sessionstate` 等模块判断子会话是否上报）。 */
  readonly groups: GroupSwitches
  /** 子会话轮次结束是否通知。 */
  readonly subagents: boolean
  /** 父会话结束时是否等子会话跑完。 */
  readonly deferWhileChildrenRun: boolean
  /** 正文截断长度。 */
  readonly bodyLimit: number
}

/**
 * 由配置构造策略对象。
 * @param config - 已规范化的配置
 * @returns 策略
 */
export function createPolicy(config: TrayNotifyConfig): Policy {
  return {
    config,
    groups: config.groups,
    subagents: config.subagents,
    deferWhileChildrenRun: config.deferWhileChildrenRun,
    bodyLimit: config.bodyLimit,
    wants: (kind) => isKindEnabled(kind, config.groups),
  }
}

/**
 * 从设置服务读一次配置。
 *
 * 找不到本命名空间、读抛错、值不是对象——三种情况都退回默认配置，并记一条 warn：
 * 静默回退会让「为什么我的设置没生效」无从查起。
 * @param settings - 设置服务；宿主未提供时为 undefined
 * @param logger - 日志器
 * @returns 规范化后的配置
 */
export function readConfig(settings: SettingsReader | undefined, logger: Logger): TrayNotifyConfig {
  if (settings === undefined) {
    logger.warn('宿主未提供 settings 服务，回退标准预设')
    return DEFAULT_CONFIG
  }
  try {
    const descriptor = settings.describe().find((entry) => entry.ns === SETTINGS_NAMESPACE)
    if (descriptor === undefined) {
      logger.info('设置中尚无 tray-notify 条目，使用默认值')
      return DEFAULT_CONFIG
    }
    return normalizeConfig(descriptor.value)
  } catch (error) {
    logger.warn(`读取设置失败，回退标准预设：${error instanceof Error ? error.message : String(error)}`)
    return DEFAULT_CONFIG
  }
}

/** 可释放的订阅。 */
export interface SettingsBinding {
  /** 当前策略（每次设置变更后是新对象）。 */
  readonly current: () => Policy
  /** 取消订阅。 */
  dispose(): void
}

/**
 * 订阅设置变化并维护当前策略。
 *
 * @param ctx - 插件上下文，用它的 `on` 订阅宿主事件
 * @param settings - 设置服务；undefined 时只返回默认策略且不订阅
 * @param logger - 日志器
 * @returns 绑定句柄
 */
export function bindSettings(
  ctx: Pick<Context, 'on'>,
  settings: SettingsReader | undefined,
  logger: Logger,
): SettingsBinding {
  let policy = createPolicy(readConfig(settings, logger))

  const reload = (): void => {
    policy = createPolicy(readConfig(settings, logger))
    logger.debug(`策略已更新：preset=${policy.config.preset}`)
  }

  // 只在事件属于本命名空间时重读：宿主会把任何条目的变更都广播出来，全量重读
  // 在设置页频繁保存时是浪费。
  const off = ctx.on('settings/document-updated', (ns: SettingsNamespace) => {
    if (String(ns) === SETTINGS_NAMESPACE) reload()
  })

  return {
    current: () => policy,
    dispose: () => {
      off()
    },
  }
}
