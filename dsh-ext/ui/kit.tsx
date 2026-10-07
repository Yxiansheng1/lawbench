// 界面小部件与样式。颜色、圆角、字号一律取 DSH 的 --dsw-* 变量，跟随明暗主题；按钮、弹框用 DSH 共享组件库。
import { useCallback, useEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react'
import { Button } from '@deepseek-ai/dsh-client-ui-primitives'
import { errorText, START_FAILED } from './format.ts'

export const C = {
  text: 'var(--dsw-alias-label-primary)',
  sub: 'var(--dsw-alias-label-secondary)',
  faint: 'var(--dsw-alias-label-tertiary)',
  border: 'var(--dsw-alias-border-l2)',
  layer: 'var(--dsw-alias-bg-layer-1)',
  hover: 'var(--dsw-alias-interactive-bg-hover)',
  brand: 'var(--dsw-alias-brand-primary)',
  ok: 'var(--dsw-alias-state-success-primary)',
  warn: 'var(--dsw-alias-state-warn-primary)',
  err: 'var(--dsw-alias-state-error-primary)',
  info: 'var(--dsw-alias-state-business-primary)',
  rSm: 'var(--dsw-radius-sm, 6px)',
  rMd: 'var(--dsw-radius-md, 10px)',
  rLg: 'var(--dsw-radius-lg, 14px)',
}

/**
 * 原生下拉框展开后的选项列表（令 1609 第 1 条，用户："深色我点开设置选择思考等级就看不清楚"）：选项默认白底、却跟着下拉框用深色主题的浅色字，
 * 几乎看不见。给选项明确的底色和字色，跟 DSH 主题变量走（深浅两套都对）。行内样式管不到 <option>，只能加一条全局样式；只加一次。
 */
export const FIELD_STYLE = 'select option,select optgroup{background-color:var(--dsw-alias-bg-layer-1,Canvas);color:var(--dsw-alias-label-primary,CanvasText)}'
export function ensureFieldStyle(doc: Document = document): void {
  if (doc.getElementById('lb-field-style')) return
  const el = doc.createElement('style')
  el.id = 'lb-field-style'
  el.textContent = FIELD_STYLE
  doc.head.appendChild(el)
}

export const S: Record<string, CSSProperties> = {
  page: { height: '100%', overflow: 'auto', color: C.text, boxSizing: 'border-box' },
  pane: { padding: 12, color: C.text, fontSize: 13, display: 'flex', flexDirection: 'column', gap: 10, height: '100%', overflow: 'auto', boxSizing: 'border-box' },
  h2: { fontSize: 18, fontWeight: 600, margin: 0 },
  h3: { fontSize: 14, fontWeight: 600, margin: 0 },
  sub: { color: C.sub, fontSize: 12 },
  card: { border: `1px solid ${C.border}`, borderRadius: C.rMd, padding: 10, background: C.layer },
  row: { display: 'flex', alignItems: 'center', gap: 8 },
  between: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 },
  input: { font: 'inherit', color: C.text, background: 'transparent', border: `1px solid ${C.border}`, borderRadius: C.rSm, padding: '5px 8px', minWidth: 0 },
  list: { display: 'flex', flexDirection: 'column', gap: 6, margin: 0, padding: 0, listStyle: 'none' },
}

export { Button }

export function Section({ title, extra, children }: { title: ReactNode; extra?: ReactNode; children: ReactNode }) {
  return (
    <section style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div style={S.between}><h3 style={S.h3}>{title}</h3>{extra}</div>
      {children}
    </section>
  )
}

export function Badge({ tone, children }: { tone: 'ok' | 'warn' | 'err' | 'info' | 'faint'; children: ReactNode }) {
  const color = { ok: C.ok, warn: C.warn, err: C.err, info: C.info, faint: C.faint }[tone]
  return <span style={{ color, border: `1px solid ${color}`, borderRadius: 999, padding: '0 6px', fontSize: 11, whiteSpace: 'nowrap' }}>{children}</span>
}

export const Empty = ({ children }: { children: ReactNode }) => <div style={{ ...S.sub, padding: '8px 0' }}>{children}</div>

