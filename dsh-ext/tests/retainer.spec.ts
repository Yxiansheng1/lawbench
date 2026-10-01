// @vitest-environment jsdom
// 委托材料（T26 第 2 步，U-14，Spec 13.5）界面这一半：打开前 start 驱动、开窗（P-11 经预加载的桥）、关窗后 stop 驱动，
// 有新文件时提示导入到 01委托手续（ZIP 时 unzip:true），没有案件时说明文件在哪；stop 回 running:true 时如实显示服务的话。
import { validate } from '../shared/contracts.ts'
import { afterClose, hasZip, openRetainer, RETAINER_TARGET, TEXT, type RetainerBridge, type RetainerResult } from '../ui/retainer.ts'
import { app, setApi, type CaseRef, type LawbenchApi } from '../ui/state.ts'

const CASE: CaseRef = { case_id: '6f1c2a3b-4d5e-4f60-8a71-92b3c4d5e6f7', name: '民事-虚构戊', root: 'D:\\案件\\民事-虚构戊', exists: true }
const DIR = 'D:\\案件\\民事-虚构戊\\工作区\\临时\\委托材料\\20261001-220000'
const RID = 'lawbench://contracts/api/retainer_driver.schema.json'
const MID = 'lawbench://contracts/api/materials_import.schema.json'

let calls: Array<[string, Record<string, unknown>]>
let driver: { start: { running: boolean; message: string } | { code: string }; stop: { running: boolean; message: string } }
let answers: boolean[]
let unsub: () => void
const notices = () => app.get().dialogs.filter((d) => d.kind === 'notice') as Array<{ title: string; text: string; lines?: string[] }>
const confirmsSeen: string[] = []

beforeEach(() => {
  calls = []; answers = []; confirmsSeen.length = 0
  driver = { start: { running: true, message: '证件识别已启动' }, stop: { running: false, message: '证件识别已停止' } }
  app.set((s) => ({ ...s, dialogs: [] }))
  setApi({
    retainerDriver: async (r: unknown) => {
      const req = r as { action: 'start' | 'stop' }
      calls.push(['retainerDriver', req])
      const v = driver[req.action]
      return 'code' in v ? { ok: false, error: { code: v.code, message: '证件识别驱动没有启动成功' } } : { ok: true, value: { ...v, port: 17801 } }
    },
    materialsImport: async (r: unknown) => {
      calls.push(['materialsImport', r as Record<string, unknown>])
      return { ok: true, value: { copied: [], skipped: [], scan: { added: 0, changed: 0, removed: 0, failed: 0, review_needed: false } } }
    },
  } as unknown as LawbenchApi)
  unsub = app.subscribe(() => {
    const d = app.get().dialogs.find((x) => x.kind === 'confirm')
    if (d?.kind === 'confirm') { confirmsSeen.push(`${d.title}|${d.text}`); app.set((s) => ({ ...s, dialogs: s.dialogs.filter((x) => x !== d) })); d.resolve(answers.length ? answers.shift()! : true) }
  })
})
afterEach(() => { unsub(); setApi(undefined) })

const bridge = (result: RetainerResult | Error, seen: unknown[] = []): RetainerBridge => ({
  open: async (req) => {
    seen.push(req)
    calls.push(['open', req as unknown as Record<string, unknown>])
    if (result instanceof Error) throw result
    return result
  },
})
const closed = (files: string[], over: Partial<Extract<RetainerResult, { kind: 'closed' }>> = {}): RetainerResult => ({ kind: 'closed', dir: DIR, inCase: true, files, failed: 0, ...over })

