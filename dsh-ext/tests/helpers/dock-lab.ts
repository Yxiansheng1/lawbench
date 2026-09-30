// 输入区实验夹具：取自契约 1.2 第三轮复核员 rv-A19 的 rvh.ts（照 dock-review.spec.ts 的模拟服务），收入仓库供 dock-a19.spec.ts 用（T13 第四轮返修）。
// 只改了引用路径。
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { ComposerDock, forgetDockSyncs, TURN_ENDED } from '../../ui/dock.tsx'
import { app, setApi, type LawbenchApi, type SkillInfo } from '../../ui/state.ts'
import { TurnNotices } from '../../shared/turn-notices.ts'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
const fixture = (name: string) => JSON.parse(readFileSync(join(__dirname, '..', '..', 'ui', 'fixtures', name), 'utf8'))
export const CAPSULES = fixture('capsules.json').value
export const CASE = fixture('case_recent.json').value.cases[0] as { case_id: string; name: string; root: string; exists: boolean }
export const A = 'contract-review', B = 'contract-draft'
export const NAME: Record<string, string> = { [A]: '合同审查', [B]: '合同起草' }
export const X = '成果/起诉状_v1.md'
const skill = (name: string, params = { thinking: '中' as const, window: '64K' as const, max_tokens: 16384 }): SkillInfo => ({ name, title: name, description: '', mode: 'agent', kind: 'draft', params, inputs: [], questions: [] })
export const SKILLS = ['contract-review', 'contract-draft', 'pre-issue-check', 'doc-revise', 'litigation-docs', 'case-wiki-build', 'legal-workflow'].map((n) => n === B ? skill(n, { thinking: '高', window: '32K', max_tokens: 8192 } as never) : skill(n))

type Task = { task_id: string; session_id: string; entry: string | null; skill: string | null; inputs: string[]; stamp: number[]; params: any; seq: number }
export class LineB {
  pending: Task[] = []
  n = 0
  versions: Record<string, number> = {}
  notices = new TurnNotices()
  mode: 'ok' | 'unavailable' = 'ok'
  readDelay = 0
  writeDelay = 0
  noticeDelay = 0
  skillsDelay = 0
  creates: string[] = []
  create(d: any) {
    if (this.mode === 'unavailable') return { ok: false as const, error: { code: 'SERVICE_UNAVAILABLE', message: '工作台服务未启动，请稍后重试' } }
    this.creates.push(`${d.session_id}:${d.entry ?? 'free'}${d.inputs.length ? '+' + d.inputs.length : ''}:${JSON.stringify(d.params)}`)
    this.pending = this.pending.filter((t) => t.session_id !== d.session_id)
    const t: Task = { task_id: `T-${++this.n}`, ...d, stamp: d.inputs.map((p: string) => this.versions[p] ?? 0), seq: this.n }
    this.pending.push(t)
    return { ok: true as const, value: { task_id: t.task_id } }
  }
  cur(session: string) { return this.pending.filter((t) => t.session_id === session).sort((a, b) => a.seq - b.seq).pop() }
  current(session: string) {
    const b = this.cur(session)
    return { ok: true as const, value: { selection: b ? { task_id: b.task_id, entry: b.entry, skill: b.skill, inputs: b.inputs, params: b.params, updated_at: '2026-09-30T12:00:00+08:00' } : null } }
  }
  run(session: string): string {
    const s = this.cur(session)
    if (s && s.inputs.some((p, i) => (this.versions[p] ?? 0) !== s.stamp[i])) { this.notices.note(session, 'INPUT_CHANGED'); return '被拦下' }
    this.notices.clear(session)
    return s && s.entry ? s.entry : '自由对话'
  }
}

