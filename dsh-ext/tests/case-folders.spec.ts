// @vitest-environment jsdom
// 令 1852 第 17 条（第七版待办 17）：新建案件时子文件夹由律师勾选，默认全不勾；可自填一级目录（非法名拒）。
import { lstatSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, symlinkSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { CASE_TEMPLATES, customFolderProblem, folderRels } from '../shared/case-folders.ts'
import { chosenFolders, mkdirInCase, type DeskDeps } from '../host/desk-actions.ts'
import { LawbenchRemote } from '../host/index.ts'
import type { Supervisor } from '../host/supervisor.ts'
import { app, setApi, type LawbenchApi } from '../ui/state.ts'
import { openCase } from '../ui/cases.ts'
import { DialogHost } from '../ui/dialogs.tsx'
import { setNav, type Nav } from '../ui/kit.tsx'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
let root: Root | undefined
let box: HTMLDivElement
beforeEach(() => { box = document.createElement('div'); document.body.appendChild(box) })
afterEach(async () => { await act(async () => { root?.unmount() }); root = undefined; box.remove(); setApi(undefined); setNav(undefined); app.set((s) => ({ ...s, dialogs: [] })) })

const tick = () => new Promise((r) => setTimeout(r, 0))
const DIR = 'D:\\案件\\李某合同纠纷'

describe('标准目录与服务一致', () => {
  it('两套目录与服务 registry.py 的 TEMPLATES 展开后完全相同（服务改目录这条就红）', () => {
    const py = readFileSync(join(__dirname, '..', '..', 'service', 'lawbench', 'case', 'registry.py'), 'utf8')
    const list = (src: string) => [...src.matchAll(/"([^"]+)"/g)].map((m) => m[1]!)
    const consts: Record<string, string[]> = {
      _TRIAL6: list(/_TRIAL6 = \[(.*?)\]/s.exec(py)![1]!),
      _INVEST5: list(/_INVEST5 = \[(.*?)\]/s.exec(py)![1]!),
    }
    for (const kind of ['civil', 'criminal'] as const) {
      const body = new RegExp(`"${kind}": _expand\\(\\[(.*?)\\r?\\n\\s*\\]\\),`, 's').exec(py)![1]!
      const want: string[] = []
      for (const m of body.matchAll(/\("([^"]+)", (\[[^\]]*\]|_TRIAL6|_INVEST5)\)/g)) {
        want.push(m[1]!)
        const subs = m[2]!.startsWith('[') ? list(m[2]!) : consts[m[2]!]!
        for (const s of subs) want.push(`${m[1]}/${s}`)
      }
      expect(want.length).toBeGreaterThan(5)
      expect(folderRels(kind, { tops: CASE_TEMPLATES[kind].map((f) => f.name), custom: [] })).toEqual(want)
    }
  })

  it('自填名：非法字符、首尾空格或点、Windows 保留名、"工作区""成果"都拒；正常名照收', () => {
    for (const n of ['a/b', 'a\\b', 'a:b', 'a?', '<a>', 'a|b', 'a*', '"a"', ' a', 'a.', '.a', 'CON', 'nul.txt', 'com1', '工作区', '成果', '', '甲'.repeat(81)]) {
      expect(customFolderProblem(n), n).not.toBeNull()
    }
    for (const n of ['09往来函件', '保全', 'console', 'a.b']) expect(customFolderProblem(n), n).toBeNull()
  })
})

describe('Host：按名单建子文件夹（真文件系统）', () => {
  let dir: string
  beforeEach(() => { dir = mkdtempSync(join(tmpdir(), 'lb-folders-')) })
  afterEach(() => rmSync(dir, { recursive: true, force: true }))
  const up = { endpoint: () => ({ port: 1, token: 't' }), state: 'running' } as unknown as Supervisor
  function remote(caseRoot: string) {
    const r = new LawbenchRemote(up, tmpdir(), () => undefined)
    r.desk = { ...r.desk } as DeskDeps
    ;(r as unknown as { callApi: (route: { method: string }) => Promise<unknown> }).callApi = async (route) =>
      route.method === 'caseRecent' ? { ok: true, value: { cases: [{ case_id: 'c-1', root: caseRoot, name: '甲', exists: true }] } } : { ok: false, error: { code: 'X', message: 'x' } }
    return r
  }
  const tops = (root: string) => readdirSync(root).sort()

  it('一个不勾：什么都不建（工作区、成果由服务建）', async () => {
    const root = join(dir, '甲案'); mkdirSync(root)
    expect(await remote(root).caseFolders({ case_id: 'c-1', root, kind: 'civil', tops: [], custom: [] })).toEqual({ ok: true, value: { folders_created: [] } })
    expect(tops(root)).toEqual([])
  })

  it('勾两项：只建这两项（含二级目录），按标准顺序；已有的不动；自填一项排在后面', async () => {
    const root = join(dir, '甲案'); mkdirSync(join(root, '01委托手续'), { recursive: true })
    writeFileSync(join(root, '01委托手续', '委托合同.docx'), 'x')
    const r = await remote(root).caseFolders({ case_id: 'c-1', root, kind: 'civil', tops: ['03一审', '01委托手续'], custom: ['09往来函件'] })
    expect(r).toEqual({ ok: true, value: { folders_created: ['03一审', ...['我方文件', '我方证据', '对方文件', '对方证据', '庭审准备', '法院文书'].map((s) => `03一审/${s}`), '09往来函件'] } })
    expect(tops(root)).toEqual(['01委托手续', '03一审', '09往来函件'].sort())
    expect(readdirSync(join(root, '01委托手续'))).toEqual(['委托合同.docx'])
    expect(readdirSync(join(root, '03一审'))).toHaveLength(6)
  })

  it('请求里的非法名、标准目录外的一级名、种类不对、没登记的案件根：一概不建', async () => {
    const root = join(dir, '甲案'); mkdirSync(root)
    const r = remote(root)
    for (const req of [
      { case_id: 'c-1', root, kind: 'civil', tops: [], custom: ['..\\外面'] },
      { case_id: 'c-1', root, kind: 'civil', tops: [], custom: ['CON'] },
      { case_id: 'c-1', root, kind: 'civil', tops: [], custom: ['成果'] },
      { case_id: 'c-1', root, kind: 'civil', tops: ['07申诉与再审'], custom: [] },
      { case_id: 'c-1', root, kind: 'other', tops: [], custom: [] },
      { case_id: 'c-9', root, kind: 'civil', tops: ['01委托手续'], custom: [] },
    ]) expect((await r.caseFolders(req)).ok, JSON.stringify(req)).toBe(false)
    expect(tops(root)).toEqual([])
  })

  it('路上某一级是同名文件或联接：整条跳过，不往里建（同 gate.py mkdir_original）', () => {
    const root = join(dir, '甲案'); mkdirSync(root)
    writeFileSync(join(root, '03一审'), 'x')
    expect(mkdirInCase(root, '03一审/我方文件')).toBe(false)
    const outside = join(dir, '外面'); mkdirSync(outside)
    let linked = false
    try { symlinkSync(outside, join(root, '04二审'), 'junction'); linked = true } catch { /* 建不了联接的环境跳过 */ }
    if (linked) {
      expect(mkdirInCase(root, '04二审/我方文件')).toBe(false)
      expect(readdirSync(outside)).toEqual([])
    }
    expect(lstatSync(join(root, '03一审')).isFile()).toBe(true)
  })

  it('chosenFolders：不收数组以外的东西、自填超过 20 项', () => {
    expect(chosenFolders('civil', '01委托手续', []).ok).toBe(false)
    expect(chosenFolders('civil', [], Array.from({ length: 21 }, (_, i) => `自填${i}`)).ok).toBe(false)
    expect(chosenFolders('criminal', ['08执行（财产刑/民事赔偿）'], [])).toEqual({ ok: true, value: ['08执行（财产刑/民事赔偿）'] })
  })
})

describe('界面：新建案件弹"要建哪些子文件夹"', () => {
  function setup() {
    const calls: Array<[string, unknown]> = []
    setNav({ pickDirectory: async () => DIR, openCaseWorkspace: async () => {}, openTab: () => {}, seedTabs: () => {} } as unknown as Nav)
    setApi({
      caseOpen: async (r: unknown) => { calls.push(['caseOpen', r]); return { ok: true, value: { case_id: 'c-1', name: '李某合同纠纷', created: true, folders_created: [] } } },
      caseFolders: async (r: { tops: string[]; custom: string[] }) => { calls.push(['caseFolders', r]); return { ok: true, value: { folders_created: [...r.tops, ...r.custom] } } },
    } as unknown as LawbenchApi)
    return calls
  }
  async function show() {
    root = createRoot(box)
    await act(async () => { root!.render(createElement(DialogHost)) })
  }
  const boxes = () => [...box.querySelectorAll<HTMLInputElement>('input[type=checkbox]')]
  const button = (text: string) => [...box.ownerDocument.querySelectorAll('button')].find((b) => b.textContent?.includes(text))!

  it('默认全不勾，直接确定：登记案件（template 为 null），不问 Host 建子文件夹', async () => {
    const calls = setup()
    await show()
    const p = openCase(null, 'civil')
    await act(async () => { await tick() })
    expect(box.ownerDocument.body.textContent).toContain('要建哪些子文件夹')
    expect(boxes()).toHaveLength(6)
    expect(boxes().every((b) => !b.checked)).toBe(true)
    await act(async () => { button('不建子文件夹').click() })
    expect(await p).toMatchObject({ case_id: 'c-1' })
    expect(calls).toEqual([['caseOpen', { path: DIR, template: null }]])
  })

  it('勾两项：Host 只建这两项；"全选"后再点变"全不选"', async () => {
    const calls = setup()
    await show()
    const p = openCase(null, 'criminal')
    await act(async () => { await tick() })
    expect(boxes()).toHaveLength(8)
    await act(async () => { button('全选').click() })
    expect(boxes().every((b) => b.checked)).toBe(true)
    await act(async () => { button('全不选').click() })
    await act(async () => { boxes()[4]!.click() })
    await act(async () => { boxes()[0]!.click() })
    await act(async () => { button('新建案件并建 2 项').click() })
    await p
    expect(calls[1]).toEqual(['caseFolders', { case_id: 'c-1', root: DIR, kind: 'criminal', tops: ['01委托手续', '05一审'], custom: [] }])
  })

  it('自填一项：非法名当场拒（不加进列表）；合法名加进去并一起建', async () => {
    const calls = setup()
    await show()
    const p = openCase(null, 'civil')
    await act(async () => { await tick() })
    const input = box.ownerDocument.querySelector<HTMLInputElement>('input[aria-label="自己添加的子文件夹名"]')!
    const type = async (v: string) => {
      await act(async () => {
        Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, v)
        input.dispatchEvent(new Event('input', { bubbles: true }))
      })
    }
    await type('证据:原件')
    await act(async () => { button('添加一项').click() })
    expect(box.ownerDocument.querySelector('[role=alert]')?.textContent).toContain('不能有')
    expect(boxes()).toHaveLength(6)
    await type('CON')
    await act(async () => { button('添加一项').click() })
    expect(box.ownerDocument.querySelector('[role=alert]')?.textContent).toContain('保留')
    await type('09往来函件')
    await act(async () => { button('添加一项').click() })
    expect(boxes()).toHaveLength(7)
    await act(async () => { button('新建案件并建 1 项').click() })
    await p
    expect(calls[1]).toEqual(['caseFolders', { case_id: 'c-1', root: DIR, kind: 'civil', tops: [], custom: ['09往来函件'] }])
  })

  it('取消：不新建（不登记案件）；打开已有案件不弹', async () => {
    const calls = setup()
    await show()
    const p = openCase(null, 'civil')
    await act(async () => { await tick() })
    await act(async () => { button('取消').click() })
    expect(await p).toBeUndefined()
    expect(calls).toEqual([])
    expect(await openCase(DIR, null)).toMatchObject({ case_id: 'c-1' })
    expect(calls).toEqual([['caseOpen', { path: DIR, template: null }]])
  })
})
