// @vitest-environment jsdom
// 令 1515 第 2 条：侧栏"案件：xxx"删掉，当前案件在对话区顶部——案件名＋"切换案件 ▾"（最近案件＋"首页…"），日常事务写"（非办案）"。
import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { CaseSwitcher, switchTargets } from '../ui/case-switcher.tsx'
import { setNav, type Nav } from '../ui/kit.tsx'
import { app, setApi, type CaseRef, type LawbenchApi } from '../ui/state.ts'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
let root: Root | undefined
let box: HTMLDivElement
beforeEach(() => { box = document.createElement('div'); document.body.appendChild(box) })
afterEach(async () => { await act(async () => { root?.unmount() }); root = undefined; box.remove(); setNav(undefined); setApi(undefined); app.set((s) => ({ ...s, cases: [], currentRoot: null, dailyRoot: null })) })

const A: CaseRef = { case_id: 'a', name: '张某甲诈骗案', root: 'D:\案件\张某甲诈骗案', last_opened: '2026-10-03T10:00:00+08:00' }
const B: CaseRef = { case_id: 'b', name: '李某合同纠纷', root: 'D:\案件\李某合同纠纷', last_opened: '2026-10-04T10:00:00+08:00' }
const D: CaseRef = { case_id: 'd', name: '日常事务', root: 'D:\文档\日常事务', last_opened: '2026-10-01T10:00:00+08:00' }
const render = async () => { root = createRoot(box); await act(async () => { root!.render(createElement(CaseSwitcher)) }) }
const click = async (el: Element) => { await act(async () => { (el as HTMLElement).click() }) }

describe('对话区顶部的当前案件与切换', () => {
  it('显示当前案件名；"切换案件 ▾"列最近案件（不含当前、按上次打开倒序）和"首页…"；点案件进入它，点首页回首页', async () => {
    const opened: string[] = []
    let home = 0
    setNav({ goHome: () => { home++ }, openCaseWorkspace: async (r: string) => { opened.push(r) }, openTab: () => {} } as unknown as Nav)
    setApi({ caseOpen: async (r: { path: string }) => ({ ok: true, value: { case_id: 'x', name: 'x', created: false, folders_created: [] } }) } as unknown as LawbenchApi)
    app.set((s) => ({ ...s, cases: [A, B, D], currentRoot: A.root, dailyRoot: D.root }))
    await render()
    expect(box.textContent).toContain('张某甲诈骗案')
    await click([...box.querySelectorAll('button')].find((b) => b.textContent === '切换案件 ▾')!)
    expect([...box.querySelectorAll('[role=menuitem]')].map((b) => b.textContent)).toEqual(['李某合同纠纷', '日常事务（非办案）', '首页…'])
    expect(box.querySelector('[role=menu]')!.textContent).toContain('案件名即文件夹名，在资源管理器里改')
    await click([...box.querySelectorAll('[role=menuitem]')][0]!)
    await act(async () => { await Promise.resolve(); await Promise.resolve() })
    expect(opened).toEqual([B.root])
    await click([...box.querySelectorAll('button')].find((b) => b.textContent === '切换案件 ▾')!)
    await click([...box.querySelectorAll('[role=menuitem]')].at(-1)!)
    expect(home).toBe(1)
  })

  it('日常事务显示"（非办案）"；没有当前案件时不显示', async () => {
    app.set((s) => ({ ...s, cases: [A, D], currentRoot: D.root, dailyRoot: D.root }))
    await render()
    expect(box.textContent).toContain('日常事务（非办案）')
    await act(async () => { app.set((s) => ({ ...s, currentRoot: null })) })
    expect(box.textContent).toBe('')
    expect(switchTargets([A, B, D], undefined).map((c) => c.case_id)).toEqual(['b', 'a', 'd'])
  })
})
