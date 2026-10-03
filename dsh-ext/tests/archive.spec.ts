// @vitest-environment jsdom
// 归档面板（T26 第 3 步，U-15；契约 tools/case_save_archive_plan $defs/plan、api/archive_build 1.3）：
// 方案读入 → 律师可改名称、合并顺序、日期、承办律师 → 办案结果必须点选（未选时按钮不可用、不发请求）→ 请求过契约 →
// 生成后列出文件、页码范围、要人手处理的事项；服务端错误体显示中文。按钮背后接开发假服务（dev\fake-tools.mjs）的 /api/archive/build。
// Host 读方案（host\archive-plan.ts）：只读这一个文件、按契约校验，路径不出案件根。
import { mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { validate } from '../shared/contracts.ts'
import { makeTools } from '../dev/fake-tools.mjs'
import { NO_PLAN, BAD_PLAN, planRel, readArchivePlan } from '../host/archive-plan.ts'
import { ArchiveDialog } from '../ui/archive.tsx'
import { applyEdit, blocker, buildRequest, confirmedPlan, converterHint, pageLines, type ArchivePlan, type BuildValue } from '../ui/archive-logic.ts'
import { setApi, type LawbenchApi } from '../ui/state.ts'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
const BUILD = 'lawbench://contracts/api/archive_build.schema.json'
const PLAN_ID = 'lawbench://contracts/tools/case_save_archive_plan.schema.json'
const EXAMPLE = JSON.parse(readFileSync(join(__dirname, '..', '..', 'contracts', 'examples', 'tool_archive_plan.args.json'), 'utf8')) as ArchivePlan
const TASK = 'T-20261002180000-a1b2'

const plan = (over: Partial<ArchivePlan> = {}): ArchivePlan => ({
  ...EXAMPLE,
  items: [
    { code: 1, name: '民事委托代理合同', materials: ['委托代理合同'] },
    { code: 5, name: '证据材料', materials: ['借条', '转账记录', '催款短信'] },
    { code: 14, name: '民事调解书', materials: ['民事调解书'] },
  ],
  ...over,
})

describe('归档面板的逻辑', () => {
  it('样例方案过契约；办案结果为 null 时不能生成，点选后可以；名称为空、日期不对也不能', () => {
    expect(validate(PLAN_ID, 'plan', plan())).toEqual([])
    expect(blocker(plan())).toBe('请先点选办案结果')
    const p = applyEdit(plan(), { kind: 'result', result: '调解' })
    expect(blocker(p)).toBeNull()
    expect(blocker(applyEdit(p, { kind: 'name', code: 5, name: '  ' }))).toBe('材料名称不能为空')
    expect(blocker(applyEdit(p, { kind: 'date', field: 'close_date', value: '2026-02-30' }))).toBe('日期格式应为 年-月-日')
  })
  it('改名称、调合并顺序（越界不动）、承办律师与日期；交出去的请求过契约，空着的律师、日期交 null', () => {
    let p = applyEdit(plan(), { kind: 'result', result: '胜诉' })
    p = applyEdit(p, { kind: 'name', code: 5, name: ' 证据材料（借款） ' })
    p = applyEdit(p, { kind: 'move', code: 5, index: 2, by: -1 })
    p = applyEdit(p, { kind: 'move', code: 5, index: 0, by: -1 }) // 越界：不动
    p = applyEdit(p, { kind: 'lawyer', lawyer: '  ' })
    p = applyEdit(p, { kind: 'date', field: 'entrust_date', value: '' })
    const req = buildRequest('3f2b9c1e-7a4d-4e8b-9c2a-1b5d6e7f8a90', TASK, planRel(TASK), p)
    expect(validate(BUILD, 'request', req)).toEqual([])
    expect(req.plan).toBe(`工作区/任务/${TASK}/归档方案.json`)
    expect(req.confirmed.items.find((it) => it.code === 5)).toEqual({ code: 5, name: '证据材料（借款）', materials: ['借条', '催款短信', '转账记录'] })
    expect([req.confirmed.lawyer, req.confirmed.entrust_date, req.confirmed.close_date]).toEqual([null, null, '2026-08-20'])
    // 别的字段原样交回
    expect({ ...confirmedPlan(p), items: undefined, lawyer: undefined, entrust_date: undefined }).toEqual({ ...p, items: undefined, lawyer: undefined, entrust_date: undefined })
  })
  it('页码范围按编号对上名称（程序生成的项写"程序生成"），按起始页排；转换程序的提示', () => {
    const v: BuildValue = { folder: 'f', files: [], converter: 'libreoffice', manual: [], page_ranges: [{ code: 5, from: 3, to: 9 }, { code: 1, from: 1, to: 2 }, { code: 15, from: 10, to: 10 }] }
    expect(pageLines(v, plan())).toEqual(['1. 民事委托代理合同：第 1–2 页', '5. 证据材料：第 3–9 页', '15. （程序生成）：第 10 页'])
    expect(converterHint(v)).toContain('LibreOffice')
    expect(converterHint({ ...v, converter: 'word' })).toContain('Word')
  })
})

// ── 界面（按钮背后接开发假服务） ─────────────────────────────────────────
// --archive-fail 在建假服务时读一次：要失败体的用例另建一个
const mkTools = (failCode: string | null) => makeTools({
  arg: (name: string, dflt: string | null) => (name === '--invoice-delay' ? '0' : name === '--archive-fail' ? failCode : dflt),
  flag: () => false,
  check: (id: string, def: string, value: unknown) => validate(`lawbench://contracts/${id}.schema.json`, def, value),
  fail: (code: string, message: string) => ({ ok: false, error: { code, message } }),
  ok: (value: unknown) => ({ ok: true, value }),
  settings: () => ({}),
})
const tools = mkTools(null)
const failing = mkTools('CONVERTER_UNAVAILABLE')
let useFailing = false

let box: HTMLDivElement
let root: Root | undefined
let sent: Array<Record<string, unknown>>
let planReply: () => unknown
const flush = async () => { for (let i = 0; i < 5; i++) await act(async () => { await new Promise((r) => setTimeout(r, 0)) }) }
const page = () => document.body
const btn = (text: string) => [...page().querySelectorAll('button')].find((b) => b.textContent === text) as HTMLButtonElement | undefined
const click = async (el: HTMLElement) => { await act(async () => { el.click() }); await flush() }
const radio = (label: string) => [...page().querySelectorAll('input[type="radio"]')].find((r) => r.parentElement?.textContent === label) as HTMLInputElement
const text = () => page().textContent ?? ''

async function render(caseRoot = 'D:\\案件\\某某物流') {
  root = createRoot(box)
  await act(async () => { root!.render(createElement(ArchiveDialog, { caseRef: { case_id: '3f2b9c1e-7a4d-4e8b-9c2a-1b5d6e7f8a90', name: '某某物流', root: caseRoot }, taskId: TASK, onClose: () => {} })) })
  await flush()
}

beforeEach(() => {
  useFailing = false
  sent = []
  planReply = () => ({ ok: true, value: { plan: plan(), path: planRel(TASK) } })
  setApi({
    archivePlan: async () => planReply(),
    archiveBuild: async (req: unknown) => {
      sent.push(req as Record<string, unknown>)
      // 真走开发假服务的处理（契约校验、PLAN_NOT_CONFIRMED、失败体），返回值按契约 response 校验
      const [out] = (await (useFailing ? failing : tools).handle('POST', '/api/archive/build', req)) as [unknown]
      expect(validate(BUILD, 'response', out)).toEqual([])
      return out
    },
  } as unknown as LawbenchApi)
  box = document.createElement('div'); document.body.appendChild(box)
})
afterEach(async () => { await act(async () => { root?.unmount() }); root = undefined; box.remove(); setApi(undefined) })

describe('归档面板', () => {
  it('办案结果未选：按钮不可用，点了也不发请求；点选后可用', async () => {
    await render()
    expect(text()).toContain('某某物流')
    expect(text()).toContain('请先点选办案结果')
    const go = btn('生成归档文件')!
    expect(go.disabled).toBe(true)
    await click(go)
    expect(sent).toEqual([])
    await click(radio('调解'))
    expect(btn('生成归档文件')!.disabled).toBe(false)
  })

  it('成功：改过的名称和顺序随请求交出；列出生成的文件、页码范围、转换提示和要人手处理的事项', async () => {
    await render()
    await click(radio('胜诉'))
    const name = page().querySelector('[aria-label="第 5 项名称"]') as HTMLInputElement
    await act(async () => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(name, '证据材料（借款）'); name.dispatchEvent(new Event('input', { bubbles: true })) })
    await click(page().querySelector('[aria-label="催款短信 上移"]') as HTMLElement)
    await click(btn('生成归档文件')!)
    expect(sent).toHaveLength(1)
    const req = sent[0] as ReturnType<typeof buildRequest>
    expect(validate(BUILD, 'request', req)).toEqual([])
    expect(req.confirmed.result).toBe('胜诉')
    expect(req.confirmed.items.find((it) => it.code === 5)).toEqual({ code: 5, name: '证据材料（借款）', materials: ['借条', '催款短信', '转账记录'] })
    const t = text()
    expect(t).toContain('已生成')
    for (const f of ['卷宗.pdf', '立卷申请书.docx', '结案报告.docx', '归档目录.md']) expect(t).toContain(f)
    expect(t).toContain('5. 证据材料（借款）：第 3–8 页')
    expect(t).toContain('15. （程序生成）：第 11 页')
    expect(t).toContain('还需要您手动处理')
    expect(t).toContain('立卷申请书需打印手签后扫描')
    expect(t).toContain('LibreOffice')
    expect(btn('完成')).toBeTruthy()
  })

  it('服务端错误体：显示中文提示，可再试', async () => {
    useFailing = true
    await render()
    await click(radio('撤诉'))
    await click(btn('生成归档文件')!)
    expect(page().querySelector('[role="alert"]')?.textContent).toContain('没有生成成功：本机没有可用的 Word、WPS')
    expect(text()).not.toContain('已生成')
    expect(btn('生成归档文件')!.disabled).toBe(false)
  })

  it('读不到方案：显示原因，没有生成按钮可点', async () => {
    planReply = () => ({ ok: false, error: { code: 'TASK_NOT_FOUND', message: NO_PLAN } })
    await render()
    expect(page().querySelector('[role="alert"]')?.textContent).toContain('还没有保存归档方案')
    expect(btn('生成归档文件')!.disabled).toBe(true)
  })
})

