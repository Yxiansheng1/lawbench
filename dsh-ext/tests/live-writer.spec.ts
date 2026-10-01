// 活着的会话跟着案件走（T17 第五轮复核 F1；改编自复核员 B 的 zz-rvb22-agent / zz-rvb22-move，打印改为断言）：
// DSH 真 AgentLoop（假模型）+ 我方会话存储 + 我方 Host 的 caseOpen；假工作台服务按真服务语义（按案件编号去重，
// /api/case/open 之后只列新位置）。会话的事件不经句柄的 append（原版实例监听 session/event 投给自己登记的写入者），
// 所以名单变了以后由会话存储把写入者搬到新位置（Agent 空闲时；正在跑的等这一轮结束），搬不了就记为已失效。
import { createHash, randomUUID } from 'node:crypto'
import { createRequire } from 'node:module'
import { cpSync, existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, realpathSync, renameSync, rmSync, writeFileSync } from 'node:fs'
import { createServer, type Server } from 'node:http'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { CaseRoots } from '../session-store/case-roots.ts'
import { apply as applyStore, name as storeName } from '../session-store/index.ts'
import { LawbenchRemote } from '../host/index.ts'
import type { Supervisor } from '../host/supervisor.ts'

const DSH = join(__dirname, '..', '..', 'dsh')
const AL = join(DSH, 'packages', 'core', 'agent-loop')
const req = createRequire(join(AL, 'package.json'))
const imp = async (name: string) => (await import(/* @vite-ignore */ realpathSync(req.resolve(name))))
const { Context } = await imp('@deepseek-ai/cordis')
const Llm = await imp('@deepseek-ai/dsh-llm')
const SessionMod = await imp('@deepseek-ai/dsh-session')
const SystemPrompt = (await imp('@deepseek-ai/dsh-system-prompt')).default
const ToolRuntime = (await imp('@deepseek-ai/dsh-tools')).default
const AgentRegistry = (await imp('@deepseek-ai/dsh-agent')).default
const Jsonl = (await imp('@deepseek-ai/dsh-session-persistence-jsonl')).default
const AgentLoop = (await imp('@deepseek-ai/dsh-agent-loop')).default
const Projection = (await imp('@deepseek-ai/dsh-session-projection')).default
const { MockAdapter, textResponse } = await import(/* @vite-ignore */ join(AL, 'tests', 'mock-adapter.ts'))
const CASE_OPEN_OK = JSON.parse(readFileSync(join(__dirname, '..', 'ui', 'fixtures', 'case_open.json'), 'utf8'))

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))
/** 假模型：script 里的元素可写成 { delayMs, chunks }，那一次回答先等这么久（让 caseOpen 落在一轮当中）。 */
class DelayAdapter extends MockAdapter {
  private readonly delays: number[]
  constructor(script: unknown[]) {
    super(script.map((e: any) => (e && typeof e === 'object' && 'chunks' in e ? e.chunks : e)))
    this.delays = script.map((e: any) => (e && typeof e === 'object' && 'delayMs' in e ? e.delayMs : 0))
  }
  async * stream(options: any): AsyncIterable<any> {
    const ms = this.delays.shift() ?? 0
    if (ms) await sleep(ms)
    yield* super.stream(options)
  }
}

