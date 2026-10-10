// @vitest-environment jsdom
// 令 2125：左栏"从列表移除案件"后，首页的案件卡片和"切换案件"也不再列它；再次打开同一文件夹就恢复。
// 记录在 Host 的应用数据目录（hidden-cases.json）；没有对应登记的位置忽略；记录文件损坏按空处理。
import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { addHidden, dropHidden, HIDDEN_FILE, readHidden } from '../host/hidden-cases.ts'
import { LawbenchRemote } from '../host/index.ts'
import type { DeskDeps } from '../host/desk-actions.ts'
import type { Supervisor } from '../host/supervisor.ts'
import { CaseSwitcher } from '../ui/case-switcher.tsx'
import { loadRecent } from '../ui/cases.ts'
import { removedPaths, visibleCases, watchRemovedCases } from '../ui/hidden-cases.ts'
import { HomeLanding } from '../ui/home-page.tsx'
import { setNav, type Nav } from '../ui/kit.tsx'
import { app, rememberCase, setApi, type CaseRef, type LawbenchApi } from '../ui/state.ts'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const A: CaseRef = { case_id: 'a', name: '张某甲诈骗案', root: 'D:\\案件\\张某甲诈骗案', exists: true, last_opened: '2026-10-03T10:00:00+08:00' }
const B: CaseRef = { case_id: 'b', name: '李某合同纠纷', root: 'D:\\案件\\李某合同纠纷', exists: true, last_opened: '2026-10-04T10:00:00+08:00' }
const D: CaseRef = { case_id: 'd', name: '日常事务', root: 'D:\\文档\\日常事务', exists: true, last_opened: '2026-10-01T10:00:00+08:00' }

let dir: string
beforeEach(() => { dir = mkdtempSync(join(tmpdir(), 'lb-hidden-')) })
afterEach(() => { rmSync(dir, { recursive: true, force: true }) })

describe('Host：已从列表移除的案件（记录文件）', () => {
  it('记下、读回、重复记不多一条；再次打开（按 case_id，或同一位置）去掉记录', () => {
    const file = join(dir, HIDDEN_FILE)
    expect(readHidden(file)).toEqual([])
    expect(addHidden(file, { case_id: 'a', root: A.root })).toEqual([{ case_id: 'a', root: A.root }])
    expect(addHidden(file, { case_id: 'a', root: A.root }).length).toBe(1)
    addHidden(file, { case_id: 'b', root: B.root })
    expect(readHidden(file).map((c) => c.case_id)).toEqual(['a', 'b'])
    expect(dropHidden(file, 'a', undefined)).toBe(1)
    // 同一位置换了 case_id（文件夹里的案件库重建过）：旧记录一并去掉；路径不分大小写、正反斜杠
    expect(dropHidden(file, 'b2', 'd:/案件/李某合同纠纷/')).toBe(1)
    expect(readHidden(file)).toEqual([])
  })

  it('没有记录时再次打开不写文件', () => {
    const file = join(dir, HIDDEN_FILE)
    expect(dropHidden(file, 'a', A.root)).toBe(0)
    expect(existsSync(file)).toBe(false)
  })

  it('记录文件损坏、格式不对：按空处理，之后照常能记', () => {
    const file = join(dir, HIDDEN_FILE)
    for (const text of ['{不是 JSON', '[]', '{"v":1,"cases":"x"}', '{"v":1,"cases":[{"case_id":1,"root":"D:\\\\x"},null,{"case_id":"","root":"D:\\\\y"}]}']) {
      writeFileSync(file, text, 'utf8')
      expect(readHidden(file)).toEqual([])
    }
    writeFileSync(file, '{坏的', 'utf8')
    expect(addHidden(file, { case_id: 'a', root: A.root })).toEqual([{ case_id: 'a', root: A.root }])
    expect(JSON.parse(readFileSync(file, 'utf8'))).toEqual({ v: 1, cases: [{ case_id: 'a', root: A.root }] })
  })
})

