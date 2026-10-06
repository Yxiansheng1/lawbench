// 发票整理页（U-13，Spec 13.3；PRD 7.11）：首页点"发票整理"胶囊后在首页位置显示。
// 只调 /api/invoice/run（白名单动作，参数由服务拼装）；引擎输出原样显示在页面下方，不写日志。
// 一个动作进行中全部动作按钮停用；收到 ENGINE_BUSY 也停用并提示（排队的不可逆动作一旦拿到锁就会执行，所以不设短超时）。
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Badge, Button, C, ErrorLine, getNav, S, Section } from './kit.tsx'
import { call, confirm, lb } from './state.ts'
import { errorText } from './format.ts'
import { isMac, MAC_NO_INVOICE } from './platform.ts'
import {
  ACTION_LABEL, BUSY_CODE, BUSY_HOLD_MS, BUSY_TEXT, buildInvoiceRequest, emptyForm, EXCLUDE_CONFIRM, homeView, PRINT_FROM_OUTPUT, REVIEW_CONFIRM,
  REPLACE_CONFIRM, resultTone, TONE_TEXT, TWO_STEP, type InvoiceAction, type InvoiceForm, type InvoiceValue,
} from './invoice-logic.ts'

type Office = { dir: string | null; buyer: string | null; lawyer: string | null }
type Shown =
  | { action: InvoiceAction; preview?: boolean; value: InvoiceValue }
  | { action: InvoiceAction; error: { code: string; message: string } }

export const SETUP_TEXT = '发票整理要先在设置里指定日常办公文件夹（发票台账放在这里）和发票购买方名称（用来核对发票抬头）。请到左下角"设置"→"律师工作台"→"日常办公"填好后再回来。'

/** Mac 版（令 1424 第 1 条）：发票引擎只有 Windows 版，整页换成一句说明，不显示任何动作。 */
export function InvoicePage() {
  return isMac() ? <MacInvoiceNotice /> : <InvoiceWorkbench />
}

function MacInvoiceNotice() {
  return (
    <div style={S.page}>
      <div style={{ maxWidth: 980, margin: '0 auto', padding: '28px 24px', display: 'flex', flexDirection: 'column', gap: 18 }}>
        <div style={S.between}>
          <h2 style={S.h2}>发票整理</h2>
          <Button size="sm" variant="outline" onClick={() => homeView.set('home')}>返回首页</Button>
        </div>
        <div role="alert" style={{ ...S.card, borderColor: C.warn, lineHeight: 1.7 }}>{MAC_NO_INVOICE}</div>
      </div>
    </div>
  )
}