describe('委托材料窗口（界面）', () => {
  it('顺序：start → 开窗（带当前案件）→ 关窗后 stop → 确认后导入 01委托手续；请求都合契约', async () => {
    const files = [`${DIR}\\授权委托书.docx`, `${DIR}\\授权委托书(2).docx`]
    await openRetainer(CASE, bridge(closed(files)))
    expect(calls.map((c) => c[0] === 'retainerDriver' ? `driver:${c[1].action}` : c[0])).toEqual(['driver:start', 'open', 'driver:stop', 'materialsImport'])
    expect(calls[1]![1]).toEqual({ caseRoot: CASE.root, caseName: CASE.name })
    expect(calls[3]![1]).toEqual({ case_id: CASE.case_id, paths: files, target: RETAINER_TARGET, unzip: false })
    expect(confirmsSeen[0]).toContain(TEXT.importTitle)
    expect(confirmsSeen[0]).toContain('同名文件改名，不覆盖')
    for (const [m, r] of calls) {
      if (m === 'retainerDriver') expect(validate(RID, 'request', r)).toEqual([])
      if (m === 'materialsImport') expect(validate(MID, 'request', r), JSON.stringify(r)).toEqual([])
    }
  })

  it('有 ZIP（"保存案件目录"回退为下载整个案件 ZIP）时 unzip:true；律师不确认就不导入', async () => {
    expect(hasZip(['a.docx', 'b.ZIP'])).toBe(true)
    await openRetainer(CASE, bridge(closed([`${DIR}\\民事-虚构戊.zip`])))
    expect(calls.at(-1)).toEqual(['materialsImport', expect.objectContaining({ unzip: true })])
    calls = []; answers.push(false)
    await openRetainer(CASE, bridge(closed([`${DIR}\\授权委托书.docx`])))
    expect(calls.some((c) => c[0] === 'materialsImport')).toBe(false)
  })

  it('没有新文件：只停驱动，不提示', async () => {
    await openRetainer(CASE, bridge(closed([])))
    expect(calls.map((c) => c[0])).toEqual(['retainerDriver', 'open', 'retainerDriver'])
    expect(notices()).toEqual([])
  })

  it('没有案件：开窗不带案件；关窗后说明文件在哪、先打开案件再导入，不导入', async () => {
    const seen: unknown[] = []
    await openRetainer(undefined, bridge(closed(['C:\\x\\临时\\委托材料\\t\\a.docx'], { inCase: false, dir: 'C:\\x\\临时\\委托材料\\t' }), seen))
    expect(seen).toEqual([{ caseRoot: null, caseName: null }])
    expect(notices()[0]!.title).toBe(TEXT.noCaseTitle)
    expect(notices()[0]!.text).toContain('C:\\x\\临时\\委托材料\\t')
    expect(calls.some((c) => c[0] === 'materialsImport')).toBe(false)
  })

  it('主进程没认这个案件文件夹（inCase:false）时同样不导入', async () => {
    await afterClose({ kind: 'closed', dir: 'C:\\x', inCase: false, files: ['C:\\x\\a.docx'], failed: 0 }, CASE)
    expect(notices()[0]!.title).toBe(TEXT.noCaseTitle)
  })

  it('stop 回 running:true：如实显示服务的话（关闭未完成，请稍后再试）', async () => {
    driver.stop = { running: true, message: '关闭未完成，请稍后再试' }
    await openRetainer(CASE, bridge(closed([])))
    expect(notices().map((n) => n.text)).toEqual(['关闭未完成，请稍后再试'])
  })

  it('驱动没起来：提示可手工填写，窗口照开', async () => {
    driver.start = { code: 'ENGINE_FAILED' }
    await openRetainer(CASE, bridge(closed([])))
    expect(calls.some((c) => c[0] === 'open')).toBe(true)
    expect(notices()[0]!.title).toBe(TEXT.driverDown)
    expect(notices()[0]!.text).toContain(TEXT.driverDownTail)
  })

  it('窗口已开着：只聚焦，不停驱动', async () => {
    await openRetainer(CASE, bridge({ kind: 'already-open' }))
    expect(calls.map((c) => c[0] === 'retainerDriver' ? `driver:${c[1].action}` : c[0])).toEqual(['driver:start', 'open'])
  })

  it('开窗失败：显示主进程的中文原因并停驱动；不是桌面端时说明', async () => {
    await openRetainer(CASE, bridge(new Error("Error invoking remote method 'lawbench:open-retainer': Error: 委托材料工具没有找到，请重新安装律师工作台。")))
    expect(notices()[0]!.text).toBe('委托材料工具没有找到，请重新安装律师工作台。')
    expect(calls.at(-1)).toEqual(['retainerDriver', { action: 'stop' }])
    app.set((s) => ({ ...s, dialogs: [] })); calls = []
    await openRetainer(CASE, undefined)
    expect(notices()[0]!.title).toBe(TEXT.noDesktop[0])
    expect(calls).toEqual([])
  })

  it('有下载没保存成功：一并告诉律师', async () => {
    await afterClose({ kind: 'closed', dir: DIR, inCase: true, files: [], failed: 2 }, CASE)
    expect(notices()[0]!.text).toContain('2 个文件没有保存成功')
  })
})