describe('Host 方法 caseHide / caseHidden', () => {
  const up = { endpoint: () => ({ port: 1, token: 't' }), state: 'running' } as unknown as Supervisor
  function remote(cases: CaseRef[], recentOk = true) {
    const logs: Array<[string, string, unknown]> = []
    const r = new LawbenchRemote(up, dir, () => undefined, [], (level, event, meta) => { logs.push([level, event, meta]) })
    r.desk = { realpath: (p: string) => p } as unknown as DeskDeps
    const opened: Record<string, string> = {}
    ;(r as unknown as { callApi: (route: { method: string }, body: unknown) => Promise<unknown> }).callApi = async (route, body) => {
      if (route.method === 'caseRecent') return recentOk ? { ok: true, value: { cases } } : { ok: false, error: { code: 'SERVICE_UNAVAILABLE', message: 'x' } }
      if (route.method === 'caseOpen') {
        const path = (body as { path: string }).path
        const c = cases.find((x) => x.root === path)
        return c ? { ok: true, value: { case_id: opened[path] ?? c.case_id, name: c.name, created: false, folders_created: [] } } : { ok: false, error: { code: 'CASE_IN_SYNC_FOLDER', message: 'x' } }
      }
      return { ok: false, error: { code: 'X', message: 'x' } }
    }
    ;(r as unknown as { refreshCaseRoots: () => Promise<void> }).refreshCaseRoots = async () => undefined
    return { r: r as LawbenchRemote & { caseOpen(request: unknown): Promise<{ ok: boolean }> }, logs }
  }

  it('移除一个登记过的案件：记下并回现在记着的；再打开同一文件夹成功后去掉', async () => {
    const { r, logs } = remote([A, B])
    expect(await r.caseHidden()).toEqual({ ok: true, value: { case_ids: [] } })
    // 位置写法不同（大小写、斜杠）也认得出
    expect(await r.caseHide({ root: 'd:/案件/张某甲诈骗案' })).toEqual({ ok: true, value: { hidden: true, case_ids: ['a'] } })
    expect(await r.caseHidden()).toEqual({ ok: true, value: { case_ids: ['a'] } })
    expect(JSON.parse(readFileSync(join(dir, HIDDEN_FILE), 'utf8')).cases).toEqual([{ case_id: 'a', root: A.root }])
    // 打开别的案件不影响它
    expect((await r.caseOpen({ path: B.root, template: null })).ok).toBe(true)
    expect((await r.caseHidden()).value.case_ids).toEqual(['a'])
    expect((await r.caseOpen({ path: A.root, template: null })).ok).toBe(true)
    expect((await r.caseHidden()).value.case_ids).toEqual([])
    // 日志只有事件名和个数，没有路径、案件名
    expect(JSON.stringify(logs)).not.toMatch(/案件|诈骗|D:/)
    expect(logs.filter((l) => l[1] === 'case.hide')).toEqual([['info', 'case.hide', { hidden: true, total: 1 }]])
  })

  it('没有对应登记的位置：忽略，不写记录', async () => {
    const { r } = remote([A])
    expect(await r.caseHide({ root: 'D:\\别处\\没登记过' })).toEqual({ ok: true, value: { hidden: false, case_ids: [] } })
    expect(existsSync(join(dir, HIDDEN_FILE))).toBe(false)
  })

  it('打开没成功：记录不动', async () => {
    const { r } = remote([A])
    await r.caseHide({ root: A.root })
    expect((await r.caseOpen({ path: 'D:\\OneDrive\\别的', template: null })).ok).toBe(false)
    expect((await r.caseHidden()).value.case_ids).toEqual(['a'])
  })

  it('参数不对、服务读不到登记：回错误，不写记录', async () => {
    expect(await remote([A]).r.caseHide({ root: 7 })).toMatchObject({ ok: false, error: { code: 'INVALID_ARGUMENT' } })
    expect(await remote([A], false).r.caseHide({ root: A.root })).toMatchObject({ ok: false, error: { code: 'SERVICE_UNAVAILABLE' } })
    expect(existsSync(join(dir, HIDDEN_FILE))).toBe(false)
  })

  it('记录文件损坏：caseHidden 回空，caseHide 照常记', async () => {
    writeFileSync(join(dir, HIDDEN_FILE), '{坏的', 'utf8')
    const { r } = remote([A])
    expect(await r.caseHidden()).toEqual({ ok: true, value: { case_ids: [] } })
    expect((await r.caseHide({ root: A.root })).ok).toBe(true)
    expect((await r.caseHidden()).value.case_ids).toEqual(['a'])
  })
})

