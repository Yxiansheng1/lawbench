// 空会话顶部的案件概览卡（令 1347 第 2 条，用户："工作区和案件是分开的吗""首页不是很大气"）：
// 案件名；材料 N 份（其中待识别 M 份）；最近 3 条成果（点开成果标签）；最近一次对话（点开那条会话）。
// "日常事务"换成一句提示和最近 3 条对话。数据走现有的 /api/materials、/api/outputs 和 DSH 会话列表，不加接口。
import { TABS } from './cases.ts'
import { C, getNav, useLoad } from './kit.tsx'
import { call, type CaseRef } from './state.ts'

export interface SessionBrief { id: string; title: string; updatedAt: number }

export const DAILY_HINT = '非办案事务的对话都在这里；办案请在左侧切换到案件。'

/** 时间：今天的只写时分，别的写月日时分。 */
export function shortTime(t: number | string, now: Date = new Date()): string {
  const d = new Date(t)
  if (Number.isNaN(d.getTime())) return ''
  const p = (n: number) => String(n).padStart(2, '0')
  const hm = `${p(d.getHours())}:${p(d.getMinutes())}`
  return d.toDateString() === now.toDateString() ? `今天 ${hm}` : `${d.getMonth() + 1}月${d.getDate()}日 ${hm}`
}

/** 材料份数与待识别份数（有待识别页的算一份）。 */
export function materialCounts(materials: Array<{ pages_need_ocr?: unknown[] }>): { total: number; pending: number } {
  return { total: materials.length, pending: materials.filter((m) => Array.isArray(m.pages_need_ocr) && m.pages_need_ocr.length > 0).length }
}

type Output = { title: string; version: number; confirmed_at: string; files: Array<{ path: string }> }

/** 最近 n 条成果（按确认时间倒序）。 */
export function recentOutputs(outputs: Output[], n = 3): Output[] {
  return [...outputs].sort((a, b) => Date.parse(b.confirmed_at) - Date.parse(a.confirmed_at)).slice(0, n)
}

const row = { display: 'flex', alignItems: 'baseline', gap: 8, minWidth: 0 } as const
const link = { background: 'none', border: 'none', padding: 0, font: 'inherit', color: C.brand, cursor: 'pointer', textAlign: 'left' as const, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' as const }
const label = { color: C.sub, flex: 'none' } as const

export function CaseOverview({ caseRef, daily, sessions }: { caseRef: CaseRef; daily: boolean; sessions: SessionBrief[] }) {
  const recent = [...sessions].sort((a, b) => b.updatedAt - a.updatedAt)
  const open = (id: string) => getNav().openSession(id)
  return (
    <section aria-label="案件概览" style={{ border: `1px solid ${C.border}`, borderRadius: 12, padding: '14px 16px', display: 'flex', flexDirection: 'column', gap: 8, fontSize: 14 }}>
      <div style={{ fontSize: 17, fontWeight: 600 }}>{daily ? `${caseRef.name}（非办案）` : caseRef.name}</div>
      {daily ? <DailyBody recent={recent.slice(0, 3)} open={open} /> : <CaseBody caseRef={caseRef} last={recent[0]} open={open} />}
    </section>
  )
}

function DailyBody({ recent, open }: { recent: SessionBrief[]; open: (id: string) => void }) {
  return (
    <>
      <div style={{ color: C.sub }}>{DAILY_HINT}</div>
      {recent.length ? recent.map((s) => (
        <div key={s.id} style={row}><button type="button" style={link} onClick={() => open(s.id)}>{s.title}</button><span style={{ ...label, fontSize: 12 }}>{shortTime(s.updatedAt)}</span></div>
      )) : <div style={{ color: C.faint }}>还没有对话。</div>}
    </>
  )
}

function CaseBody({ caseRef, last, open }: { caseRef: CaseRef; last: SessionBrief | undefined; open: (id: string) => void }) {
  const [mats] = useLoad(() => call<{ materials: Array<{ pages_need_ocr?: unknown[] }> }>('materialsList', { case_id: caseRef.case_id }), [caseRef.case_id])
  const [outs] = useLoad(() => call<{ outputs: Output[] }>('outputsList', { case_id: caseRef.case_id }), [caseRef.case_id])
  const counts = mats.state === 'ok' ? materialCounts(mats.value.materials) : null
  const latest = outs.state === 'ok' ? recentOutputs(outs.value.outputs) : []
  return (
    <>
      <div style={row}>
        <span style={label}>材料</span>
        <button type="button" style={link} onClick={() => getNav().openTab(TABS.materials)}>
          {counts ? `${counts.total} 份${counts.pending ? `（其中待识别 ${counts.pending} 份）` : ''}` : mats.state === 'fail' ? '读不到' : '…'}
        </button>
      </div>
      <div style={{ ...row, alignItems: 'flex-start' }}>
        <span style={label}>最近成果</span>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4, minWidth: 0 }}>
          {latest.length ? latest.map((o) => (
            <div key={`${o.title}-${o.version}`} style={row}>
              <button type="button" style={link} onClick={() => getNav().openTab(TABS.results)}>{o.files[0]?.path.split('/').pop() ?? `${o.title} v${o.version}`}</button>
              <span style={{ ...label, fontSize: 12 }}>{shortTime(o.confirmed_at)}</span>
            </div>
          )) : <span style={{ color: C.faint }}>{outs.state === 'loading' ? '…' : '还没有'}</span>}
        </div>
      </div>
      <div style={row}>
        <span style={label}>最近对话</span>
        {last ? <><button type="button" style={link} onClick={() => open(last.id)}>{last.title}</button><span style={{ ...label, fontSize: 12 }}>{shortTime(last.updatedAt)}</span></> : <span style={{ color: C.faint }}>还没有</span>}
      </div>
    </>
  )
}
