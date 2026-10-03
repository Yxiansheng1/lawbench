// 改编自契约 1.2 第二轮复核员的实验 rv-t13r2-z.spec.ts（Z1、Z2：Skill 列表比 task/current 慢回来），收为回归用例（N48，复核 P2-A）；去掉打印，Z2 加断言。
// @vitest-environment jsdom
// 复核员自写（T13 契约 1.2 界面侧第二轮复核）：照线 B（origin/line-B service/lawbench/case/task.py）1.2 语义的模拟服务，
// 加上 input_refs 的 sha256 快照语义（read_input 与快照不符报 INPUT_CHANGED），Host 侧用真实的 shared/turn-notices.ts。
// 跑真实 dock.tsx，假时钟；默认不重挂（插槽同一实例换 sessionId）。每条打印 ROW|名|发时看到|实际|判定。
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { ComposerDock, forgetDockSyncs, TURN_ENDED } from '../ui/dock.tsx'
import { app, setApi, setIntent, type LawbenchApi, type SkillInfo } from '../ui/state.ts'
import { TurnNotices } from '../shared/turn-notices.ts'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
const fixture = (name: string) => JSON.parse(readFileSync(join(__dirname, '..', 'ui', 'fixtures', name), 'utf8'))
const CAPSULES = fixture('capsules.json').value
const CASE = fixture('case_recent.json').value.cases[0] as { case_id: string; name: string; root: string; exists: boolean }
const A = 'contract-review', B = 'contract-draft'
const NAME: Record<string, string> = { [A]: '合同审查', [B]: '合同起草' }
const X = '成果/起诉状_v1.md'
const skill = (name: string): SkillInfo => ({ name, title: name, description: '', mode: 'agent', kind: 'draft', params: { thinking: '中', window: '64K', max_tokens: 16384 }, inputs: [], questions: [] })
const SKILLS = ['contract-review', 'contract-draft', 'pre-issue-check', 'doc-revise', 'litigation-docs', 'case-wiki-build', 'legal-workflow'].map(skill)

type Task = { task_id: string; case_id: string; session_id: string; entry: string | null; skill: string | null; inputs: string[]; stamp: number[]; params: unknown; created_at: string; seq: number }
class LineB {
  pending: Task[] = []
  n = 0
  versions: Record<string, number> = {}
  notices = new TurnNotices()
  mode: 'ok' | 'unavailable' | 'timeout-after-write' | 'bad-after-write' = 'ok'
  failRead = false
  readDelay = 0
  writeDelay = 0
  creates: string[] = []
  create(d: { case_id: string; session_id: string; entry: string | null; skill: string | null; inputs: string[]; params: unknown }) {
    if (this.mode === 'unavailable') return { ok: false as const, error: { code: 'SERVICE_UNAVAILABLE', message: '工作台服务未启动，请稍后重试' } }
    this.creates.push(`${d.session_id}:${d.entry ?? 'free'}${d.inputs.length ? '+' + d.inputs.length : ''}`)
    this.pending = this.pending.filter((t) => !(t.session_id === d.session_id && t.case_id === d.case_id)) // _void_pending
    const t: Task = { task_id: `T-${++this.n}`, ...d, stamp: d.inputs.map((p) => this.versions[p] ?? 0), created_at: new Date(Date.now()).toISOString().slice(0, 19), seq: this.n }
    this.pending.push(t)
    if (this.mode === 'timeout-after-write') return { ok: false as const, error: { code: 'TIMEOUT', message: '工作台服务响应超时，请稍后重试' } }
    if (this.mode === 'bad-after-write') return { ok: false as const, error: { code: 'BAD_RESPONSE', message: '工作台服务返回的内容不对，请联系技术支持' } }
    return { ok: true as const, value: { task_id: t.task_id } }
  }
  cur(session: string) { return this.pending.filter((t) => t.session_id === session).sort((a, b) => a.seq - b.seq).pop() }
  current(session: string) {
    if (this.failRead) return { ok: false as const, error: { code: 'SERVICE_UNAVAILABLE', message: '工作台服务未启动，请稍后重试' } }
    const b = this.cur(session)
    return { ok: true as const, value: { selection: b ? { task_id: b.task_id, entry: b.entry, skill: b.skill, inputs: b.inputs, params: b.params, updated_at: b.created_at + '+08:00' } : null } }
  }
  /** /core/task/begin + /core/context：选用的输入被改过则整轮被拦（Agent 插件 noteBlocked → Host TurnNotices）。 */
  run(session: string): string {
    const s = this.cur(session)
    if (s && s.inputs.some((p, i) => (this.versions[p] ?? 0) !== s.stamp[i])) { this.notices.note(session, 'INPUT_CHANGED'); return '被拦下' }
    return s && s.entry ? s.entry : '自由对话'
  }
}