describe('界面：盯着左栏的案件列表', () => {
  type Item = { workspaceId: string; path: string }
  function fakeList(items: Item[], state = 'idle') {
    let snap = { items, state }
    const fns = new Set<() => void>()
    return {
      getSnapshot: () => snap,
      subscribe: (fn: () => void) => { fns.add(fn); return () => { fns.delete(fn) } },
      set: (next: Item[], st = 'idle') => { snap = { items: next, state: st }; for (const fn of fns) fn() },
      listeners: () => fns.size,
    }
  }
  const wa = { workspaceId: 'wa', path: A.root }
  const wb = { workspaceId: 'wb', path: B.root }
  const wd = { workspaceId: 'wd', path: D.root }
  afterEach(() => { app.set((s) => ({ ...s, cases: [], hiddenCases: [], dailyRoot: null })) })

  it('少了哪些位置：同一位置还有别的项留着的不算', () => {
    expect(removedPaths([wa, wb], [wb])).toEqual([A.root])
    expect(removedPaths([wa, wb], [wa, wb])).toEqual([])
    expect(removedPaths([wa, wb], [wb, { workspaceId: 'wa2', path: 'd:/案件/张某甲诈骗案/' }])).toEqual([])
  })

  it('律师移除一项：告诉 Host 那个位置；新增、顺序变化不触发；停止后不再盯', () => {
    const list = fakeList([wa, wb])
    const hidden: string[] = []
    const stop = watchRemovedCases(list, new Set(), async (root) => { hidden.push(root) })
    list.set([wb, wa])
    list.set([wb, wa, wd])
    expect(hidden).toEqual([])
    list.set([wb, wd])
    expect(hidden).toEqual([A.root])
    stop()
    expect(list.listeners()).toBe(0)
    list.set([wd])
    expect(hidden).toEqual([A.root])
  })

  it('程序自己撤掉的项、"日常事务"不记', () => {
    app.set((s) => ({ ...s, dailyRoot: D.root }))
    const list = fakeList([wa, wb, wd])
    const own = new Set<string>()
    const hidden: string[] = []
    watchRemovedCases(list, own, async (root) => { hidden.push(root) })
    own.add('wa')
    list.set([wb, wd])
    list.set([wb])
    expect(hidden).toEqual([])
    list.set([])
    expect(hidden).toEqual([B.root])
  })

  it('连接断开重连中的列表不比、也不当成基准：重连后整份换新时只按读全了的两次比', () => {
    const list = fakeList([], 'loading')
    const hidden: string[] = []
    watchRemovedCases(list, new Set(), async (root) => { hidden.push(root) })
    list.set([wa, wb])
    expect(hidden).toEqual([])
    list.set([], 'loading')
    list.set([], 'error')
    expect(hidden).toEqual([])
    list.set([wa, wb])
    expect(hidden).toEqual([])
    list.set([wa])
    expect(hidden).toEqual([B.root])
  })

  it('Host 没能记下（抛错）不影响后面的', () => {
    const list = fakeList([wa, wb])
    const hidden: string[] = []
    watchRemovedCases(list, new Set(), async (root) => { hidden.push(root); throw new Error('x') })
    list.set([wb])
    list.set([])
    expect(hidden).toEqual([A.root, B.root])
  })
})

