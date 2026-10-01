// 复制、搬家后第一次在新位置打开案件（T17 第四轮复核 B-F1、B 的 X1、X1b、X7、X10；Host 包装 A-P3-3）：
// 真 JSONL 实例 + 我方会话存储插件 + 真工作区登记（已构建的 lib）+ 我方 Host 的 LawbenchRemote（caseOpen、attachCaseSessions），
// 假工作台服务只听 127.0.0.1，按真服务语义：律师在新位置打开案件（/api/case/open）之后，/api/case/recent 才只列新位置。
// 全程不重启，断言第一次打开就挂上、续写落新文件夹、旧文件夹字节不变。
import { createHash } from 'node:crypto'
import { createRequire } from 'node:module'
import { cpSync, existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, realpathSync, renameSync, rmSync } from 'node:fs'
import { createServer, type Server } from 'node:http'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { CaseRoots } from '../session-store/case-roots.ts'
import type { Backend, Header } from '../session-store/router.ts'
import { apply as applyStore, name as storeName } from '../session-store/index.ts'
import { LawbenchRemote } from '../host/index.ts'
import type { Supervisor } from '../host/supervisor.ts'

const DSH = join(__dirname, '..', '..', 'dsh')
const JSONL_PKG = join(DSH, 'packages', 'session', 'session-persistence-jsonl')
const WS_PKG = join(DSH, 'packages', 'workspace', 'workspace')
const reqJ = createRequire(join(JSONL_PKG, 'package.json'))
const reqW = createRequire(join(WS_PKG, 'package.json'))
const cordis = (await import(/* @vite-ignore */ realpathSync(reqJ.resolve('@deepseek-ai/cordis')))) as { Context: new () => any }
const Jsonl = ((await import(/* @vite-ignore */ realpathSync(join(JSONL_PKG, 'lib', 'index.js')))) as { default: unknown }).default
const CONTRACT = join(DSH, 'packages', 'session', 'session-persistence', 'tests', 'contract.ts')
const { meta, oneTurnLog } = (await import(/* @vite-ignore */ CONTRACT)) as { meta(id: string, cwd?: string): Header; oneTurnLog(): unknown[] }
const WCordis = (await import(/* @vite-ignore */ realpathSync(reqW.resolve('@deepseek-ai/cordis')))) as { Context: new () => any }
const Storage = ((await import(/* @vite-ignore */ realpathSync(reqW.resolve('@deepseek-ai/dsh-storage')))) as { default: unknown }).default
const { DomainFacility } = (await import(/* @vite-ignore */ realpathSync(reqW.resolve('@deepseek-ai/dsh-storage-domain')))) as { DomainFacility: new (...a: unknown[]) => any }
const WorkspaceRegistry = ((await import(/* @vite-ignore */ realpathSync(join(WS_PKG, 'lib', 'index.js')))) as { default: unknown }).default
const MEMORY = join(DSH, 'packages', 'storage', 'storage-domain', 'tests', 'helpers', 'memory-backend.ts')
const { MemoryMediaPool, MemoryStorageBackend } = (await import(/* @vite-ignore */ MEMORY)) as { MemoryMediaPool: new () => unknown; MemoryStorageBackend: new (p: unknown) => unknown }
const CASE_OPEN_OK = JSON.parse(readFileSync(join(__dirname, '..', 'ui', 'fixtures', 'case_open.json'), 'utf8'))

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))
type H = { header: Header; append(e: unknown): Promise<void>; close(): Promise<void> }

