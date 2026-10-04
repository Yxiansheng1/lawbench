// 右侧栏默认展开（令 1347 第 3 条；第二轮复核 AMEND F2）：每个案件会话只自动展开一次；打开案件时依次开成果、原文查看、材料，停在材料。
import { createRightbarSeeder, RIGHTBAR_TABS } from '../ui/rightbar.ts'
import { openCase, TABS } from '../ui/cases.ts'
import { setNav, type Nav } from '../ui/kit.tsx'
import { setApi, type LawbenchApi } from '../ui/state.ts'

afterEach(() => { setNav(undefined); setApi(undefined) })

describe('右侧栏默认展开', () => {
  it('每个案件会话只开一次（记下的会话再显示不再开）；不是案件会话、没有会话不开；最后开的是材料', () => {
    const opened: string[] = []
    const saved: string[][] = []
    const seed = createRightbarSeeder(new Set(['s-old']), (ids) => { saved.push(ids) }, (k) => { opened.push(k) })
    expect(seed('s1', true)).toBe(true)
    expect(opened).toEqual([TABS.results, TABS.source, TABS.materials])
    expect(seed('s1', true)).toBe(false)
    expect(seed('s-old', true)).toBe(false)
    expect(seed('s2', false)).toBe(false)
    expect(seed(undefined, true)).toBe(false)
    expect(opened.length).toBe(3)
    expect(saved.at(-1)).toEqual(['s-old', 's1'])
    expect(RIGHTBAR_TABS.at(-1)).toBe(TABS.materials)
  })

  it('openCase：登记后打开案件，依次开成果、原文查看、材料（停在材料）', async () => {
    const tabs: string[] = []
    setNav({ pickDirectory: async () => null, openCaseWorkspace: async () => {}, openTab: (k: string) => { tabs.push(k) } } as unknown as Nav)
    setApi({ caseOpen: async () => ({ ok: true, value: { case_id: 'c', name: '张某甲诈骗案', created: false, folders_created: [] } }) } as unknown as LawbenchApi)
    await openCase('D:\\案件\\张某甲诈骗案', null)
    expect(tabs).toEqual([TABS.results, TABS.source, TABS.materials])
  })
})

describe('案件改名后在新位置重新打开（令 1515 第 3 条）', () => {
  it('同一 case_id 原来在别的位置：界面只留新的一条（名字取新文件夹名），打开后移除侧栏里旧位置那一项', async () => {
    const { app } = await import('../ui/state.ts')
    const forgotten: string[] = []
    setNav({ pickDirectory: async () => null, openCaseWorkspace: async () => {}, openTab: () => {}, forgetCaseWorkspace: async (r: string) => { forgotten.push(r) } } as unknown as Nav)
    setApi({ caseOpen: async () => ({ ok: true, value: { case_id: 'c', name: '张某甲诈骗案（改名）', created: false, folders_created: [] } }) } as unknown as LawbenchApi)
    app.set((s) => ({ ...s, cases: [{ case_id: 'c', name: '张某甲诈骗案', root: 'D:\\案件\\张某甲诈骗案' }] }))
    await openCase('D:\\案件\\张某甲诈骗案（改名）', null)
    expect(app.get().cases.map((c) => [c.name, c.root])).toEqual([['张某甲诈骗案（改名）', 'D:\\案件\\张某甲诈骗案（改名）']])
    expect(forgotten).toEqual(['D:\\案件\\张某甲诈骗案'])
    app.set((s) => ({ ...s, cases: [] }))
  })
})

describe('重启后侧栏里的旧位置（令 1515 第 3 条）', () => {
  it('不是已登记案件位置的项移除，默认工作区不动；案件列表没读到时什么都不移除', async () => {
    const { staleWorkspaces } = await import('../ui/rightbar.ts')
    const { samePath } = await import('../ui/state.ts')
    const items = [
      { workspaceId: 'w1', path: 'D:/案件/张某甲诈骗案', title: '张某甲诈骗案' },
      { workspaceId: 'w2', path: 'D:/案件/张某甲诈骗案（改名）', title: '张某甲诈骗案（改名）' },
      { workspaceId: 'w3', path: 'C:/Users/x/.dsh/default', title: 'default-workspace' },
    ]
    expect(staleWorkspaces(items, ['D:/案件/张某甲诈骗案（改名）'], samePath)).toEqual(['w1'])
    expect(staleWorkspaces(items, [], samePath)).toEqual([])
  })
})