// 假工作台服务：案件编号取自 <案件>\工作区\case-id.txt（复制后两处同号，按号去重，打开哪个就只列哪个）
let reg: Array<{ case_id: string; root: string; t: number }> = []
let clock = 0
const cidOf = (root: string): string => {
  const f = join(root, '工作区', 'case-id.txt')
  if (existsSync(f)) return readFileSync(f, 'utf8')
  mkdirSync(join(root, '工作区'), { recursive: true }); const id = randomUUID(); writeFileSync(f, id); return id
}
const svcOpen = (root: string) => { const id = cidOf(root); reg = reg.filter((c) => c.case_id !== id && c.root.toLowerCase() !== root.toLowerCase()); reg.push({ case_id: id, root, t: ++clock }) }
let server: Server
let port = 0
beforeAll(async () => {
  server = createServer((q, r) => {
    r.setHeader('content-type', 'application/json')
    if (q.url === '/api/case/recent') { r.end(JSON.stringify({ ok: true, value: { cases: [...reg].sort((a, b) => b.t - a.t).map((c) => ({ case_id: c.case_id, name: 'x', root: c.root, last_opened: '2026-10-01T12:00:00+08:00', exists: existsSync(c.root) })) } })); return }
    if (q.url === '/api/case/open') { let b = ''; q.on('data', (d) => { b += d }); q.on('end', () => { svcOpen(JSON.parse(b).path); r.end(JSON.stringify(CASE_OPEN_OK)) }); return }
    r.statusCode = 404; r.end('{}')
  })
  await new Promise<void>((res) => server.listen(0, '127.0.0.1', () => res()))
  port = (server.address() as { port: number }).port
})
afterAll(async () => { server.closeAllConnections?.(); await new Promise((r) => server.close(r)) })

let tmp: string
beforeEach(() => { tmp = realpathSync(mkdtempSync(join(tmpdir(), 'lb-live-'))); reg = [] })
afterEach(() => { rmSync(tmp, { recursive: true, force: true }) })

function files(dir: string): string[] {
  if (!existsSync(dir)) return []
  return readdirSync(dir, { recursive: true, withFileTypes: true }).filter((e) => e.isFile()).map((e) => join(e.parentPath, e.name))
}
const has = (d: string, s: string) => files(d).filter((f) => readFileSync(f).includes(Buffer.from(s))).length
const hashDir = (d: string) => files(d).sort().map((f) => f.slice(d.length) + ':' + createHash('sha256').update(readFileSync(f)).digest('hex')).join('|')
const user = (text: string) => Llm.createUserMessage({ content: [{ type: 'text', text }], source: { kind: 'user' } })
const idle = (ctx: any, agent: any) => new Promise<void>((resolve) => { const off = ctx.on('agent/status', ({ agent: a, status }: any) => { if (a === agent && status === 'idle') { off(); resolve() } }) })

/** 起 DSH 真 AgentLoop + 我方会话存储；Host 的 caseOpen 走假服务。replies 是假模型依次给的回答（可带延迟）。 */
async function boot(appData: string, home: string, replies: unknown[]) {
  const ctx = new Context()
  await ctx.plugin(Llm.default); await ctx.plugin(SessionMod.default); await ctx.plugin(Projection); await ctx.plugin(SystemPrompt); await ctx.plugin(ToolRuntime); await ctx.plugin(AgentRegistry)
  ctx.provide('lawbenchCore', { endpoint: () => ({ port, token: 't' }), onState: (fn: (s: string) => void) => { fn('running'); return () => {} } })
  await ctx.plugin({ name: storeName, apply: applyStore }, { backend: Jsonl, defaultRoot: home, appData, compression: 'none' })
  await ctx.plugin(AgentLoop, { agents: [] })
  ctx.llm.registerAdapter(['mock'], new DelayAdapter(replies))
  const api = new LawbenchRemote({ endpoint: () => ({ port, token: 't' }), state: 'running' } as unknown as Supervisor, appData, () => undefined, [], () => {}, undefined,
    (n) => (n === 'sessionPersistence' ? ctx.sessionPersistence : undefined)) as LawbenchRemote & { caseOpen(r: unknown): Promise<{ ok: boolean }> }
  return { ctx, api }
}
/** 重启后读这个会话的全部事件（新进程，只有会话存储）。 */
async function readAfterRestart(appData: string, home: string, id: unknown): Promise<string> {
  const ctx2 = new Context()
  await ctx2.plugin(Llm.default); await ctx2.plugin(SessionMod.default)
  ctx2.provide('lawbenchCore', { endpoint: () => ({ port, token: 't' }), onState: (fn: (s: string) => void) => { fn('running'); return () => {} } })
  await ctx2.plugin({ name: storeName, apply: applyStore }, { backend: Jsonl, defaultRoot: home, appData, compression: 'none' })
  await sleep(300)
  await ctx2.sessionPersistence.list()
  const h = await ctx2.sessionPersistence.open(id, 'read')
  const evs = JSON.stringify((await h.read()).events)
  await h.close(); await ctx2.fiber.dispose()
  return evs
}

