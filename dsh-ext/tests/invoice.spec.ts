// @vitest-environment jsdom
// 发票整理页（T26 第 1 步，U-13，Spec 13.3，契约 api/invoice_run 1.3）：
// 表单 → 请求逐个动作过契约；结果标色；--apply 类先预览再确认、cancel 先报表再确认；动作进行中与 ENGINE_BUSY 时全部按钮停用；
// 没设日常办公文件夹或购买方时引导去设置；重印时 files 为空提示看输出；失败显示 output 里的原因。
import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { validate } from '../shared/contracts.ts'
import { API_ROUTES } from '../shared/api-routes.ts'
import { ERROR_HINT } from '../ui/format.ts'
import { InvoicePage, SETUP_TEXT } from '../ui/invoice.tsx'
import {
  ACTION_LABEL, BUSY_HOLD_MS, BUSY_TEXT, buildInvoiceRequest, emptyForm, homeView, parseNumbers, PRINT_FROM_OUTPUT, resultTone, TONE_TEXT,
  type InvoiceAction, type InvoiceForm,
} from '../ui/invoice-logic.ts'
import { app, setApi, type LawbenchApi } from '../ui/state.ts'
import { setNav } from '../ui/kit.tsx'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
const ID = 'lawbench://contracts/api/invoice_run.schema.json'

const filled = (over: Partial<InvoiceForm> = {}): InvoiceForm => ({
  ...emptyForm(new Date(2026, 8, 15), '张律师'), src: 'D:\\发票\\2026-09', item: 'a'.repeat(64), reason: '分类缺失', sha256: 'b'.repeat(64), ...over,
})

describe('表单 → 请求（契约 1.3）', () => {
  const all = Object.keys(ACTION_LABEL) as InvoiceAction[]
  it('每个动作、两种 apply/confirm 都过契约 request', () => {
    for (const a of all) for (const apply of [false, true]) {
      const b = buildInvoiceRequest(a, filled(), { apply, confirm: apply })
      expect(b.ok, a).toBe(true)
      if (b.ok) expect(validate(ID, 'request', b.request), `${a} ${apply}`).toEqual([])
    }
  })
  it('纳入历史票：号码按 18–20 位筛、去重；格式不对的报出来；EML 要起止日期', () => {
    expect(parseNumbers('044002400111223344, 044002400111223344、12345\n04400240011122334455')).toEqual({ numbers: ['044002400111223344', '04400240011122334455'], bad: ['12345'] })
    expect(buildInvoiceRequest('plan', filled({ history: 'selected', historyNumbers: '' }))).toMatchObject({ ok: false })
    expect(buildInvoiceRequest('plan', filled({ history: 'selected', historyNumbers: '123' }))).toMatchObject({ ok: false, problem: expect.stringContaining('123') })
    const sel = buildInvoiceRequest('plan', filled({ history: 'selected', historyNumbers: '044002400111223344' }))
    expect(sel).toMatchObject({ ok: true, request: { history: 'selected', history_numbers: ['044002400111223344'] } })
    expect(buildInvoiceRequest('plan', filled({ history: 'exclude', historyNumbers: '044002400111223344' }))).toMatchObject({ request: { history_numbers: [] } })
    expect(buildInvoiceRequest('plan', filled({ channel: 'eml' }))).toMatchObject({ ok: false })
    expect(buildInvoiceRequest('plan', filled({ channel: 'eml', start: '2026-09-30', end: '2026-09-01' }))).toMatchObject({ ok: false })
    const eml = buildInvoiceRequest('plan', filled({ channel: 'eml', start: '2026-09-01', end: '2026-09-30' }))
    expect(eml.ok && validate(ID, 'request', eml.request)).toEqual([])
  })
  it('批次名、文件夹、记录编号、核验人不合规时不发', () => {
    expect(buildInvoiceRequest('run', filled({ batch: '九月/报销' }))).toMatchObject({ ok: false })
    expect(buildInvoiceRequest('run', filled({ src: '' }))).toMatchObject({ ok: false, problem: '请先选择要导入的发票文件夹。' })
    expect(buildInvoiceRequest('exclude', filled({ item: 'A'.repeat(64) }))).toMatchObject({ ok: false })
    expect(buildInvoiceRequest('exclude', filled({ reviewer: ' ' }))).toMatchObject({ ok: false })
    expect(buildInvoiceRequest('history', filled({ period: '2026-13' }))).toMatchObject({ ok: false })
  })
  it('reimburse 默认只预览；cancel 一律 apply:true（只在两步路径里构造）；review、exclude 一律 confirm:true（引擎没有 review 预览）', () => {
    expect(buildInvoiceRequest('reimburse', filled())).toMatchObject({ request: { apply: false } })
    expect(buildInvoiceRequest('cancel', filled(), { apply: false })).toMatchObject({ request: { apply: true } })
    expect(buildInvoiceRequest('review', filled(), { confirm: false })).toMatchObject({ request: { confirm: true } })
    expect(buildInvoiceRequest('exclude', filled())).toMatchObject({ request: { confirm: true } })
  })
  it('结果标色：failed 红、退出码 2 黄、其余绿；契约样例', () => {
    expect(resultTone({ exit_code: 2, attention: false, failed: true, output: '', files: [] })).toBe('err')
    expect(resultTone({ exit_code: 2, attention: true, failed: false, output: '', files: [] })).toBe('warn')
    expect(resultTone({ exit_code: 0, attention: false, failed: false, output: '', files: [] })).toBe('ok')
  })
  it('发票动作不设短超时（单个动作最长 30 分钟）；ENGINE_BUSY、OFFICE_DIR_NOT_SET 有说明', () => {
    expect(API_ROUTES.find((r) => r.method === 'invoiceRun')!.timeoutMs).toBeGreaterThan(30 * 60_000)
    expect(ERROR_HINT.ENGINE_BUSY).toContain('发票整理正在进行中')
    expect(ERROR_HINT.OFFICE_DIR_NOT_SET).toContain('日常办公文件夹')
  })
})

