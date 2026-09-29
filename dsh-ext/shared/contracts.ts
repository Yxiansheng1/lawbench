// 契约加载与校验（Spec 20.1、20.4；T7 步骤 3）。
// 数据来自构建期读入的 contracts\（虚拟模块 lawbench:contracts），不手抄。
import * as ajv2020Module from 'ajv/dist/2020.js'
import * as ajvFormatsModule from 'ajv-formats'
import data from 'lawbench:contracts'

export const CONTRACT_VERSION: string = data.version
const SCHEMAS: Record<string, JsonObject> = data.schemas as Record<string, JsonObject>

export type JsonObject = { [key: string]: unknown }

const CORE = 'lawbench://contracts/core/'
const TOOLS = 'lawbench://contracts/tools/'

/** 契约里的 11 个 AI 工具名（按文件名排序）。 */
export const TOOL_NAMES: readonly string[] = Object.keys(SCHEMAS)
  .filter((id) => id.startsWith(TOOLS))
  .map((id) => id.slice(TOOLS.length).replace(/\.schema\.json$/, ''))
  .sort()

// ajv 是 CommonJS；tsc（NodeNext）和 esbuild 看到的默认导出形状不同，统一取 .default
type AjvLike = { addSchema(s: unknown): unknown; getSchema(ref: string): (((v: unknown) => boolean) & { errors?: Array<{ instancePath: string; message?: string }> | null }) | undefined }
const Ajv2020 = ((ajv2020Module as unknown as { default?: unknown }).default ?? ajv2020Module) as new (opts: object) => AjvLike
const addFormats = ((ajvFormatsModule as unknown as { default?: unknown }).default ?? ajvFormatsModule) as (a: AjvLike) => void

let ajv: AjvLike | undefined
function getAjv(): AjvLike {
  if (ajv) return ajv
  const a = new Ajv2020({ strict: false, allErrors: true })
  addFormats(a)
  for (const schema of Object.values(SCHEMAS)) a.addSchema(schema)
  ajv = a
  return a
}

/**
 * 按 `$id#/$defs/<def>` 校验数据。
 * @returns 空数组表示通过；否则是可读的错误列表（只含路径和规则，不含数据内容）。
 */
export function validate(id: string, def: string, value: unknown): string[] {
  const ref = `${id}#/$defs/${def}`
  const fn = getAjv().getSchema(ref)
  if (!fn) throw new Error(`契约中没有 ${ref}`)
  if (fn(value)) return []
  return (fn.errors ?? []).map((e) => `${e.instancePath || '/'} ${e.message ?? ''}`.trim())
}

/** 按整个 schema（`$id` 本身，不取 `$defs`）校验；返回值同 validate。 */
export function validateRoot(id: string, value: unknown): string[] {
  const fn = getAjv().getSchema(id)
  if (!fn) throw new Error(`契约中没有 ${id}`)
  if (fn(value)) return []
  return (fn.errors ?? []).map((e) => `${e.instancePath || '/'} ${e.message ?? ''}`.trim())
}

export const coreId = (command: string): string => `${CORE}${command}.schema.json`
export const toolId = (tool: string): string => `${TOOLS}${tool}.schema.json`

/** 取出 `$ref` 指向的子 schema（只支持 `<$id>#/<json pointer>` 写法）。 */
function resolveRef(ref: string): JsonObject {
  const [id, pointer = ''] = ref.split('#')
  const base = SCHEMAS[id]
  if (!base) throw new Error(`无法解析 $ref：${ref}`)
  let node: unknown = base
  for (const raw of pointer.split('/').filter(Boolean)) {
    const key = raw.replace(/~1/g, '/').replace(/~0/g, '~')
    node = (node as JsonObject)[key]
    if (node === undefined) throw new Error(`无法解析 $ref：${ref}`)
  }
  return node as JsonObject
}

/** 递归展开 `$ref`，去掉 `$schema`、`$id`，得到模型能直接读的 JSON Schema。 */
export function expandRefs(node: unknown, seen: string[] = []): unknown {
  if (Array.isArray(node)) return node.map((x) => expandRefs(x, seen))
  if (node === null || typeof node !== 'object') return node
  const obj = node as JsonObject
  if (typeof obj.$ref === 'string') {
    const ref = obj.$ref
    if (seen.includes(ref)) throw new Error(`$ref 循环：${ref}`)
    const { $ref: _drop, ...rest } = obj
    const target = expandRefs(resolveRef(ref), [...seen, ref]) as JsonObject
    return { ...target, ...(expandRefs(rest, seen) as JsonObject) }
  }
  const out: JsonObject = {}
  for (const [k, v] of Object.entries(obj)) {
    if (k === '$schema' || k === '$id' || k === '$defs') continue
    out[k] = expandRefs(v, seen)
  }
  return out
}

/** 工具的 DSH 参数定义：契约 `$defs/args` 展开 `$ref` 后的结果。 */
export function toolParameters(tool: string): JsonObject {
  const id = toolId(tool)
  const schema = SCHEMAS[id]
  if (!schema) throw new Error(`契约中没有工具 ${tool}`)
  return expandRefs((schema.$defs as JsonObject).args) as JsonObject
}

/** 工具的说明文字（契约的 description）。 */
export function toolDescription(tool: string): string {
  const schema = SCHEMAS[toolId(tool)]
  return typeof schema?.description === 'string' ? schema.description : tool
}
