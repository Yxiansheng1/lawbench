// @vitest-environment jsdom
// 契约 1.4（令 0242 第一优先）："移除此材料"放开——界面直接调 POST /api/materials/remove（原件移到系统回收站，可找回），
// Host 不再自己删文件；移走了 / 此前已移除 / 没移走三种结果分别告诉律师，没移走的原因照服务给的原样说；
// 已移除的材料（status = removed）在列表里标"已移除"、默认收起；wiki 生成时用过它就提示更新 wiki，wiki 卡把它算进"移除"。
import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { readCaseWiki } from '../host/case-wiki.ts'
import { LawbenchRemote } from '../host/index.ts'
import { API_ROUTES } from '../shared/api-routes.ts'
import { CONTRACT_VERSION, validate } from '../shared/contracts.ts'
import { REMOTE_METHODS } from '../shared/remote-methods.ts'
import { removeMaterial, REMOVE_TITLE, removeText, WIKI_UPDATE_HINT } from '../ui/folder-actions.ts'
import { STATUS_WORD } from '../ui/format.ts'
import { setNav, type Nav } from '../ui/kit.tsx'
import { Materials } from '../ui/materials.tsx'
import { app, setApi, type CaseRef, type LawbenchApi } from '../ui/state.ts'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
let root: Root | undefined
let box: HTMLDivElement
beforeEach(() => { box = document.createElement('div'); document.body.appendChild(box); localStorage.clear() })
afterEach(async () => { await act(async () => { root?.unmount() }); root = undefined; box.remove(); setApi(undefined); setNav(undefined); app.set((s) => ({ ...s, dialogs: [] })) })

const CASE: CaseRef = { case_id: '3f2b9c1e-7a4d-4e8b-9c2a-1b5d6e7f8a90', name: '张某甲诈骗案', root: 'D:\\案件\\张某甲诈骗案' }
const M = { material_id: 'M0003', name: '起诉意见书', rel_path: '02案件材料/起诉意见书.pdf' }
type Dialog = { kind: string; title?: string; text?: string; okLabel?: string; resolve?: (v: unknown) => void }
const dialogs = () => (app.get() as unknown as { dialogs: Dialog[] }).dialogs
const lastDialog = () => dialogs().at(-1)
const notices = () => dialogs().filter((d) => d.kind === 'notice').map((d) => [d.title, d.text])
const value = (v: Partial<{ removed: string[]; already_removed: string[]; failed: Array<{ material_id: string; reason: string }>; wiki_needs_update: boolean }>) =>
  ({ ok: true, value: { removed: [], already_removed: [], failed: [], wiki_needs_update: false, ...v } })

describe('契约版本', () => {
  it('客户端按 1.4 构建，与仓库 contracts\\VERSION 一致（Host 启动服务后严格比对）', () => {
    expect(CONTRACT_VERSION).toBe('1.4')
    expect(readFileSync(join(__dirname, '..', '..', 'contracts', 'VERSION'), 'utf8').trim()).toBe(CONTRACT_VERSION)
  })
})

describe('接线：移除走服务的接口，Host 不再自己删文件', () => {
  it('路由表有 materialsRemove（POST /api/materials/remove），请求按契约校验；Host 的旧方法 materialRemove 已撤', () => {
    expect(API_ROUTES.find((r) => r.method === 'materialsRemove')).toMatchObject({ http: 'POST', path: '/api/materials/remove', contract: 'materials_remove' })
    const id = 'lawbench://contracts/api/materials_remove.schema.json'
    expect(validate(id, 'request', { case_id: CASE.case_id, material_ids: ['M0003'] })).toEqual([])
    // 旧的请求形状（给路径）不合契约：界面只能按材料编号移除
    expect(validate(id, 'request', { case_id: CASE.case_id, root: CASE.root, rel_path: M.rel_path }).length).toBeGreaterThan(0)
    expect(validate(id, 'request', { case_id: CASE.case_id, material_ids: [] }).length).toBeGreaterThan(0)
    expect(REMOTE_METHODS.some((m) => m.method === 'materialRemove')).toBe(false)
    expect(REMOTE_METHODS.some((m) => m.method === 'materialsRemove')).toBe(true)
    const proto = LawbenchRemote.prototype as unknown as Record<string, unknown>
    expect(typeof proto.materialsRemove).toBe('function')
    expect(proto.materialRemove).toBeUndefined()
  })
})

