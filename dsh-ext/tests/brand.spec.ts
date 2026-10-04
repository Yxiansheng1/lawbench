// @vitest-environment jsdom
// 律所 logo 常驻品牌位、"技术支持"一行常驻侧栏底部（执行令 2026-10-04 11:56 第 1、2 条）。
import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { BrandMark, VendorCorner, VendorLine } from '../ui/brand.tsx'
import { FIRM_LOGO, FIRM_LOGO_DARK, VENDOR_MARK } from '../ui/brand-assets.ts'

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
    // 深色界面换白字版（令 1426）：两张都在，按根元素的 color-scheme 显示其一
    expect(box.querySelector('img.lb-logo-dark')!.getAttribute('src')).toBe(FIRM_LOGO_DARK)
    expect(document.getElementById('lb-logo-style')!.textContent).toContain('color-scheme: dark')
  })
  it('技术支持一行（右下角用它）：小标志＋"技术支持：上海莫来特智能科技有限公司"；收起时只留标志，全称在提示里', async () => {
    await render(createElement(VendorLine, { wide: true }))
    expect(box.textContent).toBe('技术支持：上海莫来特智能科技有限公司')
    expect(box.querySelector('img')!.getAttribute('src')).toBe(VENDOR_MARK)
    await act(async () => { root!.render(createElement(VendorLine, { wide: false })) })
    expect(box.textContent).toBe('')
    expect((box.firstElementChild as HTMLElement).title).toBe('技术支持：上海莫来特智能科技有限公司')
  })

  it('令 1515：右下角常驻一行——固定定位在窗口右下角、不接鼠标（不挡下面的按钮）', async () => {
    await render(createElement(VendorCorner))
    const el = box.querySelector('[data-lawbench-vendor-corner]') as HTMLElement
    expect(el.style.position).toBe('fixed')
    expect([el.style.right, el.style.bottom]).toEqual(['12px', '6px'])
    expect(el.style.pointerEvents).toBe('none')
    expect(el.textContent).toBe('技术支持：上海莫来特智能科技有限公司')
  })
})

describe('设置"通用"里的当前版本（注记 1706，P-4）', () => {
  it('DSH 那一行写的是工作台版本，与 PRODUCT_VERSION 一致', async () => {
    const { readFileSync } = await import('node:fs')
    const { join } = await import('node:path')
    const { PRODUCT_VERSION } = await import('../shared/product.ts')
    const src = readFileSync(join(__dirname, '..', '..', 'dsh', 'packages', 'client', 'ui-settings-general', 'src', 'client', 'CurrentVersionRow.tsx'), 'utf8')
    expect(src).toContain(`LAWBENCH_VERSION = '${PRODUCT_VERSION}'`)
  })
})
