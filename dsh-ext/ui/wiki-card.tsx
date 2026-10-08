// 案件 wiki 合成一张卡（令 1852 第 18 条，第七版待办 18）：案件卡片、概览、当事人、时间线、材料清单、争议焦点六个板块折叠在一张卡里，
// 顶部写生成于何时、生成后材料有没有变化；一个"核对完成"一次清掉待复核。展开板块看内容，出处可点（打开原文查看）；
// "打开 wiki 文件夹"和每个板块的"打开文件"经 Host（openFolder / openFile，限案件根里）。
// 内容由 Host 读（caseWiki，服务没有读 wiki 正文的接口）。"核对完成"记在本机（按案件），记的是这一版 wiki 加此刻材料的指纹：
// 重新生成、更新或材料变化后指纹变了，就又显示待复核。聊天流里 AI 的"wiki 修改建议"仍逐条采纳，不在这里。
import { useEffect, useState, type ReactNode } from 'react'
import { citationTargets, errorText } from './format.ts'
import { Badge, Button, C, getNav, S, useLoad } from './kit.tsx'
import { call, notice, type CaseRef } from './state.ts'
import { TABS } from './cases.ts'
import { openCaseFile } from './folder-actions.ts'

export const WIKI_FOLDER = '工作区/wiki'

export interface WikiFact { text: string; citations: string[]; status: string }
export interface WikiSectionView { key: string; title: string; rel: string | null; text: string | null; truncated: boolean }
export interface CaseWiki {
  exists: boolean
  generated_at: string | null
  sections: WikiSectionView[]
  card: { parties: WikiFact[]; issues: WikiFact[]; key_facts: WikiFact[] } | null
  changes: { added: number; changed: number; removed: number } | null
  signature: string
}

interface CheckedRecord { signature: string; at: string }
const CHECKED_KEY = (caseId: string) => `lawbench.wikiChecked.${caseId}`

/** 本机记的"核对完成"（读不到为 null）。 */
export function readChecked(caseId: string): CheckedRecord | null {
  try {
    const v = JSON.parse(localStorage.getItem(CHECKED_KEY(caseId)) ?? 'null') as unknown
    return v && typeof v === 'object' && typeof (v as CheckedRecord).signature === 'string' ? v as CheckedRecord : null
  } catch { return null }
}
export function recordChecked(caseId: string, signature: string, at: Date = new Date()): CheckedRecord {
  const rec = { signature, at: at.toISOString() }
  try { localStorage.setItem(CHECKED_KEY(caseId), JSON.stringify(rec)) } catch { /* 记不下：本次运行内仍对 */ }
  return rec
}

/** 生成后材料的变化，一句话；没变化为 null。已核对过这一版时不再说"需要复核"（与右上角"已核对"一致）。 */
export function changesText(c: CaseWiki['changes'], reviewed = false): string | null {
  if (!c || c.added + c.changed + c.removed === 0) return null
  const parts = [c.added ? `新增 ${c.added} 份` : '', c.changed ? `变化 ${c.changed} 份` : '', c.removed ? `移除 ${c.removed} 份` : ''].filter(Boolean)
  return reviewed
    ? `生成后材料有变化（${parts.join('、')}），已核对；需要时点"生成 / 更新 wiki"更新。`
    : `生成后材料有变化（${parts.join('、')}），需要复核，可以点"生成 / 更新 wiki"更新。`
}

/** 这一版是否待复核：有 wiki、且本机没记过这一版的"核对完成"。 */
export const needsReview = (w: CaseWiki, checked: CheckedRecord | null): boolean => w.exists && checked?.signature !== w.signature

const fmt = (t: string) => { const d = new Date(t); return Number.isNaN(d.getTime()) ? t : d.toLocaleString('zh-CN') }

/** 卡片标题下那句：生成于…；没生成过的板块计数。 */
export function statusLine(w: CaseWiki): string {
  const missing = w.sections.filter((s) => (s.key === 'card' ? w.card === null : s.text === null)).length
  const gen = w.generated_at ? `生成于 ${fmt(w.generated_at)}` : '生成时间读不到'
  return missing ? `${gen}；${missing} 个板块还没有内容` : gen
}

const linkBtn = { font: 'inherit', color: C.brand, background: 'none', border: 'none', padding: 0, cursor: 'pointer', textDecoration: 'underline' } as const

