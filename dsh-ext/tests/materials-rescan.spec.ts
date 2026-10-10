// @vitest-environment jsdom
// 令 1818 第 3 条（rv-A57 P3）：材料页"重新扫描"按钮的界面用例；第 2 条：已有案件重新扫描的说法照旧（带"需要复核"那句）。
import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { Materials } from '../ui/materials.tsx'
import { scanMaterials } from '../ui/cases.ts'
import { app, setApi, type CaseRef, type LawbenchApi } from '../ui/state.ts'
import { setNav, type Nav } from '../ui/kit.tsx'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
let root: Root | undefined
let box: HTMLDivElement
beforeEach(() => { box = document.createElement('div'); document.body.appendChild(box); localStorage.clear() })
afterEach(async () => { await act(async () => { root?.unmount() }); root = undefined; box.remove(); setApi(undefined); setNav(undefined); app.set((s) => ({ ...s, dialogs: [] })) })

const CASE: CaseRef = { case_id: 'c-1', name: '张某诈骗案', root: 'D:\\案件\\张某诈骗案' }
const MATERIAL = { material_id: 'M0001', name: '起诉意见书', rel_path: '02案件材料/起诉意见书.pdf', type: 'pdf', status: 'parsed', unit: 'page', unit_count: 3, is_ocr: 'no', stale_ocr: false, error: null, pages_need_ocr: [], pages_mixed: [] }
const notices = () => (app.get() as unknown as { dialogs: Array<{ kind: string; title?: string; text?: string }> }).dialogs.filter((d) => d.kind === 'notice').map((d) => [d.title, d.text])

function setup(scan: () => unknown) {
  const calls: Array<[string, unknown]> = []
  let listed = 0
  setNav({ openTab: () => {}, pathFor: () => '', pickDirectory: async () => null } as unknown as Nav)
  setApi({
    materialsList: async (r: unknown) => { calls.push(['materialsList', r]); listed++; return { ok: true, value: { materials: listed > 1 ? [MATERIAL, { ...MATERIAL, material_id: 'M0002', name: '询问笔录' }] : [MATERIAL] } } },
    ocrList: async () => ({ ok: true, value: { jobs: [] } }),
    tasksList: async () => ({ ok: true, value: { tasks: [] } }),
    getWikiSuggestions: async () => ({ ok: true, value: { suggestions: [] } }),
    caseWiki: async () => ({ ok: true, value: { exists: false, generated_at: null, sections: [], card: null, changes: null, signature: 'x' } }),
    materialsScan: async (r: unknown) => { calls.push(['materialsScan', r]); return scan() },
  } as unknown as LawbenchApi)
  return calls
}
async function render() {
  root = createRoot(box)
  await act(async () => { root!.render(createElement(Materials, { caseRef: CASE })) })
  for (let i = 0; i < 4; i++) await act(async () => { await Promise.resolve() })
}
const button = (text: string) => [...box.querySelectorAll('button')].find((b) => b.textContent === text)!
const only = (calls: Array<[string, unknown]>, name: string) => calls.filter((c) => c[0] === name)

describe('材料页"重新扫描"', () => {
  it('点一下：调一次扫描（带这个案件的编号），说明"扫描完成：新增…"（已有案件带"需要复核"那句），材料列表随即重读', async () => {
    const calls = setup(() => ({ ok: true, value: { added: 1, changed: 0, removed: 0, failed: 0, review_needed: true } }))
    await render()
    expect(box.textContent).toContain('起诉意见书')
    expect(box.textContent).not.toContain('询问笔录')
    expect(only(calls, 'materialsScan')).toEqual([])
    const listedBefore = only(calls, 'materialsList').length
    await act(async () => { button('重新扫描').click(); await new Promise((r) => setTimeout(r, 0)) })
    for (let i = 0; i < 4; i++) await act(async () => { await Promise.resolve() })
    expect(only(calls, 'materialsScan')).toEqual([['materialsScan', { case_id: 'c-1' }]])
    expect(notices()).toEqual([['扫描完成', '新增 1、变化 0、移除 0、失败 0。材料有变化，案件 wiki 和已有成果需要复核。']])
    expect(only(calls, 'materialsList').length).toBeGreaterThan(listedBefore)
    expect(box.textContent).toContain('询问笔录')
  })

  it('扫描没成：说明"扫描没有完成"，不说完成', async () => {
    const calls = setup(() => ({ ok: false, error: { code: 'INTERNAL', message: '内部错误，请重试' } }))
    await render()
    await act(async () => { button('重新扫描').click(); await new Promise((r) => setTimeout(r, 0)) })
    expect(only(calls, 'materialsScan')).toHaveLength(1)
    expect(notices().map((n) => n[0])).toEqual(['扫描没有完成'])
  })

  it('没有变化时不带"需要复核"；刚建成的案件（fresh）有变化也不带（令 1818 第 2 条：刚建的案件没有 wiki 和成果）', async () => {
    setup(() => ({ ok: true, value: { added: 0, changed: 0, removed: 0, failed: 0, review_needed: false } }))
    expect(await scanMaterials(CASE)).toBe(true)
    setup(() => ({ ok: true, value: { added: 3, changed: 0, removed: 0, failed: 0, review_needed: true } }))
    expect(await scanMaterials(CASE, true)).toBe(true)
    expect(notices()).toEqual([['扫描完成', '新增 0、变化 0、移除 0、失败 0。'], ['扫描完成', '新增 3、变化 0、移除 0、失败 0。']])
  })
})
