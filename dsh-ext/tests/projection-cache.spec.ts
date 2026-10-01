// 会话投影缓存按案件存（T17 第三轮综合裁决 A-P2-1 = B-F3 ①）：
// 一、替身表本身：落盘位置、默认根只放内存、读坏当没有、搬家后身份 cwd 换成现根、写失败不抛；
// 二、DSH 原版缓存类（SessionProjectionCache，已构建的 lib）经会话存储插件接上：写下的标题重启后冷会话能读到，
//     记录在 <案件>\工作区\会话缓存，案件搬家后照样读到；$DSH_HOME 下没有任何缓存文件。
import { createRequire } from 'node:module'
import { existsSync, mkdirSync, mkdtempSync, readdirSync, realpathSync, renameSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { CaseRoots } from '../session-store/case-roots.ts'
import { CASE_CACHE_DIR, CaseProjectionTable, type CacheRecord } from '../session-store/projection-cache.ts'
import { apply as applyStore, name as storeName } from '../session-store/index.ts'

const JSONL_PKG = join(__dirname, '..', '..', 'dsh', 'packages', 'session', 'session-persistence-jsonl')
const CACHE_PKG = join(__dirname, '..', '..', 'dsh', 'packages', 'session', 'session-projection-cache')
const cordis = (await import(/* @vite-ignore */ realpathSync(createRequire(join(JSONL_PKG, 'package.json')).resolve('@deepseek-ai/cordis')))) as { Context: new () => any }
const Jsonl = ((await import(/* @vite-ignore */ realpathSync(join(JSONL_PKG, 'lib', 'index.js')))) as { default: unknown }).default
// 会话记录头与一轮记录借 DSH 存储契约用例的（与 session-store.spec 同）
const CONTRACT = join(__dirname, '..', '..', 'dsh', 'packages', 'session', 'session-persistence', 'tests', 'contract.ts')
const { meta, oneTurnLog } = (await import(/* @vite-ignore */ CONTRACT)) as { meta(id: string, cwd?: string): { id: string; cwd?: string }; oneTurnLog(): unknown[] }
const CacheMod = (await import(/* @vite-ignore */ realpathSync(join(CACHE_PKG, 'lib', 'index.js')))) as {
  default: unknown; checkpointRecord: { safeParse(v: unknown): { success: boolean; data?: unknown } }
}

function files(dir: string): string[] {
  if (!existsSync(dir)) return []
  return readdirSync(dir, { recursive: true, withFileTypes: true }).filter((e) => e.isFile()).map((e) => join(e.parentPath, e.name))
}

const rec = (cwd: string, title = '标题甲'): CacheRecord => ({
  identity: { formatVersion: 3, createdAt: 1, cwd, isSeeded: false, inheritedEventCount: 0 },
  rows: { title: { ver: 1, seq: 3, val: title } },
})
const parse = (v: unknown) => { const r = CacheMod.checkpointRecord.safeParse(v); return r.success ? (r.data as CacheRecord) : undefined }

let tmp: string
beforeEach(() => { tmp = realpathSync(mkdtempSync(join(tmpdir(), 'lb-projcache-'))) })
afterEach(() => { rmSync(tmp, { recursive: true, force: true }) })

describe('替身表', () => {
  it('案件里的会话落在 <案件>\\工作区\\会话缓存\\<编号>.json，新实例读得到；默认根和不知道在哪的只放内存', async () => {
    const A = join(tmp, '案甲')
    const owners: Record<string, string | null> = { s1: A, s0: null }
    const t = new CaseProjectionTable({ caseRootOf: (id) => owners[id], parse })
    await t.put('s1', rec(A)); await t.put('s0', rec(join(tmp, '别处'))); await t.put('sx', rec(A))
    expect(files(tmp).map((f) => f.slice(tmp.length))).toEqual([join('\\案甲', CASE_CACHE_DIR, 's1.json')])
    expect([t.get('s0')?.rows, t.get('sx')?.rows]).toEqual([rec('').rows, rec('').rows])
    const t2 = new CaseProjectionTable({ caseRootOf: (id) => owners[id], parse })
    expect(t2.get('s1')).toEqual(rec(A))
    expect(t2.get('s0')).toBeUndefined()
  })

  it('读坏、不合格的记录当没有并记日志（不带路径）；编号不能当文件名时只放内存', async () => {
    const A = join(tmp, '案甲')
    mkdirSync(join(A, CASE_CACHE_DIR), { recursive: true })
    writeFileSync(join(A, CASE_CACHE_DIR, 'bad.json'), '{坏')
    writeFileSync(join(A, CASE_CACHE_DIR, 'odd.json'), JSON.stringify({ identity: {}, rows: { title: { ver: 'x' } } }))
    const logs: Array<[string, unknown]> = []
    const t = new CaseProjectionTable({ caseRootOf: () => A, parse, log: (_l, e, m) => { logs.push([e, m]) } })
    expect([t.get('bad'), t.get('odd')]).toEqual([undefined, undefined])
    expect(logs.map(([e]) => e).sort()).toEqual(['session_store.projection_cache_invalid', 'session_store.projection_cache_unreadable'])
    expect(JSON.stringify(logs)).not.toContain('案甲')
    await t.put('../x', rec(A))
    expect(files(tmp).some((f) => f.includes('x.json'))).toBe(false)
    expect(t.get('../x')).toBeDefined()
  })

  it('搬家后读出的身份 cwd 换成现根（记录就在这个案件的文件夹里）；同根不同写法不改', async () => {
    const oldA = join(tmp, '旧', '案甲'); const newA = join(tmp, '新', '案甲')
    let root = oldA
    const t = new CaseProjectionTable({ caseRootOf: () => root, parse })
    await t.put('s1', rec(oldA))
    mkdirSync(join(tmp, '新'))
    renameSync(oldA, newA)
    root = newA
    const t2 = new CaseProjectionTable({ caseRootOf: () => root, parse })
    expect(t2.get('s1')?.identity.cwd).toBe(newA)
    await t2.put('s2', rec(newA.toUpperCase()))
    expect(new CaseProjectionTable({ caseRootOf: () => root, parse }).get('s2')?.identity.cwd).toBe(newA.toUpperCase())
  })

  it('写不进去：不抛、记一条只带错误码的日志、内存也不改', async () => {
    writeFileSync(join(tmp, '是文件'), 'x')
    const logs: Array<[string, unknown]> = []
    const t = new CaseProjectionTable({ caseRootOf: () => join(tmp, '是文件'), parse, log: (_l, e, m) => { logs.push([e, m]) } })
    await expect(t.put('s1', rec(tmp))).resolves.toBeUndefined()
    expect(logs.map(([e]) => e)).toEqual(['session_store.projection_cache_write_failed'])
    expect(JSON.stringify(logs)).not.toContain('是文件')
    expect(t.get('s1')).toBeUndefined()
  })
})

describe('接 DSH 原版投影缓存类', () => {
  /** 起会话存储插件 + 原版缓存类；sessionProjections、sessions 用最小的替身（只用到这几个方法）。 */
  async function start(appData: string, home: string) {
    const ctx = new cordis.Context()
    ctx.provide('sessionProjections', {
      checkpoint: (s: { title: string }) => ({ title: { ver: 1, seq: 3, val: s.title } }),
      viewCheckpoint: (rows: Record<string, { val: unknown }>, keys?: string[]) =>
        Object.fromEntries(Object.entries(rows).filter(([k]) => !keys || keys.includes(k)).map(([k, r]) => [k, r.val])),
    })
    ctx.provide('sessions', { get: () => undefined, flush: async () => {} })
    const fiber = await ctx.plugin({ name: storeName, apply: applyStore }, {
      backend: Jsonl, defaultRoot: home, appData, compression: 'none',
      projectionCache: { impl: CacheMod.default, writeEveryEvents: 200, writeIntervalMs: 5000 },
    })
    for (let i = 0; i < 100 && !ctx.get('sessionProjectionCache'); i++) await new Promise((r) => setTimeout(r, 10))
    return { ctx, persistence: ctx.sessionPersistence, cache: ctx.get('sessionProjectionCache'), dispose: () => fiber.dispose() }
  }

  it('标题写进案件文件夹；重启后冷会话从缓存拿到标题；案件搬家后照样拿到；$DSH_HOME 下没有缓存文件', async () => {
    const appData = join(tmp, 'appdata'); const home = join(tmp, 'dsh-home', 'sessions')
    const oldA = join(tmp, '旧', '民事-虚构乙'); const newA = join(tmp, '新', '民事-虚构乙')
    mkdirSync(oldA, { recursive: true })
    new CaseRoots(appData).replace([{ root: oldA, exists: true }])
    let s = await start(appData, home)
    try {
      expect(s.cache).toBeDefined()
      const h = await s.persistence.create(meta('s1', oldA))
      await h.append(oneTurnLog())
      // 原版缓存在建会话、一轮结束、会话退出时写；这里直接调它的 write（同一条路径）
      await s.cache.write({ id: 's1', header: h.header, inheritedEventCount: 0, title: '借款合同纠纷' })
      await h.close()
    } finally { await s.dispose() }
    expect(files(join(oldA, CASE_CACHE_DIR)).map((f) => f.slice(oldA.length))).toEqual([join('\\', CASE_CACHE_DIR, 's1.json')])

    s = await start(appData, home)
    try {
      const row = (await s.persistence.list()).find((r: { header: { id: string } }) => r.header.id === 's1')
      expect(s.cache.cachedSnapshot(row.header)?.values).toEqual({ title: '借款合同纠纷' })
    } finally { await s.dispose() }

    mkdirSync(join(tmp, '新'))
    renameSync(oldA, newA)
    new CaseRoots(appData).load().replace([{ root: newA, exists: true }])
    s = await start(appData, home)
    try {
      const row = (await s.persistence.list()).find((r: { header: { id: string } }) => r.header.id === 's1')
      expect(row.header.cwd).toBe(newA)
      expect(s.cache.cachedSnapshot(row.header)?.values).toEqual({ title: '借款合同纠纷' })
    } finally { await s.dispose() }
    expect(files(join(tmp, 'dsh-home'))).toEqual([])
    expect(files(appData).map((f) => f.slice(appData.length))).not.toContain(expect.stringContaining('s1'))
  })
})
