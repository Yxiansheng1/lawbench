// 令 2043 第 4 条：选 Skill（写任务单）之前按材料篇幅估一次，读不全先问。
import { confirmScope, ESTIMATE_OK, ESTIMATE_TITLE, estimateCoverage, estimateText, OCR_TITLE, ocrTargets, ocrText, pendingOcr, READ_BUDGET_FILES, READ_BUDGET_PAGES } from '../ui/estimate.ts'
import { app, setApi, type LawbenchApi } from '../ui/state.ts'
import { setNav, type Nav } from '../ui/kit.tsx'

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

describe('运行前有材料还没识别（令 1257 第 1 条）', () => {
  const SCAN = { unit: 'page', unit_count: 12, status: 'needs_ocr', pages_need_ocr: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12] }
  const PART = { unit: 'page', unit_count: 9, status: 'partial', pages_need_ocr: [3, 4] }
  const OK = { unit: 'page', unit_count: 2, status: 'parsed', pages_need_ocr: [] }
  const opened: Array<[string, Record<string, string> | undefined]> = []
  beforeEach(() => { opened.length = 0; setNav({ openTab: (k: string, p?: Record<string, string>) => { opened.push([k, p]) } } as unknown as Nav) })
  afterEach(() => setNav(undefined))
  const ask = async (materials: unknown[]) => {
    setApi({ materialsList: async () => ({ ok: true, value: { materials } }) } as unknown as LawbenchApi)
    const p = confirmScope(CASE)
    await new Promise((r) => setTimeout(r, 0))
    return { p } // 包一层：直接返回会被 await 摊平成"等弹框答完"
  }

  it('数份数和页数：有待识别页的都算；整份没识别但页号为空的按页数算', () => {
    expect(pendingOcr([SCAN, PART, OK] as never)).toEqual({ files: 2, pages: 14 })
    expect(pendingOcr([{ status: 'needs_ocr', unit_count: 5, pages_need_ocr: [] }] as never)).toEqual({ files: 1, pages: 5 })
    expect(pendingOcr([OK] as never)).toEqual({ files: 0, pages: 0 })
    // 复核 rv-A52 P3-3：已经在识别的不算、也不进提交框
    const RUNNING = { ...SCAN, status: 'ocr_running' }
    expect(pendingOcr([RUNNING, PART] as never)).toEqual({ files: 1, pages: 2 })
    expect(ocrTargets([RUNNING, PART] as never)).toEqual([PART])
    expect(ocrText({ files: 2, pages: 14 })).toBe('有 2 份材料（14 页）还没识别，分析时读不到它们的文字。先识别吗？')
    // "去识别"打开的提交框里列的材料：同一口径
    const blank = { status: 'needs_ocr', unit_count: 5, pages_need_ocr: [] }
    expect(ocrTargets([SCAN, PART, OK, blank] as never)).toEqual([SCAN, PART, blank])
  })

  it('"去识别"：不写任务单，打开右栏"材料"并请它弹出待识别页的提交框', async () => {
    const { p } = await ask([SCAN, OK])
    expect(lastDialog()).toMatchObject({ kind: 'ocrFirst', title: OCR_TITLE, text: ocrText({ files: 1, pages: 12 }) })
    lastDialog()!.resolve!('ocr')
    expect(await p).toBe(false)
    expect(opened).toHaveLength(1)
    expect(opened[0]![0]).toBe('lawbench-materials')
    expect(opened[0]![1]).toMatchObject({ ocr: 'pending' })
  })

  it('"仍然开始"：接着按篇幅估（没超额就直接开始）；"取消"：不开始、不跳转', async () => {
    const go = await ask([PART, OK])
    lastDialog()!.resolve!('go')
    expect(await go.p).toBe(true)
    const cancel = await ask([PART])
    lastDialog()!.resolve!('cancel')
    expect(await cancel.p).toBe(false)
    expect(opened).toHaveLength(0)
  })

  it('"仍然开始"后材料又超额：再弹"材料较长"', async () => {
    const big = { ...PART, unit_count: READ_BUDGET_PAGES + 1 }
    const { p } = await ask([big])
    lastDialog()!.resolve!('go')
    await new Promise((r) => setTimeout(r, 0))
    expect(lastDialog()).toMatchObject({ kind: 'confirm', title: ESTIMATE_TITLE })
    lastDialog()!.resolve!(true)
    expect(await p).toBe(true)
  })

  it('都识别过了：不问', async () => {
    expect(await (await ask([OK])).p).toBe(true)
    expect(app.get().dialogs).toHaveLength(0)
  })
})
