// 界面 → Host → 工作台服务 /api/* 的路由表（Spec 4.3 表、20.5；T13 执行令 Q6）。
// 方法名 = 契约文件名驼峰；一个文件对应两个 HTTP 方法时加 get / put / post 前缀。
// settings、connection_test 两个文件沿用 T7 的方法（getSettings、putSettings、testConnection），不在本表。
// 每个方法只收一个参数 request（对 GET 即查询参数），路径里的 {x} 从 request 同名字段取出。

export type HttpMethod = 'GET' | 'PUT' | 'POST'

export interface ApiRoute {
  /** 远程方法名（ctx.remote.lawbench.<method>）。 */
  readonly method: string
  readonly http: HttpMethod
  /** 服务端路径；{x} 由 request.x 填入（并从查询参数、请求体里去掉）。 */
  readonly path: string
  /** 契约文件名（contracts/api/<contract>.schema.json）。 */
  readonly contract: string
  /** 不校验、不发送 request（GET 胶囊配置：契约的 request 是 PUT 的请求体）。 */
  readonly noRequest?: boolean
  /** request 里还必须有的字段（契约 request 为 GET、POST 共用时，POST 另要的字段）。 */
  readonly require?: readonly string[]
  /** 超时（毫秒）；复制、生成类接口给长一些。 */
  readonly timeoutMs?: number
}

const LONG = 10 * 60_000

export const API_ROUTES: readonly ApiRoute[] = [
  { method: 'caseOpen', http: 'POST', path: '/api/case/open', contract: 'case_open' },
  { method: 'caseRecent', http: 'GET', path: '/api/case/recent', contract: 'case_recent' },
  { method: 'materialsScan', http: 'POST', path: '/api/materials/scan', contract: 'materials_scan', timeoutMs: LONG },
  { method: 'materialsImport', http: 'POST', path: '/api/materials/import', contract: 'materials_import', timeoutMs: LONG },
  { method: 'materialsList', http: 'GET', path: '/api/materials', contract: 'materials_list' },
  { method: 'ocrSubmit', http: 'POST', path: '/api/ocr/jobs', contract: 'ocr_submit' },
  { method: 'ocrList', http: 'GET', path: '/api/ocr/jobs', contract: 'ocr_list' },
  { method: 'ocrCancel', http: 'POST', path: '/api/ocr/jobs/{job_id}/cancel', contract: 'ocr_cancel' },
  { method: 'taskCreate', http: 'POST', path: '/api/task', contract: 'task_create' },
  // 契约 1.2：读该会话当前的选择（界面每次显示之前读，不在本地记）
  { method: 'taskCurrent', http: 'GET', path: '/api/task/current', contract: 'task_current' },
  { method: 'pipelineRun', http: 'POST', path: '/api/pipeline/run', contract: 'pipeline_run' },
  { method: 'pipelineStatus', http: 'GET', path: '/api/pipeline/{task_id}', contract: 'pipeline_status' },
  { method: 'pipelineCancel', http: 'POST', path: '/api/pipeline/{task_id}/cancel', contract: 'pipeline_cancel' },
  { method: 'tasksList', http: 'GET', path: '/api/tasks', contract: 'tasks_list' },
  { method: 'redline', http: 'POST', path: '/api/redline', contract: 'redline', timeoutMs: LONG },
  { method: 'getWikiSuggestions', http: 'GET', path: '/api/wiki/suggestions', contract: 'wiki_suggestions' },
  { method: 'postWikiSuggestions', http: 'POST', path: '/api/wiki/suggestions/{id}', contract: 'wiki_suggestions', require: ['id', 'accept'] },
  // 契约 1.2（N35 ⑥）：本案已确认的成果（成果/索引.json）
  { method: 'outputsList', http: 'GET', path: '/api/outputs', contract: 'outputs_list' },
  { method: 'outputsConfirm', http: 'POST', path: '/api/outputs/confirm', contract: 'outputs_confirm', timeoutMs: LONG },
  { method: 'source', http: 'GET', path: '/api/source', contract: 'source' },
  { method: 'search', http: 'GET', path: '/api/search', contract: 'search' },
  { method: 'getCapsules', http: 'GET', path: '/api/capsules', contract: 'capsules', noRequest: true },
  { method: 'putCapsules', http: 'PUT', path: '/api/capsules', contract: 'capsules' },
  { method: 'capsulesReset', http: 'POST', path: '/api/capsules/reset', contract: 'capsules_reset' },
  { method: 'archiveBuild', http: 'POST', path: '/api/archive/build', contract: 'archive_build', timeoutMs: LONG },
  { method: 'invoiceRun', http: 'POST', path: '/api/invoice/run', contract: 'invoice_run', timeoutMs: LONG },
  { method: 'retainerDriver', http: 'POST', path: '/api/retainer/driver', contract: 'retainer_driver' },
]

/** 把 request 拆成路径、查询串、请求体。路径参数缺失时返回 undefined。 */
export function buildRequest(route: ApiRoute, request: Record<string, unknown>): { path: string; body?: unknown } | undefined {
  const rest: Record<string, unknown> = { ...request }
  let missing = false
  const path = route.path.replace(/\{(\w+)\}/g, (_m, key: string) => {
    const v = rest[key]
    delete rest[key]
    if (typeof v !== 'string' || v === '') { missing = true; return '' }
    return encodeURIComponent(v)
  })
  if (missing) return undefined
  if (route.noRequest) return { path }
  if (route.http === 'GET') {
    const q = new URLSearchParams()
    for (const [k, v] of Object.entries(rest)) if (v !== undefined && v !== null) q.set(k, String(v))
    const qs = q.toString()
    return { path: qs ? `${path}?${qs}` : path }
  }
  return { path, body: rest }
}
