// 会话存储路由（session-store，T17 第三步）：
// 一、假实例测路由本身：按 cwd 选实例、编号表、列表合并与单个案件根失败跳过、开关两态、记录头 cwd 换成案件现根；
// 二、接 DSH 自己装的原版 JSONL 包和 cordis：记录落在 <案件>\工作区\会话、默认根里没有；案件目录整个改名后
//     旧会话能列出、能打开、能续写（不改原版包）；
// 三、DSH 的存储契约用例整套对路由再跑三遍：不在案件里的会话走默认根；会话 cwd 是已登记的案件根；
//     cwd 在案件根的子目录里（记录头交出时改写成案件根，与搬家后同一条路）。
// 第三轮复核返修（B-F1 复制、B-F4 名单未就绪、B-F5 超时、B-F6 同进程搬家、A-P3-2 flush 与重复编号、
// A-P3-3 默认根只读、A-P3-5 列表不等服务）的用例随各节。
import { createServer, type Server } from 'node:http'
import { createRequire } from 'node:module'
import { cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, realpathSync, renameSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { CACHE_FILE, CaseRoots, inside } from '../session-store/case-roots.ts'
import { NOT_READY, OUTSIDE_CASE, SessionRouter, encodeSegment, type Backend, type Handle, type Header, type Snapshot } from '../session-store/router.ts'
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
  /** 读取永不返回（网络盘挂住）。 */
  hang = false
  flushed = 0
  /** 关句柄永不返回（盘慢、网络盘挂住）。 */
  hangClose = false
  /** 以写方式打开永不返回。 */
  hangOpen = false
  /** 句柄的 read 按原版返回 { events }（接回核对用）；不设时返回编号（看代理的 this 绑定）。 */
  eventRead = false
  /** 交出去的第几个句柄。 */
  private opened = 0
  constructor(public root: string) {}
  async create(h: Header) { this.sessions.set(h.id, h); return { ...this.h(h), access: 'write' } }
  async open(id: string, access: 'read' | 'write') {
    if (this.hangOpen && access === 'write') await new Promise(() => {})
    const h = this.sessions.get(id)
    if (!h) throw Object.assign(new Error(`not found ${id}`), { name: 'SessionPersistenceNotFoundError' })
    return { ...this.h(h), access }
  }
  async flush() { this.flushed++ }
  async stat(id: string) {
    if (this.hang) await new Promise(() => {})
    const h = this.sessions.get(id); return h && { header: h, revision: 'r' }
  }
  async list() {
    if (this.hang) await new Promise(() => {})
    if (this.failList) throw Object.assign(new Error('EIO'), { code: 'EIO' })
    return [...this.sessions.values()].map((header) => ({ header, revision: 'r' }))
  }
  private h(header: Header): Handle {
    const b = this
    return {
      id: header.id, header, serial: ++this.opened,
      read: function (this: Handle) { return b.eventRead ? Promise.resolve({ events: [] }) : this.id },
      close: () => (b.hangClose ? new Promise<void>(() => {}) : Promise.resolve()),
    }
  }
}

type Gate = { done(): boolean; wait(): Promise<boolean> }
function fakeRouter(roots: string[], opts: { allowOutsideCase?: boolean; refresh?: (r: CaseRoots) => void | Promise<void>; firstRefresh?: Gate; timeoutMs?: number; liveSeq?: (id: string) => number | undefined } = {}) {
  const made: FakeBackend[] = []
  const caseRoots = new CaseRoots()
  caseRoots.replace(roots.map((root) => ({ root, exists: true })))
  const logs: Array<[string, Record<string, unknown> | undefined]> = []
  const router = new SessionRouter((root) => { const b = new FakeBackend(root); made.push(b); return b }, caseRoots, {
    defaultRoot: 'C:\\dsh\\sessions',
    allowOutsideCase: opts.allowOutsideCase ?? true,
    refresh: opts.refresh ? async () => opts.refresh!(caseRoots) : undefined,
    firstRefresh: opts.firstRefresh,
    caseRootTimeoutMs: opts.timeoutMs,
    liveSeq: opts.liveSeq,
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
    const { router, backendOf } = fakeRouter([], { refresh: (r) => { r.replace([{ root: B, exists: true }]) } })
    await router.create(H('s', B))
    expect([...backendOf(B_STORE).sessions.keys()]).toEqual(['s'])
  })
})

