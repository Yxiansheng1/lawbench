// 令 2043 第 4 条：选 Skill（写任务单）之前按材料篇幅估一次，读不全先问。
import { confirmScope, ESTIMATE_OK, ESTIMATE_TITLE, estimateCoverage, estimateText, READ_BUDGET_FILES, READ_BUDGET_PAGES } from '../ui/estimate.ts'
import { app, setApi, type LawbenchApi } from '../ui/state.ts'

afterEach(() => { setApi(undefined); app.set((s) => ({ ...s, dialogs: [] })) })
const lastDialog = () => (app.get() as unknown as { dialogs: Array<{ kind: string; title: string; text: string; ok: string; resolve?: (v: unknown) => void }> }).dialogs.at(-1)
const CASE = { case_id: 'c-1', name: '甲案', root: 'D:\\案件\\甲案' }

describe('估算', () => {
  it('按折合页数从小到大装：总量不超过额度为"读得全"；超过时给出能读全约几份', () => {
    expect(estimateCoverage([{ unit: 'page', unit_count: 50 }, { unit: 'page', unit_count: 40 }], 100)).toEqual({ total: 2, fit: 2, pages: 90, over: false })
    const e = estimateCoverage([{ unit: 'page', unit_count: 80 }, { unit: 'page', unit_count: 30 }, { unit: 'line', unit_count: 400 }, { unit: 'cell', unit_count: 3 }], 100)
    // 折合：80、30、10（400 行 / 40）、6（3 张表 × 2）→ 共 126 页；从小到大 6 + 10 + 30 = 46，再加 80 超额
    expect(e).toEqual({ total: 4, fit: 3, pages: 126, over: true })
    expect(estimateText(e)).toContain('预计能读全约 3 份 / 共 4 份')
    expect(estimateText(e)).toContain('按案件全部材料估')
  })

  it('阈值：100 页或 11 份，先到者触发；"能读全约 N 份"按 11 份封顶（注记 2156）', () => {
    expect([READ_BUDGET_PAGES, READ_BUDGET_FILES]).toEqual([100, 11])
    const small = Array.from({ length: 12 }, () => ({ unit: 'page' as const, unit_count: 1 }))
    expect(estimateCoverage(small)).toEqual({ total: 12, fit: 11, pages: 12, over: true })
    expect(estimateCoverage(small.slice(0, 11))).toEqual({ total: 11, fit: 11, pages: 11, over: false })
    expect(estimateCoverage([{ unit: 'page', unit_count: 60 }, { unit: 'page', unit_count: 50 }])).toEqual({ total: 2, fit: 1, pages: 110, over: true })
  })
})

describe('选 Skill 之前问', () => {
  it('超额时弹"材料较长"，选"仍然开始"继续、取消不继续；没超额、读不到列表都不拦', async () => {
    setApi({ materialsList: async () => ({ ok: true, value: { materials: [{ unit: 'page', unit_count: READ_BUDGET_PAGES + 1 }] } }) } as unknown as LawbenchApi)
    const yes = confirmScope(CASE)
    await new Promise((r) => setTimeout(r, 0))
    expect(lastDialog()).toMatchObject({ kind: 'confirm', title: ESTIMATE_TITLE, ok: ESTIMATE_OK })
    lastDialog()!.resolve!(true)
    expect(await yes).toBe(true)
    const no = confirmScope(CASE)
    await new Promise((r) => setTimeout(r, 0))
    lastDialog()!.resolve!(false)
    expect(await no).toBe(false)
    setApi({ materialsList: async () => ({ ok: true, value: { materials: [{ unit: 'page', unit_count: 3 }] } }) } as unknown as LawbenchApi)
    expect(await confirmScope(CASE)).toBe(true)
    setApi({ materialsList: async () => ({ ok: false, error: { code: 'X', message: 'x' } }) } as unknown as LawbenchApi)
    expect(await confirmScope(CASE)).toBe(true)
    expect(await confirmScope(undefined)).toBe(true)
  })
})
