// 对话区顶部标题位的当前案件（令 1515 第 2 条，用户："新会话下面那个东西是干嘛的，点击它跟首页功能一样"）：
// 侧栏"案件：xxx"一块删掉，当前案件改在对话区顶部显示——案件名＋右侧"切换案件 ▾"（最近案件＋"首页…"）；
// 日常事务只写"日常事务"（注记 1653 去掉"（非办案）"）。登记在 DSH 的 conversation.session.header.actions（会话标题右边）。
import { useEffect, useRef, useState } from 'react'
import { openCase } from './cases.ts'
import { C, getNav } from './kit.tsx'
import { app, currentCase, samePath, type CaseRef } from './state.ts'
import { useStore } from './store.ts'

/** 侧栏案件的"重命名"已藏掉（令 1609 第 3 条）：案件名就是文件夹名。 */
export const RENAME_HINT = '案件名即文件夹名，在资源管理器里改'

/** 切换菜单里列的最近案件个数。 */
export const SWITCH_MAX = 10

/** 切换菜单里的案件：去掉当前的，按上次打开倒序。 */
export function switchTargets(cases: CaseRef[], current: CaseRef | undefined): CaseRef[] {
  return cases.filter((c) => !current || !samePath(c.root, current.root))
    .sort((a, b) => (Date.parse(b.last_opened ?? '') || 0) - (Date.parse(a.last_opened ?? '') || 0))
    .slice(0, SWITCH_MAX)
}

const MENU_WIDTH = 280

/**
 * 菜单位置（注记 1653，用户截图：左半边被裁）：原来是标题容器里的绝对定位，往左伸出容器被裁、被侧栏盖住。
 * 改成固定定位、层级在标题与侧栏之上：右边缘对齐按钮，夹在窗口内（左右各留 8px）。
 */
export function menuAt(btn: { right: number; bottom: number }, viewportWidth: number): { top: number; left: number } {
  const left = Math.max(8, Math.min(btn.right - MENU_WIDTH, viewportWidth - MENU_WIDTH - 8))
  return { top: btn.bottom + 4, left }
}

export function CaseSwitcher() {
  const current = useStore(app, currentCase)
  const cases = useStore(app, (s) => s.cases)
  const [open, setOpen] = useState(false)
  const [at, setAt] = useState<{ top: number; left: number } | null>(null)
  const box = useRef<HTMLSpanElement>(null)
  useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false) }
    const shut = () => setOpen(false) // 固定定位不跟着走：窗口变大小、页面滚动时先收起
    document.addEventListener('mousedown', close)
    window.addEventListener('resize', shut)
    window.addEventListener('scroll', shut, true)
    return () => { document.removeEventListener('mousedown', close); window.removeEventListener('resize', shut); window.removeEventListener('scroll', shut, true) }
  }, [open])
  if (!current) return null
  const go = (c: CaseRef) => { setOpen(false); void openCase(c.root, null) }
  const item = { display: 'block', width: '100%', textAlign: 'left' as const, background: 'none', border: 'none', padding: '6px 12px', font: 'inherit', fontSize: 13, color: C.text, cursor: 'pointer', whiteSpace: 'nowrap' as const, overflow: 'hidden', textOverflow: 'ellipsis' }
  return (
    <span ref={box} data-lawbench-case-switcher="" style={{ position: 'relative', display: 'inline-flex', alignItems: 'center', gap: 8, fontSize: 13 }}>
      <span style={{ fontWeight: 600, color: C.text, maxWidth: 260, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{current.name}</span>
      <button type="button" aria-haspopup="menu" aria-expanded={open} onClick={(e) => { setAt(menuAt(e.currentTarget.getBoundingClientRect(), window.innerWidth)); setOpen(!open) }}
        style={{ font: 'inherit', fontSize: 12, color: C.sub, background: 'none', border: `1px solid ${C.border}`, borderRadius: 999, padding: '1px 10px', cursor: 'pointer' }}>切换案件 ▾</button>
      {open ? (
        <div role="menu" aria-label="切换案件" style={{ position: 'fixed', top: at?.top ?? 0, left: at?.left ?? 0, width: MENU_WIDTH, zIndex: 1000, background: 'var(--dsw-alias-bg-layer-1, Canvas)', border: `1px solid ${C.border}`, borderRadius: 10, boxShadow: '0 6px 24px rgba(0,0,0,0.12)', padding: '4px 0' }}>
          {switchTargets(cases, current).map((c) => (
            <button key={c.case_id} type="button" role="menuitem" style={item} onClick={() => go(c)} title={c.root}>
              {c.name}
              {c.exists === false ? <span style={{ color: C.faint }}>（不在）</span> : null}
            </button>
          ))}
          <div style={{ borderTop: `1px solid ${C.border}`, margin: '4px 0' }} />
          <button type="button" role="menuitem" style={item} onClick={() => { setOpen(false); getNav().goHome() }}>首页…</button>
          <div style={{ padding: '6px 12px 4px', fontSize: 11, color: C.faint }}>{RENAME_HINT}</div>
        </div>
      ) : null}
    </span>
  )
}