describe('移除一份材料（界面流程）', () => {
  function api(answer: () => unknown) {
    const asked: unknown[] = []
    setApi({ materialsRemove: async (r: unknown) => { asked.push(r); return answer() } } as unknown as LawbenchApi)
    return asked
  }
  const run = async (yes: boolean) => { const p = removeMaterial(CASE, M); lastDialog()!.resolve!(yes); return p }

  it('先问：说明会移到回收站、可以找回；取消就什么都不做', async () => {
    const asked = api(() => value({ removed: ['M0003'] }))
    const p = removeMaterial(CASE, M)
    expect(lastDialog()).toMatchObject({ kind: 'confirm', title: REMOVE_TITLE })
    expect(removeText(M)).toContain('移到回收站，可从回收站找回')
    expect(removeText(M)).not.toContain('不进回收站')
    lastDialog()!.resolve!(false)
    expect(await p).toBe(false)
    expect(asked).toEqual([])
  })

  it('移走了：只按案件编号和材料编号请服务移除（不给路径）；告诉律师已移到回收站；通知材料列表和 wiki 卡刷新', async () => {
    const asked = api(() => value({ removed: ['M0003'] }))
    let changed = 0
    const on = () => { changed++ }
    window.addEventListener('lawbench:materials-changed', on)
    try {
      expect(await run(true)).toBe(true)
    } finally { window.removeEventListener('lawbench:materials-changed', on) }
    expect(asked).toEqual([{ case_id: CASE.case_id, material_ids: ['M0003'] }])
    expect(notices()).toEqual([['已移到回收站', '"起诉意见书"已从案件里移除，需要时可从回收站找回。']])
    expect(changed).toBe(1)
  })

  it('wiki 生成时用过这份材料（wiki_needs_update）：多说一句请更新 wiki', async () => {
    api(() => value({ removed: ['M0003'], wiki_needs_update: true }))
    expect(await run(true)).toBe(true)
    expect(notices()[0]![1]).toBe(`"起诉意见书"已从案件里移除，需要时可从回收站找回。${WIKI_UPDATE_HINT}`)
  })

  it('此前已经移除过（already_removed）：不报错，说明已经不在，列表照样刷新', async () => {
    api(() => value({ already_removed: ['M0003'] }))
    expect(await run(true)).toBe(true)
    expect(notices()).toEqual([['这份材料此前已经移除', '"起诉意见书"已经不在案件里，列表已更新。']])
  })

  it('没移走（failed）：服务给的原因原样告诉律师，不算移除', async () => {
    const reason = '该位置没有回收站，未移除；请在资源管理器里自行处理'
    api(() => value({ failed: [{ material_id: 'M0003', reason }] }))
    let changed = 0
    const on = () => { changed++ }
    window.addEventListener('lawbench:materials-changed', on)
    try {
      expect(await run(true)).toBe(false)
    } finally { window.removeEventListener('lawbench:materials-changed', on) }
    expect(notices()).toEqual([['材料没能移除', `"起诉意见书"：${reason}`]])
    expect(changed).toBe(0)
  })

  it('服务拒绝整个请求（如编号不在本案）：照服务的提示说，不算移除', async () => {
    api(() => ({ ok: false, error: { code: 'MATERIAL_NOT_FOUND', message: '找不到这份材料' } }))
    expect(await run(true)).toBe(false)
    expect(notices()[0]![0]).toBe('材料没能移除')
    expect(notices()[0]![1]).toContain('找不到这份材料')
  })
})

