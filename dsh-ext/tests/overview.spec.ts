// @vitest-environment jsdom
// 令 1347：空会话顶部的案件概览卡（第 2 条）、侧栏"（非办案）"（第 4 条）、日常事务建不了时停止重试（P3-1）、胶囊读失败不缓存（P3-4）。
import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { CaseOverview, DAILY_HINT, materialCounts, outputFile, recentOutputs, shortTime } from '../ui/overview.tsx'
import { setNav, type Nav } from '../ui/kit.tsx'
import { app, setApi, type LawbenchApi } from '../ui/state.ts'
import { landOnDailyCase } from '../ui/cases.ts'
import { dailyErrorText } from '../ui/daily-error.tsx'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
let root: Root | undefined
let box: HTMLDivElement
beforeEach(() => { box = document.createElement('div'); document.body.appendChild(box) })
afterEach(async () => { await act(async () => { root?.unmount() }); root = undefined; box.remove(); setApi(undefined); setNav(undefined); app.set((s) => ({ ...s, dailyRoot: null, dailyError: null })) })

const CASE = { case_id: 'c-1', name: '张某甲诈骗案', root: 'D:\案件\张某甲诈骗案', exists: true }
const DAILY = { case_id: 'd-1', name: '日常事务', root: 'D:\文档\连越律师工作台\日常事务', exists: true }
const render = async (el: ReturnType<typeof createElement>) => { root = createRoot(box); await act(async () => { root!.render(el) }); await act(async () => { await Promise.resolve(); await Promise.resolve() }) }

describe('案件概览卡', () => {
  it('材料份数与待识别份数、已确认的成果（全部、按确认时间倒序）、最近一次对话；点成果用默认程序打开、"打开所在文件夹"开成果文件夹，点对话转到那条会话（令 1321 D.2）', async () => {
    const tabs: string[] = []
    const opened: string[] = []
    setNav({ openTab: (k: string) => { tabs.push(k) }, openSession: (id: string) => { opened.push(id) } } as unknown as Nav)
    const out = (title: string, at: string) => ({ title, version: 1, confirmed_at: at, files: [{ path: `成果/${title}-v1.docx` }] })
    const calls: Array<[string, unknown]> = []
    setApi({
      openFile: async (req: unknown) => { calls.push(['openFile', req]); return { ok: true, value: { opened: true } } },
      openFolder: async (req: unknown) => { calls.push(['openFolder', req]); return { ok: true, value: { opened: true } } },
      materialsList: async () => ({ ok: true, value: { materials: [{ pages_need_ocr: [] }, { pages_need_ocr: [3, 4] }, { pages_need_ocr: [] }] } }),
      outputsList: async () => ({ ok: true, value: { outputs: [out('甲', '2026-10-01T10:00:00+08:00'), out('乙', '2026-10-03T10:00:00+08:00'), out('丙', '2026-10-02T10:00:00+08:00'), out('丁', '2026-09-30T10:00:00+08:00')] } }),
    } as unknown as LawbenchApi)
    await render(createElement(CaseOverview, { caseRef: CASE, daily: false, sessions: [{ id: 's-old', title: '旧对话', updatedAt: 1 }, { id: 's-new', title: '取保候审', updatedAt: 2 }] }))
    expect(box.textContent).toContain('张某甲诈骗案')
    expect(box.textContent).toContain('3 份（其中待识别 1 份）')
    const outs = [...box.querySelectorAll('button')].map((b) => b.textContent).filter((t) => t?.endsWith('.docx'))
    expect(outs).toEqual(['乙-v1.docx', '丙-v1.docx', '甲-v1.docx', '丁-v1.docx'])
    expect(box.textContent).toContain('已确认的成果')
    await act(async () => { [...box.querySelectorAll('button')].find((b) => b.textContent === '乙-v1.docx')!.click() })
    await act(async () => { [...box.querySelectorAll('button')].find((b) => b.textContent === '打开所在文件夹')!.click() })
    ;[...box.querySelectorAll('button')].find((b) => b.textContent === '取保候审')!.click()
    expect(calls).toEqual([
      ['openFile', { case_id: 'c-1', root: CASE.root, rel: '成果/乙-v1.docx' }],
      ['openFolder', { case_id: 'c-1', root: CASE.root, rel: '成果' }],
    ])
    expect(tabs).toEqual([])
    expect(opened).toEqual(['s-new'])
  })

  it('日常事务：一句提示＋最近 3 条对话＋已确认的成果（注记 1432 第 2 条）；不读材料', async () => {
    let reads = 0
    let outReads = 0
    setApi({ materialsList: async () => { reads++; return { ok: true, value: { materials: [] } } }, outputsList: async () => { outReads++; return { ok: true, value: { outputs: [{ title: '起草的通知', version: 1, confirmed_at: '2026-10-08T10:00:00+08:00', files: [{ path: '成果/起草的通知-v1.docx' }] }] } } } } as unknown as LawbenchApi)
    const ss = [1, 2, 3, 4].map((n) => ({ id: `s${n}`, title: `对话${n}`, updatedAt: n }))
    await render(createElement(CaseOverview, { caseRef: DAILY, daily: true, sessions: ss }))
    expect(box.textContent).toContain('日常事务')
    expect(box.textContent).not.toContain('（非办案）')
    expect(box.textContent).toContain(DAILY_HINT)
    expect([...box.querySelectorAll('button')].map((b) => b.textContent)).toEqual(['对话4', '对话3', '对话2', '起草的通知-v1.docx', '打开所在文件夹'])
    expect(box.textContent).toContain('已确认的成果')
    expect(reads).toBe(0)
    expect(outReads).toBe(1)
  })

  it('小工具：份数、成果排序、时间', () => {
    expect(materialCounts([{ pages_need_ocr: [1] }, {}])).toEqual({ total: 2, pending: 1 })
    expect(recentOutputs([{ title: 'a', version: 1, confirmed_at: '2026-01-01T00:00:00Z', files: [] }], 3).length).toBe(1)
    // 点开哪个文件：有 Word 开 Word，否则第一个
    expect(outputFile({ title: 'a', version: 1, confirmed_at: '', files: [{ path: '成果/a-v1.md' }, { path: '成果/a-v1.docx' }] })).toBe('成果/a-v1.docx')
    expect(outputFile({ title: 'a', version: 1, confirmed_at: '', files: [{ path: '成果/a-v1.md' }] })).toBe('成果/a-v1.md')
    expect(outputFile({ title: 'a', version: 1, confirmed_at: '', files: [] })).toBeUndefined()
    const now = new Date('2026-10-04T13:00:00')
    expect(shortTime(new Date('2026-10-04T09:05:00').getTime(), now)).toBe('今天 09:05')
    expect(shortTime(new Date('2026-10-02T09:05:00').getTime(), now)).toBe('10月2日 09:05')
  })
})

