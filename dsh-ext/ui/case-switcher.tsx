// 对话区顶部标题位的当前案件（令 1515 第 2 条，用户："新会话下面那个东西是干嘛的，点击它跟首页功能一样"）：
// 侧栏"案件：xxx"一块删掉，当前案件改在对话区顶部显示——案件名＋右侧"切换案件 ▾"（最近案件＋"首页…"）；
// 日常事务显示"日常事务（非办案）"。登记在 DSH 的 conversation.session.header.actions（会话标题右边）。
import { useEffect, useRef, useState } from 'react'
import { openCase } from './cases.ts'
import { C, getNav } from './kit.tsx'
import { app, currentCase, isDaily, samePath, type CaseRef } from './state.ts'
import { useStore } from './store.ts'

/** 切换菜单里列的最近案件个数。 */
export const SWITCH_MAX = 10

/** 切换菜单里的案件：去掉当前的，按上次打开倒序。 */
export function switchTargets(cases: CaseRef[], current: CaseRef | undefined): CaseRef[] {
  return cases.filter((c) => !current || !samePath(c.root, current.root))
    .sort((a, b) => (Date.parse(b.last_opened ?? '') || 0) - (Date.parse(a.last_opened ?? '') || 0))
    .slice(0, SWITCH_MAX)
}

export function CaseSwitcher() {
  const current = useStore(app, currentCase)
  const daily = useStore(app, (s) => isDaily(s, current))
  const dailyRoot = useStore(app, (s) => s.dailyRoot)
  const cases = useStore(app, (s) => s.cases)
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLSpanElement>(null)
  useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false) }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [open])
  if (!current) return null
  const go = (c: CaseRef) => { setOpen(false); void openCase(c.root, null) }
  const item = { display: 'block', width: '100%', textAlign: 'left' as const, background: 'none', border: 'none', padding: '6px 12px', font: 'inherit', fontSize: 13, color: C.text, cursor: 'pointer', whiteSpace: 'nowrap' as const, overflow: 'hidden', textOverflow: 'ellipsis' }
  return (
    <span ref={box} data-lawbench-case-switcher="" style={{ position: 'relative', display: 'inline-flex', alignItems: 'center', gap: 8, fontSize: 13 }}>
      <span style={{ fontWeight: 600, color: C.text, maxWidth: 260, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{daily ? `${current.name}（非办案）` : current.name}</span>
      <button type="button" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(!open)}
        style={{ font: 'inherit', fontSize: 12, color: C.sub, background: 'none', border: `1px solid ${C.border}`, borderRadius: 999, padding: '1px 10px', cursor: 'pointer' }}>切换案件 ▾</button>
      {open ? (
        <div role="menu" aria-label="切换案件" style={{ position: 'absolute', top: '100%', right: 0, marginTop: 4, minWidth: 220, maxWidth: 320, zIndex: 20, background: 'var(--dsh-color-bg-elevated, Canvas)', border: `1px solid ${C.border}`, borderRadius: 10, boxShadow: '0 6px 24px rgba(0,0,0,0.12)', padding: '4px 0' }}>
          {switchTargets(cases, current).map((c) => (
            <button key={c.case_id} type="button" role="menuitem" style={item} onClick={() => go(c)} title={c.root}>
              {dailyRoot && samePath(c.root, dailyRoot) ? `${c.name}（非办案）` : c.name}
            </button>
          ))}
          <div style={{ borderTop: `1px solid ${C.border}`, margin: '4px 0' }} />
          <button type="button" role="menuitem" style={item} onClick={() => { setOpen(false); getNav().goHome() }}>首页…</button>
        </div>
      ) : null}
    </span>
  )
}