// 假工作台服务：/api/case/recent 列 cases；/api/case/open 之后改成只列打开的那个位置（真服务的 registry.open 语义）
let cases: Array<{ root: string; exists: boolean }> = []
let opens = 0
/** /api/case/recent 的回答延迟（毫秒）：列表在收到请求时取，过这么久才回（第五轮复核 A-P3-1 的"途中那次"）。 */
let recentDelay = 0
/** 为 true 时 /api/case/open 不改列表（模拟服务没把打开的位置列出来，第五轮复核 F2）。 */
let openIgnored = false
let server: Server
let port = 0
beforeAll(async () => {
  server = createServer((req, res) => {
    res.setHeader('content-type', 'application/json')
    if (req.headers.authorization !== 'Bearer t') { res.statusCode = 401; res.end('{}'); return }
    if (req.url === '/api/case/recent') {
      const snapshot = cases.map((c) => ({ case_id: 'C-1', name: '虚构', last_opened: '2026-10-01T12:00:00+08:00', ...c }))
      setTimeout(() => res.end(JSON.stringify({ ok: true, value: { cases: snapshot } })), recentDelay)
      return
    }
    if (req.url === '/api/case/open' && req.method === 'POST') {
      let body = ''
      req.on('data', (d) => { body += d })
      req.on('end', () => { opens++; if (!openIgnored) cases = [{ root: JSON.parse(body).path, exists: true }]; res.end(JSON.stringify(CASE_OPEN_OK)) })
      return
    }
    res.statusCode = 404; res.end('{}')
  })
  await new Promise<void>((r) => server.listen(0, '127.0.0.1', () => r()))
  port = (server.address() as { port: number }).port
})
afterAll(async () => { server.closeAllConnections?.(); await new Promise((r) => server.close(r)) })

const core = () => ({ endpoint: () => ({ port, token: 't' }), onState: (fn: (s: string) => void) => { fn('running'); return () => {} } })
async function startStore(appData: string, home: string) {
  const ctx = new cordis.Context()
  ctx.provide('lawbenchCore', core())
  const fiber = await ctx.plugin({ name: storeName, apply: applyStore }, { backend: Jsonl, defaultRoot: home, appData, compression: 'none' })
  return { persistence: ctx.sessionPersistence as Backend & { refreshCaseRoots(): Promise<void> }, dispose: () => fiber.dispose() }
}
async function bootReg(pool: unknown, p: Backend) {
  const ctx = new WCordis.Context()
  await ctx.plugin(Storage)
  ctx.storage.backend.register('memory', new MemoryStorageBackend(pool))
  const facility = new DomainFacility(ctx, { backend: 'memory', routes: {} })
  ctx.storage.mount('domain', facility)
  ctx.provide('storageDomain', facility)
  ctx.provide('sessionPersistence', { list: () => p.list(), open: (id: string, a: 'read' | 'write') => p.open(id, a), stat: (id: string) => p.stat(id) })
  ctx.provide('sessions', { get: () => undefined, list: () => [] })
  const fiber = await ctx.plugin(WorkspaceRegistry)
  return { reg: ctx.workspaceRegistry, dispose: () => fiber.dispose() }
}
/** /api 各接口是按路由表挂到原型上的方法（类型里没有）。 */
type Api = LawbenchRemote & { caseOpen(request: unknown): Promise<{ ok: boolean }> }
/** 我方 Host 的远程接口：工作台服务指向假服务，DSH 的两个服务取自上面的会话存储与登记。 */
const remote = (p: unknown, reg: unknown, appData: string, sessions?: unknown): Api =>
  new LawbenchRemote({ endpoint: () => ({ port, token: 't' }), state: 'running' } as unknown as Supervisor, appData, () => undefined, [], () => {}, undefined,
    (name) => (name === 'sessionPersistence' ? p : name === 'workspaceRegistry' ? reg : name === 'sessions' ? sessions : undefined)) as Api