/** 旧位置建案件，会话 s1 说一句（FIRST），让它落盘；返回各路径与活着的 Agent。 */
async function prepare(replies: unknown[]) {
  const appData = join(tmp, 'Local', 'lawbench'); const home = join(tmp, 'dsh-home', 'sessions')
  const oldR = join(tmp, '桌面', '案丙'); const newR = join(tmp, '案件盘', '案丙')
  mkdirSync(oldR, { recursive: true }); mkdirSync(join(tmp, '案件盘'))
  const { ctx, api } = await boot(appData, home, replies)
  expect((await api.caseOpen({ path: oldR, template: null })).ok).toBe(true)
  for (let i = 0; i < 100 && !new CaseRoots(appData).load().list().includes(oldR); i++) await sleep(20)
  const id = SessionMod.SessionId('s1')
  const h = await ctx.agents.create({ sessionId: id, meta: { cwd: oldR }, agentOptions: { provider: 'mock', model: 'mock' } })
  const p = idle(ctx, h.agent); h.agent.followup(user('FIRST-LIVE')); await p
  await sleep(1500); await ctx.sessionPersistence.flush()
  expect(has(oldR, 'FIRST-LIVE')).toBe(1)
  return { appData, home, oldR, newR, ctx, api, id, h }
}

for (const how of ['copy', 'move'] as const) {
  it(`${how === 'copy' ? '复制' : '搬家'}：会话活着（Agent 还在）→ 新位置 caseOpen → 在这个会话里续写：落新文件夹，旧处不变，重启后看得到`, async () => {
    const { appData, home, oldR, newR, ctx, api, id, h } = await prepare([textResponse('a1'), textResponse('a2')])
    if (how === 'copy') cpSync(oldR, newR, { recursive: true }); else renameSync(oldR, newR)
    const oldHash = hashDir(oldR)
    expect((await api.caseOpen({ path: newR, template: null })).ok).toBe(true)
    expect(ctx.agents.get(id)).toBe(h.agent) // 还是那个活着的 Agent
    const p = idle(ctx, h.agent); h.agent.followup(user('AFTER-LIVE')); await p
    await ctx.sessionPersistence.flush()
    expect(has(newR, 'AFTER-LIVE')).toBe(1)
    expect(hashDir(oldR)).toBe(oldHash) // 复制：旧处一个字节不变；搬家：旧处本来就没有
    expect(ctx.sessionPersistence.writerLost(id)).toBe(false)
    await ctx.fiber.dispose()
    expect(await readAfterRestart(appData, home, id)).toContain('AFTER-LIVE')
  }, 40000)
}

it('复制：会话已放下（下次续写走 resume）→ 新位置 caseOpen → 续写落新文件夹', async () => {
  const { appData, home, oldR, newR, ctx, api, id, h } = await prepare([textResponse('a1'), textResponse('a2')])
  await h.dispose()
  cpSync(oldR, newR, { recursive: true })
  const oldHash = hashDir(oldR)
  expect((await api.caseOpen({ path: newR, template: null })).ok).toBe(true)
  await ctx.sessionPersistence.list()
  const agent = (await ctx.agents.resume({ resumeSessionId: id, agentOptions: { provider: 'mock', model: 'mock' } })).agent
  const p = idle(ctx, agent); agent.followup(user('AFTER-RESUME')); await p
  await ctx.sessionPersistence.flush()
  expect([has(newR, 'AFTER-RESUME'), hashDir(oldR) === oldHash]).toEqual([1, true])
  await ctx.fiber.dispose()
  expect(await readAfterRestart(appData, home, id)).toContain('AFTER-RESUME')
}, 40000)

