// @vitest-environment jsdom
// 律所 logo 常驻品牌位、"技术支持"一行常驻侧栏底部（执行令 2026-10-04 11:56 第 1、2 条）。
import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { BrandMark, VendorLine } from '../ui/brand.tsx'
import { FIRM_LOGO, VENDOR_MARK } from '../ui/brand-assets.ts'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
let root: Root | undefined
let box: HTMLDivElement
beforeEach(() => { box = document.createElement('div'); document.body.appendChild(box) })
afterEach(async () => { await act(async () => { root?.unmount() }); root = undefined; box.remove() })
const render = async (el: ReturnType<typeof createElement>) => { root = createRoot(box); await act(async () => { root!.render(el) }) }

describe('品牌位与技术支持一行', () => {
  it('律所 logo：内嵌 PNG，按品牌位给的高度显示', async () => {
    expect(FIRM_LOGO).toMatch(/^data:image\/png;base64,/)
    await render(createElement(BrandMark, { size: 24 }))
    const img = box.querySelector('img')!
    expect(img.getAttribute('src')).toBe(FIRM_LOGO)
    expect(img.style.height).toBe('22px') // 比品牌位小 2 px，免得底下一行被切
  })
  it('侧栏底部：小标志＋"技术支持：上海莫来特智能科技有限公司"；收起时只留标志，全称在提示里', async () => {
    await render(createElement(VendorLine, { wide: true }))
    expect(box.textContent).toBe('技术支持：上海莫来特智能科技有限公司')
    expect(box.querySelector('img')!.getAttribute('src')).toBe(VENDOR_MARK)
    await act(async () => { root!.render(createElement(VendorLine, { wide: false })) })
    expect(box.textContent).toBe('')
    expect((box.firstElementChild as HTMLElement).title).toBe('技术支持：上海莫来特智能科技有限公司')
  })
})