describe('案件根名单缓存', () => {
  it('读写缓存；名单以服务为准整个换掉：没列出的去掉、exists 为假的去掉、同一路径不同写法只留一个；坏缓存当空并记日志', () => {
    const dir = mkdtempSync(join(tmpdir(), 'lb-roots-'))
    const logs: Array<[string, Record<string, unknown> | undefined]> = []
    try {
      const r = new CaseRoots(dir).load()
      expect(r.list()).toEqual([])
      r.replace([{ root: A, exists: true }, { root: B, exists: true }])
      expect(new CaseRoots(dir).load().list()).toEqual([A, B])
      expect(r.replace([{ root: 'd:/案件/张三诉李四', exists: false }, { root: 'F:\\新案', exists: true }, { root: 'f:/新案/', exists: true }])).toBe(true)
      expect(new CaseRoots(dir).load().list()).toEqual(['F:\\新案'])
      expect(r.replace([{ root: 'F:\\新案', exists: true }])).toBe(false)
      writeFileSync(join(dir, CACHE_FILE), '{坏', 'utf8')
      expect(new CaseRoots(dir, (_l, e, m) => { logs.push([e, m]) }).load().list()).toEqual([])
      expect(logs).toEqual([['session_store.case_roots_cache_unreadable', { code: 'SyntaxError' }]])
      expect([inside('D:\\案件\\张三诉李四2', A), inside('D:\\案件\\张三诉李四\\x', A)]).toEqual([false, true])
    } finally { rmSync(dir, { recursive: true, force: true }) }
  })

  it('第四轮 B-F6：服务返回空列表（一个案件也没有）时保留旧名单', () => {
    const r = new CaseRoots()
    r.replace([{ root: A, exists: true }])
    expect(r.replace([])).toBe(false)
    expect(r.list()).toEqual([A])
    expect(r.has('d:/案件/张三诉李四/')).toBe(true)
  })

  it('B-F1：盘拔了（exists 为假）从名单去掉，插回来（exists 为真）加回', () => {
    const r = new CaseRoots()
    r.replace([{ root: A, exists: true }, { root: B, exists: true }])
    r.replace([{ root: A, exists: false }, { root: B, exists: true }])
    expect(r.list()).toEqual([B])
    expect(r.match(join(A, 'x'))).toBeUndefined()
    r.replace([{ root: A, exists: true }, { root: B, exists: true }])
    expect(r.list()).toEqual([A, B])
  })

  it('A-P3-5：缓存写不进去记一条只带错误码的日志', () => {
    const dir = mkdtempSync(join(tmpdir(), 'lb-roots-'))
    const logs: Array<[string, Record<string, unknown> | undefined]> = []
    try {
      writeFileSync(join(dir, 'x'), 'x')
      new CaseRoots(join(dir, 'x', '子'), (_l, e, m) => { logs.push([e, m]) }).replace([{ root: A, exists: true }])
      expect(logs.map(([e]) => e)).toEqual(['session_store.case_roots_cache_write_failed'])
      expect(typeof logs[0][1]?.code).toBe('string')
      expect(JSON.stringify(logs)).not.toContain('案件')
    } finally { rmSync(dir, { recursive: true, force: true }) }
  })
})

