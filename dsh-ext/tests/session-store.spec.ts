// 会话存储路由（session-store，T17 第三步）：
// 一、假实例测路由本身：按 cwd 选实例、编号表、列表合并与单个案件根失败跳过、开关两态、记录头 cwd 换成案件现根；
// 二、接 DSH 自己装的原版 JSONL 包和 cordis：记录落在 <案件>\工作区\会话、默认根里没有；案件目录整个改名后
//     旧会话能列出、能打开、能续写（不改原版包）；
// 三、DSH 的存储契约用例整套对路由再跑一遍（不在案件里的会话走默认根）。
import { createRequire } from 'node:module'
import { existsSync, mkdirSync, mkdtempSync, readdirSync, realpathSync, renameSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { CACHE_FILE, CaseRoots, inside } from '../session-store/case-roots.ts'
import { OUTSIDE_CASE, SessionRouter, type Backend, type Handle, type Header, type Snapshot } from '../session-store/router.ts'
import { apply as applyStore, name as storeName } from '../session-store/index.ts'


const JSONL_PKG = join(__dirname, '..', '..', 'dsh', 'packages', 'session', 'session-persistence-jsonl')
const JSONL = join(JSONL_PKG, 'lib', 'index.js')
const req = createRequire(join(JSONL_PKG, 'package.json'))
// DSH 的存储契约用例（按路径动态引入：它是 DSH 的测试源码，不进我方类型检查）
const CONTRACT = join(__dirname, '..', '..', 'dsh', 'packages', 'session', 'session-persistence', 'tests', 'contract.ts')
const { meta, oneTurnLog, runPersistenceContract } = (await import(/* @vite-ignore */ CONTRACT)) as {
  meta(id: string, cwd?: string): Header
  oneTurnLog(): unknown[]
  runPersistenceContract(name: string, make: () => Promise<unknown>): void
}
// 原版包和 cordis 都经测试的模块系统引入（与契约用例引的错误类是同一份），原版类直接交给插件
const cordis = (await import(/* @vite-ignore */ realpathSync(req.resolve('@deepseek-ai/cordis')))) as { Context: new () => any }
const Jsonl = ((await import(/* @vite-ignore */ realpathSync(JSONL))) as { default: unknown }).default

// ── 一、假实例 ─────────────────────────────────────────────────────────────
class FakeBackend implements Backend {
  sessions = new Map<string, Header>()
  failList = false
  constructor(public root: string) {}
  async create(h: Header) { this.sessions.set(h.id, h); return this.h(h) }
  async open(id: string, access: 'read' | 'write') {
    const h = this.sessions.get(id)
    if (!h) throw Object.assign(new Error(`not found ${id}`), { name: 'SessionPersistenceNotFoundError' })
    return { ...this.h(h), access }
  }
  async flush() {}
  async stat(id: string) { const h = this.sessions.get(id); return h && { header: h, revision: 'r' } }
  async list() {
    if (this.failList) throw Object.assign(new Error('EIO'), { code: 'EIO' })
    return [...this.sessions.values()].map((header) => ({ header, revision: 'r' }))
  }
  private h(header: Header): Handle { return { id: header.id, header, read: function (this: Handle) { return this.id } } }
}

function fakeRouter(roots: string[], opts: { allowOutsideCase?: boolean; refresh?: (r: CaseRoots) => void } = {}) {
  const made: FakeBackend[] = []
  const caseRoots = new CaseRoots()
  caseRoots.merge(roots.map((root) => ({ root, exists: true })))
  const logs: Array<[string, Record<string, unknown> | undefined]> = []
  const router = new SessionRouter((root) => { const b = new FakeBackend(root); made.push(b); return b }, caseRoots, {
    defaultRoot: 'C:\\dsh\\sessions',
    allowOutsideCase: opts.allowOutsideCase ?? true,
    refresh: opts.refresh ? async () => opts.refresh!(caseRoots) : undefined,
    log: (_l, e, m) => { logs.push([e, m]) },
  })
  const backendOf = (root: string) => made.find((b) => b.root === root)!
  return { router, made, backendOf, logs, caseRoots }
}

const H = (id: string, cwd?: string): Header => ({ id, version: 3, createdAt: 1, isSeeded: false, ...(cwd ? { cwd } : {}) })
const A = 'D:\\案件\\张三诉李四'
const B = 'D:\\案件\\王五借款'
const A_STORE = join(A, '工作区', '会话')
const B_STORE = join(B, '工作区', '会话')

describe('会话存储路由：选实例、编号表、列表合并', () => {
  it('新建按 cwd 选实例：在案件根里（含子目录、大小写、斜杠不同）进该案件，不在的进默认根', async () => {
    const { router, backendOf } = fakeRouter([A, B])
    await router.create(H('s1', A))
    await router.create(H('s2', 'd:/案件/王五借款/'))
    await router.create(H('s3', join(A, '01原始材料')))
    await router.create(H('s4', 'D:\\别处'))
    expect([...backendOf(A_STORE).sessions.keys()]).toEqual(['s1', 's3'])
    expect([...backendOf(B_STORE).sessions.keys()]).toEqual(['s2'])
    expect([...backendOf('C:\\dsh\\sessions').sessions.keys()]).toEqual(['s4'])
    expect([router.ownerOf('s1'), router.ownerOf('s4')]).toEqual([A, null])
  })

  it('打开、stat 按编号找实例：新进程（表是空的）逐个实例找到后记下；哪里都没有时按原样报不存在', async () => {
    const first = fakeRouter([A])
    await first.router.create(H('s1', A))
    // 模拟重启：同样的实例内容，新的路由
    const again = fakeRouter([A])
    again.backendOf('C:\\dsh\\sessions') // 默认根总是先建
    ;(again.router as unknown as { all(): unknown }).all()
    again.backendOf(A_STORE).sessions = first.backendOf(A_STORE).sessions
    expect((await again.router.stat('s1'))?.header.id).toBe('s1')
    expect(again.router.ownerOf('s1')).toBe(A)
    expect((await again.router.open('s1', 'write')).access).toBe('write')
    await expect(again.router.open('nope', 'read')).rejects.toThrow('not found nope')
    expect(await again.router.stat('nope')).toBeUndefined()
  })

  it('列表合并各实例；某个案件根读不出来只跳过它、记一条不带路径的日志；默认根读不出来照原样失败', async () => {
    const { router, backendOf, logs } = fakeRouter([A, B])
    await router.create(H('s1', A)); await router.create(H('s2', B)); await router.create(H('s0', 'D:\\别处'))
    backendOf(B_STORE).failList = true
    expect((await router.list()).map((r) => r.header.id).sort()).toEqual(['s0', 's1'])
    expect(logs.find(([e]) => e === 'session_store.case_root_skipped')?.[1]).toEqual({ index: 2, code: 'EIO' })
    expect(JSON.stringify(logs)).not.toContain('案件')
    backendOf('C:\\dsh\\sessions').failList = true
    await expect(router.list()).rejects.toThrow('EIO')
  })

  it('记录头 cwd 换成案件现根：记录里的旧 cwd 不在名单上时，list、stat、open 交出去的都是现根；句柄方法照常可用', async () => {
    const { router, backendOf } = fakeRouter([A])
    ;(router as unknown as { all(): unknown }).all()
    backendOf(A_STORE).sessions.set('old', H('old', 'E:\\搬家前\\张三诉李四'))
    expect((await router.list()).find((r) => r.header.id === 'old')?.header.cwd).toBe(A)
    expect((await router.stat('old'))?.header.cwd).toBe(A)
    const h = await router.open('old', 'read') as Handle & { read(): string }
    expect(h.header.cwd).toBe(A)
    expect(h.read()).toBe('old')
    expect(Object.isFrozen(h.header)).toBe(true)
  })

  it('开关两态：允许时不在案件里的会话进默认根；不允许时拒绝新建并给中文说明（案件里的照常）', async () => {
    const off = fakeRouter([A], { allowOutsideCase: false })
    await expect(off.router.create(H('x', 'D:\\别处'))).rejects.toThrow(OUTSIDE_CASE)
    await expect(off.router.create(H('y'))).rejects.toThrow(OUTSIDE_CASE)
    await off.router.create(H('z', A))
    expect(off.router.ownerOf('z')).toBe(A)
    const on = fakeRouter([A])
    await on.router.create(H('x', 'D:\\别处'))
    expect(on.router.ownerOf('x')).toBeNull()
  })

  it('刚登记的案件还不在名单里：新建时先问一次服务再判', async () => {
    const { router, backendOf } = fakeRouter([], { refresh: (r) => { r.merge([{ root: B, exists: true }]) } })
    await router.create(H('s', B))
    expect([...backendOf(B_STORE).sessions.keys()]).toEqual(['s'])
  })
})

describe('案件根名单缓存', () => {
  it('读写缓存；服务说"不在了"的去掉、在的加入、没列出的保留；坏缓存当空', () => {
    const dir = mkdtempSync(join(tmpdir(), 'lb-roots-'))
    try {
      const r = new CaseRoots(dir).load()
      expect(r.list()).toEqual([])
      r.merge([{ root: A, exists: true }, { root: B, exists: true }])
      expect(new CaseRoots(dir).load().list()).toEqual([A, B])
      r.merge([{ root: 'd:/案件/张三诉李四', exists: false }, { root: 'F:\\新案', exists: true }])
      expect(new CaseRoots(dir).load().list()).toEqual([B, 'F:\\新案'])
      writeFileSync(join(dir, CACHE_FILE), '{坏', 'utf8')
      expect(new CaseRoots(dir).load().list()).toEqual([])
      expect([inside('D:\\案件\\张三诉李四2', A), inside('D:\\案件\\张三诉李四\\x', A)]).toEqual([false, true])
    } finally { rmSync(dir, { recursive: true, force: true }) }
  })
})

// ── 二、接原版 JSONL 包 ────────────────────────────────────────────────────
async function startStore(appData: string, defaultRoot: string, extra: Record<string, unknown> = {}) {
  const ctx = new cordis.Context()
  const fiber = await ctx.plugin({ name: storeName, apply: applyStore }, { backend: Jsonl, defaultRoot, appData, compression: 'none', ...extra })
  return { persistence: ctx.sessionPersistence as Backend, dispose: () => fiber.dispose() }
}

function files(dir: string): string[] {
  if (!existsSync(dir)) return []
  return readdirSync(dir, { recursive: true, withFileTypes: true }).filter((e) => e.isFile()).map((e) => join(e.parentPath, e.name))
}

describe('接原版 JSONL 包：记录进案件文件夹；案件搬家后能列、能开、能续写', () => {
  let tmp: string
  beforeEach(() => { tmp = mkdtempSync(join(tmpdir(), 'lb-store-')) })
  afterEach(() => { rmSync(tmp, { recursive: true, force: true }) })

  it('案件里的会话只写进 <案件>\\工作区\\会话，默认根没有；开关打开时不在案件里的写默认根', async () => {
    const appData = join(tmp, 'appdata'); const home = join(tmp, 'dsh-home', 'sessions'); const caseRoot = join(tmp, '刑事-虚构甲')
    mkdirSync(caseRoot, { recursive: true })
    new CaseRoots(appData).merge([{ root: caseRoot, exists: true }])
    const s = await startStore(appData, home, { allowOutsideCase: true })
    try {
      const h = await s.persistence.create(meta('in-case', caseRoot) as never)
      await (h as unknown as { append(e: unknown): Promise<void> }).append(oneTurnLog())
      await (h as unknown as { close(): Promise<void> }).close()
      const o = await s.persistence.create(meta('outside', join(tmp, '别处')) as never)
      await (o as unknown as { append(e: unknown): Promise<void> }).append(oneTurnLog())
      await (o as unknown as { close(): Promise<void> }).close()
    } finally { await s.dispose() }
    expect(files(join(caseRoot, '工作区', '会话')).some((f) => f.includes('in-case'))).toBe(true)
    expect(files(home).some((f) => f.includes('in-case'))).toBe(false)
    expect(files(home).some((f) => f.includes('outside'))).toBe(true)
  })

  it('N46 ②（默认）：不在案件里的会话拒绝新建、给中文说明，$DSH_HOME\\sessions 下不新增目录；案件里的照常', async () => {
    const appData = join(tmp, 'appdata'); const home = join(tmp, 'dsh-home', 'sessions'); const caseRoot = join(tmp, '刑事-虚构丙')
    mkdirSync(caseRoot, { recursive: true }); mkdirSync(home, { recursive: true })
    new CaseRoots(appData).merge([{ root: caseRoot, exists: true }])
    const before = readdirSync(home)
    const s = await startStore(appData, home)
    try {
      await expect(s.persistence.create(meta('outside', join(tmp, '别处')) as never)).rejects.toThrow(OUTSIDE_CASE)
      await expect(s.persistence.create(meta('no-cwd') as never)).rejects.toThrow(OUTSIDE_CASE)
      const h = await s.persistence.create(meta('in-case', caseRoot) as never)
      await (h as unknown as { append(e: unknown): Promise<void> }).append(oneTurnLog())
      await (h as unknown as { close(): Promise<void> }).close()
    } finally { await s.dispose() }
    expect(readdirSync(home)).toEqual(before)
    expect(files(join(caseRoot, '工作区', '会话')).some((f) => f.includes('in-case'))).toBe(true)
  })

  it('搬家：案件目录整个改名、名单按服务更新后重启，旧会话能列出（cwd 为新路径）、能打开、能续写，不需要改原版包', async () => {
    const appData = join(tmp, 'appdata'); const home = join(tmp, 'dsh-home', 'sessions')
    const oldRoot = join(tmp, '旧位置', '民事-虚构乙'); const newRoot = join(tmp, '新位置', '民事-虚构乙')
    mkdirSync(oldRoot, { recursive: true })
    new CaseRoots(appData).merge([{ root: oldRoot, exists: true }])
    let s = await startStore(appData, home)
    try {
      const h = await s.persistence.create(meta('moved', oldRoot) as never)
      await (h as unknown as { append(e: unknown): Promise<void> }).append(oneTurnLog().slice(0, 2))
      await (h as unknown as { close(): Promise<void> }).close()
    } finally { await s.dispose() }
    mkdirSync(join(tmp, '新位置'), { recursive: true })
    renameSync(oldRoot, newRoot)
    new CaseRoots(appData).load().merge([{ root: oldRoot, exists: false }, { root: newRoot, exists: true }])
    s = await startStore(appData, home)
    try {
      const row = (await s.persistence.list()).find((r) => r.header.id === 'moved')
      expect(row?.header.cwd).toBe(newRoot)
      const w = (await s.persistence.open('moved', 'write')) as unknown as { header: Header; append(e: unknown): Promise<void>; read(): Promise<{ events: unknown[] }>; close(): Promise<void> }
      expect(w.header.cwd).toBe(newRoot)
      await w.append(oneTurnLog().slice(2))
      expect((await w.read()).events).toEqual(oneTurnLog())
      await w.close()
      const r = (await s.persistence.open('moved', 'read')) as unknown as { read(): Promise<{ events: unknown[] }>; close(): Promise<void> }
      expect((await r.read()).events).toHaveLength(oneTurnLog().length)
      await r.close()
    } finally { await s.dispose() }
    expect(files(home)).toEqual([])
  })

  it('某个案件根读不出来（路径被占成文件）：列表只跳过它，其余照常', async () => {
    const appData = join(tmp, 'appdata'); const home = join(tmp, 'dsh-home', 'sessions')
    const good = join(tmp, '好的案件'); const bad = join(tmp, '坏的案件')
    mkdirSync(good, { recursive: true }); mkdirSync(bad, { recursive: true })
    new CaseRoots(appData).merge([{ root: good, exists: true }, { root: bad, exists: true }])
    let s = await startStore(appData, home)
    try {
      for (const [id, cwd] of [['g', good], ['b', bad]] as const) {
        const h = await s.persistence.create(meta(id, cwd) as never)
        await (h as unknown as { append(e: unknown): Promise<void> }).append(oneTurnLog())
        await (h as unknown as { close(): Promise<void> }).close()
      }
    } finally { await s.dispose() }
    rmSync(join(bad, '工作区'), { recursive: true, force: true })
    writeFileSync(join(bad, '工作区'), 'x') // 案件根下的"工作区"成了文件：读它会报 ENOTDIR
    s = await startStore(appData, home)
    try {
      expect((await s.persistence.list()).map((r) => r.header.id)).toEqual(['g'])
    } finally { await s.dispose() }
  })
})

// ── 三、DSH 的存储契约整套对路由再跑一遍 ──────────────────────────────────
runPersistenceContract('lawbench-session-store（默认根）', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'lb-store-contract-'))
  // 契约用例的会话 cwd 不在任何案件里，按开关打开跑（验的是原版实例经路由转发的语义）
  const s = await startStore(join(dir, 'appdata'), join(dir, 'sessions'), { allowOutsideCase: true })
  return { persistence: s.persistence as never, dispose: async () => { await s.dispose(); rmSync(dir, { recursive: true, force: true }) } } as never
})