const raw = (reg: any, path: string): string[] => { const w = reg.list().find((x: any) => x.path === path); return w ? [...reg.table.get(w.id).sessionIds].sort() : ['<no ws>'] }
async function write(p: Backend, id: string, cwd: string, events = oneTurnLog()) {
  const h = (await p.create(meta(id, cwd) as never)) as unknown as H
  await h.append(events); await h.close()
}
function files(dir: string): string[] {
  if (!existsSync(dir)) return []
  return readdirSync(dir, { recursive: true, withFileTypes: true }).filter((e) => e.isFile()).map((e) => join(e.parentPath, e.name))
}
const hashDir = (d: string) => files(d).sort().map((f) => f.slice(d.length) + ':' + createHash('sha256').update(readFileSync(f)).digest('hex')).join('|')
const waitRoots = async (appData: string, want: string) => { for (let i = 0; i < 150; i++) { if (new CaseRoots(appData).load().list().includes(want)) return; await sleep(20) } }

let tmp: string
beforeEach(() => { tmp = realpathSync(mkdtempSync(join(tmpdir(), 'lb-caseopen-'))); cases = []; opens = 0; recentDelay = 0; openIgnored = false })
afterEach(() => { rmSync(tmp, { recursive: true, force: true }) })

/** 旧位置建案件、写一个会话 s1 并挂进旧工作区；停掉；复制（或搬家）到新位置；重启（服务仍只列旧位置）。 */
async function prepare(how: 'copy' | 'move', pool: unknown) {
  const appData = join(tmp, 'appdata'); const home = join(tmp, 'home', 'sessions')
  const oldR = join(tmp, '桌面', '案丙'); const newR = join(tmp, '案件盘', '案丙')
  mkdirSync(oldR, { recursive: true }); mkdirSync(join(tmp, '案件盘'))
  cases = [{ root: oldR, exists: true }]
  let s = await startStore(appData, home)
  await waitRoots(appData, oldR)
  let b = await bootReg(pool, s.persistence)
  const w = await b.reg.create(oldR)
  await write(s.persistence, 's1', oldR, oneTurnLog().slice(0, 2))
  await w.attachSession('s1')
  await b.dispose(); await s.dispose()
  if (how === 'copy') cpSync(oldR, newR, { recursive: true })
  else { renameSync(oldR, newR); cases = [{ root: oldR, exists: false }] }
  s = await startStore(appData, home)
  await sleep(300)
  b = await bootReg(pool, s.persistence)
  return { appData, home, oldR, newR, s, b }
}

for (const [label, waitBefore] of [['刚刷新过（5 秒节流内）', 0], ['距上次刷新超过 5 秒', 5200]] as const) {
  it(`X1 复制后第一次在新位置打开（${label}）：caseOpen → 挂回就挂上，续写落新文件夹，旧文件夹字节不变，重启正常`, async () => {
    const pool = new MemoryMediaPool()
    const { appData, home, oldR, newR, s, b } = await prepare('copy', pool)
    expect(raw(b.reg, oldR)).toEqual(['s1'])
    if (waitBefore) await sleep(waitBefore)
    const oldHash = hashDir(oldR)
    const r = remote(s.persistence, b.reg, appData)
    // 界面 openCase：caseOpen → workspaces.create → attachCaseSessions → openWorkspace
    expect((await r.caseOpen({ path: newR, template: null })).ok).toBe(true)
    await b.reg.create(newR)
    expect(await r.attachCaseSessions({ root: newR })).toEqual({ ok: true, value: { attached: 1, failed: 0 } })
    expect([raw(b.reg, newR), raw(b.reg, oldR)]).toEqual([['s1'], []])
    const h = (await s.persistence.open('s1', 'write')) as unknown as H
    expect(h.header.cwd).toBe(newR)
    await h.append(oneTurnLog().slice(2)); await h.close()
    expect(hashDir(oldR)).toBe(oldHash)
    expect(hashDir(newR)).not.toBe(oldHash)
    await b.dispose()
    const b2 = await bootReg(pool, s.persistence)
    expect([raw(b2.reg, newR), raw(b2.reg, oldR)]).toEqual([['s1'], []])
    await b2.dispose(); await s.dispose()
    void home
  }, 30000)
}

