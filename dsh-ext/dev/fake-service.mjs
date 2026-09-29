// 开发期本机假工作台服务（T7 步骤 6）：只监听 127.0.0.1，按契约校验每个请求，按样例回答。
// 不属于产品。T3/T8 合并后换真服务复测。
// 用法：node dev/fake-service.mjs --port 18801  （令牌取环境变量 LB_TOKEN；应用数据目录取 LB_APPDATA）
// 另支持：--fail-begin（task/begin 返回 CASE_NOT_FOUND）、--calls <jsonl>（记录每次调用的元数据）、
//   --bad-response（成功返回的内容故意不合契约：/core/* 少字段、工具结果少字段，用来测插件的返回校验）、
//   --fixtures（T13：其余 /api/* 按 ui/fixtures/<契约>.json 回答，供界面开发和截图；胶囊配置存在 LB_APPDATA 里，重启后保持）、
//   --fail-api <契约,…>（T13：这些接口改回 ui/fixtures/<契约>.fail.json，截错误提示用）、
//   --case-root <目录>（T13：假数据里第一个案件的文件夹改成这个真实存在的空目录，桌面端才能把它当工作区打开）
import { createServer } from 'node:http'
import { readFileSync, writeFileSync, existsSync, mkdirSync, appendFileSync, rmSync } from 'node:fs'
import { API_ROUTES } from '../shared/api-routes.ts'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { randomBytes } from 'node:crypto'
import { createRequire } from 'node:module'
import { loadContracts, CONTRACTS_DIR } from '../scripts/contracts-source.mjs'

const require = createRequire(import.meta.url)
const Ajv2020 = require('ajv/dist/2020.js').default
const addFormats = require('ajv-formats').default

const arg = (name, dflt) => { const i = process.argv.indexOf(name); return i > 0 ? process.argv[i + 1] : dflt }
const flag = (name) => process.argv.includes(name)
const PORT = Number(arg('--port', process.env.LB_PORT ?? '18801'))
const TOKEN = process.env.LB_TOKEN ?? ''
const APPDATA = process.env.LB_APPDATA ?? join(dirname(fileURLToPath(import.meta.url)), '.fake-appdata')
const CALLS = arg('--calls', null)
const FAIL_BEGIN = flag('--fail-begin')
const BAD_RESPONSE = flag('--bad-response')
const FIXTURES = flag('--fixtures')
const CASE_ROOT = arg('--case-root', null)
// T13 第二次返修：任务单按线 B 的语义模拟——/api/task 每次给新编号；/api/tasks 只列已开始执行的；
// --consume-after-ms N：模拟"一条消息"在任务单写入 N 毫秒后取走该会话最新的一张（created_at 精确到秒）。不给就不取走
const CONSUME_AFTER = Number(arg('--consume-after-ms', '0')) || 0
const created = []
const taskIdNow = (d = new Date()) => { const p = (n) => String(n).padStart(2, '0'); return `T-${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}-${randomBytes(2).toString('hex')}` }
function consumeDue() {
  if (!CONSUME_AFTER) return
  for (const session of new Set(created.map((c) => c.session_id))) {
    const pending = created.filter((c) => c.session_id === session && !c.started)
    if (!pending.length) continue
    const maxSec = Math.max(...pending.map((c) => Math.floor(c.at / 1000)))
    const latest = pending.filter((c) => Math.floor(c.at / 1000) === maxSec).at(-1)
    if (Date.now() - latest.at >= CONSUME_AFTER) latest.started = true
  }
}
const FAIL_API = new Set((arg('--fail-api', '') ?? '').split(',').filter(Boolean))
const FIXTURE_DIR = join(dirname(fileURLToPath(import.meta.url)), '..', 'ui', 'fixtures')
if (PORT < 18801 || PORT > 18809) throw new Error('假服务端口限 18801–18809')
if (TOKEN.length < 16) throw new Error('需要环境变量 LB_TOKEN（至少 16 位）')

const { version, schemas } = loadContracts()
const ajv = new Ajv2020({ strict: false, allErrors: true })
addFormats(ajv)
for (const s of Object.values(schemas)) ajv.addSchema(s)
const check = (id, def, value) => {
  const fn = ajv.getSchema(`lawbench://contracts/${id}.schema.json#/$defs/${def}`)
  if (!fn) return [`契约缺 ${id}#${def}`]
  return fn(value) ? [] : fn.errors.map((e) => `${e.instancePath || '/'} ${e.message}`)
}
const example = (name) => JSON.parse(readFileSync(join(CONTRACTS_DIR, 'examples', name), 'utf8'))

// 工具样例：有官方样例的用样例；T23/T24 的三个工具按工单返回 SERVICE_UNAVAILABLE；其余没有样例的如实返回 INTERNAL
const TOOL_RESULTS = {
  case_list_materials: () => example('tool_list.result.json'),
  case_read_material: () => example('tool_read.result.json'),
}
const LATER = new Set(['case_calc_sentence', 'case_archive_match', 'case_save_archive_plan'])
export const MISSING_EXAMPLES = ['core_tool（各工具返回，除 case_list_materials、case_read_material）', 'core_progress.res', 'core_task_end.res', 'core_context.req']

