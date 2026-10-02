// @vitest-environment jsdom
// 首页启动检查提示条（T20 准备，复核 NOTE）：有问题的项逐条显示、error 标红；"知道了"后本次运行不再显示；没有问题不显示。
import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { SelfCheckBanner } from '../ui/home.tsx'
import { setApi, type LawbenchApi } from '../ui/state.ts'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
let root: Root | undefined
let box: HTMLDivElement
let items: Array<{ id: string; level: string; message: string }>

beforeEach(() => {
  items = []
  setApi({ selfCheck: async () => ({ ok: true, value: { items } }) } as unknown as LawbenchApi)
  box = document.createElement('div'); document.body.appendChild(box)
})
afterEach(async () => { await act(async () => { root?.unmount() }); root = undefined; box.remove(); setApi(undefined) })
const render = async () => { root = createRoot(box); await act(async () => { root!.render(createElement(SelfCheckBanner)) }); await act(async () => { await Promise.resolve() }) }

describe('首页启动检查提示条', () => {
  it('没有问题：不显示', async () => {
    await render()
    expect(box.textContent).toBe('')
  })
  it('有问题：显示条数和每条说明，"知道了"后不再显示（本次运行内，换页再回来也不显示）', async () => {
    items = [{ id: 'pandoc', level: 'warn', message: '没找到 pandoc，导出 Word 用不了。' }, { id: 'python', level: 'error', message: '内置的 Python 不在或版本不对。' }]
    await render()
    expect(box.textContent).toContain('启动检查发现 2 个问题')
    expect(box.textContent).toContain('没找到 pandoc')
    expect(box.querySelector('[role=alert]')).not.toBeNull()
    const btn = [...box.querySelectorAll('button')].find((b) => b.textContent === '知道了')!
    await act(async () => { btn.click() })
    expect(box.textContent).toBe('')
    await act(async () => { root!.unmount() }); await render()
    expect(box.textContent).toBe('')
  })
})