it('X1d 会话在内存里、记录头还是旧位置：Host 挂回时不动它，留在旧工作区（不进"未分组"）；内存里记录头就是这个根的照常挂', async () => {
  const pool = new MemoryMediaPool()
  const { appData, oldR, newR, s, b } = await prepare('copy', pool)
  let liveCwd = oldR
  const r = remote(s.persistence, b.reg, appData, { get: (id: string) => (id === 's1' ? { header: { cwd: liveCwd } } : undefined) })
  expect((await r.caseOpen({ path: newR, template: null })).ok).toBe(true)
  await b.reg.create(newR)
  expect(await r.attachCaseSessions({ root: newR })).toEqual({ ok: true, value: { attached: 0, failed: 0 } })
  expect([raw(b.reg, newR), raw(b.reg, oldR)]).toEqual([[], ['s1']])
  liveCwd = newR // 比如这时内存里的会话已是从新位置 resume 的
  expect(await r.attachCaseSessions({ root: newR })).toEqual({ ok: true, value: { attached: 1, failed: 0 } })
  expect([raw(b.reg, newR), raw(b.reg, oldR)]).toEqual([['s1'], []])
  await b.dispose(); await s.dispose()
}, 30000)

it('X1b 纯搬家后第一次在新位置打开：caseOpen → 挂回就挂上（不进"未分组"）', async () => {
  const pool = new MemoryMediaPool()
  const { appData, newR, s, b } = await prepare('move', pool)
  const r = remote(s.persistence, b.reg, appData)
  expect((await r.caseOpen({ path: newR, template: null })).ok).toBe(true)
  await b.reg.create(newR)
  expect(await r.attachCaseSessions({ root: newR })).toEqual({ ok: true, value: { attached: 1, failed: 0 } })
  expect(raw(b.reg, newR)).toEqual(['s1'])
  await b.dispose(); await s.dispose()
}, 30000)

it('X1c 不经 caseOpen 直接打开工作区（首页点当前案件那条路）：挂回前先刷新名单，照样挂上', async () => {
  const pool = new MemoryMediaPool()
  const { appData, newR, s, b } = await prepare('copy', pool)
  cases = [{ root: newR, exists: true }] // 服务已只列新位置（别处 caseOpen 过）；本进程名单还是旧的、5 秒节流内
  await b.reg.create(newR)
  expect(await remote(s.persistence, b.reg, appData).attachCaseSessions({ root: newR })).toEqual({ ok: true, value: { attached: 1, failed: 0 } })
  expect(raw(b.reg, newR)).toEqual(['s1'])
  await b.dispose(); await s.dispose()
}, 30000)

it('X10 复制后在新位置 caseOpen、还没挂回就续写：句柄 cwd 是新位置，续写落新文件夹，旧文件夹字节不变', async () => {
  const pool = new MemoryMediaPool()
  const { appData, oldR, newR, s, b } = await prepare('copy', pool)
  // 登记启动时按旧名单列过一次：编号表记的是旧位置
  expect((await s.persistence.list()).map((x) => x.header.cwd)).toEqual([oldR])
  const oldHash = hashDir(oldR)
  expect((await remote(s.persistence, b.reg, appData).caseOpen({ path: newR, template: null })).ok).toBe(true)
  const h = (await s.persistence.open('s1', 'write')) as unknown as H
  expect(h.header.cwd).toBe(newR)
  await h.append(oneTurnLog().slice(2)); await h.close()
  expect(hashDir(oldR)).toBe(oldHash)
  await b.dispose(); await s.dispose()
}, 30000)