const fail = (code, message) => ({ ok: false, error: { code, message } })
const ok = (value) => ({ ok: true, value })
const taskId = () => {
  const d = new Date(); const p = (n) => String(n).padStart(2, '0')
  return `T-${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}-${randomBytes(2).toString('hex')}`
}
const tasks = new Map()

const END_STATUS = { completed: 'completed', aborted: 'cancelled', interrupted: 'interrupted', blocked: 'failed', error: 'failed', 'max-tokens': 'output_limit', budget: 'budget_stopped' }

function handle(method, path, body) {
  switch (`${method} ${path}`) {
    case 'POST /core/task/begin': {
      const v = check('core/task_begin', 'request', body); if (v.length) return [fail('INVALID_ARGUMENT', '请求参数有误'), v]
      if (FAIL_BEGIN) return [fail('CASE_NOT_FOUND', '找不到该案件，请重新打开')]
      const res = example('core_task_begin.res.json'); res.value.task_id = taskId()
      tasks.set(res.value.task_id, { tools: 0 })
      return [res]
    }
    case 'POST /core/context': {
      const v = check('core/context', 'request', body); if (v.length) return [fail('INVALID_ARGUMENT', '请求参数有误'), v]
      if (!tasks.has(body.task_id) && !BAD_RESPONSE) return [fail('TASK_NOT_FOUND', '找不到该任务')]
      return [example('core_context.res.json')]
    }
    case 'POST /core/tool': {
      const v = check('core/tool', 'request', body); if (v.length) return [fail('INVALID_ARGUMENT', '请求参数有误'), v]
      if (!tasks.has(body.task_id) && !BAD_RESPONSE) return [fail('TASK_NOT_FOUND', '找不到该任务')]
      const va = check(`tools/${body.tool}`, 'args', body.args); if (va.length) return [fail('INVALID_ARGUMENT', '请求参数有误'), va]
      if (LATER.has(body.tool)) return [fail('SERVICE_UNAVAILABLE', '工作台服务未启动，请稍后重试')]
      const make = TOOL_RESULTS[body.tool]
      if (!make) return [fail('INTERNAL', '内部错误，请重试；多次出现请联系技术支持'), [`假服务没有 ${body.tool} 的样例`]]
      return [ok(make())]
    }
    case 'POST /core/progress': {
      const v = check('core/progress', 'request', body); if (v.length) return [fail('INVALID_ARGUMENT', '请求参数有误'), v]
      return [ok({})]
    }
    case 'POST /core/task/end': {
      const v = check('core/task_end', 'request', body); if (v.length) return [fail('INVALID_ARGUMENT', '请求参数有误'), v]
      return [ok({ status: END_STATUS[body.reason] })]
    }
    case 'GET /api/settings': {
      const f = join(APPDATA, 'settings.json')
      return [ok(existsSync(f) ? JSON.parse(readFileSync(f, 'utf8')) : example('file_settings.json'))]
    }
    case 'PUT /api/settings': {
      const v = check('api/settings', 'request', body); if (v.length) return [fail('INVALID_ARGUMENT', '请求参数有误'), v]
      mkdirSync(APPDATA, { recursive: true })
      writeFileSync(join(APPDATA, 'settings.json'), JSON.stringify(body, null, 2), 'utf8')
      return [ok(body)]
    }
    case 'POST /api/connection/test': {
      const v = check('api/connection_test', 'request', body); if (v.length) return [fail('INVALID_ARGUMENT', '请求参数有误'), v]
      // 已保存的地址里含 .invalid（保留域名，永不解析）就当连不上，供测试"测试失败时恢复"用
      const f = join(APPDATA, 'settings.json')
      const servers = existsSync(f) ? JSON.parse(readFileSync(f, 'utf8')).servers : {}
      const url = body.server === 'llm' ? servers.llm_base_url : servers.prep_base_url
      if (typeof url === 'string' && url.includes('.invalid')) {
        return [ok({ reachable: false, key_valid: null, latency_ms: null, route: null, message: '无法连接服务器，请检查网络' })]
      }
      return [ok({ reachable: true, key_valid: body.server === 'llm' ? true : null, latency_ms: 12, route: 'primary', message: '连接正常（假服务）' })]
    }
    default:
      return null
  }
}

