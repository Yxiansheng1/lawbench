// 打开案件时把游离会话挂回案件工作区（T17 第三轮复核 B-F2；改编自复核员实验 workspace-zz-rvb.spec.ts 的 W1–W3，
// 打印改为断言）：DSH 真的工作区登记（WorkspaceRegistry，已构建的 lib）+ 我方会话存储路由 + host/attach-sessions.ts。
// 记录用按根分的"磁盘"假实例（换根即换数据，模拟整个文件夹搬走或复制）。
import { createRequire } from 'node:module'
import { cpSync, mkdirSync, mkdtempSync, realpathSync, renameSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { CaseRoots } from '../session-store/case-roots.ts'
import { SessionRouter, type Backend, type Header } from '../session-store/router.ts'
import { attachCaseSessions } from '../host/attach-sessions.ts'

const WS_PKG = join(__dirname, '..', '..', 'dsh', 'packages', 'workspace', 'workspace')
const req = createRequire(join(WS_PKG, 'package.json'))
const load = async (spec: string) => import(/* @vite-ignore */ realpathSync(req.resolve(spec)))
const { Context } = (await load('@deepseek-ai/cordis')) as { Context: new () => any }
const Storage = ((await load('@deepseek-ai/dsh-storage')) as { default: unknown }).default
const { DomainFacility } = (await load('@deepseek-ai/dsh-storage-domain')) as { DomainFacility: new (...a: unknown[]) => any }
const WorkspaceRegistry = ((await import(/* @vite-ignore */ realpathSync(join(WS_PKG, 'lib', 'index.js')))) as { default: unknown }).default
const MEMORY = join(__dirname, '..', '..', 'dsh', 'packages', 'storage', 'storage-domain', 'tests', 'helpers', 'memory-backend.ts')
const { MemoryMediaPool, MemoryStorageBackend } = (await import(/* @vite-ignore */ MEMORY)) as { MemoryMediaPool: new () => unknown; MemoryStorageBackend: new (p: unknown) => unknown }

const disk = new Map<string, Map<string, Header>>()
class DiskBackend implements Backend {
  constructor(private root: string) {}
  private get m() { let m = disk.get(this.root.toLowerCase()); if (!m) { m = new Map(); disk.set(this.root.toLowerCase(), m) } return m }
  async create(h: Header) { this.m.set(h.id, h); return { id: h.id, header: h } }
  async open(id: string) { const h = this.m.get(id); if (!h) throw Object.assign(new Error('nf'), { name: 'SessionPersistenceNotFoundError' }); return { id, header: h } }
  async flush() {}
  async stat(id: string) { const h = this.m.get(id); return h && { header: h, revision: 'r' } }
  async list() { return [...this.m.values()].map((header) => ({ header, revision: 'r' })) }
}
const copyDisk = (from: string, to: string, keep: boolean) => {
  const f = disk.get(from.toLowerCase()); if (!f) return
  disk.set(to.toLowerCase(), new Map(f)); if (!keep) disk.delete(from.toLowerCase())
}
const store = (r: string) => join(r, '工作区', '会话')

async function boot(pool: unknown, router: SessionRouter, live: Map<string, { header: Header }>) {
  const ctx = new Context()
  await ctx.plugin(Storage)
  ctx.storage.backend.register('memory', new MemoryStorageBackend(pool))
  const facility = new DomainFacility(ctx, { backend: 'memory', routes: {} })
  ctx.storage.mount('domain', facility)
  ctx.provide('storageDomain', facility)
  ctx.provide('sessionPersistence', { list: () => router.list(), open: (id: string, a: 'read' | 'write') => router.open(id, a), stat: (id: string) => router.stat(id) })
  ctx.provide('sessions', { get: (id: string) => live.get(id), list: () => [...live.values()] })
  const fiber = await ctx.plugin(WorkspaceRegistry)
  const reg = ctx.workspaceRegistry
  return { reg, persistence: { list: () => router.list() }, dispose: () => fiber.dispose() }
}
const H = (id: string, cwd: string): Header => ({ id, version: 3, createdAt: 1, isSeeded: false, cwd })
const members = (reg: any, path: string): string[] => [...(reg.list().find((w: any) => w.path === path)?.sessionIds ?? [])].sort()
/** 登记的原始记录（未经路径索引过滤）。 */
const raw = (reg: any, path: string): string[] => { const w = reg.list().find((x: any) => x.path === path); return w ? [...reg.table.get(w.id).sessionIds].sort() : ['<no ws>'] }
const newRouter = (roots: CaseRoots, tmp: string) => new SessionRouter((r) => new DiskBackend(r), roots, { defaultRoot: join(tmp, 'home'), allowOutsideCase: false })

let tmp: string
beforeEach(() => { disk.clear(); tmp = realpathSync(mkdtempSync(join(tmpdir(), 'lb-ws-'))) })
afterEach(() => { rmSync(tmp, { recursive: true, force: true }) })

it('W1 搬家（改名）后在新位置打开案件：旧会话挂回新案件工作区（不再落进"未分组"）', async () => {
  const oldR = join(tmp, 'a', '案甲'); const newR = join(tmp, 'b', '案甲')
  mkdirSync(oldR, { recursive: true }); mkdirSync(join(tmp, 'b'))
  const pool = new MemoryMediaPool()
  const roots = new CaseRoots(); roots.replace([{ root: oldR, exists: true }])
  const live = new Map<string, { header: Header }>()
  let router = newRouter(roots, tmp)
  let b = await boot(pool, router, live)
  const w = await b.reg.create(oldR)
  await router.create(H('s1', oldR)); live.set('s1', { header: H('s1', oldR) })
  await w.attachSession('s1')
  expect(members(b.reg, oldR)).toEqual(['s1'])
  await b.dispose(); live.clear()

  renameSync(oldR, newR); copyDisk(store(oldR), store(newR), false)
  roots.replace([{ root: newR, exists: true }]) // 真服务只列新位置
  router = newRouter(roots, tmp)
  b = await boot(pool, router, live)
  await b.reg.create(newR) // 律师在新位置打开案件
  expect(members(b.reg, newR)).toEqual([]) // 复核员 W1 的现象：没有挂回
  expect(await attachCaseSessions(b.reg, b.persistence, newR)).toEqual({ attached: 1, failed: 0 })
  expect(members(b.reg, newR)).toEqual(['s1'])
  expect(members(b.reg, oldR)).toEqual([])
  // 再打开一次不重复挂
  expect(await attachCaseSessions(b.reg, b.persistence, newR)).toEqual({ attached: 0, failed: 0 })
  await b.dispose(); live.clear()
  // 重启：旧工作区的登记记录里也已去掉（同一编号记在两处，DSH 启动会判登记不一致而起不来）
  b = await boot(pool, router, live)
  expect([members(b.reg, newR), members(b.reg, oldR)]).toEqual([['s1'], []])
  await b.dispose()
})

it('W2 名单缓存丢了、服务没起时启动，之后在该案件新建会话：打开案件时旧会话挂回，再重启仍在', async () => {
  const C = join(tmp, '案乙'); mkdirSync(C, { recursive: true })
  const pool = new MemoryMediaPool()
  let roots = new CaseRoots(); roots.replace([{ root: C, exists: true }])
  const live = new Map<string, { header: Header }>()
  let router = newRouter(roots, tmp)
  let b = await boot(pool, router, live)
  const w = await b.reg.create(C)
  for (const id of ['s1', 's2']) { await router.create(H(id, C)); live.set(id, { header: H(id, C) }); await w.attachSession(id) }
  await b.dispose(); live.clear()

  roots = new CaseRoots() // 缓存为空、服务没起
  router = newRouter(roots, tmp)
  b = await boot(pool, router, live)
  roots.replace([{ root: C, exists: true }]) // 服务起来后刷新
  await b.reg.create(C) // 打开案件（界面在这之后请 Host 挂回）
  expect(await attachCaseSessions(b.reg, b.persistence, C)).toEqual({ attached: 2, failed: 0 })
  await router.create(H('s3', C)); live.set('s3', { header: H('s3', C) })
  await b.reg.list().find((x: any) => x.path === C).attachSession('s3')
  expect(members(b.reg, C)).toEqual(['s1', 's2', 's3'])
  await b.dispose(); live.clear()

  b = await boot(pool, router, live)
  expect(members(b.reg, C)).toEqual(['s1', 's2', 's3'])
  await b.dispose()
})

// 第四轮复核 A-P3-1、B 的 X2：私有写法（indexHeaders、table）任一不在时一个也不挂，登记不会写成两处
for (const [label, view] of [
  ['只有公开的 list', (r: any) => ({ list: () => r.list() })],
  ['有 indexHeaders、没有 table', (r: any) => ({ list: () => r.list(), indexHeaders: (h: any) => r.indexHeaders(h) })],
  ['有 table、没有 indexHeaders', (r: any) => ({ list: () => r.list(), table: r.table })],
] as const) it(`W2b 登记的私有写法不全（${label}）：复制后打开新位置一个也不挂、计为失败、记日志；重启正常、旧工作区照旧`, async () => {
  const oldR = join(tmp, '桌面', '案辛'); const newR = join(tmp, '案件盘', '案辛')
  mkdirSync(oldR, { recursive: true })
  const pool = new MemoryMediaPool()
  const roots = new CaseRoots(); roots.replace([{ root: oldR, exists: true }])
  const live = new Map<string, { header: Header }>()
  let router = newRouter(roots, tmp)
  let b = await boot(pool, router, live)
  const w = await b.reg.create(oldR)
  await router.create(H('s1', oldR)); live.set('s1', { header: H('s1', oldR) }); await w.attachSession('s1')
  await b.dispose(); live.clear()

  cpSync(oldR, newR, { recursive: true }); copyDisk(store(oldR), store(newR), true)
  router = newRouter(roots, tmp) // 缓存仍是旧位置
  b = await boot(pool, router, live)
  roots.replace([{ root: newR, exists: true }])
  await b.reg.create(newR)
  const logs: string[] = []
  expect(await attachCaseSessions(view(b.reg), b.persistence, newR, (_l, e) => { logs.push(e) })).toEqual({ attached: 0, failed: 1 })
  expect(logs).toContain('workspace.attach_unsupported')
  expect([raw(b.reg, newR), raw(b.reg, oldR)]).toEqual([[], ['s1']])
  await b.dispose(); live.clear()
  b = await boot(pool, router, live) // 起得来（没有同一编号记两处）
  expect(raw(b.reg, oldR)).toEqual(['s1'])
  await b.dispose()
})

it('W3 F-CASE-04 复制后在新位置打开：会话归新案件工作区，旧工作区里不再算它', async () => {
  const oldR = join(tmp, '桌面', '案丙'); const newR = join(tmp, '案件盘', '案丙')
  mkdirSync(oldR, { recursive: true })
  const pool = new MemoryMediaPool()
  const roots = new CaseRoots(); roots.replace([{ root: oldR, exists: true }])
  const live = new Map<string, { header: Header }>()
  let router = newRouter(roots, tmp)
  let b = await boot(pool, router, live)
  const w = await b.reg.create(oldR)
  await router.create(H('s1', oldR)); live.set('s1', { header: H('s1', oldR) }); await w.attachSession('s1')
  await b.dispose(); live.clear()

  cpSync(oldR, newR, { recursive: true }); copyDisk(store(oldR), store(newR), true)
  roots.replace([{ root: newR, exists: true }])
  expect(roots.list()).toEqual([newR])
  router = newRouter(roots, tmp)
  b = await boot(pool, router, live)
  await b.reg.create(newR)
  expect((await router.list()).map((r) => [r.header.id, r.header.cwd])).toEqual([['s1', newR]])
  await attachCaseSessions(b.reg, b.persistence, newR)
  expect(members(b.reg, newR)).toEqual(['s1'])
  expect(members(b.reg, oldR)).toEqual([])
  await b.dispose(); live.clear()
  b = await boot(pool, router, live)
  expect([members(b.reg, newR), members(b.reg, oldR)]).toEqual([['s1'], []])
  await b.dispose()
})

it('W4 复制后启动时名单缓存还是旧位置（服务还没刷新）：登记把会话算在旧工作区；打开新位置时挂到新工作区，旧工作区不再算它', async () => {
  const oldR = join(tmp, '桌面', '案戊'); const newR = join(tmp, '案件盘', '案戊')
  mkdirSync(oldR, { recursive: true })
  const pool = new MemoryMediaPool()
  const roots = new CaseRoots(); roots.replace([{ root: oldR, exists: true }])
  const live = new Map<string, { header: Header }>()
  let router = newRouter(roots, tmp)
  let b = await boot(pool, router, live)
  const w = await b.reg.create(oldR)
  await router.create(H('s1', oldR)); live.set('s1', { header: H('s1', oldR) }); await w.attachSession('s1')
  await b.dispose(); live.clear()

  cpSync(oldR, newR, { recursive: true }); copyDisk(store(oldR), store(newR), true)
  router = newRouter(roots, tmp) // 缓存仍是旧位置
  b = await boot(pool, router, live)
  expect(members(b.reg, oldR)).toEqual(['s1']) // 登记按旧 cwd 算在旧工作区
  roots.replace([{ root: newR, exists: true }]) // 服务起来后刷新：只列新位置
  await b.reg.create(newR)
  const oldWs = b.reg.list().find((x: any) => x.path === oldR)
  const newWs = b.reg.list().find((x: any) => x.path === newR)
  const recorded = (w: any): string[] => [...b.reg.table.get(w.id).sessionIds]
  const steps: string[] = []
  const detach = oldWs.detachSession.bind(oldWs)
  oldWs.detachSession = async (id: string) => { steps.push(`detach ${id}`); await detach(id) }
  const attach = newWs.attachSession.bind(newWs)
  newWs.attachSession = async (id: string) => {
    // 挂到新工作区的那一刻，旧工作区的登记记录里已经没有它（同一编号记在两处，DSH 下次启动会判登记不一致）
    steps.push(`attach ${id} old=${recorded(oldWs).join(',')}`)
    await attach(id)
  }
  expect(recorded(oldWs)).toEqual(['s1'])
  expect(await attachCaseSessions(b.reg, b.persistence, newR)).toEqual({ attached: 1, failed: 0 })
  expect(steps).toEqual(['detach s1', 'attach s1 old='])
  expect(members(b.reg, newR)).toEqual(['s1'])
  expect(members(b.reg, oldR)).toEqual([])
  // 旧工作区的登记记录也去掉了它（写一次记录、发变更，界面侧栏才会更新）；重启能起来、归属不变
  expect(recorded(oldWs)).toEqual([])
  await b.dispose(); live.clear()
  b = await boot(pool, router, live)
  expect([members(b.reg, newR), members(b.reg, oldR)]).toEqual([['s1'], []])
  await b.dispose()
})

it('W5 打开一个案件时，不在名单上的别的案件（盘拔了）的工作区不被改写，它的会话不被剪掉', async () => {
  const C = join(tmp, '案己'); const D = join(tmp, 'U盘', '案庚')
  mkdirSync(C, { recursive: true }); mkdirSync(D, { recursive: true })
  const pool = new MemoryMediaPool()
  const roots = new CaseRoots(); roots.replace([{ root: C, exists: true }, { root: D, exists: true }])
  const live = new Map<string, { header: Header }>()
  let router = newRouter(roots, tmp)
  let b = await boot(pool, router, live)
  const wd = await b.reg.create(D)
  await router.create(H('sd', D)); live.set('sd', { header: H('sd', D) }); await wd.attachSession('sd')
  await b.dispose(); live.clear()

  disk.set(store(C).toLowerCase(), new Map([['sc', H('sc', C)]])) // C 里有一个还没挂进工作区的会话
  roots.replace([{ root: C, exists: true }, { root: D, exists: false }]) // D 的盘拔了
  router = newRouter(roots, tmp)
  b = await boot(pool, router, live)
  await b.reg.create(C)
  expect(await attachCaseSessions(b.reg, b.persistence, C)).toEqual({ attached: 1, failed: 0 })
  const wdNow = b.reg.list().find((x: any) => x.path === D)
  expect([...b.reg.table.get(wdNow.id).sessionIds]).toEqual(['sd'])
  await b.dispose(); live.clear()
  roots.replace([{ root: C, exists: true }, { root: D, exists: true }]) // 插回来
  b = await boot(pool, newRouter(roots, tmp), live)
  expect([members(b.reg, C), members(b.reg, D)]).toEqual([['sc'], ['sd']])
  await b.dispose()
})

it('W6 从旧工作区去掉时出错（写盘失败）：这个会话不挂、计为失败；登记不写成两处，重启正常（第四轮复核 A-P2-1 = B-F2）', async () => {
  const oldR = join(tmp, '桌面', '案壬'); const newR = join(tmp, '案件盘', '案壬')
  mkdirSync(oldR, { recursive: true })
  const pool = new MemoryMediaPool()
  const roots = new CaseRoots(); roots.replace([{ root: oldR, exists: true }])
  const live = new Map<string, { header: Header }>()
  let router = newRouter(roots, tmp)
  let b = await boot(pool, router, live)
  const w = await b.reg.create(oldR)
  for (const id of ['s1', 's2']) { await router.create(H(id, oldR)); live.set(id, { header: H(id, oldR) }); await w.attachSession(id) }
  await b.dispose(); live.clear()

  cpSync(oldR, newR, { recursive: true }); copyDisk(store(oldR), store(newR), true)
  router = newRouter(roots, tmp)
  b = await boot(pool, router, live)
  roots.replace([{ root: newR, exists: true }])
  await b.reg.create(newR)
  const oldWs = b.reg.list().find((x: any) => x.path === oldR)
  const detach = oldWs.detachSession.bind(oldWs)
  oldWs.detachSession = async (id: string) => { if (id === 's1') throw new Error('disk write failed'); await detach(id) }
  const logs: string[] = []
  expect(await attachCaseSessions(b.reg, b.persistence, newR, (_l, e) => { logs.push(e) })).toEqual({ attached: 1, failed: 1 })
  expect(logs).toContain('workspace.detach_failed')
  // s1 不在新工作区；去掉 s2 那次写旧记录时 DSH 把索引已不指向旧位置的 s1 也剪掉了，s1 暂时不在任何工作区（不是两处）
  expect([raw(b.reg, newR), raw(b.reg, oldR)]).toEqual([['s2'], []])
  await b.dispose(); live.clear()
  b = await boot(pool, router, live)
  expect(raw(b.reg, newR)).toEqual(['s2'])
  // 再打开一次案件：s1 挂上
  expect(await attachCaseSessions(b.reg, b.persistence, newR)).toEqual({ attached: 1, failed: 0 })
  expect(raw(b.reg, newR)).toEqual(['s1', 's2'])
  await b.dispose()
})

it('找不到这个案件的工作区时什么也不做；挂不上的只计数、日志不带路径和编号', async () => {
  const logs: Array<[string, unknown]> = []
  const reg = { list: () => [{ path: join(tmp, '案丁'), sessionIds: [], attachSession: async () => { throw new Error(`cannot attach session 's9' to workspace '${tmp}'`) } }] }
  const persistence = { list: async () => [{ header: { id: 's9', cwd: join(tmp, '案丁') } }, { header: { id: 's8', cwd: join(tmp, '别处') } }] }
  expect(await attachCaseSessions(reg, persistence, join(tmp, '没有'))).toEqual({ attached: 0, failed: 0 })
  expect(await attachCaseSessions(reg, persistence, join(tmp, '案丁'), (_l, e, m) => { logs.push([e, m]) })).toEqual({ attached: 0, failed: 1 })
  expect(JSON.stringify(logs)).not.toMatch(/s9|案丁|lb-ws/)
})
