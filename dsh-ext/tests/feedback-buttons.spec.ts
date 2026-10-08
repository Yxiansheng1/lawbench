// @vitest-environment jsdom
// 令 2043（律师第一批反馈）第 1、2 条：首页日常事务卡片的"工具"一栏；右栏"打开所在文件夹""移除此材料"。
import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { ToolsRow } from '../ui/home-page.tsx'
import { MATERIAL_REMOVE_ENABLED, openCaseFolder, removeMaterial, REMOVE_TITLE } from '../ui/folder-actions.ts'
import { app, setApi, type CaseRef, type LawbenchApi } from '../ui/state.ts'
import { openCase, SYNC_NAME_TITLE, SYNC_OK, SYNC_TITLE, syncText } from '../ui/cases.ts'
import { setNav, type Nav } from '../ui/kit.tsx'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
let root: Root | undefined
let box: HTMLDivElement
beforeEach(() => { box = document.createElement('div'); document.body.appendChild(box) })
afterEach(async () => { await act(async () => { root?.unmount() }); root = undefined; box.remove(); setApi(undefined); setNav(undefined); app.set((s) => ({ ...s, dialogs: [] })) })

const CASE: CaseRef = { case_id: 'c-1', name: '张某甲诈骗案', root: 'D:\\案件\\张某甲诈骗案' }
const lastDialog = () => (app.get() as unknown as { dialogs: Array<{ kind: string; title: string; resolve?: (v: unknown) => void }> }).dialogs.at(-1)

describe('首页"工具"一栏', () => {
  it('两个按钮，点了经 Host 打开对应小工具；点按钮不触发卡片进入（不冒泡）', async () => {
    const opened: unknown[] = []
    setApi({ openTool: async (r: unknown) => { opened.push(r); return { ok: true, value: { opened: true } } } } as unknown as LawbenchApi)
    let cardClicks = 0
    root = createRoot(box)
    await act(async () => { root!.render(createElement('div', { onClick: () => { cardClicks++ } }, createElement(ToolsRow, { mac: false }))) })
    const buttons = [...box.querySelectorAll('button')]
    expect(buttons.map((b) => b.textContent)).toEqual(['长截图切分', '格式互转'])
    await act(async () => { buttons[1]!.click() })
    expect(opened).toEqual([{ name: 'convert' }])
    expect(cardClicks).toBe(0)
  })

  it('Mac 版不显示（没有这两个小工具）', async () => {
    root = createRoot(box)
    await act(async () => { root!.render(createElement(ToolsRow, { mac: true })) })
    expect(box.textContent).toBe('')
  })
})

describe('右栏按钮', () => {
  it('打开所在文件夹：材料区开默认导入位置，还没建出来时开案件根；成果区开"成果"', async () => {
    const asked: Array<{ case_id?: string; root: string; rel: string }> = []
    setApi({ openFolder: async (r: { root: string; rel: string }) => { asked.push(r); return r.rel === '02案件材料' ? { ok: false, error: { code: 'NOT_FOUND', message: '这个文件夹还没有内容（还没建出来）' } } : { ok: true, value: { opened: true } } } } as unknown as LawbenchApi)
    expect(await openCaseFolder(CASE, 'materials')).toBe(true)
    expect(await openCaseFolder(CASE, 'outputs')).toBe(true)
    expect(asked).toEqual([{ case_id: 'c-1', root: CASE.root, rel: '02案件材料' }, { case_id: 'c-1', root: CASE.root, rel: '' }, { case_id: 'c-1', root: CASE.root, rel: '成果' }])
  })

  it('移除此材料暂为禁用态（服务删原件后仍保留文本和检索，做不到从索引里去掉；令 2043 第 2 条退路）', () => {
    expect(MATERIAL_REMOVE_ENABLED).toBe(false)
  })

  it('（服务支持后启用）移除流程：先问；取消不动；确认后经 Host 删文件并重新扫描', async () => {
    const removed: unknown[] = []
    setApi({ materialRemove: async (r: unknown) => { removed.push(r); return { ok: true, value: { added: 0, changed: 0, removed: 1, failed: 0, review_needed: true } } } } as unknown as LawbenchApi)
    const m = { name: '起诉意见书', rel_path: '02案件材料\\起诉意见书.pdf' }
    const no = removeMaterial(CASE, m)
    expect(lastDialog()).toMatchObject({ kind: 'confirm', title: REMOVE_TITLE })
    lastDialog()!.resolve!(false)
    expect(await no).toBe(false)
    expect(removed).toEqual([])
    const yes = removeMaterial(CASE, m)
    lastDialog()!.resolve!(true)
    expect(await yes).toBe(true)
    expect(removed).toEqual([{ case_id: 'c-1', root: CASE.root, rel_path: '02案件材料\\起诉意见书.pdf' }])
  })
})