it('X7 同一进程里案件整个搬走、先打开后列表：找不到时强制刷新名单再找，打开成功、cwd 是新位置', async () => {
  const appData = join(tmp, 'appdata'); const home = join(tmp, 'home', 'sessions')
  const oldR = join(tmp, 'a', '案甲'); const newR = join(tmp, 'b', '案甲')
  mkdirSync(oldR, { recursive: true }); mkdirSync(join(tmp, 'b'))
  cases = [{ root: oldR, exists: true }]
  const s = await startStore(appData, home)
  await waitRoots(appData, oldR)
  await write(s.persistence, 's1', oldR)
  renameSync(oldR, newR)
  cases = [{ root: newR, exists: true }] // 服务已只报新位置（名单只经列表或新建刷新，此刻还是旧的）
  const h = (await s.persistence.open('s1', 'read')) as unknown as H
  expect(h.header.cwd).toBe(newR)
  await h.close()
  await s.dispose()
}, 30000)

it('A-P3-1 途中那次刷新是打开之前发出的：caseOpen 后先等它回来、再问一次，续写落新文件夹', async () => {
  const pool = new MemoryMediaPool()
  const { appData, oldR, newR, s, b } = await prepare('copy', pool)
  const oldHash = hashDir(oldR)
  recentDelay = 800
  await sleep(5200) // 过了 5 秒节流
  await s.persistence.list() // 触发后台刷新：服务这时还只列旧位置，800 毫秒后才回
  await sleep(100)
  expect((await remote(s.persistence, b.reg, appData).caseOpen({ path: newR, template: null })).ok).toBe(true)
  expect(new CaseRoots(appData).load().list()).toEqual([newR])
  const h = (await s.persistence.open('s1', 'write')) as unknown as H
  expect(h.header.cwd).toBe(newR)
  await h.append(oneTurnLog().slice(2)); await h.close()
  expect(hashDir(oldR)).toBe(oldHash)
  await b.dispose(); await s.dispose()
}, 30000)

it('F2 打开后服务没把这个位置列出来：挂回结果带 listed:false（界面据此提示稍后再打开）', async () => {
  const pool = new MemoryMediaPool()
  const { appData, newR, s, b } = await prepare('copy', pool)
  openIgnored = true
  const r = remote(s.persistence, b.reg, appData)
  expect((await r.caseOpen({ path: newR, template: null })).ok).toBe(true)
  await b.reg.create(newR)
  expect(await r.attachCaseSessions({ root: newR })).toEqual({ ok: true, value: { attached: 0, failed: 0, listed: false } })
  openIgnored = false
  expect((await r.caseOpen({ path: newR, template: null })).ok).toBe(true)
  expect(await r.attachCaseSessions({ root: newR })).toEqual({ ok: true, value: { attached: 1, failed: 0 } })
  await b.dispose(); await s.dispose()
}, 30000)

describe('Host 包装（第四轮复核 A-P3-3）', () => {
  it('attachCaseSessions：参数不对 → INVALID_ARGUMENT；DSH 的两个服务不在 → 挂回 0 个', async () => {
    const r = new LawbenchRemote({ endpoint: () => undefined, state: 'starting' } as unknown as Supervisor, tmp, () => undefined)
    expect(await r.attachCaseSessions({})).toMatchObject({ ok: false, error: { code: 'INVALID_ARGUMENT' } })
    expect(await r.attachCaseSessions(null)).toMatchObject({ ok: false, error: { code: 'INVALID_ARGUMENT' } })
    expect(await r.attachCaseSessions({ root: tmp })).toEqual({ ok: true, value: { attached: 0, failed: 0 } })
  })

  it('caseOpen 成功后请会话存储刷新名单、等它回来；失败时不刷新', async () => {
    let refreshed = 0
    const p = { refreshCaseRoots: async () => { await sleep(50); refreshed++ } }
    const r = remote(p, undefined, tmp)
    expect((await r.caseOpen({ path: join(tmp, 'x'), template: null })).ok).toBe(true)
    expect(refreshed).toBe(1)
    const down = new LawbenchRemote({ endpoint: () => undefined, state: 'starting' } as unknown as Supervisor, tmp, () => undefined, [], () => {}, undefined, () => p) as Api
    expect((await down.caseOpen({ path: join(tmp, 'x'), template: null })).ok).toBe(false)
    expect(refreshed).toBe(1)
  })
})