function InvoiceWorkbench() {
  const [office, setOffice] = useState<Office | null | 'fail'>(null)
  const [form, setForm] = useState<InvoiceForm>(() => emptyForm())
  const [running, setRunning] = useState<InvoiceAction | null>(null)
  const [busyUntil, setBusyUntil] = useState(0)
  const [shown, setShown] = useState<Shown | null>(null)
  const [problem, setProblem] = useState<string | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout>>()

  useEffect(() => {
    void lb().getSettings().then((s) => {
      const v = s as { office?: { dir?: string | null; invoice_buyer?: string | null }; profile?: { lawyer_name?: string | null } }
      const o = { dir: v.office?.dir ?? null, buyer: v.office?.invoice_buyer ?? null, lawyer: v.profile?.lawyer_name ?? null }
      setOffice(o)
      if (o.lawyer) setForm((f) => (f.reviewer ? f : { ...f, reviewer: o.lawyer! }))
    }).catch(() => setOffice('fail'))
    return () => clearTimeout(timer.current)
  }, [])

  const blocked = running !== null || busyUntil > 0
  const ready = office !== null && office !== 'fail' && !!office.dir && !!office.buyer
  const set = <K extends keyof InvoiceForm>(k: K, v: InvoiceForm[K]) => setForm((f) => ({ ...f, [k]: v }))

  /** 发一个动作；返回结果（失败、被拦返回 undefined）。 */
  const send = async (action: InvoiceAction, request: Record<string, unknown>, preview = false): Promise<InvoiceValue | undefined> => {
    setRunning(action)
    setProblem(null)
    try {
      const r = await call<InvoiceValue>('invoiceRun', request)
      if (!r.ok) {
        if (r.error.code === BUSY_CODE) {
          setBusyUntil(Date.now() + BUSY_HOLD_MS)
          clearTimeout(timer.current)
          timer.current = setTimeout(() => setBusyUntil(0), BUSY_HOLD_MS)
        }
        setShown({ action, error: r.error })
        return undefined
      }
      setShown({ action, preview, value: r.value })
      return r.value
    } finally {
      setRunning(null)
    }
  }

  const run = async (action: InvoiceAction) => {
    if (blocked) return
    const two = TWO_STEP[action]
    if (two) {
      // 先预览（cancel 用报表展示，引擎不支持 cancel 预览），预览成功再确认、再真的执行
      const pre = two.preview === 'report' ? buildInvoiceRequest('report', form) : buildInvoiceRequest(action, form, { apply: false })
      const real = buildInvoiceRequest(action, form, { apply: true })
      if (!real.ok) { setProblem(real.problem); return }
      if (!pre.ok) { setProblem(pre.problem); return }
      const v = await send(two.preview === 'report' ? 'report' : action, pre.request, true)
      if (!v || v.failed) return
      if (!(await confirm(two.title, two.text(form.batch.trim()), two.ok))) return
      await send(action, real.request)
      return
    }
    const built = buildInvoiceRequest(action, form)
    if (!built.ok) { setProblem(built.problem); return }
    if (action === 'exclude' && !(await confirm(EXCLUDE_CONFIRM.title, EXCLUDE_CONFIRM.text, EXCLUDE_CONFIRM.ok))) return
    if (action === 'review' && !(await confirm(REVIEW_CONFIRM.title, REVIEW_CONFIRM.text(form.reviewer.trim()), REVIEW_CONFIRM.ok))) return
    if (action === 'prepare' && form.replace && !(await confirm(REPLACE_CONFIRM.title, REPLACE_CONFIRM.text, REPLACE_CONFIRM.ok))) return
    await send(action, built.request)
  }

  const btn = (action: InvoiceAction, primary = false, needsSetup = true) => (
    <Button key={action} size="sm" variant={primary ? 'primary' : 'outline'} disabled={blocked || (needsSetup && !ready)} onClick={() => void run(action)}>
      {running === action ? `${ACTION_LABEL[action]}…` : ACTION_LABEL[action]}
    </Button>
  )
  const pickSrc = async () => { const p = await getNav().pickDirectory(); if (p) set('src', p) }

  return (
    <div style={S.page}>
      <div style={{ maxWidth: 980, margin: '0 auto', padding: '28px 24px', display: 'flex', flexDirection: 'column', gap: 18 }}>
        <div style={S.between}>
          <h2 style={S.h2}>发票整理</h2>
          <Button size="sm" variant="outline" onClick={() => homeView.set('home')}>返回首页</Button>
        </div>
        <div style={{ ...S.card, color: C.sub, lineHeight: 1.7 }}>
          发票台账和原票放在日常办公文件夹，不进案件、不发给模型。每次只做一个动作，做完再点下一个。
        </div>
        {office === 'fail' ? <ErrorLine error={{ code: 'SERVICE_UNAVAILABLE', message: '没能读取设置，请稍后重试' }} /> : null}
        {office !== null && office !== 'fail' && !ready ? (
          <div role="alert" style={{ ...S.card, borderColor: C.warn, lineHeight: 1.7 }}>{SETUP_TEXT}</div>
        ) : null}
        {ready ? <div style={S.sub}>台账在：{office.dir}\发票台账　购买方：{office.buyer}</div> : null}
        {busyUntil > 0 ? <div role="status" style={{ ...S.card, borderColor: C.warn, color: C.text }}>{BUSY_TEXT}</div> : null}

        <Section title="本期">
          <Row label="报销年月"><input type="month" aria-label="报销年月" style={S.input} value={form.period} onChange={(e) => set('period', e.target.value)} /></Row>
          <Row label="批次名"><input aria-label="批次名" style={{ ...S.input, width: 220 }} value={form.batch} onChange={(e) => set('batch', e.target.value)} /></Row>
          <Row label="发票来源">
            <label style={S.row}><input type="radio" checked={form.channel === 'local'} onChange={() => set('channel', 'local')} />文件夹里的 PDF、压缩包</label>
            <label style={S.row}><input type="radio" checked={form.channel === 'eml'} onChange={() => set('channel', 'eml')} />从邮件客户端导出的 EML 文件</label>
          </Row>
          {form.channel === 'eml' ? (
            <Row label="邮件日期">
              <input type="date" aria-label="起始日期" style={S.input} value={form.start} onChange={(e) => set('start', e.target.value)} />至
              <input type="date" aria-label="截止日期" style={S.input} value={form.end} onChange={(e) => set('end', e.target.value)} />
            </Row>
          ) : null}
          <Row label="历史未报票">
            <label style={S.row}><input type="radio" checked={form.history === 'exclude'} onChange={() => set('history', 'exclude')} />不纳入本期</label>
            <label style={S.row}><input type="radio" checked={form.history === 'selected'} onChange={() => set('history', 'selected')} />纳入下面这些号码</label>
            {btn('history')}
          </Row>
          {form.history === 'selected' ? (
            <textarea aria-label="要纳入的发票号码" rows={3} style={{ ...S.input, width: '100%' }} placeholder="每行一个发票号码（18 到 20 位数字），可从上面的历史未报清单里复制"
              value={form.historyNumbers} onChange={(e) => set('historyNumbers', e.target.value)} />
          ) : null}
          <div style={S.row}>{btn('plan', true)}</div>
        </Section>

        <Section title="导入发票">
          <Row label="发票文件夹">
            <input aria-label="发票文件夹" style={{ ...S.input, flex: 1 }} placeholder="选择或粘贴存放发票的文件夹" value={form.src} onChange={(e) => set('src', e.target.value)} />
            <Button size="sm" variant="outline" disabled={blocked} onClick={() => void pickSrc()}>选择文件夹…</Button>
          </Row>
          <div style={S.sub}>
            图片发票请先转成 PDF（可用小工具）。邮箱里的发票请自己下载，或在邮件客户端导出为 EML 文件放进一个文件夹；这里不连邮箱。
          </div>
          <div style={S.row}>{btn('run', true)}</div>
        </Section>

        <Section title="对账、入账与贴票包">
          <div style={{ ...S.row, flexWrap: 'wrap' }}>
            {btn('analyze')}{btn('import')}{btn('prepare')}
            <label style={S.row}><input type="checkbox" checked={form.replace} onChange={(e) => set('replace', e.target.checked)} />替换已有的贴票包</label>
          </div>
          <div style={{ ...S.row, flexWrap: 'wrap' }}>{btn('reprint')}{btn('reimburse')}{btn('cancel')}</div>
          <div style={S.sub}>确认已报销先显示预览，取消批次先显示台账报表，核对后再确认。改过发票购买方名称后，旧批次重印会失败；需要重印旧批次时，先把名称改回当时的。</div>
        </Section>

        <Section title="人工处理">
          <Row label="核验人"><input aria-label="核验人" style={{ ...S.input, width: 160 }} value={form.reviewer} onChange={(e) => set('reviewer', e.target.value)} /></Row>
          <Row label="排除">
            <input aria-label="记录编号" style={{ ...S.input, flex: 1 }} placeholder="对账表里的记录编号" value={form.item} onChange={(e) => set('item', e.target.value)} />
            <input aria-label="排除理由" style={{ ...S.input, flex: 1 }} placeholder="排除理由" value={form.reason} onChange={(e) => set('reason', e.target.value)} />
            {btn('exclude')}
          </Row>
          <Row label="核验">
            <input aria-label="文件指纹" style={{ ...S.input, flex: 1 }} placeholder="引擎输出里的文件指纹" value={form.sha256} onChange={(e) => set('sha256', e.target.value)} />
            {btn('review')}
          </Row>
        </Section>

        <Section title="台账">
          <div style={{ ...S.row, flexWrap: 'wrap' }}>{btn('report')}{btn('check_schema')}{btn('env_check', false, false)}</div>
        </Section>

        {problem ? <div role="alert" style={{ color: C.err, fontSize: 12 }}>{problem}</div> : null}
        <Output shown={shown} />
      </div>
    </div>
  )
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return <div style={{ ...S.row, flexWrap: 'wrap' }}><span style={{ ...S.sub, width: 72 }}>{label}</span>{children}</div>
}

