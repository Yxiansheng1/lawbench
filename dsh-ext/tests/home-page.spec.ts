// @vitest-environment jsdom
// 首页（令 1426）：日常事务排第一、其余按上次打开倒序最多 12 个；卡片数据（材料 / 待识别 / 成果、上次打开）；空状态；顶部律师姓名与日期。
import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { HOME_MAX_CASES, HomeLanding, homeCases, todayText, WELCOME_TEXT } from '../ui/home-page.tsx'
import { app, setApi, type CaseRef, type LawbenchApi } from '../ui/state.ts'
import { HOME_ORDER } from '../ui/index.tsx'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
let root: Root | undefined
let box: HTMLDivElement
beforeEach(() => { box = document.createElement('div'); document.body.appendChild(box) })
afterEach(async () => { await act(async () => { root?.unmount() }); root = undefined; box.remove(); setApi(undefined); app.set((s) => ({ ...s, cases: [], dailyRoot: null, lawyerName: null })) })

const DAILY: CaseRef = { case_id: 'd', name: '日常事务', root: 'D:\文档\日常事务', exists: true, last_opened: '2026-10-01T09:00:00+08:00' }
const mk = (n: number, day: number): CaseRef => ({ case_id: `c${n}`, name: `案件${n}`, root: `D:\案件\${n}`, exists: true, last_opened: `2026-09-${String(day).padStart(2, '0')}T10:00:00+08:00` })

function api(cases: CaseRef[]) {
  setApi({
    caseRecent: async () => ({ ok: true, value: { cases } }),
    getCapsules: async () => ({ ok: true, value: { v: 1, hint: '涉及隐私的材料进入本机案件。', shared: [], groups: [] } }),
    materialsList: async () => ({ ok: true, value: { materials: [{ pages_need_ocr: [] }, { pages_need_ocr: [2] }, { pages_need_ocr: [] }] } }),
    outputsList: async () => ({ ok: true, value: { outputs: [{}, {}] } }),
  } as unknown as LawbenchApi)
}
const render = async () => {
  root = createRoot(box)
  await act(async () => { root!.render(createElement(HomeLanding)) })
  for (let i = 0; i < 4; i++) await act(async () => { await Promise.resolve() })
}

describe('首页', () => {
  it('侧栏"首页"入口排在新会话上方（P-21 按 order <= -1000）', () => {
    expect(HOME_ORDER).toBeLessThanOrEqual(-1000)
  })

  it('卡片顺序：日常事务第一，其余按上次打开倒序，最多 12 个', () => {
    const cases = [mk(1, 1), DAILY, ...Array.from({ length: 14 }, (_, i) => mk(i + 2, i + 2))]
    const { daily, others } = homeCases(cases, DAILY.root)
    expect(daily?.case_id).toBe('d')
    expect(others.length).toBe(HOME_MAX_CASES)
    expect(others[0]!.case_id).toBe('c15')
    expect(others.some((c) => c.case_id === 'c1')).toBe(false)
  })

  it('有案件：日常事务一张样式区分排第一；每张显示材料 / 待识别 / 成果份数和上次打开；顶部律师姓名、日期、分流提示；三个主按钮', async () => {
    api([mk(1, 3), DAILY])
    app.set((s) => ({ ...s, dailyRoot: DAILY.root, lawyerName: '王律师' }))
    await render()
    const cards = [...box.querySelectorAll('[data-case-card]')] as HTMLElement[]
    expect(cards.map((c) => c.dataset.caseCard)).toEqual(['daily', 'case'])
    expect(cards[0]!.textContent).toContain('日常事务')
    expect(cards[0]!.textContent).not.toContain('（非办案）')
    expect(cards[1]!.textContent).toContain('材料 3 份 · 待识别 1 份 · 成果 2 份')
    expect(cards[1]!.textContent).toContain('上次打开')
    expect(box.textContent).toContain(`王律师 · ${todayText()}`)
    expect(box.textContent).toContain('涉及隐私的材料进入本机案件。')
    expect([...box.querySelectorAll('[aria-label="案件操作"] button')].map((b) => b.textContent)).toEqual(['打开案件…', '新建民商事案件…', '新建刑事案件…'])
    expect(box.textContent).not.toContain('技术支持') // 令 1515：首页不放技术支持，只在窗口右下角
  })

  it('空状态（只有日常事务或什么都没有）：居中欢迎语和三个按钮', async () => {
    api([])
    await render()
    expect(box.querySelector('[aria-label="欢迎"]')!.textContent).toContain(WELCOME_TEXT)
    expect(box.querySelectorAll('[aria-label="欢迎"] button').length).toBe(3)
    expect(box.querySelector('[aria-label="最近案件"]')).toBeNull()
  })

  it('日期写法', () => {
    expect(todayText(new Date('2026-10-04T12:00:00'))).toBe('2026年10月4日 星期日')
  })
})
