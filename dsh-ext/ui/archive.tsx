// 归档面板（T26 第 3 步，U-15；PRD 7.12）：读归档方案（Host 的 archivePlan），律师核对材料名称、合并顺序、日期、承办律师，
// 点选办案结果后"生成归档文件"调 /api/archive/build（长任务，Host 走 node:http），列出生成的文件、页码范围和要人手处理的事项。
// 生成全在服务端；这里只改方案里律师能改的几项（见 archive-logic.ts），不碰文件。
import { useEffect, useState, type CSSProperties } from 'react'
import { Modal } from '@deepseek-ai/dsh-client-ui-primitives'
import { RESULTS, applyEdit, blocker, buildRequest, converterHint, pageLines, type ArchivePlan, type BuildValue, type Edit } from './archive-logic.ts'
import { errorText } from './format.ts'
import { Badge, Button, C, S } from './kit.tsx'
import { call, type CaseRef } from './state.ts'

/** 归档方案出自这个 Skill（skills\case-archiving）；成果标签里它的任务旁边有"生成归档文件"入口。 */
export const ARCHIVE_SKILL = 'case-archiving'

/**
 * DSH 的对话框固定 380px 宽（ui-primitives Modal.module.css），放不下方案表格。我方界面只用行内样式，这里给对话框加一个类名、
 * 注入一条规则把它放宽（只此一处；同一页面只注入一次）。
 */
export const WIDE_DIALOG = 'lawbench-wide-dialog'
function ensureWideDialogStyle(): void {
  if (typeof document === 'undefined' || document.getElementById(WIDE_DIALOG)) return
  const el = document.createElement('style')
  el.id = WIDE_DIALOG
  el.textContent = `.${WIDE_DIALOG}{width:min(820px, calc(100vw - 48px)) !important;}`
  document.head.appendChild(el)
}

type Loaded = { state: 'loading' } | { state: 'fail'; text: string } | { state: 'ok'; plan: ArchivePlan; path: string }

export function ArchiveDialog({ caseRef, taskId, onClose }: { caseRef: CaseRef; taskId: string; onClose: () => void }) {
  const [loaded, setLoaded] = useState<Loaded>({ state: 'loading' })
  const [plan, setPlan] = useState<ArchivePlan | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [built, setBuilt] = useState<BuildValue | null>(null)

  useEffect(ensureWideDialogStyle, [])
  useEffect(() => {
    let alive = true
    void call<{ plan: ArchivePlan; path: string }>('archivePlan', { root: caseRef.root, task_id: taskId }).then((r) => {
      if (!alive) return
      if (!r.ok) { setLoaded({ state: 'fail', text: errorText(r.error) }); return }
      setLoaded({ state: 'ok', plan: r.value.plan, path: r.value.path })
      setPlan(r.value.plan)
    })
    return () => { alive = false }
  }, [caseRef.root, taskId])

  const edit = (e: Edit) => { setPlan((p) => (p ? applyEdit(p, e) : p)); setError(null) }
  const why = plan ? blocker(plan) : null

  const build = async () => {
    if (!plan || loaded.state !== 'ok' || blocker(plan)) return // 办案结果没选不发请求
    setBusy(true); setError(null)
    const r = await call<BuildValue>('archiveBuild', buildRequest(caseRef.case_id, taskId, loaded.path, plan))
    setBusy(false)
    if (!r.ok) { setError(errorText(r.error)); return }
    setBuilt(r.value)
  }

  const footer = built
    ? <Button variant="primary" onClick={onClose}>完成</Button>
    : <>
        <Button variant="outline" onClick={onClose}>取消</Button>
        <Button variant="primary" disabled={!plan || !!why || busy} onClick={() => void build()}>{busy ? '正在生成…' : '生成归档文件'}</Button>
      </>

  return (
    <Modal open className={WIDE_DIALOG} onClose={busy ? () => undefined : onClose} title="生成归档文件" closeLabel="关闭" footer={footer}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10, maxHeight: '70vh', overflow: 'auto' }}>
        {loaded.state === 'loading' ? <div style={S.sub}>正在读取归档方案…</div> : null}
        {loaded.state === 'fail' ? <div role="alert" style={{ color: C.err }}>{loaded.text}</div> : null}
        {plan && !built ? <PlanForm plan={plan} edit={edit} disabled={busy} /> : null}
        {plan && !built && why ? <div style={{ color: C.err, fontSize: 12 }}>{why}</div> : null}
        {busy ? <div style={S.sub}>正在合并卷宗、生成文书，材料多时要几分钟，请不要关闭。</div> : null}
        {error ? <div role="alert" style={{ color: C.err }}>没有生成成功：{error}</div> : null}
        {built && plan ? <BuildResult v={built} plan={plan} /> : null}
      </div>
    </Modal>
  )
}