/** 正文里的出处（〔材料名 第N页〕，旧写法里包着的 markdown 链接只取文字）做成可点的，点开在"原文查看"里看。 */
function WithCitations({ text, materials }: { text: string; materials: ReadonlyArray<{ material_id: string; name: string }> }) {
  const out: ReactNode[] = []
  let last = 0
  const re = /〔([^〕]*)〕/g
  for (let m = re.exec(text); m; m = re.exec(text)) {
    if (m.index > last) out.push(text.slice(last, m.index))
    const inner = m[1]!.replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
    const targets = citationTargets(`〔${inner}〕`, materials)
    out.push(<span key={m.index}>〔{targets.map((t, i) => (
      <span key={i}>{i ? '、' : ''}{t.material_id
        ? <button type="button" style={linkBtn} onClick={() => getNav().openTab(TABS.source, { material_id: t.material_id!, citation: t.citation })}>{t.text}</button>
        : t.text}</span>
    ))}〕</span>)
    last = m.index + m[0].length
  }
  if (last < text.length) out.push(text.slice(last))
  return <>{out}</>
}

/**
 * 文章正文按行轻量显示（不引 markdown 库）：一级标题与板块名相同就不重复；二至六级标题加粗；"> "开头的说明行用浅色；去掉 ** 加粗记号；
 * 出处照样可点。
 */
export function articleLines(text: string, title: string): Array<{ kind: 'h' | 'note' | 'text'; text: string }> {
  const out: Array<{ kind: 'h' | 'note' | 'text'; text: string }> = []
  for (const raw of text.replace(/\r\n/g, '\n').split('\n')) {
    const line = raw.replace(/\*\*/g, '')
    const h = /^(#{1,6})\s+(.*)$/.exec(line)
    if (h) { if (!(h[1] === '#' && h[2]!.trim() === title)) out.push({ kind: 'h', text: h[2]! }); continue }
    if (/^>\s?/.test(line)) { out.push({ kind: 'note', text: line.replace(/^>\s?/, '') }); continue }
    if (line.trim() === '' && (out.length === 0 || out[out.length - 1]!.text.trim() === '')) continue
    out.push({ kind: 'text', text: line })
  }
  return out
}

function Article({ text, title, materials }: { text: string; title: string; materials: ReadonlyArray<{ material_id: string; name: string }> }) {
  return (
    <>{articleLines(text, title).map((l, i) => (
      <div key={i} style={l.kind === 'h' ? { fontWeight: 600, marginTop: 4 } : l.kind === 'note' ? { color: C.sub } : undefined}>
        {l.text.trim() === '' ? '\u00a0' : <WithCitations text={l.text} materials={materials} />}
      </div>
    ))}</>
  )
}

const FACT_WORD: Record<string, string> = { excerpt: '', unconfirmed: '（出处待核）', lawyer_confirmed: '（律师已确认）' }

function CardFacts({ card, materials }: { card: NonNullable<CaseWiki['card']>; materials: ReadonlyArray<{ material_id: string; name: string }> }) {
  const groups: Array<[string, WikiFact[]]> = [['当事人', card.parties], ['争议焦点', card.issues], ['关键事实', card.key_facts]]
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      {groups.map(([title, list]) => (
        <div key={title}>
          <div style={{ fontWeight: 500 }}>{title}</div>
          {list.length ? <ul style={{ margin: '2px 0 0', paddingLeft: 18 }}>{list.map((f, i) => (
            <li key={i}>{f.text}{f.citations.map((c, j) => <WithCitations key={j} text={c} materials={materials} />)}<span style={S.sub}>{FACT_WORD[f.status] ?? ''}</span></li>
          ))}</ul> : <div style={S.sub}>（没有）</div>}
        </div>
      ))}
    </div>
  )
}

