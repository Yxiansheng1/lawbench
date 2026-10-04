// @vitest-environment jsdom
// 设置页（令 1609）：深色下原生下拉框选项看得清（全局样式跟 DSH 主题变量）；底部固定保存条的显隐；带着未保存的修改离开、关窗口时先问。
import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { ensureFieldStyle, FIELD_STYLE } from '../ui/kit.tsx'
import { SaveBar } from '../ui/settings.tsx'
import * as draftModule from '../ui/settings-draft.ts'
import { isDirty, onLeaveSettings, settingsDraft, UNSAVED_TEXT } from '../ui/settings-draft.ts'
import { readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { app, setApi, type LawbenchApi } from '../ui/state.ts'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
let root: Root | undefined
let box: HTMLDivElement
const S0 = { v: 1, servers: { llm_base_url: 'http://a' }, ocr_fallback_llm: false, defaults: { thinking: '中' }, skill_presets: {}, profile: { lawyer_name: '王律师' } }
beforeEach(() => { box = document.createElement('div'); document.body.appendChild(box); app.set((s) => ({ ...s, dialogs: [] })) })
afterEach(async () => {
  await act(async () => { root?.unmount() }); root = undefined; box.remove(); setApi(undefined)
  settingsDraft.set({ loaded: null, draft: null, savedAt: null }); app.set((s) => ({ ...s, dialogs: [] }))
})
const dirtyDraft = () => settingsDraft.set({ loaded: structuredClone(S0), draft: { ...structuredClone(S0), profile: { lawyer_name: '李律师' } }, savedAt: null })
const lastDialog = () => app.get().dialogs.at(-1) as { kind: string; text?: string; resolve?: (c: string) => void } | undefined

describe('深色下拉框', () => {
  it('选项的底色和字色跟 DSH 主题变量（只加一次）', () => {
    ensureFieldStyle(); ensureFieldStyle()
    const el = document.querySelectorAll('#lb-field-style')
    expect(el.length).toBe(1)
    expect(FIELD_STYLE).toContain('select option')
    expect(FIELD_STYLE).toContain('background-color:var(--dsw-alias-bg-layer-1')
    expect(FIELD_STYLE).toContain('color:var(--dsw-alias-label-primary')
  })
})

describe('固定保存条', () => {
  it('没有修改时不显示；有修改时贴底显示"有未保存的修改"＋放弃修改＋保存；保存后两秒内"已保存 HH:mm"', async () => {
    settingsDraft.set({ loaded: structuredClone(S0), draft: structuredClone(S0), savedAt: null })
    root = createRoot(box)
    let saves = 0
    await act(async () => { root!.render(createElement(SaveBar, { onSave: () => { saves++ } })) })
    expect(box.textContent).toBe('')
    await act(async () => { dirtyDraft() })
    const bar = box.querySelector('[data-lawbench-savebar]') as HTMLElement
    expect(bar.style.position).toBe('sticky')
    expect(bar.style.bottom).toBe('0px')
    expect(bar.textContent).toContain('有未保存的修改')
    ;[...bar.querySelectorAll('button')].find((b) => b.textContent === '保存')!.click()
    expect(saves).toBe(1)
    await act(async () => { [...bar.querySelectorAll('button')].find((b) => b.textContent === '放弃修改')!.click() })
    expect(isDirty()).toBe(false)
    const t = new Date('2026-10-04T16:30:00').getTime()
    await act(async () => { settingsDraft.set((s) => ({ ...s, savedAt: t })) })
    await act(async () => { root!.render(createElement(SaveBar, { onSave: () => {}, now: () => t + 500 })) })
    expect(box.textContent).toBe('已保存 16:30')
    await act(async () => { root!.render(createElement(SaveBar, { onSave: () => {}, now: () => t + 2500 })) })
    expect(box.textContent).toBe('')
  })
})

describe('带着未保存的修改离开', () => {
  it('切到别的页面：问"修改尚未保存"——不保存则丢弃，保存则写服务；没有修改时不问', async () => {
    expect(await onLeaveSettings()).toBeNull()
    dirtyDraft()
    const p = onLeaveSettings()
    expect(lastDialog()!.kind).toBe('unsaved')
    expect(lastDialog()!.text).toBe(UNSAVED_TEXT)
    lastDialog()!.resolve!('discard')
    expect(await p).toBe('discard')
    expect(isDirty()).toBe(false)
    const puts: unknown[] = []
    setApi({ putSettings: async (s: unknown) => { puts.push(s) } } as unknown as LawbenchApi)
    dirtyDraft()
    const q = onLeaveSettings()
    lastDialog()!.resolve!('save')
    expect(await q).toBe('save')
    expect((puts[0] as { profile: { lawyer_name: string } }).profile.lawyer_name).toBe('李律师')
    expect(isDirty()).toBe(false)
  })

  it('留着修改：草稿原样留着，不保存也不丢', async () => {
    dirtyDraft()
    const p = onLeaveSettings()
    lastDialog()!.resolve!('cancel')
    expect(await p).toBe('cancel')
    expect(isDirty()).toBe(true)
  })

  it('有修改时关窗口（beforeunload）不阻止：界面代码里没有 beforeunload 拦截（复核 AMEND 令 1726：拦了会让 DSH 退出卡在后台）', () => {
    expect('installUnloadGuard' in draftModule).toBe(false)
    const ui = join(__dirname, '..', 'ui')
    const hits = readdirSync(ui).filter((f) => /\.tsx?$/.test(f) && /addEventListener\(\s*['"]beforeunload/.test(readFileSync(join(ui, f), 'utf8')))
    expect(hits).toEqual([])
    dirtyDraft()
    const e = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(e)
    expect(e.defaultPrevented).toBe(false)
  })
})