export function ErrorLine({ error }: { error?: { code: string; message: string } | null }) {
  if (!error) return null
  return <div role="alert" style={{ color: C.err, fontSize: 12 }}>{errorText(error)}</div>
}

export type Loaded<T> = { state: 'loading' } | { state: 'ok'; value: T } | { state: 'fail'; error: { code: string; message: string } }

/** 读一次数据；reload() 重读；pollMs 给定时定时重读（只读，不做写操作）。 */
export function useLoad<T>(load: () => Promise<{ ok: true; value: T } | { ok: false; error: { code: string; message: string } }>, deps: unknown[], pollMs?: number) {
  const [data, setData] = useState<Loaded<T>>({ state: 'loading' })
  const seq = useRef(0)
  const reload = useCallback(async () => {
    const my = ++seq.current
    const r = await load()
    if (my !== seq.current) return
    setData(r.ok ? { state: 'ok', value: r.value } : { state: 'fail', error: r.error })
  }, deps) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    void reload()
    if (!pollMs) return
    const t = setInterval(() => { void reload() }, pollMs)
    return () => clearInterval(t)
  }, [reload, pollMs])
  return [data, reload] as const
}

/** 首页启动时服务可能还没就绪：读失败每隔这么久自动重读，最多重读到 RETRY_FOR_MS（T14 第二次实跑派修 1）。 */
export const RETRY_EVERY_MS = 2000
export const RETRY_FOR_MS = 30_000
export const CONNECTING_TEXT = '正在连接本机服务…'

/**
 * 同 useLoad，但读失败时每 RETRY_EVERY_MS 自动重读（期间为 connecting），满 RETRY_FOR_MS 仍失败才给出 fail；
 * reload() 重新开始一轮（"重试"按钮用）。卸载或重新开始后，上一轮不再改状态。
 */
export function useRetryLoad<T>(load: () => Promise<{ ok: true; value: T } | { ok: false; error: { code: string; message: string } }>, deps: unknown[]) {
  const [data, setData] = useState<Loaded<T> | { state: 'connecting' }>({ state: 'loading' })
  const seq = useRef(0)
  const reload = useCallback(async () => {
    const my = ++seq.current
    for (let waited = 0; ; waited += RETRY_EVERY_MS) {
      const r = await load()
      if (my !== seq.current) return
      if (r.ok) { setData({ state: 'ok', value: r.value }); return }
      // Host 已说出服务起不来的原因（如端口被占，令 1556）：再读也一样，直接显示
      if (waited + RETRY_EVERY_MS > RETRY_FOR_MS || START_FAILED.test(r.error.message)) { setData({ state: 'fail', error: r.error }); return }
      setData({ state: 'connecting' })
      await new Promise((res) => setTimeout(res, RETRY_EVERY_MS))
      if (my !== seq.current) return
    }
  }, deps) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    void reload()
    return () => { seq.current++ }
  }, [reload])
  return [data, reload] as const
}

export function Loading<T>({ data, children }: { data: Loaded<T>; children: (v: T) => ReactNode }) {
  if (data.state === 'loading') return <Empty>读取中…</Empty>
  if (data.state === 'fail') return <ErrorLine error={data.error} />
  return <>{children(data.value)}</>
}

/** 外部导航能力（apply 里按 DSH 服务填入）：选目录、打开案件工作区、打开右侧栏标签、回首页。 */
export interface Nav {
  pickDirectory(): Promise<string | null>
  pathFor(file: File): string
  /** @returns 打开的工作区 id（侧栏移除旧位置时排除它，1612 复核 P1）。 */
  openCaseWorkspace(root: string): Promise<string | void>
  openTab(kind: string, params?: Record<string, string>): void
  goHome(): void
  refreshModels(): void
  /** 转到某个会话（成果页"在对话区查看"，T14 派修 2）。 */
  openSession(sessionId: string): void
  /** 从侧栏案件列表移除某个旧位置的登记（文件夹改名或搬走后在新位置重新打开，令 1515 第 3 条）；不删文件和会话。 */
  forgetCaseWorkspace?(root: string, except?: string): Promise<void>
}
let nav: Nav | undefined
export const setNav = (n: Nav | undefined): void => { nav = n }
export function getNav(): Nav {
  if (!nav) throw new Error('界面还没准备好')
  return nav
}
