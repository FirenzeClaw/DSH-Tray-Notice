/**
 * 客户端半骨架。
 *
 * 真正的深链解析与设置页在 T035 / T059 落地。客户端产物受「单文件、无相对
 * require」约束（见 scripts/build-client.mjs），所以这里是唯一的客户端源文件。
 * @module
 */

/** 宿主模块表的最小形状：只声明本文件用到的部分。 */
interface ClientContext {
  readonly remote: unknown
}

/**
 * 客户端插件装载点。
 * @param ctx - 客户端上下文
 */
export function apply(ctx: ClientContext): void {
  void ctx
}