describe('日常事务', () => {
  it('还没做首次配置（NOT_CONFIGURED）：照样等，但按慢节奏问，不每 2 秒一次（令 2033）', async () => {
    let n = 0
    setApi({ dailyCase: async () => { n++; return n < 3 ? { ok: false, error: { code: 'NOT_CONFIGURED', message: '还没完成首次配置' } } : { ok: false, error: { code: 'CASE_IN_SYNC_FOLDER', message: '不能选云同步文件夹' } } } } as unknown as LawbenchApi)
    const waits: number[] = []
    expect(await landOnDailyCase(async () => {}, async (ms) => { waits.push(ms) })).toBe(false)
    expect(waits).toEqual([10_000, 10_000])
  })

  it('P3-1：建不了且不会自己好（CASE_IN_SYNC_FOLDER）：不再重试，错误码照实记下，侧栏一行说明', async () => {
    let n = 0
    setApi({ dailyCase: async () => { n++; return { ok: false, error: { code: 'CASE_IN_SYNC_FOLDER', message: '不能选云同步文件夹' } } } } as unknown as LawbenchApi)
    expect(await landOnDailyCase(async () => {}, async () => {})).toBe(false)
    expect(n).toBe(1)
    expect(app.get().dailyError).toEqual({ code: 'CASE_IN_SYNC_FOLDER', message: '不能选云同步文件夹' })
    expect(dailyErrorText(app.get().dailyError!)).toBe('日常事务未能创建：不能选云同步文件夹，请在设置里改"日常办公文件夹"。')
  })
})