const SYNCED = String.raw`C:\Users\x\OneDrive\文档\李某合同纠纷`
const LOCAL = String.raw`C:\Users\x\连越律师工作台` + '\\'
/** 令 1852 第 17 条：新建时先问子文件夹；这几例只看云同步，按"一个不勾"传入，不弹那一框。 */
const NONE = { tops: [], custom: [] }

describe('案件文件夹在云同步目录里（令 2043 第 3 条）', () => {
  it('被拒时问"为我在本机建一个文件夹"；同意就在本机建好并以它打开；不同意什么都不做', async () => {
    const opened: unknown[] = []
    setNav({ pickDirectory: async () => null, openCaseWorkspace: async () => {}, openTab: () => {} } as unknown as Nav)
    setApi({
      caseOpen: async (r: { path: string; template: unknown }) => { opened.push(r); return r.path.includes('OneDrive') ? { ok: false, error: { code: 'CASE_IN_SYNC_FOLDER', message: '该文件夹在云同步目录中，请移到本机普通文件夹后再打开' } } : { ok: true, value: { case_id: 'c-9', name: '李某合同纠纷', created: true, folders_created: [] } } },
      localCaseFolder: async (r: { name: string }) => ({ ok: true, value: { path: LOCAL + r.name } }),
    } as unknown as LawbenchApi)
    const p = openCase(SYNCED, 'civil', true, true, NONE)
    await new Promise((r) => setTimeout(r, 0))
    expect(lastDialog()).toMatchObject({ kind: 'confirm', title: SYNC_TITLE, ok: SYNC_OK })
    expect((lastDialog() as unknown as { text: string }).text).toBe(syncText('李某合同纠纷'))
    expect(syncText('李某合同纠纷')).toContain(String.raw`连越律师工作台\李某合同纠纷`)
    lastDialog()!.resolve!(true)
    const c = await p
    expect(c).toMatchObject({ case_id: 'c-9', root: LOCAL + '李某合同纠纷' })
    expect(opened).toEqual([
      { path: SYNCED, template: null },
      { path: LOCAL + '李某合同纠纷', template: null },
    ])
    const q = openCase(SYNCED, null)
    await new Promise((r) => setTimeout(r, 0))
    lastDialog()!.resolve!(false)
    expect(await q).toBeUndefined()
  })

  it('名字里含同步软件名（如"Dropbox公司诉某某案"）：不提议建本机文件夹（建了也同样被拒），直接说明要改名（复核 P2-4）', async () => {
    const made: unknown[] = []
    setNav({ pickDirectory: async () => null, openCaseWorkspace: async () => {}, openTab: () => {} } as unknown as Nav)
    setApi({
      caseOpen: async () => ({ ok: false, error: { code: 'CASE_IN_SYNC_FOLDER', message: '该文件夹在云同步目录中，请移到本机普通文件夹后再打开' } }),
      localCaseFolder: async (r: unknown) => { made.push(r); return { ok: true, value: { path: LOCAL + 'x' } } },
    } as unknown as LawbenchApi)
    expect(await openCase(String.raw`D:\案件\Dropbox公司诉某某案`, 'civil', true, true, NONE)).toBeUndefined()
    expect(lastDialog()).toMatchObject({ kind: 'notice', title: SYNC_NAME_TITLE })
    expect((lastDialog() as unknown as { text: string }).text).toContain('Dropbox')
    expect(made).toEqual([])
  })

  it('本机建好的文件夹仍被拒：只说明，不再提议（不会每确认一次多一个空的"(n)"文件夹）（复核 P2-4）', async () => {
    const made: unknown[] = []
    setNav({ pickDirectory: async () => null, openCaseWorkspace: async () => {}, openTab: () => {} } as unknown as Nav)
    setApi({
      caseOpen: async () => ({ ok: false, error: { code: 'CASE_IN_SYNC_FOLDER', message: '该文件夹在云同步目录中，请移到本机普通文件夹后再打开' } }),
      localCaseFolder: async (r: { name: string }) => { made.push(r); return { ok: true, value: { path: LOCAL + r.name } } },
    } as unknown as LawbenchApi)
    const p = openCase(SYNCED, 'civil', true, true, NONE)
    await new Promise((r) => setTimeout(r, 0))
    lastDialog()!.resolve!(true)
    expect(await p).toBeUndefined()
    expect(made).toEqual([{ name: '李某合同纠纷' }])
    expect(lastDialog()).toMatchObject({ kind: 'notice', title: '没能打开案件' })
    expect((app.get() as unknown as { dialogs: Array<{ kind: string }> }).dialogs.filter((d) => d.kind === 'confirm')).toHaveLength(1)
  })
})