export const h = { svc: undefined as unknown as LineB, root: undefined as Root | undefined, container: undefined as unknown as HTMLDivElement }
const sleep = (ms: number) => (ms ? new Promise((res) => setTimeout(res, ms)) : Promise.resolve())
export const api = (): LawbenchApi => ({
  taskCreate: async (r: any) => { await sleep(h.svc.writeDelay); return h.svc.create(r) },
  taskCurrent: async (r: any) => { await sleep(h.svc.readDelay); return h.svc.current(r.session_id) },
  turnNotice: async (r: any) => { await sleep(h.svc.noticeDelay); return { ok: true, value: { code: h.svc.notices.take(r.session_id) } } },
  getCapsules: async () => ({ ok: true, value: CAPSULES }),
  caseRecent: async () => ({ ok: true, value: { cases: [CASE] } }),
  listSkills: async () => { await sleep(h.svc.skillsDelay); return { ok: true, value: { skills: SKILLS } } },
}) as unknown as LawbenchApi

export async function flush(ms = 0) { await act(async () => { await vi.advanceTimersByTimeAsync(ms) }); await act(async () => { await Promise.resolve() }) }
export async function mount(sessionId: string, remount = false) {
  if (!h.root) h.root = createRoot(h.container)
  const useSessions = <T,>(select: (s: { byId: Record<string, { cwd?: string }> }) => T): T => select({ byId: { [sessionId]: { cwd: CASE.root } } })
  await act(async () => { h.root!.render(createElement(ComposerDock, { key: remount ? sessionId : 'dock', sessionId, useSessions })) })
  await flush()
}
export async function unmount() { await act(async () => { h.root?.unmount() }); h.root = undefined }
export const capSel = () => h.container.querySelector('select[aria-label="胶囊"]') as HTMLSelectElement
export const status = () => h.container.querySelector('[role=status]')?.textContent ?? ''
export const shown = () => (capSel().value || '自由对话') + (h.container.textContent?.includes('选用：') ? '+X' : '')
const setVal = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value')!.set!
export async function pick(id: string) { await act(async () => { setVal.call(capSel(), id); capSel().dispatchEvent(new Event('change', { bubbles: true })) }) }
export const paramSelects = () => [...h.container.querySelectorAll('select')].filter((s) => s.getAttribute('aria-label') === null)
export const paramsPanel = () => { const [t, w] = paramSelects(); const n = h.container.querySelector('input[type=number]') as HTMLInputElement | null; return t ? { thinking: t.value, window: w!.value, max_tokens: Number(n?.value) } : null }
export async function setParamSel(idx: number, v: string) { const s = paramSelects()[idx]!; await act(async () => { setVal.call(s, v); s.dispatchEvent(new Event('change', { bubbles: true })) }) }
export const button = (text: string) => [...h.container.querySelectorAll('button')].find((x) => x.textContent === text)
export async function click(text: string) { const b = button(text); if (!b) throw new Error('no button ' + text); await act(async () => { b.click() }) }
export async function turnEnded(s: string) { await act(async () => { window.dispatchEvent(new CustomEvent(TURN_ENDED, { detail: s })) }); await flush() }
export let seen = { shown: '', status: '' }
export const begin = (s: string) => { seen = { shown: shown(), status: status() }; return h.svc.run(s) }
export async function send(s: string) { const r = begin(s); await turnEnded(s); return r }
export function verdict(actual: string) {
  const st = seen.status
  const claimed = st.startsWith('下一条消息按「') ? Object.keys(NAME).find((k) => st.includes(NAME[k]!)) ?? '?' : st === '自由对话' ? '自由对话' : null
  return claimed === null ? `非就绪:${st}` : claimed === actual ? '一致' : `不一致:${st}→${actual}`
}
export async function setup() {
  vi.useFakeTimers({ now: new Date('2026-09-30T12:00:00Z') })
  forgetDockSyncs()
  h.svc = new LineB()
  setApi(api())
  app.set((s) => ({ ...s, cases: [CASE], selections: {}, intents: {}, inputChanged: {}, staleServer: {}, presets: {}, defaults: null }))
  h.container = document.createElement('div'); document.body.appendChild(h.container)
}
export async function teardown() { await unmount(); h.container.remove(); vi.useRealTimers() }
