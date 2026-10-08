// @vitest-environment jsdom
// 令 1852 第 18 条（第七版待办 18）：案件 wiki 六板块合成一张卡、一次核对、可打开 wiki 文件夹和各板块文件。
import { mkdirSync, mkdtempSync, realpathSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { readCaseWiki, WIKI_SECTIONS } from '../host/case-wiki.ts'
import { openableFile, openableFolder } from '../host/desk-actions.ts'
import { articleLines, WikiCard, WIKI_FOLDER, type CaseWiki } from '../ui/wiki-card.tsx'
import { setApi, type CaseRef, type LawbenchApi } from '../ui/state.ts'
import { setNav, type Nav } from '../ui/kit.tsx'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
let root: Root | undefined
let box: HTMLDivElement
beforeEach(() => { box = document.createElement('div'); document.body.appendChild(box); localStorage.clear() })
afterEach(async () => { await act(async () => { root?.unmount() }); root = undefined; box.remove(); setApi(undefined); setNav(undefined) })

const SHA = (c: string) => c.repeat(64)
const fact = (text: string, cite: string) => ({ id: 'F0001', text, citations: [cite], status: 'excerpt' })

function writeWiki(caseRoot: string, materialsNow: Array<[string, string]>) {
  const wiki = join(caseRoot, '工作区', 'wiki')
  mkdirSync(join(wiki, '案件'), { recursive: true })
  mkdirSync(join(caseRoot, '工作区', '材料'), { recursive: true })
  writeFileSync(join(wiki, 'case.json'), JSON.stringify({
    v: 1, case_id: 'c-1', case_type: 'civil', stance: null,
    parties: [fact('周某（出借人）', '〔借条 第1页〕')], issues: [fact('借款是否已归还', '〔借条 第1页〕')], key_facts: [],
    generated_by: 'P-20261008100000-abcd', generated_at: '2026-10-08T10:00:00+08:00',
    materials_at_generation: [{ material_id: 'M0001', sha256: SHA('a') }, { material_id: 'M0002', sha256: SHA('b') }],
  }))
  for (const t of ['概览', '当事人', '时间线', '材料清单', '争议焦点']) writeFileSync(join(wiki, '案件', `${t}.md`), `# ${t}\n\n- 周某出借 30 万元〔借条 第1页〕\n`)
  writeFileSync(join(caseRoot, '工作区', '材料', 'index.json'), JSON.stringify({ v: 1, case_id: 'c-1', next_seq: 4, materials: materialsNow.map(([id, sha]) => ({ material_id: id, sha256: sha })) }))
}

describe('Host 读 wiki（真文件系统）', () => {
  let dir: string
  beforeEach(() => { dir = mkdtempSync(join(tmpdir(), 'lb-wiki-')) })
  afterEach(() => rmSync(dir, { recursive: true, force: true }))

  it('六个板块按顺序、生成时间、生成后材料变化（新增、变化、移除）；材料变了指纹就变', () => {
    const caseRoot = join(dir, '甲案')
    writeWiki(caseRoot, [['M0001', SHA('a')], ['M0002', SHA('b')]])
    const a = readCaseWiki(caseRoot)
    if (!a.ok) throw new Error('读不到')
    expect(a.value.sections.map((s) => s.title)).toEqual(['案件卡片', '概览', '当事人', '时间线', '材料清单', '争议焦点'])
    expect(a.value.sections.slice(1).every((s) => s.text?.includes('借条 第1页'))).toBe(true)
    expect(a.value.card?.parties[0]).toMatchObject({ text: '周某（出借人）', citations: ['〔借条 第1页〕'] })
    expect(a.value).toMatchObject({ exists: true, generated_at: '2026-10-08T10:00:00+08:00', changes: { added: 0, changed: 0, removed: 0 } })
    writeWiki(caseRoot, [['M0001', SHA('c')], ['M0003', SHA('d')]])
    const b = readCaseWiki(caseRoot)
    if (!b.ok) throw new Error('读不到')
    expect(b.value.changes).toEqual({ added: 1, changed: 1, removed: 1 })
    expect(b.value.signature).not.toBe(a.value.signature)
  })

  it('没有 wiki：exists 为 false；板块文件路径都在案件根里，"打开文件夹""打开文件"的核对都放行', () => {
    const caseRoot = join(dir, '乙案')
    mkdirSync(caseRoot)
    const r = readCaseWiki(caseRoot)
    expect(r.ok && r.value.exists).toBe(false)
    writeWiki(caseRoot, [])
    expect(openableFolder(caseRoot, WIKI_FOLDER)).toEqual({ ok: true, value: realpathSync.native(join(caseRoot, '工作区', 'wiki')) })
    for (const s of WIKI_SECTIONS) if (s.rel) expect(openableFile(caseRoot, s.rel).ok, s.rel).toBe(true)
  })
})

describe('文章正文轻量显示', () => {
  it('与板块同名的一级标题不重复；小标题、说明行分开；去掉 ** 记号；连续空行并成一行', () => {
    expect(articleLines('# 争议焦点\n\n\n### 1. 款项性质\n> Updated: 2026-10-08\n- **需要律师关注**：无书面协议', '争议焦点')).toEqual([
      { kind: 'h', text: '1. 款项性质' },
      { kind: 'note', text: 'Updated: 2026-10-08' },
      { kind: 'text', text: '- 需要律师关注：无书面协议' },
    ])
    expect(articleLines('# 别的标题', '概览')).toEqual([{ kind: 'h', text: '别的标题' }])
  })
})

describe('界面：一张卡', () => {
  const CASE: CaseRef = { case_id: 'c-1', name: '李某借贷案', root: 'D:\\案件\\李某借贷案' }
  const MATS = [{ material_id: 'M0001', name: '借条' }]
  const wiki = (signature: string): CaseWiki => ({
    exists: true, generated_at: '2026-10-08T10:00:00+08:00', signature,
    sections: [
      { key: 'card', title: '案件卡片', rel: null, text: null, truncated: false },
      ...['概览', '当事人', '时间线', '材料清单', '争议焦点'].map((t, i) => ({ key: `k${i}`, title: t, rel: `工作区/wiki/案件/${t}.md`, text: `# ${t}\n- 周某出借 30 万元〔借条 第1页〕`, truncated: false })),
    ],
    card: { parties: [{ text: '周某（出借人）', citations: ['〔借条 第1页〕'], status: 'excerpt' }], issues: [], key_facts: [] },
    changes: { added: 1, changed: 0, removed: 0 },
  })
  let current = wiki('v1')
  const calls: Array<[string, unknown]> = []
  const opened: unknown[] = []
  function setup() {
    calls.length = 0; opened.length = 0; current = wiki('v1')
    setNav({ openTab: (...a: unknown[]) => { opened.push(a) } } as unknown as Nav)
    setApi({
      caseWiki: async (r: unknown) => { calls.push(['caseWiki', r]); return { ok: true, value: current } },
      openFolder: async (r: unknown) => { calls.push(['openFolder', r]); return { ok: true, value: { opened: true } } },
      openFile: async (r: unknown) => { calls.push(['openFile', r]); return { ok: true, value: { opened: true } } },
    } as unknown as LawbenchApi)
  }
  async function render(refreshKey = 0) {
    root ??= createRoot(box)
    await act(async () => { root!.render(createElement(WikiCard, { caseRef: CASE, materials: MATS, refreshKey })) })
    await act(async () => { await new Promise((r) => setTimeout(r, 0)) })
  }
  const button = (text: string) => [...box.querySelectorAll('button')].find((b) => b.textContent?.includes(text))!

  it('六个板块折在一张卡里；顶部写生成时间、材料变化和"待复核"；展开看内容，出处可点', async () => {
    setup()
    await render()
    expect(box.querySelectorAll('section[aria-label="案件 wiki"]')).toHaveLength(1)
    const rows = [...box.querySelectorAll('button[aria-expanded]')].map((b) => b.textContent!.replace(/^[▸▾] /, ''))
    expect(rows).toEqual(['案件卡片', '概览', '当事人', '时间线', '材料清单', '争议焦点'])
    expect(box.textContent).toContain('生成于')
    expect(box.textContent).toContain('新增 1 份')
    expect(box.textContent).toContain('待复核')
    expect(box.textContent).not.toContain('周某出借')
    await act(async () => { button('争议焦点').click() })
    expect(box.textContent).toContain('周某出借 30 万元')
    await act(async () => { button('借条 第1页').click() })
    expect(opened).toEqual([['lawbench-source', { material_id: 'M0001', citation: '〔借条 第1页〕' }]])
    await act(async () => { button('案件卡片').click() })
    expect(box.textContent).toContain('周某（出借人）')
  })

  it('"核对完成"一次清掉待复核（本机记下）；wiki 重新生成或材料变化（指纹变）后又待复核', async () => {
    setup()
    await render()
    await act(async () => { button('核对完成').click() })
    expect(box.textContent).toContain('已核对')
    expect(box.textContent).not.toContain('待复核')
    expect(box.textContent).not.toContain('需要复核')
    expect(JSON.parse(localStorage.getItem('lawbench.wikiChecked.c-1')!)).toMatchObject({ signature: 'v1' })
    await act(async () => { root!.unmount() }); root = undefined
    await render()
    expect(box.textContent).toContain('已核对')
    current = wiki('v2')
    await render(1)
    expect(box.textContent).toContain('待复核')
  })

  it('"打开 wiki 文件夹"开案件里的 工作区/wiki；板块"打开文件"开对应 md；案件卡片没有"打开文件"', async () => {
    setup()
    await render()
    await act(async () => { button('打开 wiki 文件夹').click() })
    const files = [...box.querySelectorAll('button')].filter((b) => b.textContent === '打开文件')
    expect(files).toHaveLength(5)
    await act(async () => { files[0]!.click() })
    expect(calls.filter((c) => c[0] !== 'caseWiki')).toEqual([
      ['openFolder', { case_id: 'c-1', root: CASE.root, rel: '工作区/wiki' }],
      ['openFile', { case_id: 'c-1', root: CASE.root, rel: '工作区/wiki/案件/概览.md' }],
    ])
  })

  it('没有 wiki：只说还没生成，不显示核对按钮', async () => {
    setup()
    current = { ...wiki('x'), exists: false }
    await render()
    expect(box.textContent).toContain('还没有生成')
    expect(button('核对完成')).toBeUndefined()
  })
})