let skillsDelay = 300
let svc: LineB
let root: Root | undefined
let container: HTMLDivElement
const api = (): LawbenchApi => ({
  taskCreate: async (r: any) => { if (svc.writeDelay) await new Promise((res) => setTimeout(res, svc.writeDelay)); return svc.create(r) },
  taskCurrent: async (r: any) => { if (svc.readDelay) await new Promise((res) => setTimeout(res, svc.readDelay)); return svc.current(r.session_id) },
  turnNotice: async (r: any) => ({ ok: true, value: { code: svc.notices.take(r.session_id) } }),
  getCapsules: async () => ({ ok: true, value: CAPSULES }),
  caseRecent: async () => ({ ok: true, value: { cases: [CASE] } }),
  listSkills: async () => { await new Promise((res) => setTimeout(res, skillsDelay)); return { ok: true, value: { skills: SKILLS } } },
}) as unknown as LawbenchApi

async function flush(ms = 0) { await act(async () => { await vi.advanceTimersByTimeAsync(ms) }); await act(async () => { await Promise.resolve() }) }
async function mount(sessionId: string, remount = false) {
  if (!root) root = createRoot(container)
  const useSessions = <T,>(select: (s: { byId: Record<string, { cwd?: string }> }) => T): T => select({ byId: { [sessionId]: { cwd: CASE.root } } })
  await act(async () => { root!.render(createElement(ComposerDock, { key: remount ? sessionId : 'dock', sessionId, useSessions })) })
  await flush()
}
async function unmount() { await act(async () => { root?.unmount() }); root = undefined }
async function restart(sessionId: string) { await unmount(); forgetDockSyncs(); app.set((s) => ({ ...s, selections: {}, intents: {}, inputChanged: {}, staleServer: {} })); await mount(sessionId) }
const capSel = () => container.querySelector('select[aria-label="胶囊"]') as HTMLSelectElement
const status = () => container.querySelector('[role=status]')?.textContent ?? ''
const shown = () => (capSel().value || '自由对话') + (container.textContent?.includes('选用：') ? '+X' : '')
async function pick(id: string) { const set = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value')!.set!; await act(async () => { set.call(capSel(), id); capSel().dispatchEvent(new Event('change', { bubbles: true })) }) }
const button = (text: string) => [...container.querySelectorAll('button')].find((x) => x.textContent === text)
async function click(text: string) { const b = button(text); if (!b) throw new Error('no button ' + text); await act(async () => { b.click() }) }
async function turnEnded(s: string) { await act(async () => { window.dispatchEvent(new CustomEvent(TURN_ENDED, { detail: s })) }); await flush() }
let seen = { shown: '', status: '' }
const begin = (s: string) => { seen = { shown: shown(), status: status() }; return svc.run(s) }
async function send(s: string) { const r = begin(s); await turnEnded(s); return r }


beforeEach(async () => {
  vi.useFakeTimers({ now: new Date('2026-09-30T12:00:00Z') })
  forgetDockSyncs()
  svc = new LineB()
  setApi(api())
  app.set((s) => ({ ...s, cases: [CASE], selections: {}, intents: {}, inputChanged: {}, staleServer: {} }))
  container = document.createElement('div'); document.body.appendChild(container)
})
afterEach(async () => { await unmount(); container.remove(); vi.useRealTimers() })
const paramsPanel = () => [...container.querySelectorAll('select')].filter((s) => s.getAttribute('aria-label') === null).map((s) => s.value).join('/')

describe('Z：新挂上的输入区、Skill 列表还没读回时写入', () => {
  it('Z1 首页点胶囊进案件（软件刚启动、Skill 列表读得比 task/current 慢）：写给服务的参数', async () => {
    setIntent(CASE.case_id, { capsuleId: A, skill: A, params: null, inputs: [] })
    await mount('S1'); for (let i = 0; i < 20; i++) await flush(50)
    await click('参数')
    expect(svc.cur('S1')?.params).toEqual(SKILLS[0]!.params)
  })
  it('Z2 S1 改 B 未写成就离开（插槽卸下），回来重挂：写给服务的参数；写失败时状态行', async () => {
    skillsDelay = 0
    await mount('S1'); await flush(100)
    await pick(A); await flush(600)
    await pick(B); await flush(100)
    await unmount(); svc.mode = 'unavailable'
    await mount('S1'); for (let i = 0; i < 20; i++) await flush(50)
    expect(status()).toBe('任务单没有写成，请重试') // 写失败要显示错误（执行令 1751 必修 2 的说法）
    expect(!!button('重试')).toBe(true) // 并有"重试"
    svc.mode = 'ok'; await unmount(); await mount('S1'); for (let i = 0; i < 20; i++) await flush(50)
    await click('参数')
    expect(svc.cur('S1')?.params).toEqual(SKILLS[1]!.params)
  })
})
