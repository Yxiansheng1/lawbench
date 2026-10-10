// @vitest-environment jsdom
// 令 1422（第七版待办 20）：首页空白处拖入文件夹 = 建案件；拖到案件卡片仍是加进该案的材料。
import { existsSync, mkdirSync, mkdtempSync, rmSync, symlinkSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { droppedItems } from '../host/desk-actions.ts'
import { BLANK_OVER_MS, HomeLanding } from '../ui/home-page.tsx'
import { DialogHost } from '../ui/dialogs.tsx'
import { ASK_OK, askTitle, badCaseName, BLANK_HINT, cardHint, dropOnBlank, FILE_TEXT, NAME_TITLE, readKind, ROOT_TEXT, SYNC_DROP_OK, SYNC_DROP_TITLE, type DroppedItem } from '../ui/drop-case.ts'
import { app, setApi, type CaseRef, type LawbenchApi } from '../ui/state.ts'
import { setNav, type Nav } from '../ui/kit.tsx'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
let root: Root | undefined
let box: HTMLDivElement
beforeEach(() => { box = document.createElement('div'); document.body.appendChild(box); localStorage.clear() })
afterEach(async () => {
  await act(async () => { root?.unmount() }); root = undefined; box.remove(); setApi(undefined); setNav(undefined)
  app.set((s) => ({ ...s, cases: [], dailyRoot: null, lawyerName: null, dialogs: [] }))
})

const tick = () => new Promise((r) => setTimeout(r, 0))
const dialogs = () => (app.get() as unknown as { dialogs: Array<{ kind: string; title?: string; text?: string; name?: string; resolve?: (v: unknown) => void }> }).dialogs
const last = () => dialogs().at(-1)

const DIR = 'D:\\我的案子\\李某合同纠纷'
const dir = (path: string, more: Partial<DroppedItem> = {}): DroppedItem => ({ path, name: path.split('\\').pop()!, kind: 'dir', has_case: false, children: [`${path}\\合同.pdf`, `${path}\\证据`], ...more })
const file = (path: string): DroppedItem => ({ path, name: path.split('\\').pop()!, kind: 'file', has_case: false, children: [] })

/** 假 Host / 服务：记下每次调用；云同步目录（路径含 OneDrive）拒。 */
function setup(items: DroppedItem[], recent: CaseRef[] = []) {
  const calls: Array<[string, unknown]> = []
  setNav({ openCaseWorkspace: async () => {}, openTab: () => {}, seedTabs: () => {}, pathFor: (f: File) => (f as unknown as { path: string }).path } as unknown as Nav)
  setApi({
    dropInfo: async (r: unknown) => { calls.push(['dropInfo', r]); return { ok: true, value: { items } } },
    caseOpen: async (r: { path: string }) => {
      calls.push(['caseOpen', r])
      return r.path.includes('OneDrive')
        ? { ok: false, error: { code: 'CASE_IN_SYNC_FOLDER', message: '该文件夹在云同步目录中，请移到本机普通文件夹后再打开' } }
        : { ok: true, value: { case_id: `id-${r.path.split('\\').pop()}`, name: 'x', created: true, folders_created: [] } }
    },
    localCaseFolder: async (r: { name: string }) => { calls.push(['localCaseFolder', r]); return { ok: true, value: { path: `C:\\Users\\x\\连越律师工作台\\${r.name}` } } },
    materialsImport: async (r: unknown) => { calls.push(['materialsImport', r]); return { ok: true, value: { copied: [{ from: 'a', to: '合同.pdf' }], skipped: [], scan: { added: 1, changed: 0, removed: 0, failed: 0, review_needed: false } } } },
    caseRecent: async () => ({ ok: true, value: { cases: recent } }),
    getCapsules: async () => ({ ok: true, value: { v: 1, hint: '', shared: [], groups: [] } }),
    materialsList: async () => ({ ok: true, value: { materials: [] } }),
    outputsList: async () => ({ ok: true, value: { outputs: [] } }),
  } as unknown as LawbenchApi)
  return calls
}
const only = (calls: Array<[string, unknown]>, name: string) => calls.filter((c) => c[0] === name).map((c) => c[1])

describe('Host：看拖进来的是什么（真文件系统）', () => {
  let tmp: string
  beforeEach(() => { tmp = mkdtempSync(join(tmpdir(), 'lb-drop-')) })
  afterEach(() => rmSync(tmp, { recursive: true, force: true }))

  it('文件夹 / 文件 / 不存在 / 网络路径 / 相对路径分开；当过案件的认得出；顶层不列 . 开头的和 工作区、成果', () => {
    const a = join(tmp, '甲案'); mkdirSync(join(a, '证据'), { recursive: true }); writeFileSync(join(a, '合同.pdf'), 'x'); writeFileSync(join(a, '.DS_Store'), 'x')
    const b = join(tmp, '乙案'); mkdirSync(join(b, '工作区', 'wiki'), { recursive: true }); mkdirSync(join(b, '成果')); writeFileSync(join(b, '起诉状.docx'), 'x')
    const f = join(tmp, '单个.pdf'); writeFileSync(f, 'x')
    // 复核 rv-A55 P2-1：只有一个叫"工作区"的子文件夹不算当过案件；有 case.db 或 wiki 才算
    const c = join(tmp, '丙案'); mkdirSync(join(c, '工作区', '草稿'), { recursive: true })
    const d = join(tmp, '丁案'); mkdirSync(join(d, '工作区'), { recursive: true }); writeFileSync(join(d, '工作区', 'case.db'), 'x')
    const more = droppedItems([c, d]) as { value: DroppedItem[] }
    expect(more.value.map((x) => [x.kind, x.has_case])).toEqual([['dir', false], ['dir', true]])
    // 复核 rv-A55 P3-1：真实存在的文件夹，换成设备路径、本机管理共享的写法也不收（没有 plainAbsolute 守卫时 lstat 会成功、判成文件夹）
    const device = '\\\\?\\' + a
    const share = '\\\\localhost\\' + a[0] + '$' + a.slice(2)
    expect(existsSync(device)).toBe(true)
    expect((droppedItems([device, share]) as { value: DroppedItem[] }).value.map((x) => x.kind)).toEqual(['other', 'other'])
    const lnk = join(tmp, '甲案 - 快捷方式.lnk'); writeFileSync(lnk, 'x')
    expect((droppedItems([lnk]) as { value: DroppedItem[] }).value[0]!.kind).toBe('other')
    const r = droppedItems([a, b, f, join(tmp, '没有'), '\\\\fs01\\案卷\\丙', '相对\\路径'])
    if (!r.ok) throw new Error('应当成功')
    expect(r.value.map((x) => x.kind)).toEqual(['dir', 'dir', 'file', 'other', 'other', 'other'])
    expect(r.value[0]).toMatchObject({ name: '甲案', has_case: false, children: [join(a, '合同.pdf'), join(a, '证据')] })
    expect(r.value[1]).toMatchObject({ name: '乙案', has_case: true, children: [join(b, '起诉状.docx')] })
    let linked = false
    try { symlinkSync(a, join(tmp, '联接'), 'junction'); linked = true } catch { /* 建不了联接的环境跳过 */ }
    if (linked) expect((droppedItems([join(tmp, '联接')]) as { value: DroppedItem[] }).value[0]!.kind).toBe('other')
    expect(droppedItems([]).ok).toBe(false)
    expect(droppedItems('x').ok).toBe(false)
    expect(droppedItems([1]).ok).toBe(false)
  })
})

describe('空白处松手', () => {
  it('一个文件夹：问"把『…』建成案件？"；确定 → 原地登记（template 为 null，不弹子文件夹框、不复制），类型记在本机', async () => {
    const calls = setup([dir(DIR)])
    const p = dropOnBlank([DIR])
    await tick()
    expect(last()).toMatchObject({ kind: 'newCase', name: '李某合同纠纷' })
    expect(askTitle('李某合同纠纷')).toBe('把『李某合同纠纷』建成案件？')
    last()!.resolve!('criminal')
    app.set((s) => ({ ...s, dialogs: [] }))
    const made = await p
    expect(made).toMatchObject([{ case_id: 'id-李某合同纠纷', root: DIR }])
    expect(only(calls, 'caseOpen')).toEqual([{ path: DIR, template: null }])
    expect(only(calls, 'materialsImport')).toEqual([])
    expect(dialogs().some((d) => d.kind === 'folders')).toBe(false)
    expect(readKind('id-李某合同纠纷')).toBe('criminal')
  })

  it('取消：什么都不发生', async () => {
    const calls = setup([dir(DIR)])
    const p = dropOnBlank([DIR])
    await tick()
    last()!.resolve!(null)
    app.set((s) => ({ ...s, dialogs: s.dialogs.filter((d) => d.kind !== 'newCase') }))
    expect(await p).toEqual([])
    expect(only(calls, 'caseOpen')).toEqual([])
    // 复核 rv-A55 P3-2：取消就是取消，不弹任何说明（取消被当成出错时这里会多一个 notice）
    expect(dialogs()).toEqual([])
  })

  it('单个或多个文件：不建案件，提示拖到案件卡片或先新建；文件夹和文件混拖只处理文件夹', async () => {
    let calls = setup([file('D:\\a.pdf'), file('D:\\b.pdf')])
    expect(await dropOnBlank(['D:\\a.pdf', 'D:\\b.pdf'])).toEqual([])
    expect(dialogs().filter((d) => d.kind === 'notice').map((d) => d.text)).toEqual([FILE_TEXT])
    expect(only(calls, 'caseOpen')).toEqual([])
    app.set((s) => ({ ...s, dialogs: [] }))
    calls = setup([dir(DIR), file('D:\\a.pdf')])
    const p = dropOnBlank([DIR, 'D:\\a.pdf'])
    await tick()
    expect(dialogs().map((d) => d.kind)).toEqual(['notice', 'newCase'])
    last()!.resolve!('civil')
    expect((await p).map((c) => c.root)).toEqual([DIR])
    expect(only(calls, 'caseOpen')).toEqual([{ path: DIR, template: null }])
  })

  it('多个文件夹：逐个问，各建一案；中途取消只跳过那一个', async () => {
    const B = 'D:\\我的案子\\王某借贷', C2 = 'D:\\我的案子\\赵某劳动'
    const calls = setup([dir(DIR), dir(B), dir(C2)])
    const p = dropOnBlank([DIR, B, C2])
    for (const answer of ['civil', null, 'daily']) {
      await tick(); await tick()
      const d = dialogs().find((x) => x.kind === 'newCase')!
      app.set((s) => ({ ...s, dialogs: s.dialogs.filter((x) => x !== (d as unknown)) }))
      d.resolve!(answer)
    }
    expect((await p).map((c) => c.root)).toEqual([DIR, C2])
    expect(only(calls, 'caseOpen')).toEqual([{ path: DIR, template: null }, { path: C2, template: null }])
  })

  it('已登记的案件、以前当过案件的文件夹：不问，直接打开', async () => {
    const known: CaseRef = { case_id: 'k', name: '李某合同纠纷', root: DIR, exists: true }
    const OLD = 'D:\\我的案子\\旧案'
    const calls = setup([dir(DIR), dir(OLD, { has_case: true })])
    app.set((s) => ({ ...s, cases: [known] }))
    const made = await dropOnBlank([DIR.toLowerCase() + '\\', OLD])
    expect(made.map((c) => c.root)).toEqual([DIR, OLD])
    expect(dialogs().some((d) => d.kind === 'newCase')).toBe(false)
    expect(only(calls, 'caseOpen')).toEqual([{ path: DIR, template: null }, { path: OLD, template: null }])
  })

  it('里面只有一个"工作区"子文件夹（Host 回 has_case 为 false）：照样弹确认框，不直接登记（复核 rv-A55 P2-1）；盘根不问、直接说明', async () => {
    let calls = setup([dir(DIR, { has_case: false, children: [`${DIR}\\合同.pdf`] })])
    const p = dropOnBlank([DIR])
    await tick()
    expect(last()).toMatchObject({ kind: 'newCase', name: '李某合同纠纷' })
    expect(only(calls, 'caseOpen')).toEqual([])
    last()!.resolve!(null)
    await p
    app.set((s) => ({ ...s, dialogs: [] }))
    calls = setup([{ path: 'D:\\', name: '', kind: 'dir', has_case: false, children: [] }])
    expect(await dropOnBlank(['D:\\'])).toEqual([])
    expect(dialogs().map((d) => [d.kind, d.text])).toEqual([['notice', ROOT_TEXT]])
    expect(only(calls, 'caseOpen')).toEqual([])
  })

  it('文件夹名是工作台自用的名字或 Windows 保留名：说明要改名，不建', async () => {
    for (const n of ['工作区', '成果', 'CON', 'nul.txt']) expect(badCaseName(n), n).toBe(true)
    expect(badCaseName('李某合同纠纷')).toBe(false)
    const calls = setup([dir('D:\\我的案子\\成果')])
    expect(await dropOnBlank(['D:\\我的案子\\成果'])).toEqual([])
    expect(last()).toMatchObject({ kind: 'notice', title: NAME_TITLE })
    expect(only(calls, 'caseOpen')).toEqual([])
  })

  it('文件夹在云同步目录里：只给"复制到本机建案件"——在本机建案件，把原文件夹顶层各项复制到案件根；不同意就什么都不做', async () => {
    const SYNCED = 'C:\\Users\\x\\OneDrive\\文档\\李某合同纠纷'
    let calls = setup([dir(SYNCED)])
    let p = dropOnBlank([SYNCED])
    await tick(); last()!.resolve!('civil'); app.set((s) => ({ ...s, dialogs: [] }))
    await tick(); await tick()
    expect(last()).toMatchObject({ kind: 'confirm', title: SYNC_DROP_TITLE, ok: SYNC_DROP_OK })
    last()!.resolve!(true); app.set((s) => ({ ...s, dialogs: [] }))
    const made = await p
    const LOCAL = 'C:\\Users\\x\\连越律师工作台\\李某合同纠纷'
    expect(made).toMatchObject([{ root: LOCAL }])
    expect(calls.map((c) => c[0])).toEqual(['dropInfo', 'caseOpen', 'localCaseFolder', 'caseOpen', 'materialsImport'])
    expect(only(calls, 'materialsImport')).toEqual([{ case_id: 'id-李某合同纠纷', paths: [`${SYNCED}\\合同.pdf`, `${SYNCED}\\证据`], target: null, unzip: false }])
    expect(last()).toMatchObject({ kind: 'notice', title: '复制结果' })
    app.set((s) => ({ ...s, dialogs: [], cases: [] }))
    calls = setup([dir(SYNCED)])
    p = dropOnBlank([SYNCED])
    await tick(); last()!.resolve!('civil'); app.set((s) => ({ ...s, dialogs: [] }))
    await tick(); await tick()
    last()!.resolve!(false)
    expect(await p).toEqual([])
    expect(only(calls, 'localCaseFolder')).toEqual([])
  })
})

describe('首页：两种落点', () => {
  const CASE: CaseRef = { case_id: 'c1', name: '张某诈骗案', root: 'D:\\案件\\张某诈骗案', exists: true, last_opened: '2026-10-09T10:00:00+08:00' }
  async function render(items: DroppedItem[]) {
    const calls = setup(items, [CASE])
    root = createRoot(box)
    await act(async () => { root!.render(createElement('div', null, createElement(HomeLanding), createElement(DialogHost))) })
    for (let i = 0; i < 6; i++) await act(async () => { await Promise.resolve() })
    return calls
  }
  /** 带文件的拖放事件（jsdom 没有 DataTransfer）。 */
  function fire(el: Element, type: string, paths: string[] = ['x']) {
    const ev = new Event(type, { bubbles: true, cancelable: true }) as Event & { dataTransfer: unknown }
    ev.dataTransfer = { types: ['Files'], files: paths.map((p) => ({ path: p })), dropEffect: 'none' }
    return act(async () => { el.dispatchEvent(ev); await tick() })
  }
  const blank = () => box.querySelector('[data-home-blank]') as HTMLElement
  const card = () => box.querySelector('[data-case-card="case"]') as HTMLElement

  it('拖到空白处亮"松开：建新案件"；拖到卡片上亮"松开：加入 <案名> 的材料"，空白处的高亮关掉——两种不同时亮', async () => {
    await render([])
    await fire(box.querySelector('h1')!, 'dragover')
    expect(blank().dataset.homeBlank).toBe('over')
    expect(box.textContent).toContain(BLANK_HINT)
    expect(card().textContent).not.toContain(cardHint(CASE.name))
    await fire(card(), 'dragover')
    expect(blank().dataset.homeBlank).toBe('')
    expect(box.textContent).not.toContain(BLANK_HINT)
    expect(card().textContent).toContain('松开：加入 张某诈骗案 的材料')
  })

  it('拖动被取消而没有发 dragleave：空白处的高亮过一会儿自己关掉，不卡在亮着', async () => {
    await render([])
    await fire(box.querySelector('h1')!, 'dragover')
    expect(blank().dataset.homeBlank).toBe('over')
    await act(async () => { await new Promise((r) => setTimeout(r, BLANK_OVER_MS + 100)) })
    expect(blank().dataset.homeBlank).toBe('')
  })

  it('松在卡片上：加进该案的材料（弹原来的确认框），不问 Host、不建案件', async () => {
    const calls = await render([dir(DIR)])
    await fire(card(), 'drop', [DIR])
    expect(last()).toMatchObject({ kind: 'import', caseRef: { case_id: 'c1' }, paths: [DIR] })
    expect(only(calls, 'dropInfo')).toEqual([])
    expect(only(calls, 'caseOpen')).toEqual([])
  })

  it('松在空白处：弹确认框（三种类型，默认民商事）；点"建成案件"后原地登记', async () => {
    const calls = await render([dir(DIR)])
    await fire(box.querySelector('h1')!, 'drop', [DIR])
    expect(only(calls, 'dropInfo')).toEqual([{ paths: [DIR] }])
    expect(document.body.textContent).toContain('把『李某合同纠纷』建成案件？')
    const radios = [...document.querySelectorAll<HTMLInputElement>('input[type=radio]')]
    expect(radios.map((r) => r.parentElement!.textContent)).toEqual(['民商事', '刑事', '日常事务'])
    expect(radios.map((r) => r.checked)).toEqual([true, false, false])
    await act(async () => { radios[1]!.click() })
    await act(async () => { [...document.querySelectorAll('button')].find((b) => b.textContent === ASK_OK)!.click(); await tick(); await tick() })
    expect(only(calls, 'caseOpen')).toEqual([{ path: DIR, template: null }])
    expect(readKind('id-李某合同纠纷')).toBe('criminal')
  })
})

describe('文案', () => {
  it('新加的话不出现"导入""模板""工作区"（界面用语另由 scripts\\check_ui_words.py 查）', async () => {
    const m = await import('../ui/drop-case.ts')
    const texts = [m.BLANK_HINT, m.BLANK_IDLE, m.cardHint('甲案'), m.askTitle('甲案'), m.ASK_TEXT, m.ASK_OK, m.FILE_TITLE, m.FILE_TEXT, m.NO_PATH_TEXT, m.OTHER_TITLE, m.OTHER_TEXT,
      m.NAME_TITLE, m.nameText('成果'), m.SYNC_DROP_TITLE, m.syncDropText('甲案'), m.SYNC_DROP_OK, ...m.DROP_KINDS.map((k) => k.label)]
    for (const t of texts) expect(t, t).not.toMatch(/导入|模板|工作区/)
  })
})