// ── 页面 ──
type Reply = { ok: true; value: unknown } | { ok: false; error: { code: string; message: string } }
const value = (over: Record<string, unknown> = {}) => ({ ok: true as const, value: { exit_code: 0, attention: false, failed: false, output: '完成（虚构）', files: [], ...over } })
let root: Root | undefined
let box: HTMLDivElement
let sent: Array<Record<string, unknown>>
let replies: Array<(req: Record<string, unknown>) => Reply | Promise<Reply>>
let settings: Record<string, unknown>
let confirms: boolean[]
let confirmTexts: string[]
let unsub: () => void

const flush = async (ms = 0) => { await act(async () => { await vi.advanceTimersByTimeAsync(ms) }) }
const buttons = () => [...box.querySelectorAll('button')]
const btn = (text: string) => buttons().find((b) => b.textContent === text)!
const click = async (text: string) => { await act(async () => { btn(text).click() }); await flush() }
const actionButtons = () => buttons().filter((b) => Object.values(ACTION_LABEL).some((l) => b.textContent === l || b.textContent === `${l}…`))
const output = () => box.querySelector('section[aria-label="输出"]')
const setInput = async (label: string, v: string) => {
  const el = box.querySelector(`[aria-label="${label}"]`) as HTMLInputElement
  const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype
  await act(async () => { Object.getOwnPropertyDescriptor(proto, 'value')!.set!.call(el, v); el.dispatchEvent(new Event('input', { bubbles: true })) })
}

async function render() {
  root = createRoot(box)
  await act(async () => { root!.render(createElement(InvoicePage)) })
  await flush()
}