describe('界面：首页和"切换案件"不列已移除的案件，重开后恢复', () => {
  let root: Root | undefined
  let box: HTMLDivElement
  let hiddenNow: string[]
  beforeEach(() => {
    box = document.createElement('div'); document.body.appendChild(box)
    hiddenNow = []
    setNav({ goHome: () => {}, openCaseWorkspace: async () => undefined, openTab: () => {}, seedTabs: () => {}, pathFor: () => '' } as unknown as Nav)
    setApi({
      caseRecent: async () => ({ ok: true, value: { cases: [A, B, D] } }),
      caseHidden: async () => ({ ok: true, value: { case_ids: hiddenNow } }),
      caseHide: async () => { hiddenNow = ['b']; return { ok: true, value: { hidden: true, case_ids: hiddenNow } } },
      caseOpen: async () => { hiddenNow = []; return { ok: true, value: { case_id: 'b', name: B.name, created: false, folders_created: [] } } },
      getCapsules: async () => ({ ok: true, value: { v: 1, hint: '', shared: [], groups: [] } }),
      materialsList: async () => ({ ok: true, value: { materials: [] } }),
      outputsList: async () => ({ ok: true, value: { outputs: [] } }),
    } as unknown as LawbenchApi)
  })
  afterEach(async () => {
    await act(async () => { root?.unmount() }); root = undefined; box.remove(); setNav(undefined); setApi(undefined)
    app.set((s) => ({ ...s, cases: [], hiddenCases: [], currentRoot: null, dailyRoot: null, lawyerName: null }))
  })
  const settle = async () => { for (let i = 0; i < 6; i++) await act(async () => { await Promise.resolve() }) }
  const names = () => [...box.querySelectorAll('[data-lawbench-case-switcher] [role=menuitem]')].map((b) => b.textContent)

  it('visibleCases：去掉记着的；没有记着的原样返回', () => {
    expect(visibleCases([A, B], ['b'])).toEqual([A])
    const all = [A, B]
    expect(visibleCases(all, [])).toBe(all)
  })

  it('读案件列表时一并读 Host 记着的；读不到时沿用上次的', async () => {
    hiddenNow = ['b']
    await loadRecent()
    expect(app.get().hiddenCases).toEqual(['b'])
    expect(app.get().cases.map((c) => c.case_id).sort()).toEqual(['a', 'b', 'd']) // cases 里仍留着：开着的会话照样认得出案件
    setApi({ caseRecent: async () => ({ ok: true, value: { cases: [A, B, D] } }) } as unknown as LawbenchApi)
    await loadRecent()
    expect(app.get().hiddenCases).toEqual(['b'])
  })

  it('移除后首页和"切换案件"都不列；重新打开后两处都恢复', async () => {
    app.set((s) => ({ ...s, currentRoot: A.root, dailyRoot: D.root }))
    root = createRoot(box)
    await act(async () => { root!.render(createElement('div', null, createElement(CaseSwitcher), createElement(HomeLanding))) })
    await settle()
    const openMenu = async () => { await act(async () => { ([...box.querySelectorAll('button')].find((b) => b.textContent === '切换案件 ▾') as HTMLElement).click() }) }
    const home = () => box.querySelector('[aria-label="最近案件"]')?.textContent ?? ''
    await openMenu()
    expect(names()).toEqual(['李某合同纠纷', '日常事务', '首页…'])
    expect(home()).toContain('李某合同纠纷')

    // 律师在左栏把"李某合同纠纷"从列表移除
    const list = { snap: { items: [{ workspaceId: 'wa', path: A.root }, { workspaceId: 'wb', path: B.root }], state: 'idle' }, fn: undefined as (() => void) | undefined,
      getSnapshot() { return this.snap }, subscribe(fn: () => void) { this.fn = fn; return () => {} } }
    watchRemovedCases(list, new Set())
    list.snap = { items: [{ workspaceId: 'wa', path: A.root }], state: 'idle' }
    await act(async () => { list.fn!() })
    await settle()
    expect(app.get().hiddenCases).toEqual(['b'])
    expect(names()).toEqual(['日常事务', '首页…'])
    expect(home()).not.toContain('李某合同纠纷')
    expect(home()).toContain('张某甲诈骗案')

    // 再次打开同一文件夹（拖回来、左栏添加、"打开案件…"都走 case_open）
    await act(async () => { rememberCase({ ...B }) })
    await settle()
    expect(app.get().hiddenCases).toEqual([])
    expect(names()).toEqual(['李某合同纠纷', '日常事务', '首页…'])
    expect(home()).toContain('李某合同纠纷')
  })
})