/** 引擎输出原样显示：失败标红、退出码 2 标黄。 */
function Output({ shown }: { shown: Shown | null }) {
  if (!shown) return null
  if ('error' in shown) {
    return (
      <section aria-label="输出" style={{ ...S.card, borderColor: C.err }}>
        <div style={S.row}><Badge tone="err">{ACTION_LABEL[shown.action]}没有完成</Badge></div>
        <div role="alert" style={{ color: C.err, marginTop: 6 }}>{errorText(shown.error)}</div>
      </section>
    )
  }
  const v = shown.value
  const tone = resultTone(v)
  const color = { err: C.err, warn: C.warn, ok: C.ok }[tone]
  const printAction = shown.action === 'prepare' || shown.action === 'reprint' || shown.action === 'run'
  return (
    <section aria-label="输出" data-tone={tone} style={{ ...S.card, borderColor: color, display: 'flex', flexDirection: 'column', gap: 6 }}>
      <div style={S.row}>
        <Badge tone={tone}>{ACTION_LABEL[shown.action]}{shown.preview ? '（预览）' : ''}</Badge>
        <span style={{ color, fontSize: 12 }}>{TONE_TEXT[tone]}</span>
        <span style={S.sub}>退出码 {v.exit_code}</span>
      </div>
      {v.files.length ? (
        <ul style={{ ...S.list, fontSize: 12 }}>{v.files.map((f) => <li key={f} style={{ userSelect: 'text', overflowWrap: 'anywhere' }}>{f}</li>)}</ul>
      ) : printAction && !v.failed ? <div style={S.sub}>{PRINT_FROM_OUTPUT}</div> : null}
      <pre style={{ margin: 0, maxHeight: 360, overflow: 'auto', whiteSpace: 'pre-wrap', fontSize: 12, userSelect: 'text', color: tone === 'err' ? C.err : C.text }}>{v.output}</pre>
    </section>
  )
}