describe('开发假服务 /api/archive/build', () => {
  const call = async (body: unknown) => ((await tools.handle('POST', '/api/archive/build', body)) as [{ ok: boolean; value?: BuildValue; error?: { code: string } }])[0]
  const req = (p: ArchivePlan) => ({ case_id: '3f2b9c1e-7a4d-4e8b-9c2a-1b5d6e7f8a90', task_id: TASK, plan: planRel(TASK), confirmed: p })
  it('成功：manual 非空；返回过契约', async () => {
    const r = await call(req(plan({ result: '胜诉' })))
    expect(validate(BUILD, 'response', r)).toEqual([])
    expect(r.value!.manual.length).toBeGreaterThan(0)
  })
  it('办案结果为 null：PLAN_NOT_CONFIRMED（同真服务）；请求不合契约：INVALID_ARGUMENT', async () => {
    expect((await call(req(plan()))).error?.code).toBe('PLAN_NOT_CONFIRMED')
    expect((await call({ case_id: 'x' })).error?.code).toBe('INVALID_ARGUMENT')
  })
})

describe('Host 读归档方案（host\\archive-plan.ts）', () => {
  let dir: string
  beforeEach(() => { dir = mkdtempSync(join(tmpdir(), 'lb-plan-')) })
  afterEach(() => { rmSync(dir, { recursive: true, force: true }) })
  const put = (text: string, task = TASK) => { const d = join(dir, '工作区', '任务', task); mkdirSync(d, { recursive: true }); writeFileSync(join(d, '归档方案.json'), text) }

  it('读到并按契约校验；带 BOM 也行；交回相对路径', () => {
    put('\uFEFF' + JSON.stringify(plan()))
    expect(readArchivePlan(dir, TASK)).toEqual({ ok: true, value: { plan: plan(), path: `工作区/任务/${TASK}/归档方案.json` } })
  })
  it('没有方案、任务编号不合格式、案件根不是绝对路径、内容坏了或不合契约：各自报错', () => {
    expect(readArchivePlan(dir, TASK)).toMatchObject({ ok: false, error: { code: 'TASK_NOT_FOUND', message: NO_PLAN } })
    expect(readArchivePlan(dir, '..\\..\\x')).toMatchObject({ ok: false, error: { code: 'INVALID_ARGUMENT' } })
    // 网络路径、设备路径不收（复核 F4）
    for (const net of ['\\\\127.0.0.1\\share\\案件', '//127.0.0.1/share/案件', '\\\\?\\D:\\案件']) expect(readArchivePlan(net, TASK), net).toMatchObject({ ok: false, error: { code: 'INVALID_ARGUMENT' } })
    expect(readArchivePlan('相对路径', TASK)).toMatchObject({ ok: false, error: { code: 'INVALID_ARGUMENT' } })
    put('{坏的')
    expect(readArchivePlan(dir, TASK)).toMatchObject({ ok: false, error: { code: 'INVALID_ARGUMENT', message: BAD_PLAN } })
    put(JSON.stringify({ ...plan(), result: '赢了' }))
    expect(readArchivePlan(dir, TASK)).toMatchObject({ ok: false, error: { message: BAD_PLAN } })
  })
  it('任务目录是指向案件外的链接：不读', () => {
    const outside = mkdtempSync(join(tmpdir(), 'lb-plan-out-'))
    try {
      writeFileSync(join(outside, '归档方案.json'), JSON.stringify(plan()))
      mkdirSync(join(dir, '工作区', '任务'), { recursive: true })
      symlinkSync(outside, join(dir, '工作区', '任务', TASK), 'junction')
      expect(readArchivePlan(dir, TASK)).toMatchObject({ ok: false, error: { code: 'TASK_NOT_FOUND' } })
    } finally { rmSync(outside, { recursive: true, force: true }) }
  })
})
