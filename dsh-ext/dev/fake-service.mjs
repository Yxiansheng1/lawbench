// 开发期本机假工作台服务（T7 步骤 6）：只监听 127.0.0.1，按契约校验每个请求，按样例回答。
// 不属于产品。T3/T8 合并后换真服务复测。
// 用法：node dev/fake-service.mjs --port 18801  （令牌取环境变量 LB_TOKEN；应用数据目录取 LB_APPDATA）
// 另支持：--fail-begin（task/begin 返回 CASE_NOT_FOUND）、--calls <jsonl>（记录每次调用的元数据）、
//   --bad-response（成功返回的内容故意不合契约：/core/* 少字段、工具结果少字段，用来测插件的返回校验）、
//   --fixtures（T13：其余 /api/* 按 ui/fixtures/<契约>.json 回答，供界面开发和截图；胶囊配置存在 LB_APPDATA 里，重启后保持）、
//   --fail-api <契约,…>（T13：这些接口改回 ui/fixtures/<契约>.fail.json，截错误提示用）、
//   --fail-context <错误码>（/core/context 一律返回这个错误，如 INPUT_CHANGED：测输入材料变化后整轮被拦下的提示）、
//   --case-root <目录>（T13：假数据里第一个案件的文件夹改成这个真实存在的空目录，桌面端才能把它当工作区打开）
//   T26：发票整理与委托材料两条接口见 dev/fake-tools.mjs（--invoice-delay、--invoice-blocked、--retainer-python、--retainer-stop-stuck）
//   --llm-reply <文件>（T17：在本机转发端口 LB_FORWARD_PORT 上假扮模型网关，POST /v1/chat/completions 以流式返回这个文件的内容，
//     让 DSH 用真实的 Markdown 渲染一段回答；只监听 127.0.0.1，不连外网）
//   --llm-draft（令 1321：与 --llm-reply 同用。每轮第一次请求先流式返回一次 case_save_draft 工具调用，工具结果回来后再返回
//     --llm-reply 的内容；case_save_draft 记成该任务的草稿，/api/tasks 列出、/api/outputs/confirm 后 /api/outputs 列出——
//     看聊天里的草稿卡片 / 成果卡片用）
import { createServer } from 'node:http'
import { readFileSync, writeFileSync, existsSync, mkdirSync, appendFileSync, rmSync } from 'node:fs'
import { API_ROUTES } from '../shared/api-routes.ts'
import { basename, join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { randomBytes } from 'node:crypto'
import { createRequire } from 'node:module'
import { loadContracts, CONTRACTS_DIR } from '../scripts/contracts-source.mjs'
import { makeTools } from './fake-tools.mjs'

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
const FAIL_CONTEXT = arg('--fail-context', null)
const BAD_RESPONSE = flag('--bad-response')
const FIXTURES = flag('--fixtures')
// 真服务按案件编号去重：律师在新位置打开（/api/case/open）之后，最近案件只列新位置（T17 第五轮复核的证据缺口）。
// 这里模拟：给了 --case-root 时，打开的路径若与它同名（复制、搬家后的同一案件），之后第一个案件就报打开的那个路径。
let CASE_ROOT = arg('--case-root', null)
// --case-root-file <文件>：每次请求都从这个文件读第一个案件的位置（桌面端复测时手动切换"服务现在只列哪个位置"）
const CASE_ROOT_FILE = arg('--case-root-file', null)
// 契约 1.2（N37）：任务单按"管到律师改掉为止"模拟——/api/task 设置该会话当前的选择（新的顶掉旧的）；
// /api/task/current 读回；/core/task/begin 按当前选择复制一份新建执行中的任务，当前选择不消耗、不删除；
// /api/tasks 只列已开始执行的。--fail-task-create：写选择一律返回 SERVICE_UNAVAILABLE（测"写入失败保留下拉框"）
const FAIL_TASK_CREATE = flag('--fail-task-create')
const selections = new Map() // session_id → { task_id, entry, skill, inputs, params, updated_at }
const started = [] // 已开始执行的：{ task_id, skill, status?, drafts? }
const LLM_DRAFT = flag('--llm-draft')
const confirmed = [] // --llm-draft：确认保存过的成果
const taskIdNow = (d = new Date()) => { const p = (n) => String(n).padStart(2, '0'); return `T-${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}-${randomBytes(2).toString('hex')}` }
const isoNow = () => { const d = new Date(); const off = -d.getTimezoneOffset(); const p = (n) => String(Math.abs(n)).padStart(2, '0'); return new Date(d.getTime() + off * 60000).toISOString().slice(0, 19) + (off >= 0 ? '+' : '-') + p(Math.trunc(off / 60)) + ':' + p(off % 60) }
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
const savedSettings = () => { const f = join(APPDATA, 'settings.json'); return existsSync(f) ? JSON.parse(readFileSync(f, 'utf8')) : example('file_settings.json') }
const tools = makeTools({ arg, flag, check, fail: (code, message) => ({ ok: false, error: { code, message } }), ok: (value) => ({ ok: true, value }), settings: savedSettings })
for (const sig of ['SIGINT', 'SIGTERM', 'exit']) process.on(sig, () => { tools.close(); if (sig !== 'exit') process.exit(0) })

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
      // 1.2：按该会话当前的选择新建（复制一份），当前选择留着
      const sel = selections.get(body.session_id)
      started.push({ task_id: res.value.task_id, skill: sel?.skill ?? null })
      return [res]
    }
    case 'POST /core/context': {
      const v = check('core/context', 'request', body); if (v.length) return [fail('INVALID_ARGUMENT', '请求参数有误'), v]
      if (!tasks.has(body.task_id) && !BAD_RESPONSE) return [fail('TASK_NOT_FOUND', '找不到该任务')]
      if (FAIL_CONTEXT) return [fail(FAIL_CONTEXT, '输入材料已变化，请重新选择')]
      return [example('core_context.res.json')]
    }
    case 'POST /core/tool': {
      const v = check('core/tool', 'request', body); if (v.length) return [fail('INVALID_ARGUMENT', '请求参数有误'), v]
      if (!tasks.has(body.task_id) && !BAD_RESPONSE) return [fail('TASK_NOT_FOUND', '找不到该任务')]
      const va = check(`tools/${body.tool}`, 'args', body.args); if (va.length) return [fail('INVALID_ARGUMENT', '请求参数有误'), va]
      if (LATER.has(body.tool)) return [fail('SERVICE_UNAVAILABLE', '工作台服务未启动，请稍后重试')]
      if (LLM_DRAFT && body.tool === 'case_save_draft') {
        // 令 1321：记成该任务的草稿（路径同真服务：<任务目录>/草稿/<标题>-v<版本>.md）
        const t = started.find((x) => x.task_id === body.task_id)
        const title = String(body.args.title)
        const version = (t?.drafts ?? []).filter((d) => d.title === title).length + 1
        const path = `工作区/任务/${body.task_id}/草稿/${title}-v${version}.md`
        if (t) t.drafts = [...(t.drafts ?? []), { title, path, version }]
        const coverage = { total: 3, fully_read: ['借款合同（虚构）.pdf'], partially_read: [{ name: '银行流水（虚构）.pdf', read_units: 4, total_units: 12 }], not_read: [], unreadable: [{ name: '收条扫描件（虚构）.pdf', reason: '还没识别，读不到文字，请先提交识别' }] }
        const citation_check = { passed: false, problems: [{ class: 'B', severity: 'must_fix', excerpt: '借款本金 50 万元', citation: '〔借款合同（虚构） 第1页〕', message: '原文是 30 万元' }], stats: { citations: 5, must_fix: 1, hints: 0 } }
        return [ok({ path, version, citation_check, coverage, not_fully_read: ['银行流水（虚构）.pdf', '收条扫描件（虚构）.pdf'] })]
      }
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
      const t = started.find((x) => x.task_id === body.task_id)
      if (t) t.status = END_STATUS[body.reason]
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
    if (FAIL_TASK_CREATE) return [fail('SERVICE_UNAVAILABLE', '工作台服务未启动，请稍后重试')]
    const t = { task_id: taskIdNow(), entry: request.entry, skill: request.skill, inputs: request.inputs, params: request.params, updated_at: isoNow() }
    selections.set(request.session_id, t) // 新的顶掉旧的
    return [ok({ task_id: t.task_id })]
  }
  if (r.method === 'taskCurrent') {
    const sel = selections.get(request.session_id)
    // entry、skill 都为 null 的自由对话选择也原样返回；从没设置过返回 null
    return [ok({ selection: sel ?? null })]
  }
  if (r.method === 'tasksList') {
    const base = fixture('tasks_list.json')
    const mine = started.map((c) => ({ task_id: c.task_id, skill: c.skill, status: c.status ?? 'running', drafts: c.drafts ?? [], citation_passed: null, finished_at: c.status ? isoNow() : null, coverage: null, citation_check: null }))
    return [ok({ tasks: [...mine, ...base.value.tasks] })]
  }
  if (LLM_DRAFT && r.method === 'outputsConfirm') {
    // 令 1321：确认保存——记下成果，/api/outputs 里列出（文件不真生成）
    const t = started.find((x) => x.task_id === request.task_id)
    const d = t?.drafts?.find((x) => x.path === request.draft)
    if (!d) return [fail('INVALID_ARGUMENT', '请求参数有误')]
    // 成果版本与真服务同口径（service\lawbench\export\outputs.py _next_version）：按案件同标题（不分大小写）已有的最大版本 + 1，与草稿版本无关
    const all = [...confirmed, ...fixture('outputs_list.json').value.outputs]
    const version = Math.max(0, ...all.filter((o) => o.title.toLowerCase() === d.title.toLowerCase()).map((o) => o.version)) + 1
    const files = (request.formats ?? ['docx']).map((f) => ({ format: f, path: `成果/${d.title}-v${version}.${f}` }))
    confirmed.unshift({ title: d.title, version, files, task_id: t.task_id, inputs: [], citation_passed: false, confirmed_at: isoNow() })
    return [ok({ outputs: files.map((f) => ({ ...f, version })) })]
  }
  if (LLM_DRAFT && r.method === 'outputsList') {
    const base = fixture('outputs_list.json')
    return [ok({ ...base.value, outputs: [...confirmed, ...base.value.outputs] })]
  }
  if (!existsSync(join(FIXTURE_DIR, `${r.contract}.json`))) return [fail('INTERNAL', '内部错误，请重试；多次出现请联系技术支持'), [`没有 ${r.contract} 的假数据`]]
  const out = fixture(`${r.contract}.json`)
  if (CASE_ROOT_FILE && existsSync(CASE_ROOT_FILE)) CASE_ROOT = readFileSync(CASE_ROOT_FILE, 'utf8').trim() || CASE_ROOT
  if (CASE_ROOT && r.method === 'caseOpen' && typeof request?.path === 'string' && basename(request.path) === basename(CASE_ROOT)) CASE_ROOT = request.path
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
    void Promise.resolve(tools.handle(req.method, url.pathname, body) ?? handle(req.method, url.pathname, body) ?? (FIXTURES ? fromFixtures(req.method, url.pathname, url.searchParams, body) : null)).then((out) => {
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
  })
}).listen(PORT, '127.0.0.1', () => process.stdout.write(`fake service on 127.0.0.1:${PORT} contract ${version}\n`))