// T13 --fixtures：按路由表匹配方法和路径，校验请求后回答 ui/fixtures 里的假数据
const ROUTE_RE = API_ROUTES.map((r) => ({ r, re: new RegExp('^' + r.path.replace(/\{(\w+)\}/g, '(?<$1>[^/]+)') + '$') }))
const fixture = (name) => JSON.parse(readFileSync(join(FIXTURE_DIR, name), 'utf8'))
function fromFixtures(method, path, query, body) {
  const hit = ROUTE_RE.map(({ r, re }) => ({ r, m: re.exec(path) })).find(({ r, m }) => m && r.http === method)
  if (!hit) return null
  const { r, m } = hit
  const params = Object.fromEntries(Object.entries(m.groups ?? {}).map(([k, v]) => [k, decodeURIComponent(v)]))
  const request = method === 'GET' ? { ...Object.fromEntries(query), ...params } : { ...(body ?? {}), ...params }
  if (!r.noRequest) {
    const v = check(`api/${r.contract}`, 'request', request); if (v.length) return [fail('INVALID_ARGUMENT', '请求参数有误'), v]
  }
  if (FAIL_API.has(r.contract)) return [fixture(`${r.contract}.fail.json`)]
  const saved = join(APPDATA, 'capsules.json')
  if (r.method === 'getCapsules' && existsSync(saved)) return [ok(JSON.parse(readFileSync(saved, 'utf8')))]
  if (r.method === 'putCapsules') {
    mkdirSync(APPDATA, { recursive: true })
    writeFileSync(saved, JSON.stringify(request, null, 2), 'utf8')
    return [ok(request)]
  }
  if (r.method === 'capsulesReset') rmSync(saved, { force: true })
  if (r.method === 'taskCreate') {
    const t = { task_id: taskIdNow(), session_id: request.session_id, skill: request.skill, at: Date.now(), started: false }
    created.push(t)
    return [ok({ task_id: t.task_id })]
  }
  if (r.method === 'tasksList') {
    consumeDue()
    const base = fixture('tasks_list.json')
    const mine = created.filter((c) => c.started).map((c) => ({ task_id: c.task_id, skill: c.skill, status: 'running', drafts: [], citation_passed: null, finished_at: null }))
    // 假数据里那张运行中的任务编号与 task_create 假数据相同，去掉，免得界面误判为"刚写的被取走了"
    const fixed = base.value.tasks.filter((t) => t.task_id !== fixture('task_create.json').value.task_id)
    return [ok({ tasks: [...mine, ...fixed] })]
  }
  if (!existsSync(join(FIXTURE_DIR, `${r.contract}.json`))) return [fail('INTERNAL', '内部错误，请重试；多次出现请联系技术支持'), [`没有 ${r.contract} 的假数据`]]
  const out = fixture(`${r.contract}.json`)
  if (CASE_ROOT && r.method === 'caseRecent' && out.ok && out.value.cases[0]) out.value.cases[0].root = CASE_ROOT
  return [out]
}

const RESPONSE_SCHEMA = { '/core/task/begin': 'core/task_begin', '/core/context': 'core/context', '/core/tool': 'core/tool', '/core/progress': 'core/progress', '/core/task/end': 'core/task_end', '/api/connection/test': 'api/connection_test' }

createServer((req, res) => {
  const t0 = Date.now()
  const url = new URL(req.url, 'http://127.0.0.1')
  const send = (status, obj) => {
    res.writeHead(status, { 'content-type': 'application/json; charset=utf-8' })
    res.end(obj === undefined ? '' : JSON.stringify(obj))
    const rec = { ts: new Date().toISOString(), method: req.method, path: url.pathname, status, ms: Date.now() - t0 }
    if (CALLS) appendFileSync(CALLS, JSON.stringify({ ...rec, ...(res.meta ?? {}) }) + '\n')
    process.stdout.write(`${rec.method} ${rec.path} ${status} ${rec.ms}ms${res.meta?.violations ? ' 契约不符:' + res.meta.violations.join('; ') : ''}\n`)
  }
  if (req.method === 'GET' && url.pathname === '/health') return send(200, { status: 'ok', contract_version: version })
  if (req.headers.authorization !== `Bearer ${TOKEN}`) return send(401)
  let raw = ''
  req.on('data', (c) => { raw += c })
  req.on('end', () => {
    let body
    try { body = raw ? JSON.parse(raw) : undefined } catch { return send(200, fail('INVALID_ARGUMENT', '请求参数有误')) }
    const out = handle(req.method, url.pathname, body) ?? (FIXTURES ? fromFixtures(req.method, url.pathname, url.searchParams, body) : null)
    if (!out) return send(404, fail('INVALID_ARGUMENT', '请求参数有误'))
    let [payload, violations] = out
    if (BAD_RESPONSE && payload.ok) {
      // 去掉一个必填字段：/core/tool 去掉工具结果里的第一个字段；其他命令在 value 里塞一个契约没有的字段或删字段
      const v = structuredClone(payload.value)
      const firstKey = v && typeof v === 'object' ? Object.keys(v)[0] : undefined
      if (firstKey) delete v[firstKey]; else payload = { ...payload, unexpected: true }
      payload = { ...payload, value: v }
    }
    const route = ROUTE_RE.find(({ r, re }) => r.http === req.method && re.test(url.pathname))?.r
    const rs = RESPONSE_SCHEMA[url.pathname] ?? (route ? `api/${route.contract}` : undefined)
    const selfCheck = rs ? check(rs, 'response', payload) : []
    res.meta = {
      tool: body?.tool, ok: payload.ok, code: payload.ok ? undefined : payload.error.code,
      ...(violations?.length ? { violations } : {}), ...(selfCheck.length ? { response_violations: selfCheck } : {}),
    }
    send(200, payload)
  })
}).listen(PORT, '127.0.0.1', () => process.stdout.write(`fake service on 127.0.0.1:${PORT} contract ${version}\n`))
