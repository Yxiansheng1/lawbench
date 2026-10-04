// @vitest-environment jsdom
// 两层胶囊放到输入框上方（执行令 1156 第 3 条，用户效果图 1.png）：空会话时从上到下是分流提示、第二层"<分类> · 选要做什么"、
// 第一层"能力入口"；点第二层把能力填成小标签并写任务单（/api/task，口径不变），× 取消；会话有内容后两层收起，"选能力"展开；
// 工具胶囊打开 T26 的页面。夹具同 dock-a19（helpers/dock-lab.ts）。
import { act, createElement } from 'react'
import { ComposerDock } from '../ui/dock.tsx'
import { homeView } from '../ui/invoice-logic.ts'
import { setNav, type Nav } from '../ui/kit.tsx'
import { CAPSULES, CASE, flush, h, setup, teardown } from './helpers/dock-lab.ts'
import { createRoot } from 'react-dom/client'

beforeEach(setup)
afterEach(async () => { await teardown(); setNav(undefined); homeView.set('home') })

async function mountBlank(blank: boolean) {
  h.root = createRoot(h.container)
  const useSessions = <T,>(select: (s: { byId: Record<string, { cwd?: string; blank?: boolean }> }) => T): T => select({ byId: { S1: { cwd: CASE.root, blank } } })
  await act(async () => { h.root!.render(createElement(ComposerDock, { sessionId: 'S1', useSessions })) })
  await flush()
}
const q = (sel: string) => h.container.querySelector(sel)
const all = (sel: string) => [...h.container.querySelectorAll(sel)] as HTMLElement[]
const click = async (el: Element | null | undefined) => { await act(async () => { (el as HTMLElement).click() }) }
const tab = (name: string) => all('[aria-label="能力入口"] [role=tab]').find((b) => b.textContent === `${name} ▾`)

describe('输入框上方的两层胶囊', () => {
  it('空会话：分流提示一行、第二层是第一个分类的业务项、第一层三个分类且第一个高亮', async () => {
    await mountBlank(true)
    expect(h.container.textContent).toContain(CAPSULES.hint)
    const [g0] = CAPSULES.groups
    expect(q('[aria-label="选要做什么"]')!.textContent).toContain(`${g0.name} · 选要做什么`)
    expect(all('[data-capsule-id]').map((b) => b.dataset.capsuleId)).toEqual(g0.items.map((x: { id: string }) => x.id))
    const tabs = all('[aria-label="能力入口"] [role=tab]')
    expect(tabs.map((t) => t.getAttribute('aria-selected'))).toEqual(['true', 'false', 'false'])
    // 第二层在第一层上面
    expect(q('[aria-label="选要做什么"]')!.compareDocumentPosition(q('[aria-label="能力入口"]')!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('选第一层"刑事"：第二层换成刑事的业务项', async () => {
    await mountBlank(true)
    await click(tab('刑事案件'))
    expect(tab('刑事案件')!.getAttribute('aria-selected')).toBe('true')
    expect(all('[data-capsule-id]').map((b) => b.dataset.capsuleId)).toEqual(['case-analysis', 'sentence-calc', 'bail-application', 'defense-opinion', 'cross-exam'])
  })

  it('点第二层：输入框上方出现小标签【名称】并写任务单；点 × 取消回到自由对话，也写任务单', async () => {
    await mountBlank(true)
    await click(q('[data-capsule-id="contract-draft"]'))
    await flush(600)
    expect(q('[data-capsule-tag]')!.textContent).toContain('【合同起草】')
    expect(h.svc.cur('S1')?.entry).toBe('contract-draft')
    await click(q('[aria-label="取消这项能力"]'))
    await flush(600)
    expect(q('[data-capsule-tag]')).toBeNull()
    expect(h.svc.cur('S1')?.entry).toBeNull()
  })

  it('会话有内容后两层收起，点"选能力"展开，选完又收起', async () => {
    await mountBlank(false)
    expect(q('[aria-label="能力入口"]')).toBeNull()
    expect(h.container.textContent).not.toContain(CAPSULES.hint)
    await click(all('button').find((b) => b.textContent === '选能力'))
    expect(q('[aria-label="能力入口"]')).not.toBeNull()
    await click(q('[data-capsule-id="contract-review"]'))
    expect(q('[aria-label="能力入口"]')).toBeNull()
    expect(q('[data-capsule-tag]')!.textContent).toContain('【合同审查】')
  })

  it('工具胶囊"发票整理"：打开发票页（T26），不写任务单', async () => {
    let home = 0
    setNav({ goHome: () => { home++ } } as unknown as Nav)
    await mountBlank(true)
    await click(tab('日常办公'))
    const before = h.svc.creates.length
    await click(q('[data-capsule-id="invoice"]'))
    await flush(600)
    expect(homeView.get()).toBe('invoice')
    expect(home).toBe(1)
    expect(h.svc.creates.length).toBe(before)
  })
})