it('关软件 → 复制 → 再开（名单还是旧位置）→ 先点开这个会话（Agent 从旧位置 resume）→ 新位置 caseOpen → 续写：落新文件夹', async () => {
  const { appData, home, oldR, newR, ctx, h, id } = await prepare([textResponse('a1')])
  await h.dispose(); await ctx.fiber.dispose()
  cpSync(oldR, newR, { recursive: true })
  const { ctx: ctx2, api } = await boot(appData, home, [textResponse('a2')])
  await sleep(300)
  await ctx2.sessionPersistence.list()
  const agent = (await ctx2.agents.resume({ resumeSessionId: id, agentOptions: { provider: 'mock', model: 'mock' } })).agent
  expect(agent.session.header.cwd).toBe(oldR) // 名单还是旧位置时 resume 的
  // resume 时（名单还是旧位置）会话已在旧处补写过事件，新位置的副本少这几条：搬的时候从旧处补齐
  expect((await api.caseOpen({ path: newR, template: null })).ok).toBe(true)
  expect(ctx2.sessionPersistence.writerLost(id)).toBe(false)
  const oldHash = hashDir(oldR)
  const p = idle(ctx2, agent); agent.followup(user('AFTER-REOPEN')); await p
  await ctx2.sessionPersistence.flush()
  expect([has(newR, 'AFTER-REOPEN'), has(oldR, 'AFTER-REOPEN'), hashDir(oldR) === oldHash]).toEqual([1, 0, true])
  await ctx2.fiber.dispose()
}, 40000)

it('复制时会话正在跑一轮：不打断，等这一轮结束再搬；这一轮落在旧处，搬的时候补到新位置；之后只写新位置', async () => {
  // 第二句的回答慢 1.5 秒：caseOpen 发生在这一轮当中
  const slow = { chunks: textResponse('a2'), delayMs: 1500 }
  const { ctx, api, oldR, newR, id, h } = await prepare([textResponse('a1'), slow, textResponse('a3')])
  cpSync(oldR, newR, { recursive: true })
  const p = idle(ctx, h.agent); h.agent.followup(user('DURING-RUN'))
  await sleep(200)
  expect(h.agent.status).toBe('running')
  expect((await api.caseOpen({ path: newR, template: null })).ok).toBe(true)
  expect(has(newR, 'DURING-RUN')).toBe(0) // 正在跑：还没搬
  await p
  for (let i = 0; i < 100 && has(newR, 'DURING-RUN') === 0; i++) await sleep(20)
  expect([has(oldR, 'DURING-RUN'), has(newR, 'DURING-RUN')]).toEqual([1, 1]) // 这一轮落在旧处，搬的时候补到新位置
  expect(ctx.sessionPersistence.writerLost(id)).toBe(false)
  const oldHash = hashDir(oldR)
  const p2 = idle(ctx, h.agent); h.agent.followup(user('AFTER-RUN')); await p2
  await ctx.sessionPersistence.flush()
  expect([has(newR, 'AFTER-RUN'), hashDir(oldR) === oldHash]).toEqual([1, true])
  await ctx.fiber.dispose()
}, 40000)

