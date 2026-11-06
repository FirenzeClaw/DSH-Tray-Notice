#!/usr/bin/env node
/**
 * 把 tsc 产出的 CommonJS 客户端代码包装成宿主可加载的 bundle。
 *
 * 为什么需要这一步：宿主只接受 `window.__ModuleLoader__.load({ id, factory })`
 * 形式的产物，工厂内部是 CommonJS，依赖经 `require("裸模块名")` 从宿主模块表取。
 * tsc 直出的代码没有这层包装，故用本脚本补上——本项目约定「构建只有 tsc」，
 * 不引入 bundler。
 *
 * 另做两项校验（都对应真实失败模式）：
 *   1. 产物不得含相对 require——宿主模块表只解析裸模块名，相对路径在浏览器里
 *      必然抛错，而类型检查与 tsc 都拦不住；
 *   2. 产物不得残留 ESM import/export 语句——tsconfig.client.json 配的是
 *      CommonJS，一旦有人改了配置，这里要当场失败而不是产出坏包。
 *
 * 纯函数 `inlineCommonJs` 导出给单测用：包装器的误判曾让整条构建静默产出坏包。
 * 构建本身只在被当作入口执行时运行，import 无副作用。
 */

import { existsSync, mkdirSync, readFileSync, realpathSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const sourcePath = resolve(root, 'dist/client-raw/index.js')
const outputPath = resolve(root, 'dist/client.js')

/**
 * 把一份 CommonJS 产物包成宿主模块工厂。
 * @param moduleSource - tsc 产出的 CommonJS 源码
 * @param label - 出错信息里显示的文件名
 * @returns 可直接写盘的 bundle 源码
 * @throws 产物含相对 require 或残留 ESM 语句时抛出
 */
export function inlineCommonJs(moduleSource, label) {
  const relativeRequire = /require\(\s*["']\.{1,2}\//.exec(moduleSource)
  if (relativeRequire !== null) {
    throw new Error(
      `${label} 含相对 require（${relativeRequire[0]}）：宿主模块表只解析裸模块名。` +
        '请把客户端代码收敛到 src/client/index.ts 单文件。',
    )
  }
  // 只认行首的 import/export 声明：注释与字符串里出现这些词不算。
  const esmLeftover = /^\s*(?:import\s+(?!\()|export\s+)/m.exec(moduleSource)
  if (esmLeftover !== null) {
    throw new Error(
      `${label} 残留 ESM 语句（${esmLeftover[0].trim()}）：tsconfig.client.json 必须输出 CommonJS。`,
    )
  }
  return moduleSource
}

/** 生成并写出 `dist/client.js`。 */
function build() {
  if (!existsSync(sourcePath)) {
    throw new Error(`缺少 ${sourcePath}：请先运行 tsc -p tsconfig.client.json`)
  }
  const source = readFileSync(sourcePath, 'utf8')
  const body = inlineCommonJs(source, 'dist/client-raw/index.js')

  const packageJson = JSON.parse(readFileSync(resolve(root, 'package.json'), 'utf8'))
  const id = packageJson.name
  if (typeof id !== 'string' || id.length === 0) throw new Error('package.json 缺少 name')

  const bundle = `window.__ModuleLoader__.load({
\tid: ${JSON.stringify(id)},
\tfactory: (require) => {
\t\tvar module = { exports: {} };
\t\tvar exports = module.exports;
${body}
\t\treturn module.exports;
\t}
});
`

  mkdirSync(dirname(outputPath), { recursive: true })
  writeFileSync(outputPath, bundle, 'utf8')
  process.stdout.write(`client bundle: ${outputPath} (${Buffer.byteLength(bundle)} bytes)\n`)
}

/** 是否被当作入口执行（而不是被测试 import）。判断不出来时不执行。 */
const isEntryPoint = (() => {
  const entry = process.argv[1]
  if (entry === undefined) return false
  try {
    return realpathSync(entry) === realpathSync(fileURLToPath(import.meta.url))
  } catch {
    return false
  }
})()

if (isEntryPoint) build()