function PlanForm({ plan, edit, disabled }: { plan: ArchivePlan; edit: (e: Edit) => void; disabled: boolean }) {
  const cell: CSSProperties = { borderTop: `1px solid ${C.border}`, padding: '6px 4px', verticalAlign: 'top' }
  return (
    <>
      <div style={{ ...S.card, padding: 8, display: 'flex', flexDirection: 'column', gap: 4 }}>
        <div><span style={S.sub}>卷别：</span>{plan.catalog}</div>
        <div><span style={S.sub}>委托人：</span>{plan.client}{plan.opponent ? <><span style={S.sub}>　对方当事人：</span>{plan.opponent}</> : null}</div>
        <div><span style={S.sub}>{plan.catalog === '常法卷' ? '服务事项' : '案由'}：</span>{plan.cause}</div>
        {plan.jzl_no ? <div><span style={S.sub}>金助理案件编号：</span>{plan.jzl_no}</div> : null}
        {!plan.fee_settled ? <div style={{ color: C.warn }}>律师费未结清：生成时会附一份情况说明及承诺。</div> : null}
      </div>

      <div style={{ ...S.row, flexWrap: 'wrap', gap: 12 }}>
        <label style={S.row}>承办律师
          <input style={S.input} value={plan.lawyer ?? ''} placeholder="不填用设置里的律师姓名" disabled={disabled}
            onChange={(e) => edit({ kind: 'lawyer', lawyer: e.target.value })} />
        </label>
        <label style={S.row}>委托日期
          <input style={S.input} type="date" value={plan.entrust_date ?? ''} disabled={disabled}
            onChange={(e) => edit({ kind: 'date', field: 'entrust_date', value: e.target.value })} />
        </label>
        <label style={S.row}>结案日期
          <input style={S.input} type="date" value={plan.close_date ?? ''} disabled={disabled}
            onChange={(e) => edit({ kind: 'date', field: 'close_date', value: e.target.value })} />
        </label>
      </div>

      <fieldset style={{ border: `1px solid ${plan.result ? C.border : C.err}`, borderRadius: 6, padding: '6px 10px' }}>
        <legend style={{ fontWeight: 500 }}>办案结果（必选）</legend>
        <div role="radiogroup" aria-label="办案结果" style={{ ...S.row, flexWrap: 'wrap', gap: 12 }}>
          {RESULTS.map((r) => (
            <label key={r} style={S.row}>
              <input type="radio" name="archive-result" checked={plan.result === r} disabled={disabled} onChange={() => edit({ kind: 'result', result: r })} />{r}
            </label>
          ))}
        </div>
      </fieldset>

      <div style={{ fontWeight: 500 }}>卷宗材料（按编号合并；同一项里的材料按下面的顺序）</div>
      <table style={{ borderCollapse: 'collapse', width: '100%', fontSize: 13 }}>
        <thead><tr><th style={{ textAlign: 'left', width: 40 }}>编号</th><th style={{ textAlign: 'left', width: '35%' }}>名称</th><th style={{ textAlign: 'left' }}>材料（合并顺序）</th></tr></thead>
        <tbody>{[...plan.items].sort((a, b) => a.code - b.code).map((it) => (
          <tr key={it.code}>
            <td style={cell}>{it.code}</td>
            <td style={cell}>
              <input style={{ ...S.input, width: '100%' }} aria-label={`第 ${it.code} 项名称`} value={it.name} disabled={disabled}
                onChange={(e) => edit({ kind: 'name', code: it.code, name: e.target.value })} />
            </td>
            <td style={cell}>
              <ol style={{ margin: 0, paddingLeft: 18 }}>{it.materials.map((m, i) => (
                <li key={`${i}-${m}`} style={{ ...S.between, gap: 6 }}>
                  <span style={{ wordBreak: 'break-all' }}>{m}</span>
                  {it.materials.length > 1 ? (
                    <span style={{ ...S.row, flexShrink: 0 }}>
                      <Button size="sm" variant="ghost" aria-label={`${m} 上移`} disabled={disabled || i === 0} onClick={() => edit({ kind: 'move', code: it.code, index: i, by: -1 })}>上移</Button>
                      <Button size="sm" variant="ghost" aria-label={`${m} 下移`} disabled={disabled || i === it.materials.length - 1} onClick={() => edit({ kind: 'move', code: it.code, index: i, by: 1 })}>下移</Button>
                    </span>
                  ) : null}
                </li>
              ))}</ol>
            </td>
          </tr>
        ))}</tbody>
      </table>
      <div style={S.sub}>结案报告由程序生成后自动放进卷宗，不在上表里。</div>
    </>
  )
}

function BuildResult({ v, plan }: { v: BuildValue; plan: ArchivePlan }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div><Badge tone="ok">已生成</Badge> 归档文件在案件文件夹的 <span style={{ wordBreak: 'break-all' }}>{v.folder}</span></div>
      <div style={{ fontWeight: 500 }}>生成的文件</div>
      <ul style={{ margin: 0, paddingLeft: 18 }}>{v.files.map((f) => <li key={f.path}><span style={S.sub}>{f.kind}：</span><span style={{ wordBreak: 'break-all' }}>{f.path}</span></li>)}</ul>
      <div style={{ fontWeight: 500 }}>卷宗页码</div>
      <ul style={{ margin: 0, paddingLeft: 18 }}>{pageLines(v, plan).map((l) => <li key={l}>{l}</li>)}</ul>
      <div style={S.sub}>{converterHint(v)}</div>
      {v.manual.length ? (
        <div style={{ border: `1px solid ${C.warn}`, borderRadius: 6, padding: 8 }}>
          <div style={{ fontWeight: 500, color: C.warn }}>还需要您手动处理</div>
          <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>{v.manual.map((m) => <li key={m}>{m}</li>)}</ul>
        </div>
      ) : null}
    </div>
  )
}