for (const sameLength of [false, true]) {
  it(`复制后新位置被另一个进程续写过（${sameLength ? '旧处也接着说过一句' : '旧处没再写'}）：两处分叉，搬不了，记为已失效，两处都不再变`, async () => {
    const { appData, home, ctx, api, oldR, newR, id, h } = await prepare([textResponse('a1'), textResponse('old-side')])
    cpSync(oldR, newR, { recursive: true })
    if (sameLength) { // 活着的会话在旧处说一句（名单还是旧位置）
      const p0 = idle(ctx, h.agent); h.agent.followup(user('OLD-SIDE')); await p0
      await ctx.sessionPersistence.flush()
    }
    // 另一个进程（名单只有新位置、不连服务）在新位置 resume 这个会话说一句：新位置与旧处分叉
    const appData2 = join(tmp, 'Local2', 'lawbench')
    new CaseRoots(appData2).replace([{ root: newR, exists: true }])
    const other = new Context()
    await other.plugin(Llm.default); await other.plugin(SessionMod.default); await other.plugin(Projection); await other.plugin(SystemPrompt); await other.plugin(ToolRuntime); await other.plugin(AgentRegistry)
    await other.plugin({ name: storeName, apply: applyStore }, { backend: Jsonl, defaultRoot: join(tmp, 'home2'), appData: appData2, compression: 'none' })
    await other.plugin(AgentLoop, { agents: [] })
    other.llm.registerAdapter(['mock'], new DelayAdapter([textResponse('new-side')]))
    await other.sessionPersistence.list()
    const a2 = (await other.agents.resume({ resumeSessionId: id, agentOptions: { provider: 'mock', model: 'mock' } })).agent
    const p1 = idle(other, a2); a2.followup(user('NEW-SIDE')); await p1
    await other.sessionPersistence.flush(); await other.fiber.dispose()
    expect([has(newR, 'NEW-SIDE'), has(oldR, 'NEW-SIDE')]).toEqual([1, 0])
    expect((await api.caseOpen({ path: newR, template: null })).ok).toBe(true)
    expect(ctx.sessionPersistence.writerLost(id)).toBe(true)
    const oldHash = hashDir(oldR); const newHash = hashDir(newR)
    // 没有 Agent 插件拦着时再说一句：哪里都不写（Agent 插件会整轮拒绝并提示，见 agent.spec）
    const p = idle(ctx, h.agent); h.agent.followup(user('AFTER-LOST')); await p
    await sleep(1200)
    expect([hashDir(oldR) === oldHash, hashDir(newR) === newHash]).toEqual([true, true])
    await ctx.fiber.dispose()
    void appData; void home
  }, 40000)
}

it('搬家后、在新位置打开之前又说了一句（旧目录已不在，这句只在内存里）：新位置比内存短，搬不了，记为已失效', async () => {
  const { ctx, api, oldR, newR, id, h } = await prepare([textResponse('a1'), textResponse('a2'), textResponse('a3')])
  renameSync(oldR, newR)
  const p0 = idle(ctx, h.agent); h.agent.followup(user('IN-BETWEEN')); await p0
  await sleep(1200)
  expect(has(newR, 'IN-BETWEEN')).toBe(0)
  expect((await api.caseOpen({ path: newR, template: null })).ok).toBe(true)
  expect(ctx.sessionPersistence.writerLost(id)).toBe(true)
  const newHash = hashDir(newR)
  const p = idle(ctx, h.agent); h.agent.followup(user('AFTER-LOST')); await p
  await sleep(1200)
  expect(hashDir(newR)).toBe(newHash)
  await ctx.fiber.dispose()
}, 40000)

it('搬家后服务还没列出新位置（律师没在新位置打开）：写入者搬不过去，记为已失效，两处都不写', async () => {
  const { ctx, api, oldR, newR, id, h } = await prepare([textResponse('a1'), textResponse('a2')])
  renameSync(oldR, newR)
  await (ctx.sessionPersistence as { refreshCaseRoots(): Promise<void> }).refreshCaseRoots() // 服务报旧位置 exists:false
  expect(ctx.sessionPersistence.writerLost(id)).toBe(true)
  const newHash = hashDir(newR)
  const p = idle(ctx, h.agent); h.agent.followup(user('NOWHERE')); await p
  await sleep(1200)
  expect(hashDir(newR)).toBe(newHash)
  expect(existsSync(oldR)).toBe(false)
  void api
  await ctx.fiber.dispose()
}, 40000)
