// T13 执行令 Q6、Q3②、Q4：Host 的 /api 调用层、粘贴截图导入、Skill 列表。
import { existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { createServer, type IncomingMessage, type Server } from 'node:http'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { requestJson, RequestTimeout } from '../host/http-json.ts'
import { cleanPasteDir, LawbenchRemote, PASTE_TARGET, pasteDir, type ApiResult } from '../host/index.ts'
import { API_ROUTES } from '../shared/api-routes.ts'
import { listSkills, parseSkill } from '../host/skills.ts'
import type { Supervisor } from '../host/supervisor.ts'

const CASE = '3f2b9c1e-7a4d-4e8b-9c2a-1b5d6e7f8a90'
const JOB = 'J-20260930120000-ab12'
const TASK = 'P-20260930120000-cd34'
const PNG = Buffer.from('89504e470d0a1a0a0000000d4948445200000001000000010806000000', 'hex')

type Seen = { method: string; url: string; auth?: string; body: unknown; files?: string[] }
let server: Server
let port = 0
let seen: Seen[] = []
let reply: (s: Seen) => unknown = () => ({ ok: true, value: {} })
/** 回响应头之前等多久（模拟服务等引擎跑完才回头部）。 */
let delayMs = 0
/** 回答的状态码（测 3xx）；连接被对方断开的次数（测超时后 Host 关掉请求）。 */
let status = 200
let closedEarly = 0

async function readBody(req: IncomingMessage): Promise<unknown> {
  const chunks: Buffer[] = []
  for await (const c of req) chunks.push(c as Buffer)
  const s = Buffer.concat(chunks).toString('utf8')
  return s ? JSON.parse(s) : undefined
}

beforeAll(async () => {
  server = createServer(async (req, res) => {
    const s: Seen = { method: req.method!, url: req.url!, auth: req.headers.authorization, body: await readBody(req) }
    // 导入时记下临时文件当时是否存在（验证"导入时文件在，导入后删掉"）
    const paths = (s.body as { paths?: string[] } | undefined)?.paths
    if (paths) s.files = paths.filter((p) => existsSync(p))
    seen.push(s)
    const out = reply(s)
    let gone = false
    res.on('close', () => { if (!res.writableFinished) { gone = true; closedEarly++ } })
    if (delayMs) await new Promise((r) => setTimeout(r, delayMs))
    if (gone) return
    res.writeHead(status, { 'content-type': 'application/json', ...(status >= 300 && status < 400 ? { location: 'http://127.0.0.1:1/elsewhere' } : {}) })
    res.end(typeof out === 'string' ? out : JSON.stringify(out))
  })
  await new Promise<void>((r) => server.listen(0, '127.0.0.1', () => r()))
  port = (server.address() as { port: number }).port
})
afterAll(() => new Promise<void>((r) => server.close(() => r())))
beforeEach(() => { seen = []; reply = () => ({ ok: true, value: {} }); delayMs = 0; status = 200; closedEarly = 0 })

const up = () => ({ endpoint: () => ({ port, token: 'tok-test' }), state: 'running' }) as unknown as Supervisor
const down = () => ({ endpoint: () => undefined, state: 'starting' }) as unknown as Supervisor
const call = (r: LawbenchRemote, method: string, req?: unknown) => (r as unknown as Record<string, (x: unknown) => Promise<ApiResult>>)[method]!(req)

describe('Host /api 调用层', () => {
  let appData: string
  beforeEach(() => { appData = mkdtempSync(join(tmpdir(), 'lb-host-api-')) })
  afterEach(() => rmSync(appData, { recursive: true, force: true }))

  it('路由表里每个方法都在 LawbenchRemote 上', () => {
    const r = new LawbenchRemote(up(), appData, () => undefined)
    for (const { method } of API_ROUTES) expect(typeof (r as unknown as Record<string, unknown>)[method], method).toBe('function')
  })

  it('GET 的请求字段放进查询串，带令牌', async () => {
    reply = () => ({ ok: true, value: { materials: [] } })
    const r = new LawbenchRemote(up(), appData, () => undefined)
    const out = await call(r, 'materialsList', { case_id: CASE })
    expect(out).toEqual({ ok: true, value: { materials: [] } })
    expect(seen).toHaveLength(1)
    expect(seen[0]!.method).toBe('GET')
    expect(seen[0]!.url).toBe(`/api/materials?case_id=${CASE}`)
    expect(seen[0]!.auth).toBe('Bearer tok-test')
  })

  it('路径参数从 request 里取出，不再放进请求体', async () => {
    reply = () => ({ ok: true, value: { job_id: JOB, status: 'cancelled' } })
    const r = new LawbenchRemote(up(), appData, () => undefined)
    expect((await call(r, 'ocrCancel', { job_id: JOB })).ok).toBe(true)
    expect(seen[0]!.url).toBe(`/api/ocr/jobs/${JOB}/cancel`)
    expect(seen[0]!.body).toEqual({})
    reply = () => ({ ok: true, value: {} })
    expect((await call(r, 'pipelineCancel', { task_id: TASK })).ok).toBe(true)
    expect(seen[1]!.url).toBe(`/api/pipeline/${TASK}/cancel`)
  })

  it('请求不合契约：不发请求，返回 INVALID_ARGUMENT', async () => {
    const r = new LawbenchRemote(up(), appData, () => undefined)
    for (const bad of [undefined, null, [], 'x', { case_id: 'not-a-uuid' }, { case_id: CASE, extra: 1 }]) {
      const out = await call(r, 'materialsList', bad)
      expect(out.ok).toBe(false)
      expect(!out.ok && out.error.code).toBe('INVALID_ARGUMENT')
    }
    expect(seen).toHaveLength(0)
  })

  it('wiki 建议的 POST 必须带 id 和 accept（GET、POST 共用一份 request 契约）', async () => {
    const r = new LawbenchRemote(up(), appData, () => undefined)
    const out = await call(r, 'postWikiSuggestions', { case_id: CASE })
    expect(!out.ok && out.error.code).toBe('INVALID_ARGUMENT')
    expect(seen).toHaveLength(0)
    reply = () => ({ ok: true, value: { suggestions: [] } })
    expect((await call(r, 'postWikiSuggestions', { case_id: CASE, id: 'S0001', accept: true })).ok).toBe(true)
    expect(seen[0]!.url).toBe('/api/wiki/suggestions/S0001')
    expect(seen[0]!.body).toEqual({ case_id: CASE, accept: true })
  })

  it('GET 胶囊配置不带请求参数', async () => {
    reply = () => '{"ok": false, "error": {"code": "INTERNAL", "message": "内部错误"}}'
    const r = new LawbenchRemote(up(), appData, () => undefined)
    await call(r, 'getCapsules', { anything: 1 })
    expect(seen[0]!.url).toBe('/api/capsules')
    expect(seen[0]!.body).toBeUndefined()
  })

  it('服务返回的失败原样带回错误码和中文提示', async () => {
    reply = () => ({ ok: false, error: { code: 'CASE_IN_SYNC_FOLDER', message: '案件文件夹在云同步目录里，请换到本机文件夹' } })
    const r = new LawbenchRemote(up(), appData, () => undefined)
    expect(await call(r, 'caseOpen', { path: 'D:\\案件\\示例', template: null })).toEqual(
      { ok: false, error: { code: 'CASE_IN_SYNC_FOLDER', message: '案件文件夹在云同步目录里，请换到本机文件夹' } })
  })

  it('返回不合契约：给 INTERNAL，日志只记方法名和错误条数', async () => {
    reply = () => ({ ok: true, value: { materials: [], 多余字段: '材料名不该进日志' } })
    const logs: unknown[] = []
    const r = new LawbenchRemote(up(), appData, () => undefined, [], (...a) => { logs.push(a) })
    const out = await call(r, 'materialsList', { case_id: CASE })
    expect(!out.ok && out.error.code).toBe('INTERNAL')
    expect(JSON.stringify(logs)).not.toContain('材料名')
    expect(JSON.stringify(logs)).not.toContain(CASE)
    expect(logs.some((l) => /"invalid":[1-9]/.test(JSON.stringify(l)))).toBe(true)
  })

  it('返回不是 JSON、服务未启动：带错误码，不抛出', async () => {
    reply = () => 'not json'
    const r = new LawbenchRemote(up(), appData, () => undefined)
    expect((await call(r, 'caseRecent', {}) as { error: { code: string } }).error.code).toBe('SERVICE_UNAVAILABLE')
    const r2 = new LawbenchRemote(down(), appData, () => undefined)
    expect((await call(r2, 'caseRecent', {}) as { error: { code: string } }).error.code).toBe('SERVICE_UNAVAILABLE')
  })
})

describe('粘贴截图导入（Q3②）', () => {
  let appData: string
  beforeEach(() => { appData = mkdtempSync(join(tmpdir(), 'lb-paste-')) })
  afterEach(() => rmSync(appData, { recursive: true, force: true }))
  const importOk = { ok: true, value: { copied: [], skipped: [], scan: { added: 0, changed: 0, removed: 0, failed: 0 } } }

  it('存到 <应用数据>\\临时\\粘贴\\ 再用绝对路径导入到 02案件材料/粘贴图片，导入后删掉临时文件', async () => {
    reply = () => importOk
    const r = new LawbenchRemote(up(), appData, () => undefined)
    await r.importPastedImage({ case_id: CASE, image_base64: PNG.toString('base64') })
    expect(seen).toHaveLength(1)
    const body = seen[0]!.body as { paths: string[]; target: string; unzip: boolean; case_id: string }
    expect(seen[0]!.url).toBe('/api/materials/import')
    expect(body.target).toBe(PASTE_TARGET)
    expect(body.unzip).toBe(false)
    expect(body.paths).toHaveLength(1)
    expect(body.paths[0]!.startsWith(pasteDir(appData))).toBe(true)
    expect(body.paths[0]!.endsWith('.png')).toBe(true)
    expect(seen[0]!.files).toEqual(body.paths) // 导入时文件在
    expect(readdirSync(pasteDir(appData))).toEqual([]) // 导入后删掉
  })

  it('导入失败也删掉临时文件，并带回错误码', async () => {
    reply = () => ({ ok: false, error: { code: 'CASE_NOT_FOUND', message: '找不到这个案件，请重新打开' } })
    const r = new LawbenchRemote(up(), appData, () => undefined)
    const out = await r.importPastedImage({ case_id: CASE, image_base64: PNG.toString('base64') })
    expect(!out.ok && out.error.code).toBe('CASE_NOT_FOUND')
    expect(readdirSync(pasteDir(appData))).toEqual([])
    const r2 = new LawbenchRemote(down(), appData, () => undefined)
    expect((await r2.importPastedImage({ case_id: CASE, image_base64: PNG.toString('base64') })).ok).toBe(false)
    expect(readdirSync(pasteDir(appData))).toEqual([])
  })

  it('不是 PNG / JPEG 的不收，也不写临时文件', async () => {
    const r = new LawbenchRemote(up(), appData, () => undefined)
    const out = await r.importPastedImage({ case_id: CASE, image_base64: Buffer.from('<svg/>').toString('base64') })
    expect(!out.ok && out.error.code).toBe('INVALID_ARGUMENT')
    expect(existsSync(pasteDir(appData))).toBe(false)
    expect(seen).toHaveLength(0)
  })

  it('启动时清理残留的临时文件', async () => {
    mkdirSync(pasteDir(appData), { recursive: true })
    writeFileSync(join(pasteDir(appData), '残留.png'), PNG)
    expect(await cleanPasteDir(appData)).toBe(1)
    expect(readdirSync(pasteDir(appData))).toEqual([])
    expect(await cleanPasteDir(join(appData, '不存在'))).toBe(0)
  })
})

describe('Skill 列表（Q4）', () => {
  const repoSkills = join(__dirname, '..', '..', 'skills')
  let admin: string
  beforeEach(() => { admin = mkdtempSync(join(tmpdir(), 'lb-skills-admin-')) })
  afterEach(() => rmSync(admin, { recursive: true, force: true }))

  const skillText = (name: string, title: string, questions = '- our_party：我方是哪一方？（可从材料中获取：是）') => [
    '---', `name: ${name}`, `title: ${title}`, 'description: 测试用。', 'mode: agent', 'kind: analysis',
    'params: {thinking: 中, window: 128K, max_tokens: 8192}', 'owner: 测试', 'inputs: [materials]', '---', '',
    '## 适用场景', '', '测试。', '', '## 输入', '', '材料。', '', '## 必问问题', '', questions, '',
    '## 处理步骤', '', '1. 读。', '', '## 输出模板', '', '无。', '', '## 自检清单', '', '- 无。', '',
  ].join('\n')

  it('仓库内置 Skill 都能读出，带中文名、参数和必问问题', async () => {
    const { skills, invalid } = await listSkills([repoSkills])
    expect(invalid).toBe(0)
    expect(skills.length).toBeGreaterThan(3)
    const review = skills.find((s) => s.name === 'contract-review')!
    expect(review.title).toBeTruthy()
    expect(review.params).toHaveProperty('thinking')
    expect(review.questions.map((q) => q.key)).toContain('our_party')
  })

  it('管理员目录在前：同名时以管理员目录为准；不合格的只计数', async () => {
    mkdirSync(join(admin, 'contract-review'))
    writeFileSync(join(admin, 'contract-review', 'SKILL.md'), skillText('contract-review', '管理员版合同审查'))
    mkdirSync(join(admin, 'broken'))
    writeFileSync(join(admin, 'broken', 'SKILL.md'), '---\nname: broken\n---\n没有六部分')
    const { skills, invalid } = await listSkills([admin, repoSkills])
    expect(skills.find((s) => s.name === 'contract-review')!.title).toBe('管理员版合同审查')
    expect(invalid).toBe(1)
  })

  it('解析：必问问题写"无"为空；格式不对、缺一节、目录名与 name 不符都不收', async () => {
    expect(parseSkill(skillText('a-b', '甲', '无'))!.questions).toEqual([])
    expect(parseSkill(skillText('a-b', '甲', '- 随便写一句'))).toBeUndefined()
    expect(parseSkill(skillText('a-b', '甲').replace('## 自检清单', '## 其他'))).toBeUndefined()
    mkdirSync(join(admin, 'dir-name'))
    writeFileSync(join(admin, 'dir-name', 'SKILL.md'), skillText('other-name', '乙'))
    expect(await listSkills([admin])).toEqual({ skills: [], invalid: 1 })
  })

  it('Host 方法 listSkills 返回 {ok, value: {skills}}', async () => {
    const r = new LawbenchRemote(up(), tmpdir(), () => undefined, [repoSkills])
    const out = await r.listSkills()
    expect(out.ok).toBe(true)
    expect(out.value.skills.length).toBeGreaterThan(3)
    expect(readFileSync).toBeDefined()
  })
})

describe('T7 沿用的三个方法也校验返回（返修 P3-3）', () => {
  const settings = JSON.parse(readFileSync(join(__dirname, '..', '..', 'contracts', 'examples', 'file_settings.json'), 'utf8'))
  const good = { reachable: true, key_valid: true, latency_ms: 12, route: 'primary', message: '连接正常' }

  it('合契约的原样返回', async () => {
    reply = (s) => ({ ok: true, value: s.url === '/api/connection/test' ? good : settings })
    const r = new LawbenchRemote(up(), tmpdir(), () => undefined)
    expect(await r.getSettings()).toEqual(settings)
    expect(await r.putSettings(settings)).toEqual(settings)
    expect(await r.testConnection('llm')).toEqual(good)
  })

  it('不合契约的抛中文错误，日志只记方法名和条数', async () => {
    const logs: unknown[] = []
    const r = new LawbenchRemote(up(), tmpdir(), () => undefined, [], (...a) => { logs.push(a) })
    reply = () => ({ ok: true, value: { ...settings, 多余: 'D:\案件\不该进日志' } })
    await expect(r.getSettings()).rejects.toThrow('不符合约定')
    await expect(r.putSettings(settings)).rejects.toThrow('不符合约定')
    reply = () => ({ ok: true, value: { reachable: 'yes' } })
    await expect(r.testConnection('prep')).rejects.toThrow('不符合约定')
    expect(JSON.stringify(logs)).not.toContain('案件')
    expect(logs.filter((l) => JSON.stringify(l).includes('"code":"INTERNAL"'))).toHaveLength(3)
  })
})

describe('粘贴截图的上限与文件名（返修 P3-4）', () => {
  let appData: string
  beforeEach(() => { appData = mkdtempSync(join(tmpdir(), 'lb-paste2-')) })
  afterEach(() => rmSync(appData, { recursive: true, force: true }))

  it('base64 超过 20 MB 对应的长度：不解码、不写临时文件、不发请求', async () => {
    const r = new LawbenchRemote(up(), appData, () => undefined)
    const huge = PNG.toString('base64') + 'A'.repeat(28 * 1024 * 1024)
    const out = await r.importPastedImage({ case_id: CASE, image_base64: huge })
    expect(!out.ok && out.error).toMatchObject({ code: 'INVALID_ARGUMENT', message: expect.stringContaining('20 MB') })
    expect(existsSync(pasteDir(appData))).toBe(false)
    expect(seen).toHaveLength(0)
  })

  it('解码后恰好超过 20 MB（长度在余量内）：同样拒收', async () => {
    const r = new LawbenchRemote(up(), appData, () => undefined)
    const bytes = Buffer.concat([PNG, Buffer.alloc(20 * 1024 * 1024 + 1 - PNG.length)])
    const out = await r.importPastedImage({ case_id: CASE, image_base64: bytes.toString('base64') })
    expect(!out.ok && out.error.code).toBe('INVALID_ARGUMENT')
    expect(seen).toHaveLength(0)
  })

  it('20 MB 以内的照常导入；临时文件名带随机标识，同一秒两次粘贴不撞名', async () => {
    reply = () => ({ ok: true, value: { copied: [], skipped: [], scan: { added: 0, changed: 0, removed: 0, failed: 0, review_needed: false } } })
    const r = new LawbenchRemote(up(), appData, () => undefined)
    await Promise.all([
      r.importPastedImage({ case_id: CASE, image_base64: PNG.toString('base64') }),
      r.importPastedImage({ case_id: CASE, image_base64: PNG.toString('base64') }),
    ])
    const names = seen.map((s) => (s.body as { paths: string[] }).paths[0]!)
    expect(names).toHaveLength(2)
    expect(new Set(names).size).toBe(2)
    for (const n of names) expect(n).toMatch(/粘贴-\d{14}-[0-9a-f-]{36}\.png$/)
    expect(seen.every((s) => s.files?.length === 1)).toBe(true)
  })
})

describe('长路由不被头部时限掐断（T26 复核 P2-1）', () => {
  let appData: string
  beforeEach(() => { appData = mkdtempSync(join(tmpdir(), 'lb-host-long-')) })
  afterEach(() => rmSync(appData, { recursive: true, force: true }))
  const VALUE = { exit_code: 0, attention: false, failed: false, output: '完成', files: [] }

  it('/api 路由不走全局 fetch（它等响应头最多 300 秒），换成没有头部时限、只有路由总时限的请求', async () => {
    const real = globalThis.fetch
    globalThis.fetch = (() => { throw new Error('不该走 fetch') }) as typeof fetch
    try {
      reply = () => ({ ok: true, value: VALUE })
      const r = new LawbenchRemote(up(), appData, () => undefined)
      expect(await call(r, 'invoiceRun', { action: 'env_check' })).toEqual({ ok: true, value: VALUE })
      expect(await call(r, 'archiveBuild', { case_id: CASE })).toMatchObject({ ok: expect.any(Boolean) })
    } finally { globalThis.fetch = real }
  })

  it('响应头迟到也等到底：只看总时限（小参数：头部迟到 1.2 秒，总时限 3 秒）', async () => {
    delayMs = 1200
    reply = () => ({ ok: true, value: VALUE })
    expect(await requestJson({ method: 'POST', port, path: '/api/invoice/run', headers: {}, body: '{}', timeoutMs: 3000 })).toEqual({ ok: true, value: VALUE })
  })

  it('超过路由总时限报 TIMEOUT', async () => {
    delayMs = 1200
    await expect(requestJson({ method: 'POST', port, path: '/x', headers: {}, timeoutMs: 300 })).rejects.toBeInstanceOf(RequestTimeout)
    const route = API_ROUTES.find((x) => x.method === 'invoiceRun')! as { timeoutMs?: number }
    const keep = route.timeoutMs
    route.timeoutMs = 300
    try {
      const r = new LawbenchRemote(up(), appData, () => undefined)
      expect(await call(r, 'invoiceRun', { action: 'env_check' })).toMatchObject({ ok: false, error: { code: 'TIMEOUT' } })
    } finally { route.timeoutMs = keep }
  })

  it('长路由（发票、归档、导入）的总时限都长于发票单个动作的 30 分钟或 10 分钟', () => {
    const t = (m: string) => API_ROUTES.find((x) => x.method === m)!.timeoutMs ?? 0
    expect(t('invoiceRun')).toBeGreaterThan(30 * 60_000)
    for (const m of ['archiveBuild', 'materialsImport', 'materialsScan', 'outputsConfirm', 'redline']) expect(t(m), m).toBeGreaterThanOrEqual(10 * 60_000)
  })

  it('服务回 302：不跟随，callApi 得 SERVICE_UNAVAILABLE（复核记录项①）', async () => {
    status = 302
    reply = () => ({ ok: true, value: VALUE })
    const r = new LawbenchRemote(up(), appData, () => undefined)
    expect(await call(r, 'invoiceRun', { action: 'env_check' })).toMatchObject({ ok: false, error: { code: 'SERVICE_UNAVAILABLE' } })
    expect(seen).toHaveLength(1)
  })

  it('超过总时限后 Host 关掉这次请求，服务端看到连接断开（复核记录项①）', async () => {
    delayMs = 1000
    await expect(requestJson({ method: 'POST', port, path: '/x', headers: {}, body: '{}', timeoutMs: 200 })).rejects.toBeInstanceOf(RequestTimeout)
    await new Promise((r) => setTimeout(r, 300))
    expect(closedEarly).toBe(1)
  })
})
