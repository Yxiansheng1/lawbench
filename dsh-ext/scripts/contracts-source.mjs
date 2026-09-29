// 构建和测试时读取仓库 contracts\ 下全部 schema 与 VERSION，供虚拟模块 lawbench:contracts 使用。
// 不手抄契约：插件里的工具参数、校验用 schema、版本号都从这里来。
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

export const CONTRACTS_DIR = join(dirname(fileURLToPath(import.meta.url)), '..', '..', 'contracts')
export const VIRTUAL_ID = 'lawbench:contracts'

function walk(dir, out) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) {
      if (name === 'examples' || name === '_build' || name.startsWith('.')) continue
      walk(p, out)
    } else if (name.endsWith('.schema.json')) {
      out.push(p)
    }
  }
  return out
}

/** @returns {{ version: string, schemas: Record<string, unknown> }} */
export function loadContracts(dir = CONTRACTS_DIR) {
  const version = readFileSync(join(dir, 'VERSION'), 'utf8').trim()
  const schemas = {}
  for (const file of walk(dir, [])) {
    const schema = JSON.parse(readFileSync(file, 'utf8'))
    if (typeof schema.$id !== 'string') throw new Error(`schema 缺少 $id：${file}`)
    schemas[schema.$id] = schema
  }
  return { version, schemas }
}

export function contractsModuleSource(dir = CONTRACTS_DIR) {
  return `export default ${JSON.stringify(loadContracts(dir))}`
}
