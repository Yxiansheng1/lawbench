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
    await openCase('D:\案件\张某甲诈骗案', null)
    expect(tabs).toEqual([TABS.results, TABS.source, TABS.materials])
  })
})
