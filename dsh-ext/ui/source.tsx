// 右侧栏"原文查看"标签（PRD 7.9；Spec 4.3 /api/source、/api/search）：按出处定位到页 / 段 / 行 / 单元格，
// PDF 另显示该页的页面图片（定位到页，不做文字高亮）。另带律师检索，点命中处即查看原文。
import { useEffect, useState, type FormEvent } from 'react'
import { errorText } from './format.ts'
import { Badge, Button, C, Empty, ErrorLine, S, Section } from './kit.tsx'
import { call, type CaseRef } from './state.ts'
import { WithCase, type SessionProps } from './session-case.tsx'

type Loc = { unit: 'page' | 'para' | 'line'; from: number; to?: number } | { unit: 'cell'; sheet: string; ref: string }
interface SourceView { name: string; loc: Loc; text: string; page_png_base64: string | null; source_changed: boolean }
interface Hit { name: string; material_id: string; citation: string; snippet: string; is_ocr: boolean; match: 'exact' | 'expanded' }

type TabInfo = { tab: { navigation: { params?: Record<string, unknown>; revision?: number } } }
type Props = SessionProps & { useTabInfo?: () => TabInfo }

const locText = (l: Loc) => l.unit === 'cell' ? `${l.sheet}!${l.ref}`
  : `第 ${l.from}${l.to && l.to !== l.from ? `-${l.to}` : ''} ${{ page: '页', para: '段', line: '行' }[l.unit]}`

export function SourceTab(p: Props) {
  const nav = p.useTabInfo?.().tab.navigation
  const params = (nav?.params ?? {}) as { material_id?: string; citation?: string }
  return <WithCase p={p}>{(c) => <Source caseRef={c} initial={params.material_id && params.citation ? { material_id: params.material_id, citation: params.citation } : null} revision={nav?.revision ?? 0} />}</WithCase>
}

function Source({ caseRef, initial, revision }: { caseRef: CaseRef; initial: { material_id: string; citation: string } | null; revision: number }) {
  const [target, setTarget] = useState(initial)
  const [view, setView] = useState<SourceView | null>(null)
  const [err, setErr] = useState<{ code: string; message: string } | null>(null)
  const [q, setQ] = useState('')
  const [hits, setHits] = useState<{ hits: Hit[]; total: number; truncated: boolean } | null>(null)

  useEffect(() => { if (initial) setTarget(initial) }, [revision, initial?.material_id, initial?.citation]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!target) return
    let stop = false
    setView(null); setErr(null)
    void call<SourceView>('source', { case_id: caseRef.case_id, material_id: target.material_id, citation: target.citation }).then((r) => {
      if (stop) return
      if (r.ok) setView(r.value); else setErr(r.error)
    })
    return () => { stop = true }
  }, [caseRef.case_id, target?.material_id, target?.citation]) // eslint-disable-line react-hooks/exhaustive-deps

  const search = async (e: FormEvent) => {
    e.preventDefault()
    const text = q.trim()
    if (!text) return
    const r = await call<{ hits: Hit[]; total: number; truncated: boolean }>('search', { case_id: caseRef.case_id, q: text.slice(0, 100) })
    if (r.ok) { setHits(r.value); setErr(null) } else setErr(r.error)
  }

  return (
    <div style={S.pane}>
      <form onSubmit={(e) => void search(e)} style={S.row}>
        <input style={{ ...S.input, flex: 1 }} value={q} maxLength={100} onChange={(e) => setQ(e.target.value)} placeholder="在本案材料里检索" aria-label="检索词" />
        <Button size="sm" variant="outline" type="submit">检索</Button>
      </form>
      {hits ? (
        <Section title={`检索结果（${hits.total} 处${hits.truncated ? '，只列出前面的' : ''}）`} extra={<Button size="sm" variant="ghost" onClick={() => setHits(null)}>收起</Button>}>
          {hits.hits.length === 0 ? <Empty>没有找到</Empty> : (
            <ul style={{ ...S.list, maxHeight: 220, overflow: 'auto' }}>{hits.hits.map((h, i) => (
              <li key={i}>
                <button type="button" onClick={() => setTarget({ material_id: h.material_id, citation: h.citation })}
                  style={{ ...S.card, padding: 6, width: '100%', textAlign: 'left', font: 'inherit', color: C.text, cursor: 'pointer' }}>
                  <div style={S.between}><span>{h.citation}</span><span style={S.row}>{h.is_ocr ? <Badge tone="warn">识别所得</Badge> : null}{h.match === 'expanded' ? <Badge tone="faint">近似</Badge> : null}</span></div>
                  <div style={S.sub}>…{h.snippet}…</div>
                </button>
              </li>
            ))}</ul>
          )}
        </Section>
      ) : null}
      <ErrorLine error={err ? { ...err, message: errorText(err) } : null} />
      {!target && !hits ? <Empty>点草稿或 wiki 建议里的出处，这里显示对应的原文；也可以在上面检索。</Empty> : null}
      {target && !view && !err ? <Empty>读取原文中…</Empty> : null}
      {view ? (
        <Section title={<span>{view.name} · {locText(view.loc)}</span>}>
          {view.source_changed ? <div style={{ color: C.warn, fontSize: 12 }}>原件在引用之后改过，下面是现在的内容，可能与当时不同。</div> : null}
          {view.page_png_base64 ? <img alt={`${view.name} ${locText(view.loc)} 的页面图片`} src={`data:image/png;base64,${view.page_png_base64}`} style={{ maxWidth: '100%', border: `1px solid ${C.border}`, borderRadius: C.rSm }} /> : null}
          <pre style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', font: 'inherit', lineHeight: 1.7, margin: 0, ...S.card }}>{view.text}</pre>
        </Section>
      ) : null}
    </div>
  )
}