describe('材料页', () => {
  const row = (id: string, name: string, status: string) => ({ material_id: id, name, rel_path: `02案件材料/${name}.pdf`, type: 'pdf', status, unit: 'page', unit_count: 3, is_ocr: 'no', stale_ocr: false, error: null, pages_need_ocr: [], pages_mixed: [] })
  function setup(lists: unknown[][]) {
    const calls: Array<[string, unknown]> = []
    let n = 0
    setNav({ openTab: () => {}, pathFor: () => '', pickDirectory: async () => null } as unknown as Nav)
    setApi({
      materialsList: async () => ({ ok: true, value: { materials: lists[Math.min(n++, lists.length - 1)] } }),
      ocrList: async () => ({ ok: true, value: { jobs: [] } }),
      tasksList: async () => ({ ok: true, value: { tasks: [] } }),
      getWikiSuggestions: async () => ({ ok: true, value: { suggestions: [] } }),
      caseWiki: async () => ({ ok: true, value: { exists: false, generated_at: null, sections: [], card: null, changes: null, signature: 'x' } }),
      materialsRemove: async (r: unknown) => { calls.push(['materialsRemove', r]); return value({ removed: ['M0001'] }) },
    } as unknown as LawbenchApi)
    return calls
  }
  const settle = async () => { for (let i = 0; i < 5; i++) await act(async () => { await Promise.resolve() }) }
  async function render() {
    root = createRoot(box)
    await act(async () => { root!.render(createElement(Materials, { caseRef: CASE })) })
    await settle()
  }
  const buttons = (text: string) => [...box.querySelectorAll('button')].filter((b) => b.textContent === text) as HTMLButtonElement[]

  it('"移除此材料"可以点（不再是灰的、没有"暂不能移除"的提示）；识别进行中的那份仍不能点', async () => {
    setup([[row('M0001', '起诉意见书', 'parsed'), row('M0002', '询问笔录', 'ocr_running')]])
    await render()
    expect(buttons('移除此材料').map((b) => b.disabled)).toEqual([false, true])
    expect(box.innerHTML).not.toContain('暂不能在这里移除')
  })

  it('点了先问，确认后请服务移除，列表重新读一次、那份不再列出', async () => {
    const calls = setup([[row('M0001', '起诉意见书', 'parsed'), row('M0002', '询问笔录', 'parsed')], [row('M0002', '询问笔录', 'parsed')]])
    await render()
    await act(async () => { buttons('移除此材料')[0]!.click() })
    expect(lastDialog()).toMatchObject({ kind: 'confirm', title: REMOVE_TITLE })
    expect(calls).toEqual([])
    await act(async () => { lastDialog()!.resolve!(true) })
    await settle()
    expect(calls).toEqual([['materialsRemove', { case_id: CASE.case_id, material_ids: ['M0001'] }]])
    expect(box.textContent).not.toContain('起诉意见书')
    expect(box.textContent).toContain('询问笔录')
  })

  it('连点两次只问一次、只发一次；请求在途时按钮是灰的，答复后恢复（rv 1.4 客户端 P3-1）', async () => {
    const calls = setup([[row('M0001', '起诉意见书', 'parsed'), row('M0002', '询问笔录', 'parsed')]])
    let answer: (v: unknown) => void = () => {}
    setApi({ ...(await import('../ui/state.ts')).lb(), materialsRemove: (r: unknown) => { calls.push(['materialsRemove', r]); return new Promise((res) => { answer = res }) } } as unknown as LawbenchApi)
    await render()
    const btn = () => buttons('移除此材料')[0]!
    await act(async () => { btn().click(); btn().click() })
    expect(dialogs().filter((d) => d.kind === 'confirm').length).toBe(1)
    expect(btn().disabled).toBe(true)
    expect(buttons('移除此材料')[1]!.disabled).toBe(false) // 别的材料不受影响
    await act(async () => { dialogs().find((d) => d.kind === 'confirm')!.resolve!(true) })
    app.set((s) => ({ ...s, dialogs: [] }))
    await act(async () => { btn().click() }) // 服务还没答复：再点没有反应
    await settle()
    expect(calls.length).toBe(1)
    expect(dialogs().filter((d) => d.kind === 'confirm').length).toBe(0)
    expect(btn().disabled).toBe(true)
    await act(async () => { answer(value({ failed: [{ material_id: 'M0001', reason: '原件正在被其他程序占用' }] })) })
    await settle()
    expect(calls.length).toBe(1)
    expect(btn().disabled).toBe(false) // 没移走：可以再试
  })

  it('已移除的材料：默认收起，只写"已移除 1 份"；点开后标"已移除"、没有"移除此材料"按钮；可以再收起', async () => {
    expect(STATUS_WORD.removed).toBe('已移除')
    setup([[row('M0001', '起诉意见书', 'parsed'), row('M0002', '旧版合同', 'removed')]])
    await render()
    expect(box.textContent).toContain('已移除 1 份')
    expect(box.textContent).not.toContain('旧版合同')
    expect(buttons('移除此材料').length).toBe(1)
    await act(async () => { buttons('显示已移除的')[0]!.click() })
    expect(box.textContent).toContain('旧版合同')
    expect([...box.querySelectorAll('li')].find((li) => li.textContent!.includes('旧版合同'))!.textContent).toContain('已移除')
    expect(buttons('移除此材料').length).toBe(1)
    await act(async () => { buttons('隐藏已移除的')[0]!.click() })
    expect(box.textContent).not.toContain('旧版合同')
  })

  it('没有已移除的材料时不出现那一行', async () => {
    setup([[row('M0001', '起诉意见书', 'parsed')]])
    await render()
    expect(box.textContent).not.toContain('已移除')
  })
})

