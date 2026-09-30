// @vitest-environment jsdom
// 对话框导入（P-5 我方一半）：带文字的粘贴里的位图不导入（T17 第二步返修 B-F2）；
// 界面插件 apply 之后，P-5 的 conversationFileIntake 与 P-16 的 chatInlineMarks 各登记一次（返修 A-P3-7，拖入守卫删掉后的兜底）。
import { installPasteTextWatch, makeIntakeHook, pasteCarriedText } from '../ui/intake.ts'
import { app, setApi, type LawbenchApi } from '../ui/state.ts'
import { setNav, type Nav } from '../ui/kit.tsx'
import { apply } from '../ui/index.tsx'

const CASE = { case_id: 'C-1', name: '虚构案件', root: 'D:\\案件\\虚构' }
const png = (name: string) => new File([new Uint8Array([137, 80, 78, 71])], name, { type: 'image/png' })

function paste(text: string): void {
  const e = new Event('paste', { bubbles: true, cancelable: true }) as Event & { clipboardData: { getData(t: string): string } }
  Object.defineProperty(e, 'clipboardData', { value: { getData: (t: string) => (t === 'text/plain' ? text : '') } })
  window.dispatchEvent(e)
}

describe('带文字的粘贴里的位图不导入（B-F2）', () => {
  let calls: string[]
  let off: () => void
  beforeEach(() => {
    calls = []
    app.set((s) => ({ ...s, cases: [CASE], dialogs: [] }))
    setApi({ importPastedImage: async () => { calls.push('importPastedImage'); return { ok: true, value: { copied: [] } } } } as unknown as LawbenchApi)
    setNav({ pathFor: () => '' } as unknown as Nav)
    off = installPasteTextWatch()
  })
  afterEach(() => { off(); setApi(undefined); setNav(undefined) })

  it('Excel、WPS 复制单元格（文字加一张截图）：钩子接手但不导入位图，也不弹提示', async () => {
    const hook = makeIntakeHook(() => CASE.root)
    paste('姓名\t金额\n张三\t30000')
    expect(pasteCarriedText()).toBe(true)
    expect(hook('S1', [png('image.png')], new Set())).toBeNull()
    await new Promise((r) => setTimeout(r, 0))
    expect(calls).toEqual([])
    expect(app.get().dialogs).toEqual([])
  })

  it('只粘贴了截图（没有文字）：照常导入', async () => {
    const hook = makeIntakeHook(() => CASE.root)
    paste('   ')
    expect(pasteCarriedText()).toBe(false)
    expect(hook('S1', [png('shot.png')], new Set())).toBeNull()
    await new Promise((r) => setTimeout(r, 0))
    expect(calls).toEqual(['importPastedImage'])
  })

  it('带文字的粘贴过去 1 秒以后的位图（如拖入的截图）：照常导入', async () => {
    const hook = makeIntakeHook(() => CASE.root)
    paste('一段文字')
    expect(pasteCarriedText(Date.now() + 1500)).toBe(false)
    const later = makeIntakeHook(() => CASE.root, () => pasteCarriedText(Date.now() + 1500))
    expect(later('S1', [png('shot.png')], new Set())).toBeNull()
    await new Promise((r) => setTimeout(r, 0))
    expect(calls).toEqual(['importPastedImage'])
    void hook
  })
})

describe('界面插件 apply 之后两个 DSH 补丁服务各登记一次（A-P3-7）', () => {
  it('conversationFileIntake、chatInlineMarks 各 register 一次', async () => {
    const registered = { intake: 0, marks: 0 }
    const observable = <T,>(v: T) => ({ getSnapshot: () => v, subscribe: () => () => {} })
    const ctx: Record<string, unknown> = {}
    Object.assign(ctx, {
      slots: { inject: () => {}, register: () => () => {} },
      remote: {
        $mount: async () => async () => {},
        lawbench: new Proxy({}, { get: () => async () => ({ ok: true, value: {} }) }),
      },
      effect: (fn: () => unknown) => { fn() },
      inject: (_deps: string[], fn: (c: unknown) => void) => {
        const p = Promise.resolve().then(() => fn(ctx)) as Promise<void> & { dispose(): Promise<void> }
        p.dispose = async () => {}
        return p
      },
      layout: { selectPanel: () => {} },
      sessions: { list: observable({ byId: {} }) },
      uiSession: { adapter: { current: observable(undefined) } },
      uiWorkspace: { openWorkspace: async () => {} },
      workspaces: { create: async () => ({ workspaceId: 'w' }) },
      sidebarRight: { openTab: () => {}, mounted: observable(undefined) },
      sidebarRightTabs: { register: () => () => {} },
      conversationFileIntake: { register: () => { registered.intake++; return () => {} } },
      chatInlineMarks: { register: () => { registered.marks++; return () => {} } },
    })
    const dispose = await apply(ctx as never)
    await new Promise((r) => setTimeout(r, 0))
    expect(registered).toEqual({ intake: 1, marks: 1 })
    await dispose()
  })
})