beforeEach(() => {
  vi.useFakeTimers({ now: new Date(2026, 8, 15, 10) })
  sent = []; replies = []; confirms = []; confirmTexts = []
  settings = { office: { dir: 'D:\\日常办公', invoice_buyer: '某律师事务所（虚构）' }, profile: { lawyer_name: '张律师' } }
  setApi({
    getSettings: async () => settings,
    invoiceRun: async (req: unknown) => { sent.push(req as Record<string, unknown>); const next = replies.shift(); return next ? next(req as Record<string, unknown>) : value() },
  } as unknown as LawbenchApi)
  setNav({ pickDirectory: async () => 'D:\\发票\\九月', pathFor: () => '', openCaseWorkspace: async () => {}, openTab: () => {}, goHome: () => {}, refreshModels: () => {}, openSession: () => {} })
  app.set((s) => ({ ...s, dialogs: [] }))
  // 确认框：按 confirms 队列回答（默认确定）
  unsub = app.subscribe(() => {
    const d = app.get().dialogs[0]
    if (d?.kind === 'confirm') { confirmTexts.push(d.text); app.set((s) => ({ ...s, dialogs: s.dialogs.slice(1) })); d.resolve(confirms.length ? confirms.shift()! : true) }
  })
  box = document.createElement('div'); document.body.appendChild(box)
})
afterEach(async () => { unsub(); await act(async () => { root?.unmount() }); root = undefined; box.remove(); setApi(undefined); setNav(undefined); vi.useRealTimers() })

