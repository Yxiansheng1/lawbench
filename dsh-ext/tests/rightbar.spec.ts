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

describe('侧栏旧位置那一项（1612 复核 P1）', () => {
  it('同一位置换写法打开（映射盘、联接）：刚打开的那一项永远不撤；只认对得上旧位置、又不是刚打开的', async () => {
    const { forgettableWorkspace } = await import('../ui/rightbar.ts')
    const { samePath } = await import('../ui/state.ts')
    // 复核员的例子：登记里是规范写法 Z:/案件/甲，律师用另一写法打开，DSH 新建的那一项路径与规范写法相同
    const items = [{ workspaceId: 'w-just-opened', path: 'Z:/案件/甲' }, { workspaceId: 'w-old', path: 'D:/案件/甲（旧）' }]
    expect(forgettableWorkspace(items, 'Z:/案件/甲', 'w-just-opened', samePath)).toBeUndefined()
    expect(forgettableWorkspace(items, 'D:/案件/甲（旧）', 'w-just-opened', samePath)).toBe('w-old')
    expect(forgettableWorkspace(items, 'D:/别处', 'w-just-opened', samePath)).toBeUndefined()
  })

  it('openCase 把刚打开的工作区 id 交给移除步骤（让它排除）', async () => {
    const { app } = await import('../ui/state.ts')
    const calls: Array<[string, string | undefined]> = []
    setNav({ pickDirectory: async () => null, openCaseWorkspace: async () => 'w-new', openTab: () => {}, forgetCaseWorkspace: async (r: string, e?: string) => { calls.push([r, e]) } } as unknown as Nav)
    setApi({ caseOpen: async () => ({ ok: true, value: { case_id: 'c', name: '甲', created: false, folders_created: [] } }) } as unknown as LawbenchApi)
    app.set((s) => ({ ...s, cases: [{ case_id: 'c', name: '甲', root: 'Z:\\案件\\甲' }] }))
    await openCase('\\\\fs\\share\\案件\\甲', null)
    expect(calls).toEqual([['Z:\\案件\\甲', 'w-new']])
    app.set((s) => ({ ...s, cases: [] }))
  })
})

describe('先问 pathState 再撤（令 1726 补：复核员变异 M2）', () => {
  const items = [{ workspaceId: 'w-old', path: 'D:/案件/甲（旧）' }, { workspaceId: 'w-now', path: 'D:/案件/甲' }]
  const same = (a: string, b: string) => a.toLowerCase() === b.toLowerCase()
  it('旧位置确实不在才撤；还在、问不到都不撤', async () => {
    const { forgetIfGone } = await import('../ui/rightbar.ts')
    for (const [answer, want] of [
      [{ ok: true, value: { exists: false } }, 'w-old'],
      [{ ok: true, value: { exists: true } }, undefined],
      [{ ok: false }, undefined],
    ] as const) {
      const removed: string[] = []
      const asked: string[] = []
      const r = await forgetIfGone(items, 'D:/案件/甲（旧）', 'w-now', same, async (p) => { asked.push(p); return answer }, async (id) => { removed.push(id) })
      expect(asked).toEqual(['D:/案件/甲（旧）'])
      expect(r).toBe(want)
      expect(removed).toEqual(want ? [want] : [])
    }
  })
})