function SectionRow({ caseRef, s, w, materials }: { caseRef: CaseRef; s: WikiSectionView; w: CaseWiki; materials: ReadonlyArray<{ material_id: string; name: string }> }) {
  const [open, setOpen] = useState(false)
  const empty = s.key === 'card' ? w.card === null : s.text === null
  return (
    <li style={{ borderTop: `1px solid ${C.border}`, paddingTop: 6 }}>
      <div style={S.between}>
        <button type="button" aria-expanded={open} disabled={empty} onClick={() => setOpen(!open)}
          style={{ font: 'inherit', color: empty ? C.faint : C.text, background: 'none', border: 'none', padding: 0, cursor: empty ? 'default' : 'pointer', textAlign: 'left' }}>
          {open ? '▾' : '▸'} {s.title}{empty ? '（还没有）' : ''}
        </button>
        {s.rel && !empty ? <Button size="sm" variant="ghost" onClick={() => void openCaseFile(caseRef, s.rel!)}>打开文件</Button> : null}
      </div>
      {open && !empty ? (
        <div style={{ marginTop: 4, maxHeight: 360, overflow: 'auto', wordBreak: 'break-word', fontSize: 12, lineHeight: 1.7 }}>
          {s.key === 'card' ? <CardFacts card={w.card!} materials={materials} /> : <Article text={s.text!} title={s.title} materials={materials} />}
          {s.truncated ? <div style={S.sub}>（内容较长，只显示前一部分，完整内容请点"打开文件"）</div> : null}
        </div>
      ) : null}
    </li>
  )
}

/**
 * 一张"案件 wiki"卡。
 * @param refreshKey - 变了就重读（wiki 整理结束、建议采纳后由外面改）。
 */
export function WikiCard({ caseRef, materials, refreshKey }: { caseRef: CaseRef; materials: ReadonlyArray<{ material_id: string; name: string }>; refreshKey?: unknown }) {
  const id = caseRef.case_id
  const [data, reload] = useLoad(() => call<CaseWiki>('caseWiki', { case_id: id, root: caseRef.root }), [id, caseRef.root])
  const [checked, setChecked] = useState<CheckedRecord | null>(() => readChecked(id))
  useEffect(() => { setChecked(readChecked(id)) }, [id])
  useEffect(() => { if (refreshKey !== undefined) void reload() }, [refreshKey]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const on = (e: Event) => { if ((e as CustomEvent).detail === id) void reload() }
    window.addEventListener('lawbench:materials-changed', on)
    return () => window.removeEventListener('lawbench:materials-changed', on)
  }, [id, reload])
  const openFolder = async () => {
    const r = await call<{ opened: true }>('openFolder', { case_id: id, root: caseRef.root, rel: WIKI_FOLDER })
    if (!r.ok) notice('文件夹没能打开', errorText(r.error))
  }
  if (data.state === 'loading') return <div style={S.card}><div style={S.sub}>读取案件 wiki…</div></div>
  if (data.state === 'fail') return <div style={S.card}><div style={S.sub}>案件 wiki 读不到：{errorText(data.error)}</div></div>
  const w = data.value
  if (!w.exists) return <div style={S.card}><div style={{ fontWeight: 600 }}>案件 wiki</div><div style={S.sub}>还没有生成。点上面"生成 / 更新 wiki"整理材料。</div></div>
  const review = needsReview(w, checked)
  const change = changesText(w.changes, !review)
  return (
    <section aria-label="案件 wiki" style={{ ...S.card, display: 'flex', flexDirection: 'column', gap: 6 }}>
      <div style={S.between}>
        <span style={{ fontWeight: 600 }}>案件 wiki</span>
        {review ? <Badge tone="warn">待复核</Badge> : <Badge tone="ok">已核对</Badge>}
      </div>
      <div style={S.sub}>{statusLine(w)}{!review && checked ? `；${fmt(checked.at)} 核对完成` : ''}</div>
      {change ? <div style={{ color: review ? C.warn : C.sub, fontSize: 12 }}>{change}</div> : null}
      <ul style={{ ...S.list, gap: 6 }}>
        {w.sections.map((s) => <SectionRow key={s.key} caseRef={caseRef} s={s} w={w} materials={materials} />)}
      </ul>
      <div style={{ ...S.row, flexWrap: 'wrap', borderTop: `1px solid ${C.border}`, paddingTop: 6 }}>
        <Button size="sm" variant={review ? 'primary' : 'outline'} disabled={!review} onClick={() => setChecked(recordChecked(id, w.signature))}>核对完成</Button>
        <Button size="sm" variant="ghost" onClick={() => void openFolder()}>打开 wiki 文件夹</Button>
      </div>
    </section>
  )
}