describe('发票整理页', () => {
  it('没设日常办公文件夹或购买方：引导去设置，除环境检查外按钮不可用', async () => {
    settings = { office: { dir: null, invoice_buyer: '某所' }, profile: { lawyer_name: null } }
    await render()
    expect(box.textContent).toContain(SETUP_TEXT)
    expect(btn('开始本期').disabled).toBe(true)
    expect(btn('环境检查').disabled).toBe(false)
    settings = { office: { dir: 'D:\\日常办公', invoice_buyer: null } }
    await act(async () => { root!.unmount() }); await render()
    expect(box.textContent).toContain(SETUP_TEXT)
  })

  it('走一期：开始本期 → 选文件夹 → 导入（退出码 2 标黄）→ 入账 → 生成贴票包（files 空提示看输出）；请求都合契约', async () => {
    await render()
    await click('开始本期')
    expect(sent[0]).toEqual({ action: 'plan', period: '2026-09', channel: 'local', history: 'exclude', history_numbers: [] })
    await click('选择文件夹…')
    replies.push(() => value({ exit_code: 2, attention: true, output: '重复 1 张（虚构）' }))
    await click('导入并生成贴票包')
    expect(sent[1]).toMatchObject({ action: 'run', batch: '2026-09', src: 'D:\\发票\\九月' })
    expect(output()!.getAttribute('data-tone')).toBe('warn')
    expect(output()!.textContent).toContain(TONE_TEXT.warn)
    expect(output()!.textContent).toContain('重复 1 张（虚构）')
    await click('入账')
    await click('生成贴票包')
    expect(output()!.textContent).toContain(PRINT_FROM_OUTPUT)
    for (const r of sent) expect(validate(ID, 'request', r)).toEqual([])
  })

  it('引擎自报失败：标红，显示 output 里的原因', async () => {
    replies.push(() => ({ ok: true, value: { exit_code: 2, attention: false, failed: true, output: '[BLOCKED] ValueError 收集任务有待处理或数量不符项', files: [] } }))
    await render()
    await click('重印')
    expect(output()!.getAttribute('data-tone')).toBe('err')
    expect(output()!.textContent).toContain('[BLOCKED] ValueError 收集任务有待处理或数量不符项')
    expect(output()!.textContent).not.toContain(PRINT_FROM_OUTPUT)
  })

  it('动作进行中全部动作按钮停用，回来后恢复', async () => {
    let release!: () => void
    replies.push(() => new Promise<Reply>((r) => { release = () => r(value()) }))
    await render()
    await act(async () => { btn('分析对账').click() })
    expect(btn('分析对账…')).toBeTruthy()
    expect(actionButtons().every((b) => b.disabled)).toBe(true)
    await click('入账') // 停用中点不动
    expect(sent).toHaveLength(1)
    await act(async () => { release() }); await flush()
    expect(actionButtons().every((b) => !b.disabled)).toBe(true)
  })

  it('ENGINE_BUSY：全部动作按钮停用并提示"发票整理正在进行中"，过一会儿恢复', async () => {
    replies.push(() => ({ ok: false, error: { code: 'ENGINE_BUSY', message: '发票整理正在进行中，请稍后再试' } }))
    await render()
    await click('报表')
    expect(box.textContent).toContain(BUSY_TEXT)
    expect(actionButtons().every((b) => b.disabled)).toBe(true)
    await flush(BUSY_HOLD_MS)
    expect(actionButtons().every((b) => !b.disabled)).toBe(true)
  })

  it('确认已报销：先预览（apply:false），确认后才 apply:true；取消确认就不执行', async () => {
    await render()
    confirms.push(false)
    await click('确认已报销')
    expect(sent.map((r) => r.apply)).toEqual([false])
    expect(output()!.textContent).toContain('（预览）')
    await click('确认已报销')
    expect(sent.map((r) => r.apply)).toEqual([false, false, true])
  })

  it('预览失败不再问、不执行', async () => {
    replies.push(() => value({ failed: true, exit_code: 2, output: '[BLOCKED] 批次不存在' }))
    await render()
    await click('确认已报销')
    expect(sent).toHaveLength(1)
  })

  it('取消批次：引擎不支持预览，先发报表给律师核对，确认后发 cancel apply:true（从不发 apply:false 的 cancel）', async () => {
    await render()
    await click('取消批次')
    expect(sent.map((r) => r.action)).toEqual(['report', 'cancel'])
    expect(sent[1]).toMatchObject({ apply: true })
  })

  it('人工核验：先弹确认框（逐张核对原票、带核验人），确认后只发一次 confirm:true；不确认 0 次（复核 P1-1）', async () => {
    await render()
    await setInput('文件指纹', 'd'.repeat(64))
    confirms.push(false)
    await click('人工核验')
    expect(sent).toHaveLength(0)
    await click('人工核验')
    expect(sent).toEqual([{ action: 'review', sha256: 'd'.repeat(64), reviewer: '张律师', confirm: true }])
    expect(confirmTexts.join()).toContain('逐张核对原票')
    expect(confirmTexts.join()).toContain('张律师')
  })

  it('取消批次的确认框说清是整个台账的报表、要先确认批次尚未报销（复核 P3-1）', async () => {
    await render()
    await click('取消批次')
    expect(confirmTexts[0]).toContain('将取消批次"2026-09"并写入台账')
    expect(confirmTexts[0]).toContain('尚未报销')
    expect(confirmTexts[0]).not.toContain('请核对批次')
  })

  it('人工排除：确认框说明"排除后本期不再计入该票"，确认后发 confirm:true；不确认不发', async () => {
    await render()
    await setInput('记录编号', 'c'.repeat(64)); await setInput('排除理由', '分类缺失，人工核定不报销')
    confirms.push(false)
    await click('人工排除一项')
    expect(sent).toHaveLength(0)
    await click('人工排除一项')
    expect(sent[0]).toMatchObject({ action: 'exclude', item: 'c'.repeat(64), reviewer: '张律师', confirm: true })
    expect(confirmTexts.join()).toContain('排除后本期不再计入该票')
  })

  it('校验不过不发请求、显示问题；服务失败显示中文说明', async () => {
    replies.push(() => ({ ok: false, error: { code: 'OFFICE_DIR_NOT_SET', message: '还没有设置日常办公文件夹' } }))
    await render()
    await click('导入并生成贴票包')
    expect(sent).toHaveLength(0)
    expect(box.textContent).toContain('请先选择要导入的发票文件夹。')
    await click('入账')
    expect(output()!.textContent).toContain('还没有设置日常办公文件夹')
    expect(output()!.textContent).toContain(ERROR_HINT.OFFICE_DIR_NOT_SET)
  })

  it('返回首页', async () => {
    homeView.set('invoice')
    await render()
    await click('返回首页')
    expect(homeView.get()).toBe('home')
  })
})