describe('第三轮复核返修：路由', () => {
  const gate = () => {
    let done = false
    let waits = 0
    return { g: { done: () => done, wait: async () => { waits++; return done } } as Gate, set: () => { done = true }, waits: () => waits }
  }

  it('B-F4：名单为空、服务还没刷新过：列表先有上限地等第一次刷新；新建仍拿不到名单时说"服务还没就绪"', async () => {
    const t = gate()
    const { router } = fakeRouter([], { allowOutsideCase: false, firstRefresh: t.g })
    await router.list()
    expect(t.waits()).toBe(1)
    await expect(router.create(H('x', A))).rejects.toThrow(NOT_READY)
    t.set()
    await expect(router.create(H('x', A))).rejects.toThrow(OUTSIDE_CASE)
  })

  it('B-F4：等的这段时间里名单刷新到了，案件里的会话照常列出、照常新建', async () => {
    let fill: (() => void) | undefined
    let done = false
    const { router, caseRoots, backendOf } = fakeRouter([], {
      allowOutsideCase: false,
      firstRefresh: { done: () => done, wait: () => new Promise<boolean>((resolve) => { fill = () => { caseRoots.replace([{ root: A, exists: true }]); done = true; resolve(true) } }) },
    })
    const created = router.create(H('n', A))
    await new Promise((r) => setTimeout(r, 10))
    fill!()
    await created
    expect([...backendOf(A_STORE).sessions.keys()]).toEqual(['n'])
    expect((await router.list()).map((r) => r.header.id)).toEqual(['n'])
  })

  it('A-P3-5：平时列表不等服务刷新（刷新挂住时列表照常返回）', async () => {
    const { router } = fakeRouter([A], { refresh: () => new Promise<void>(() => {}) })
    await router.create(H('s1', A))
    expect((await router.list()).map((r) => r.header.id)).toEqual(['s1'])
  })

  it('B-F5：某个案件根的 list、stat 挂住：到时跳过它、记一条 ETIMEDOUT 日志，其余照常', async () => {
    const { router, backendOf, logs } = fakeRouter([A, B], { timeoutMs: 50 })
    await router.create(H('a', A)); await router.create(H('b', B))
    backendOf(B_STORE).hang = true
    expect((await router.list()).map((r) => r.header.id)).toEqual(['a'])
    expect(logs.find(([e]) => e === 'session_store.case_root_skipped')?.[1]).toEqual({ index: 2, code: 'ETIMEDOUT' })
    const fresh = fakeRouter([B, A], { timeoutMs: 50 })
    ;(fresh.router as unknown as { all(): unknown }).all()
    fresh.backendOf(B_STORE).hang = true
    fresh.backendOf(A_STORE).sessions.set('a', H('a', A))
    expect((await fresh.router.stat('a'))?.header.id).toBe('a')
  })

  it('B-F6：同一进程里案件搬了家，编号表还指向旧实例：打开、stat 去掉这条再逐个实例找', async () => {
    const OLD = 'D:\\旧\\张三诉李四'
    const { router, backendOf, caseRoots } = fakeRouter([OLD])
    await router.create(H('s1', OLD))
    const moved = backendOf(join(OLD, '工作区', '会话')).sessions
    caseRoots.replace([{ root: A, exists: true }])
    ;(router as unknown as { all(): unknown }).all()
    backendOf(A_STORE).sessions = new Map(moved)
    moved.clear()
    const h = await router.open('s1', 'write')
    expect(h.header.cwd).toBe(A)
    expect(router.ownerOf('s1')).toBe(A)
    const again = fakeRouter([OLD])
    await again.router.create(H('s2', OLD))
    const m2 = again.backendOf(join(OLD, '工作区', '会话')).sessions
    again.caseRoots.replace([{ root: A, exists: true }])
    ;(again.router as unknown as { all(): unknown }).all()
    again.backendOf(A_STORE).sessions = new Map(m2)
    m2.clear()
    expect((await again.router.stat('s2'))?.header.cwd).toBe(A)
  })

  it('第四轮 A-P2-2（复核员 A 的 X3）：名单换掉后编号表里指向旧根的条目作废：刷新前列过一次、刷新后直接续写，落新实例', async () => {
    const OLD = 'D:\\桌面\\案丙'; const NEW = 'D:\\案件盘\\案丙'
    const { router, backendOf, caseRoots } = fakeRouter([OLD])
    ;(router as unknown as { all(): unknown }).all()
    backendOf(join(OLD, '工作区', '会话')).sessions.set('s1', H('s1', OLD)) // 复制：两处都有
    expect((await router.list()).map((r) => r.header.cwd)).toEqual([OLD]) // 缓存还是旧位置时列过一次
    expect(router.ownerOf('s1')).toBe(OLD)
    caseRoots.replace([{ root: NEW, exists: true }]) // 服务刷新：只列新位置
    ;(router as unknown as { all(): unknown }).all()
    backendOf(join(NEW, '工作区', '会话')).sessions.set('s1', H('s1', OLD))
    expect(router.ownerOf('s1')).toBeUndefined() // 投影缓存也不再往旧位置写
    const h = await router.open('s1', 'write')
    expect(h.header.cwd).toBe(NEW)
    expect(router.ownerOf('s1')).toBe(NEW)
    expect((await router.stat('s1'))?.header.cwd).toBe(NEW)
  })

  it('第四轮 B-F1：哪里都找不到时强制刷新一次名单再找（2 秒内只刷一次）', async () => {
    const NEW = 'D:\\案件盘\\案丙'
    let refreshes = 0
    const { router } = fakeRouter([], { refresh: (r) => { refreshes++; r.replace([{ root: NEW, exists: true }]) } })
    // 名单刷新后才有新位置：实例在 all() 时建出，记录放在建出后的新位置实例上
    const origAll = (router as unknown as { all(): Array<{ backend: FakeBackend; caseRoot: string | null }> }).all.bind(router)
    ;(router as unknown as { all(): unknown }).all = () => {
      const stores = origAll()
      for (const st of stores) if (st.caseRoot === NEW) st.backend.sessions.set('s1', H('s1', NEW))
      return stores
    }
    expect((await router.stat('s1'))?.header.cwd).toBe(NEW)
    expect(refreshes).toBe(1)
    expect(await router.stat('nope')).toBeUndefined()
    expect(refreshes).toBe(1) // 2 秒内不再刷
  })

  it('N55 ②：写句柄所属案件根不在名单上、或不在盘上 → 位置失效；根回到名单、盘插回 → 解除；名单刷新失败不误判；关掉的句柄不算', async () => {
    const OLD = realpathSync(mkdtempSync(join(tmpdir(), 'lb-moved-'))); const NEW = OLD + '-新'; const GONE = OLD + '-拔'
    mkdirSync(NEW)
    try {
      // 刷新总是失败（服务不在）：名单不动
      const { router, backendOf, caseRoots } = fakeRouter([OLD], { allowOutsideCase: false, refresh: () => { throw new Error('ECONNREFUSED') } })
      await router.create(H('s1', OLD))
      backendOf(join(OLD, '工作区', '会话')).sessions.set('s2', H('s2', OLD))
      mkdirSync(join(OLD, '工作区', '会话', '项目', 's1'), { recursive: true }) // 假实例不落盘：会话记录目录手建
      const w = await router.open('s1', 'write')
      await router.open('s2', 'read') // 读句柄不记
      expect([router.caseMoved('s1'), router.caseMoved('s2'), router.caseMoved('nope')]).toEqual([false, false, false])
      // 刷新失败：名单不动、根还在盘上，不拒
      await (router as unknown as { opts: { refresh(): Promise<void> } }).opts.refresh().catch(() => undefined)
      expect(router.caseMoved('s1')).toBe(false)
      // 复制后在新位置打开：名单只剩新位置 → 失效；根回到名单（重新打开原位置）→ 解除
      caseRoots.replace([{ root: NEW, exists: true }])
      expect(router.caseMoved('s1')).toBe(true)
      caseRoots.replace([{ root: NEW, exists: true }, { root: OLD, exists: true }])
      expect(router.caseMoved('s1')).toBe(false)
      // 盘暂时不在（根还在名单上）→ 失效；插回 → 解除。新建、原版还没落过盘的会话（盘上本来没有它的记录）同样按"根不在盘上"判
      await router.create(H('s3', OLD)) // 新建：写句柄，盘上还没有记录目录
      expect(router.caseMoved('s3')).toBe(false)
      renameSync(OLD, GONE)
      expect([router.caseMoved('s1'), router.caseMoved('s3')]).toEqual([true, true])
      renameSync(GONE, OLD)
      expect([router.caseMoved('s1'), router.caseMoved('s3')]).toEqual([false, false])
      // 句柄关掉之后不再记（重启后、resume 从新位置打开的是新句柄）
      caseRoots.replace([{ root: NEW, exists: true }])
      await (w.close as () => Promise<void>)()
      expect(router.caseMoved('s1')).toBe(false)
    } finally { for (const d of [OLD, NEW, GONE]) rmSync(d, { recursive: true, force: true }) }
  })

  it('第七轮 B-F4、A-P3-2、A-P3-3：放下时关句柄挂住 → 到时照样记已放下、记一条 writer_detach_failed；接回后代理方法转给新句柄', async () => {
    const OLD = realpathSync(mkdtempSync(join(tmpdir(), 'lb-detach-'))); const NEW = OLD + '-新'
    mkdirSync(NEW)
    try {
      const { router, backendOf, caseRoots, logs } = fakeRouter([OLD], { allowOutsideCase: false, timeoutMs: 100, liveSeq: () => 0 })
      await router.create(H('s1', OLD))
      mkdirSync(join(OLD, '工作区', '会话', '项目', 's1'), { recursive: true }) // 假实例不落盘：会话记录目录手建
      const store = backendOf(join(OLD, '工作区', '会话'))
      store.eventRead = true
      const w = (await router.open('s1', 'write')) as Handle & { serial: number }
      const first = w.serial
      store.hangClose = true
      caseRoots.replace([{ root: NEW, exists: true }]) // 复制后在新位置打开：根不在名单上、还在盘上
      expect(router.writersToRecheck()).toEqual(['s1'])
      const t0 = Date.now()
      await router.recheck('s1')
      expect(Date.now() - t0).toBeLessThan(2000)
      expect([router.caseMoved('s1'), router.writersToRecheck()]).toEqual([true, []])
      expect(logs.find(([e]) => e === 'session_store.writer_detach_failed')?.[1]).toEqual({ index: 1, error: 'Error' })
      // 根回到名单，但以写方式打开挂住：到时放弃这次接回、记 writer_reattach_failed，仍算失效（第八轮复核 B-F5）
      store.hangClose = false
      store.hangOpen = true
      caseRoots.replace([{ root: OLD, exists: true }])
      const t1 = Date.now()
      await router.recheck('s1')
      expect(Date.now() - t1).toBeLessThan(2000)
      expect(router.caseMoved('s1')).toBe(true)
      expect(logs.find(([e]) => e === 'session_store.writer_reattach_failed')?.[1]).toEqual({ index: 1, error: 'Error' })
      // 打开恢复：一样长（盘上 0 条、内存 0 条）→ 在原处接回，代理上的方法转给新开的句柄
      store.hangOpen = false
      await router.recheck('s1')
      expect(router.caseMoved('s1')).toBe(false)
      expect(w.serial).toBeGreaterThan(first)
    } finally { for (const d of [OLD, NEW]) rmSync(d, { recursive: true, force: true }) }
  })

  it('A-P3-3：默认根里已有的旧会话只读，续写拒绝并给同一句中文说明（开关打开时照常）', async () => {
    const off = fakeRouter([A], { allowOutsideCase: false })
    off.backendOf('C:\\dsh\\sessions').sessions.set('old', H('old', 'D:\\别处'))
    expect((await off.router.open('old', 'read')).header.id).toBe('old')
    await expect(off.router.open('old', 'write')).rejects.toThrow(OUTSIDE_CASE)
    await off.router.create(H('c', A))
    expect((await off.router.open('c', 'write')).header.id).toBe('c')
    const on = fakeRouter([A])
    on.backendOf('C:\\dsh\\sessions').sessions.set('old', H('old', 'D:\\别处'))
    expect((await on.router.open('old', 'write')).access).toBe('write')
  })

  it('A-P3-2：flush 也刷各案件实例；两个实例里有同一编号时只交第一个、记一条日志', async () => {
    const { router, backendOf, logs } = fakeRouter([A, B])
    await router.create(H('a', A)); await router.create(H('b', B))
    await router.flush()
    expect([backendOf('C:\\dsh\\sessions').flushed, backendOf(A_STORE).flushed, backendOf(B_STORE).flushed]).toEqual([1, 1, 1])
    backendOf(B_STORE).sessions.set('a', H('a', B))
    const rows = await router.list()
    expect(rows.filter((r) => r.header.id === 'a').map((r) => r.header.cwd)).toEqual([A])
    expect(logs.find(([e]) => e === 'session_store.duplicate_id')?.[1]).toEqual({ index: 2 })
  })
})