// T17 --llm-reply：假模型网关（OpenAI 兼容的流式 chat/completions），回答固定为文件内容
const LLM_REPLY = arg('--llm-reply', null)
if (LLM_REPLY) {
  const FORWARD = Number(process.env.LB_FORWARD_PORT ?? '18765')
  createServer((req, res) => {
    let body = ''
    req.on('data', (c) => { body += c })
    req.on('end', () => {
      if (req.method !== 'POST' || !req.url.endsWith('/chat/completions')) { res.writeHead(404); res.end(); return }
      const text = readFileSync(LLM_REPLY, 'utf8')
      const id = 'chatcmpl-fake'
      const chunk = (delta, finish = null) => `data: ${JSON.stringify({ id, object: 'chat.completion.chunk', created: Math.floor(Date.now() / 1000), model: 'qwen38-27b', choices: [{ index: 0, delta, finish_reason: finish }] })}\n\n`
      res.writeHead(200, { 'content-type': 'text/event-stream', 'cache-control': 'no-cache' })
      res.write(chunk({ role: 'assistant', content: '' }))
      // 令 1321 --llm-draft：这一轮还没有工具结果时，先调一次 case_save_draft
      let messages = []
      try { messages = JSON.parse(body).messages ?? [] } catch { /* 读不出就当没有 */ }
      const lastUser = messages.map((m) => m.role).lastIndexOf('user')
      if (LLM_DRAFT && !messages.slice(lastUser + 1).some((m) => m.role === 'tool')) {
        const args = JSON.stringify({ title: '借款合同审查意见', content: '# 借款合同审查意见（虚构）\n\n- 借款本金 50 万元〔借款合同（虚构） 第1页〕\n' })
        res.write(chunk({ tool_calls: [{ index: 0, id: `call_draft_${Date.now()}`, type: 'function', function: { name: 'case_save_draft', arguments: args } }] }))
        res.write(chunk({}, 'tool_calls'))
        res.write(`data: ${JSON.stringify({ id, object: 'chat.completion.chunk', created: Math.floor(Date.now() / 1000), model: 'qwen38-27b', choices: [], usage: { prompt_tokens: 10, completion_tokens: 10, total_tokens: 20 } })}\n\n`)
        res.end('data: [DONE]\n\n')
        return
      }
      for (let i = 0; i < text.length; i += 40) res.write(chunk({ content: text.slice(i, i + 40) }))
      res.write(chunk({}, 'stop'))
      res.write(`data: ${JSON.stringify({ id, object: 'chat.completion.chunk', created: Math.floor(Date.now() / 1000), model: 'qwen38-27b', choices: [], usage: { prompt_tokens: 10, completion_tokens: 10, total_tokens: 20 } })}\n\n`)
      res.end('data: [DONE]\n\n')
    })
  }).listen(FORWARD, '127.0.0.1', () => process.stdout.write(`fake llm on 127.0.0.1:${FORWARD}\n`))
}