describe('wiki 卡：被移除的材料算进"移除"', () => {
  let dir: string
  beforeEach(() => { dir = mkdtempSync(join(tmpdir(), 'lb-rm-')) })
  afterEach(() => rmSync(dir, { recursive: true, force: true }))
  const SHA = (c: string) => c.repeat(64)

  it('index.json 里 status 为 removed 的那一条不算现有材料：生成后变化里"移除"加一，指纹跟着变', () => {
    const caseRoot = join(dir, '甲案')
    mkdirSync(join(caseRoot, '工作区', 'wiki'), { recursive: true })
    mkdirSync(join(caseRoot, '工作区', '材料'), { recursive: true })
    writeFileSync(join(caseRoot, '工作区', 'wiki', 'case.json'), JSON.stringify({
      v: 1, case_id: 'c-1', parties: [], issues: [], key_facts: [], generated_at: '2026-10-08T10:00:00+08:00',
      materials_at_generation: [{ material_id: 'M0001', sha256: SHA('a') }, { material_id: 'M0002', sha256: SHA('b') }],
    }))
    const index = (status2: string) => writeFileSync(join(caseRoot, '工作区', '材料', 'index.json'), JSON.stringify({
      v: 1, case_id: 'c-1', next_seq: 3, materials: [{ material_id: 'M0001', sha256: SHA('a'), status: 'parsed' }, { material_id: 'M0002', sha256: SHA('b'), status: status2 }],
    }))
    index('parsed')
    const before = readCaseWiki(caseRoot)
    index('removed')
    const after = readCaseWiki(caseRoot)
    if (!before.ok || !after.ok) throw new Error('读不到')
    expect(before.value.changes).toEqual({ added: 0, changed: 0, removed: 0 })
    expect(after.value.changes).toEqual({ added: 0, changed: 0, removed: 1 })
    expect(after.value.signature).not.toBe(before.value.signature)
  })
})