// ── 二、接原版 JSONL 包 ────────────────────────────────────────────────────
/** 假的工作台服务：只答 GET /api/case/recent（cases 每次现取），只听 127.0.0.1。 */
async function fakeService(cases: () => Array<{ root: string; exists: boolean }>): Promise<{ port: number; close(): Promise<void> }> {
  const server: Server = createServer((req, res) => {
    const ok = req.url === '/api/case/recent' && req.headers.authorization === 'Bearer t'
    res.setHeader('content-type', 'application/json')
    res.end(JSON.stringify(ok ? { ok: true, value: { cases: cases() } } : { ok: false, error: { code: 'NOT_FOUND', message: 'x' } }))
  })
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
  const port = (server.address() as { port: number }).port
  return { port, close: () => new Promise<void>((resolve) => server.close(() => resolve())) }
}

/**
 * 起会话存储插件（原版 JSONL 包）。给 cases 时同时起假的工作台服务并以 lawbenchCore 提供端点（名单按它刷新）；
 * 不给时没有服务（名单只有缓存）。
 */
async function startStore(appData: string, defaultRoot: string, extra: Record<string, unknown> = {}, cases?: () => Array<{ root: string; exists: boolean }>) {
  const ctx = new cordis.Context()
  const svc = cases ? await fakeService(cases) : undefined
  if (svc) ctx.provide('lawbenchCore', { endpoint: () => ({ port: svc.port, token: 't' }), onState: (fn: (s: string) => void) => { fn('running'); return () => {} } })
  const fiber = await ctx.plugin({ name: storeName, apply: applyStore }, { backend: Jsonl, defaultRoot, appData, compression: 'none', ...extra })
  return { ctx, persistence: ctx.sessionPersistence as Backend, dispose: async () => { await fiber.dispose(); await svc?.close() } }
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
    new CaseRoots(appData).replace([{ root: caseRoot, exists: true }])
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
    const before = readdirSync(home)
    // 服务在、名单按服务刷新（缓存为空）
    const s = await startStore(appData, home, {}, () => [{ root: caseRoot, exists: true }])
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

  it('搬家：案件目录整个改名、服务只列新位置后重启，旧会话能列出（cwd 为新路径）、能打开、能续写，不需要改原版包', async () => {
    const appData = join(tmp, 'appdata'); const home = join(tmp, 'dsh-home', 'sessions')
    const oldRoot = join(tmp, '旧位置', '民事-虚构乙'); const newRoot = join(tmp, '新位置', '民事-虚构乙')
    mkdirSync(oldRoot, { recursive: true })
    new CaseRoots(appData).replace([{ root: oldRoot, exists: true }])
    let s = await startStore(appData, home)
    try {
      const h = await s.persistence.create(meta('moved', oldRoot) as never)
      await (h as unknown as { append(e: unknown): Promise<void> }).append(oneTurnLog().slice(0, 2))
      await (h as unknown as { close(): Promise<void> }).close()
    } finally { await s.dispose() }
    mkdirSync(join(tmp, '新位置'), { recursive: true })
    renameSync(oldRoot, newRoot)
    new CaseRoots(appData).load().replace([{ root: newRoot, exists: true }]) // 真服务按案件编号去重，只列现在的位置
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

  it('B-F1 复制：案件文件夹复制到新位置、服务只列新位置：列出的 cwd 是新根，续写落在新文件夹，旧文件夹一个字节不变', async () => {
    const appData = join(tmp, 'appdata'); const home = join(tmp, 'dsh-home', 'sessions')
    const oldRoot = join(tmp, '桌面', '民事-虚构乙'); const newRoot = join(tmp, '案件盘', '民事-虚构乙')
    mkdirSync(oldRoot, { recursive: true })
    new CaseRoots(appData).replace([{ root: oldRoot, exists: true }])
    let s = await startStore(appData, home)
    try {
      const h = await s.persistence.create(meta('copied', oldRoot) as never)
      await (h as unknown as { append(e: unknown): Promise<void> }).append(oneTurnLog().slice(0, 2))
      await (h as unknown as { close(): Promise<void> }).close()
    } finally { await s.dispose() }
    cpSync(oldRoot, newRoot, { recursive: true })
    const snapshot = (dir: string) => files(dir).map((f) => [f.slice(dir.length), readFileSync(f).toString('base64')].join(':')).sort()
    const oldBefore = snapshot(oldRoot)
    new CaseRoots(appData).load().replace([{ root: newRoot, exists: true }]) // 真服务只列新位置，旧位置不出现
    s = await startStore(appData, home)
    try {
      const rows = (await s.persistence.list()).filter((r) => r.header.id === 'copied')
      expect(rows.map((r) => r.header.cwd)).toEqual([newRoot])
      const w = (await s.persistence.open('copied', 'write')) as unknown as { header: Header; append(e: unknown): Promise<void>; close(): Promise<void> }
      expect(w.header.cwd).toBe(newRoot)
      await w.append(oneTurnLog().slice(2))
      await w.close()
    } finally { await s.dispose() }
    expect(snapshot(oldRoot)).toEqual(oldBefore)
    const newLog = files(join(newRoot, '工作区', '会话')).filter((f) => f.includes('copied'))
    expect(newLog.length).toBeGreaterThan(0)
    expect(snapshot(newRoot)).not.toEqual(oldBefore)
  })

  it('B-F1 纯搬家对照：旧位置已不在、服务只列新位置：照常列出、打开、续写', async () => {
    const appData = join(tmp, 'appdata'); const home = join(tmp, 'dsh-home', 'sessions')
    const oldRoot = join(tmp, 'a', '案甲'); const newRoot = join(tmp, 'b', '案甲')
    mkdirSync(oldRoot, { recursive: true }); mkdirSync(join(tmp, 'b'))
    new CaseRoots(appData).replace([{ root: oldRoot, exists: true }])
    let s = await startStore(appData, home)
    try {
      const h = await s.persistence.create(meta('m', oldRoot) as never)
      await (h as unknown as { append(e: unknown): Promise<void> }).append(oneTurnLog())
      await (h as unknown as { close(): Promise<void> }).close()
    } finally { await s.dispose() }
    renameSync(oldRoot, newRoot)
    new CaseRoots(appData).load().replace([{ root: newRoot, exists: true }])
    s = await startStore(appData, home)
    try {
      expect((await s.persistence.list()).map((r) => [r.header.id, r.header.cwd])).toEqual([['m', newRoot]])
      const w = (await s.persistence.open('m', 'write')) as unknown as { read(): Promise<{ events: unknown[] }>; close(): Promise<void> }
      expect((await w.read()).events).toEqual(oneTurnLog())
      await w.close()
    } finally { await s.dispose() }
  })

  it('第四轮 B-F4：名单为空、服务一直没起来：只有第一次列表等满上限，之后不再等', async () => {
    const appData = join(tmp, 'appdata'); const home = join(tmp, 'dsh-home', 'sessions')
    const ctx = new cordis.Context()
    ctx.provide('lawbenchCore', { endpoint: () => undefined, onState: () => () => {} }) // 服务一直没起来
    const fiber = await ctx.plugin({ name: storeName, apply: applyStore }, { backend: Jsonl, defaultRoot: home, appData, compression: 'none' })
    const p = ctx.sessionPersistence as Backend
    try {
      const times: number[] = []
      for (let i = 0; i < 3; i++) { const t0 = Date.now(); await p.list(); times.push(Date.now() - t0) }
      expect(times[0]).toBeGreaterThanOrEqual(2900)
      expect(Math.max(times[1], times[2])).toBeLessThan(500)
      const t0 = Date.now()
      await expect(p.create(meta('x', join(tmp, '案件')) as never)).rejects.toThrow(NOT_READY)
      expect(Date.now() - t0).toBeLessThan(500)
    } finally { await fiber.dispose() }
  }, 30000)

  it('某个案件根读不出来（路径被占成文件）：列表只跳过它，其余照常', async () => {
    const appData = join(tmp, 'appdata'); const home = join(tmp, 'dsh-home', 'sessions')
    const good = join(tmp, '好的案件'); const bad = join(tmp, '坏的案件')
    mkdirSync(good, { recursive: true }); mkdirSync(bad, { recursive: true })
    new CaseRoots(appData).replace([{ root: good, exists: true }, { root: bad, exists: true }])
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

// ── 三、DSH 的存储契约整套对路由再跑三遍 ──────────────────────────────────
runPersistenceContract('lawbench-session-store（默认根）', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'lb-store-contract-'))
  // 契约用例的会话 cwd 不在任何案件里，按开关打开跑（验的是原版实例经路由转发的语义）
  const s = await startStore(join(dir, 'appdata'), join(dir, 'sessions'), { allowOutsideCase: true })
  return { persistence: s.persistence as never, dispose: async () => { await s.dispose(); rmSync(dir, { recursive: true, force: true }) } } as never
})

/**
 * 契约用例的会话 cwd 只有 '/work' 和不给两种。这里把它们换到案件里（to），交出来的记录头再换回原样，
 * 让整套用例走案件实例、编号表和记录头改写那条路（A-P3-2）；开关关着（N46 ②），不在案件里的会话一个也不建。
 */
function inCase(p: Backend, to: string): Backend {
  const orig = new Map<string, string | undefined>()
  const back = (h: Header): Header => {
    if (!orig.has(h.id)) return h
    const o = orig.get(h.id)
    const { cwd: _cwd, ...rest } = h
    return Object.freeze(o === undefined ? rest : { ...rest, cwd: o }) as Header
  }
  const wrap = <T extends { header: Header }>(x: T): T => {
    const header = back(x.header)
    return new Proxy(x, { get: (t, k) => { if (k === 'header') return header; const v = Reflect.get(t, k, t); return typeof v === 'function' ? v.bind(t) : v } })
  }
  return {
    create: async (h, o) => { orig.set(h.id, h.cwd); return wrap(await p.create({ ...h, cwd: to }, o)) },
    open: async (id, a, o) => wrap(await p.open(id, a, o)),
    flush: () => p.flush(),
    stat: async (id, o) => { const r = await p.stat(id, o); return r && { ...r, header: back(r.header) } },
    list: async (o) => (await p.list(o)).map((r) => ({ ...r, header: back(r.header) })),
  }
}

for (const [label, sub] of [['案件根', ''], ['案件根下子目录（记录头改写，同搬家后）', '子目录']] as const) {
  runPersistenceContract(`lawbench-session-store（${label}）`, async () => {
    const dir = realpathSync(mkdtempSync(join(tmpdir(), 'lb-store-contract-')))
    const caseRoot = join(dir, '刑事-虚构丁')
    mkdirSync(join(caseRoot, sub), { recursive: true })
    new CaseRoots(join(dir, 'appdata')).replace([{ root: caseRoot, exists: true }])
    const s = await startStore(join(dir, 'appdata'), join(dir, 'sessions'))
    return {
      persistence: inCase(s.persistence, join(caseRoot, sub)) as never,
      dispose: async () => {
        await s.dispose()
        // 记录全在案件文件夹里，默认根一个也没有
        expect(files(join(dir, 'sessions'))).toEqual([])
        rmSync(dir, { recursive: true, force: true })
      },
    } as never
  })
}

// ── 第十轮（改编自复核员 B 第九轮 zz-rvb31-f5：F5a、F5b）与编号编码 ─────────────────────
describe('第十轮：接回的上限与迟到句柄、记录目录编码', () => {
  /** 一个根、一份"已落盘"的会话 s1；第二次起的打开可迟到、读可挂住、关可挂住（第一次是交给 DSH 的写句柄）。 */
  function lab(mode: { openDelay?: number; readHang?: boolean; closeHang?: boolean }) {
    const tmp = realpathSync(mkdtempSync(join(tmpdir(), 'lb-r10-')))
    const OLD = join(tmp, 'old')
    mkdirSync(join(OLD, '工作区', '会话', 'proj', 's1'), { recursive: true })
    const caseRoots = new CaseRoots()
    caseRoots.replace([{ root: OLD, exists: true }])
    let n = 0
    let closes = 0
    const opened: number[] = []
    const backend = (root: string): Backend => ({
      async create(h: Header) { return { id: h.id, header: h, access: 'write', close: async () => { closes++ }, read: async () => ({ events: [] }) } },
      async open(id: string, access: 'read' | 'write') {
        const k = ++n
        if (k > 1 && mode.openDelay) await new Promise((r) => setTimeout(r, mode.openDelay))
        opened.push(k)
        return {
          id, header: H(id, OLD), access,
          close: async () => { if (mode.closeHang && k > 1) await new Promise(() => {}); closes++ },
          read: async () => { if (mode.readHang && k > 1) await new Promise(() => {}); return { events: [] } },
        }
      },
      async flush() {},
      async stat(id: string) { return root.includes('工作区') ? { header: H(id, OLD) } : undefined },
      async list() { return [] },
    })
    const logs: string[] = []
    const router = new SessionRouter(backend, caseRoots, {
      defaultRoot: join(tmp, 'home'), allowOutsideCase: false, caseRootTimeoutMs: 100, liveSeq: () => 0, log: (_l, e) => { logs.push(e) },
    })
    return { tmp, OLD, router, caseRoots, logs, opened, closes: () => closes }
  }

  it('F5b / R10-2：接回时读挂住、关新句柄也挂住 → recheck 到时返回，同一会话下一次 recheck 不被卡住', async () => {
    const { tmp, OLD, router, caseRoots, logs } = lab({ readHang: true, closeHang: true })
    try {
      await router.open('s1', 'write')
      caseRoots.replace([{ root: join(tmp, 'other'), exists: true }]); await router.recheck('s1') // 根不在名单上、还在盘上 → 放下（空名单会被名单保护挡下，换一个根）
      caseRoots.replace([{ root: OLD, exists: true }])
      const race = (p: Promise<void>, ms: number) => Promise.race([p.then(() => 'returned'), new Promise((r) => setTimeout(() => r('STUCK'), ms))])
      expect(await race(router.recheck('s1'), 1500)).toBe('returned')
      expect(await race(router.recheck('s1'), 1500)).toBe('returned')
      expect(router.caseMoved('s1')).toBe(true) // 没接回
      expect(logs).toContain('session_store.writer_reattach_failed') // 读到时（第九轮复核 A-P3-2）
    } finally { rmSync(tmp, { recursive: true, force: true }) }
  })

  it('F5a / 第九轮 B-F5：接回时打开到时 → 不接回；那次打开迟到返回的句柄随后被关掉', async () => {
    const { tmp, OLD, router, caseRoots, closes } = lab({ openDelay: 400 })
    try {
      await router.open('s1', 'write')
      caseRoots.replace([{ root: join(tmp, 'other'), exists: true }]); await router.recheck('s1')
      expect(router.caseMoved('s1')).toBe(true)
      const afterDetach = closes()
      caseRoots.replace([{ root: OLD, exists: true }])
      await router.recheck('s1')
      expect(router.caseMoved('s1')).toBe(true)
      await new Promise((r) => setTimeout(r, 600))
      expect(closes()).toBe(afterDetach + 1)
    } finally { rmSync(tmp, { recursive: true, force: true }) }
  })

  it('A-P3-3：记录目录名的编码与原版 encodeSegment 一致（含 ~、中文、点、空格、. 与 ..）；空串报错', async () => {
    const orig = (await import(/* @vite-ignore */ join(__dirname, '..', '..', 'dsh', 'packages', 'session', 'session-persistence-jsonl', 'src', 'format.ts'))) as { encodeSegment(raw: string): string }
    for (const raw of ['s1', 'a~b', '会话-01', 'x.y', 'a b', '.', '..', '…~.', 'A_z-9.0']) expect([raw, encodeSegment(raw)]).toEqual([raw, orig.encodeSegment(raw)])
    expect(() => encodeSegment('')).toThrow()
    expect(() => orig.encodeSegment('')).toThrow()
  })
})

describe('T14 派修 4：工作台 Host 插件起不来时记一条元数据错误', () => {
  let tmp: string
  beforeEach(() => { tmp = mkdtempSync(join(tmpdir(), 'lb-store-host-')) })
  afterEach(() => { vi.useRealTimers(); rmSync(tmp, { recursive: true, force: true }) })
  const logged = (appData: string) => files(join(appData, 'logs')).map((f) => readFileSync(f, 'utf8')).join('')

  it('启动 30 秒后仍没有 lawbenchCore：记 session_store.host_missing（只有秒数）；有 Host 时不记', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    const without = join(tmp, 'a'); const withHost = join(tmp, 'b')
    const s1 = await startStore(without, join(tmp, 'h1'))
    const s2 = await startStore(withHost, join(tmp, 'h2'), {}, () => [])
    try {
      vi.advanceTimersByTime(29_000)
      expect(logged(without)).not.toContain('host_missing')
      vi.advanceTimersByTime(2_000)
      expect(logged(without)).toContain('"event":"session_store.host_missing","after_s":30')
      expect(logged(withHost)).not.toContain('host_missing')
    } finally { await s1.dispose(); await s2.dispose() }
  })
})
