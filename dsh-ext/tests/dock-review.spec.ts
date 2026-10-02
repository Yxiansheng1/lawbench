// 改编自契约 1.2 第二轮复核员的实验 rv-t13r2.spec.ts（R、X、Y 系列，两种挂载模式），收为回归用例（T13 INPUT_CHANGED 返修）：
// Y6a–c（P3-B）、Y7 与 Y8（P3-C）由"打印判定"改为断言；模拟服务的 run 按返修 P3-C ① 在一轮顺利开始时清掉旧记录；去掉打印。
// @vitest-environment jsdom
// 复核员自写（T13 契约 1.2 界面侧第二轮复核）：照线 B（origin/line-B service/lawbench/case/task.py）1.2 语义的模拟服务，
// 加上 input_refs 的 sha256 快照语义（read_input 与快照不符报 INPUT_CHANGED），Host 侧用真实的 shared/turn-notices.ts。
// 跑真实 dock.tsx，假时钟；默认不重挂（插槽同一实例换 sessionId）。每条打印 ROW|名|发时看到|实际|判定。
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { ComposerDock, forgetDockSyncs, INPUT_CHANGED_TEXT, TURN_ENDED } from '../ui/dock.tsx'
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
    this.notices.clear(session) // Agent 插件：取任务、取上下文都成功时清掉旧记录（返修 P3-C ①）
    return s && s.entry ? s.entry : '自由对话'
  }
}

let svc: LineB
let root: Root | undefined
let container: HTMLDivElement
const api = (): LawbenchApi => ({
  taskCreate: async (r: any) => { if (svc.writeDelay) await new Promise((res) => setTimeout(res, svc.writeDelay)); return svc.create(r) },
  taskCurrent: async (r: any) => { if (svc.readDelay) await new Promise((res) => setTimeout(res, svc.readDelay)); return svc.current(r.session_id) },
  turnNotice: async (r: any) => ({ ok: true, value: { code: svc.notices.take(r.session_id) } }),
  getCapsules: async () => ({ ok: true, value: CAPSULES }),
  caseRecent: async () => ({ ok: true, value: { cases: [CASE] } }),
  listSkills: async () => ({ ok: true, value: { skills: SKILLS } }),
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

const rows: string[] = []
function row(name: string, actual: string) {
  const st = seen.status
  const claimed = st.startsWith('下一条消息按「') ? Object.keys(NAME).find((k) => st.includes(NAME[k]!)) ?? '?' : st === '自由对话' ? '自由对话' : null
  const verdict = claimed === null ? `状态行非就绪（${st}）` : claimed === actual ? '一致' : '不一致'
  const line = `ROW|${name}|下拉=${seen.shown} 状态=${st}|实际=${actual}|${verdict}`
  rows.push(line)
  return verdict
}

beforeEach(async () => {
  vi.useFakeTimers({ now: new Date('2026-09-30T12:00:00Z') })
  forgetDockSyncs()
  svc = new LineB()
  setApi(api())
  app.set((s) => ({ ...s, cases: [CASE], selections: {}, intents: {}, inputChanged: {}, staleServer: {} }))
  container = document.createElement('div'); document.body.appendChild(container)
  await mount('S1')
})
afterEach(async () => { await unmount(); container.remove(); vi.useRealTimers() })

for (const remount of [false, true]) {
  const M = remount ? '重挂' : '不重挂'
  describe(`复核员 X 系列（${M}）`, () => {
    beforeEach(async () => { if (remount) { await unmount(); await mount('S1', true) } })
    const go = (s: string) => mount(s, remount)
    it('R1 选 A 发两条', async () => { await pick(A); await flush(600); row(`${M}|R1-1`, await send('S1')); expect(row(`${M}|R1-2`, await send('S1'))).toBe('一致') })
    it('R2 选 A 改 B 发两条', async () => { await pick(A); await flush(600); await pick(B); await flush(600); expect(row(`${M}|R2`, await send('S1'))).toBe('一致') })
    it('R3 连改三次 100ms 后发', async () => { await pick(A); await flush(600); await pick(B); await flush(200); await pick(A); await flush(200); await pick(B); await flush(100); expect(row(`${M}|R3-发时`, begin('S1'))).not.toBe('不一致'); await turnEnded('S1'); await flush(600); expect(row(`${M}|R3-写完`, await send('S1'))).toBe('一致') })
    it('R4 A 切回自由对话', async () => { await pick(A); await flush(600); await pick(''); await flush(600); expect(row(`${M}|R4`, await send('S1'))).toBe('一致') })
    it('R5-R7 重启', async () => { await pick(A); await flush(600); await restart('S1'); expect(row(`${M}|R5`, await send('S1'))).toBe('一致'); await pick(B); await flush(600); expect(row(`${M}|R6`, await send('S1'))).toBe('一致') })
    it('R8 不可用时改 B、恢复后重试', async () => { await pick(A); await flush(600); svc.mode = 'unavailable'; await pick(B); await flush(600); expect(row(`${M}|R8-发`, await send('S1'))).not.toBe('不一致'); svc.mode = 'ok'; await click('重试'); await flush(600); expect(row(`${M}|R8-重试后`, await send('S1'))).toBe('一致') })
    it('R9 切 S2 再切回', async () => { await pick(A); await flush(600); await go('S2'); expect(row(`${M}|R9-S2`, begin('S2'))).not.toBe('不一致'); await flush(); expect(row(`${M}|R9-S2读回后`, begin('S2'))).toBe('一致'); await go('S1'); expect(row(`${M}|R9-回S1`, await send('S1'))).toBe('一致') })
    it('R10 同案两会话交替', async () => { await pick(A); await flush(600); await go('S2'); await pick(B); await flush(600); await go('S1'); expect(row(`${M}|R10-S1`, await send('S1'))).toBe('一致'); await go('S2'); expect(row(`${M}|R10-S2`, await send('S2'))).toBe('一致') })
    it('R11 改 B 后 200ms 发', async () => { await pick(A); await flush(600); await pick(B); await flush(200); expect(row(`${M}|R11-发时`, begin('S1'))).not.toBe('不一致'); await turnEnded('S1'); await flush(600); expect(row(`${M}|R11-之后`, await send('S1'))).toBe('一致') })
    it('X1 超时但已建 B，直接发', async () => { await pick(A); await flush(600); svc.mode = 'timeout-after-write'; await pick(B); await flush(600); svc.mode = 'ok'; expect(row(`${M}|X1`, await send('S1'))).not.toBe('不一致') })
    it('X1b 超时但已建 B，改回 A', async () => { await pick(A); await flush(600); svc.mode = 'timeout-after-write'; await pick(B); await flush(600); svc.mode = 'ok'; await pick(A); await flush(600); expect(row(`${M}|X1b`, await send('S1'))).toBe('一致') })
    it('X2 不合契约但已建 B，改回 A', async () => { await pick(A); await flush(600); svc.mode = 'bad-after-write'; await pick(B); await flush(600); svc.mode = 'ok'; await pick(A); await flush(600); expect(row(`${M}|X2`, await send('S1'))).toBe('一致') })
    it('X3 改过选择、别处改 B、一轮结束读失败', async () => { await pick(A); await flush(600); svc.create({ case_id: CASE.case_id, session_id: 'S1', entry: B, skill: B, inputs: [], params: null }); svc.failRead = true; row(`${M}|X3-别处改B后发`, begin('S1')); await turnEnded('S1'); expect(row(`${M}|X3-读失败后发`, begin('S1'))).not.toBe('不一致') })
    it('X4 切 S2 读回 2 秒，读回前发', async () => { await pick(A); await flush(600); svc.readDelay = 2000; await go('S2'); expect(row(`${M}|X4-读回前`, begin('S2'))).not.toBe('不一致'); await flush(2100); expect(row(`${M}|X4-读回后`, begin('S2'))).toBe('一致') })
    it('X5 S1 改 B 未到防抖切 S2', async () => { await pick(A); await flush(600); await pick(B); await flush(100); await go('S2'); await flush(1000); expect(svc.cur('S2')).toBeUndefined(); expect(row(`${M}|X5-S2`, begin('S2'))).toBe('一致'); await go('S1'); await flush(600); expect(row(`${M}|X5-回S1`, await send('S1'))).toBe('一致'); expect(svc.cur('S1')?.entry).toBe(B) })
    it('X6 S1 写 B 失败后切 S2', async () => { await pick(A); await flush(600); svc.mode = 'unavailable'; await pick(B); await flush(600); svc.mode = 'ok'; await go('S2'); await flush(1000); expect(svc.cur('S2')).toBeUndefined(); expect(row(`${M}|X6-S2`, begin('S2'))).toBe('一致') })
    it('X7 另一窗口改成 B（已知限制）', async () => { await pick(A); await flush(600); svc.create({ case_id: CASE.case_id, session_id: 'S1', entry: B, skill: B, inputs: [], params: null }); row(`${M}|X7-本窗口发`, begin('S1')); await turnEnded('S1'); expect(row(`${M}|X7-一轮后`, begin('S1'))).toBe('一致') })
    it('X8 改 B 未到防抖就重载', async () => { await pick(A); await flush(600); await pick(B); await flush(100); await restart('S1'); await flush(600); expect(row(`${M}|X8`, await send('S1'))).toBe('一致') })
    it('X9 写 B 在途时重载（已知限制）', async () => { await pick(A); await flush(600); svc.writeDelay = 1000; await pick(B); await flush(700); await restart('S1'); row(`${M}|X9-刚重载`, begin('S1')); await flush(1000); row(`${M}|X9-落地后一轮前`, begin('S1')); await turnEnded('S1'); expect(row(`${M}|X9-一轮后`, begin('S1'))).toBe('一致') })

    // —— 复核员新增 ——
    it('Y1 换会话读回慢于律师改动：S2 读回前改 B', async () => {
      await pick(A); await flush(600); svc.readDelay = 2000
      await go('S2'); await flush(100); await pick(B); await flush(600)
      expect(row(`${M}|Y1-读回前已改B`, begin('S2'))).not.toBe('不一致')
      await flush(2500)
      expect(row(`${M}|Y1-读回后`, await send('S2'))).toBe('一致')
      expect(svc.cur('S1')?.entry).toBe(A)
    })
    it('Y2 同案两会话交替快改（都在防抖内切走）', async () => {
      await pick(A); await flush(200); await go('S2'); await pick(B); await flush(200); await go('S1'); await flush(50)
      expect(row(`${M}|Y2-回S1立即发`, begin('S1'))).not.toBe('不一致')
      await flush(700)
      expect(row(`${M}|Y2-S1写后`, await send('S1'))).toBe('一致')
      expect(svc.cur('S2')).toBeUndefined() // S2 的 B 还没写（律师没回 S2）
      await go('S2'); expect(row(`${M}|Y2-回S2立即发`, begin('S2'))).not.toBe('不一致')
      await flush(700); expect(row(`${M}|Y2-S2写后`, await send('S2'))).toBe('一致')
    })
    it('Y3 写入在途时换会话再换回', async () => {
      await pick(A); await flush(600); svc.writeDelay = 1000; await pick(B); await flush(600)
      await go('S2'); await flush(100); await go('S1')
      expect(row(`${M}|Y3-回S1写未落地`, begin('S1'))).not.toBe('不一致')
      await flush(2000)
      expect(row(`${M}|Y3-落地后`, await send('S1'))).toBe('一致')
    })
    it('Y3b 写入在途时切走、失败时不在、回来', async () => {
      await pick(A); await flush(600); svc.writeDelay = 1000; svc.mode = 'unavailable'; await pick(B); await flush(600)
      await go('S2'); await flush(1500); await go('S1')
      expect(row(`${M}|Y3b-回S1`, begin('S1'))).not.toBe('不一致')
      await flush(2000)
      expect(row(`${M}|Y3b-再写也失败`, begin('S1'))).not.toBe('不一致')
      svc.mode = 'ok'; await click('重试'); await flush(2000)
      expect(row(`${M}|Y3b-恢复重试`, await send('S1'))).toBe('一致')
    })
    it('Y4 首页胶囊意向：S1 读回慢，读回前切到 S2', async () => {
      await unmount(); forgetDockSyncs(); app.set((s) => ({ ...s, selections: {}, intents: {}, inputChanged: {}, staleServer: {} }))
      setIntent(CASE.case_id, { capsuleId: A, skill: A, params: null, inputs: [] })
      svc.readDelay = 2000; await go('S1'); await flush(500); svc.readDelay = 0; await go('S2'); await flush(700)
      row(`${M}|Y4-S2发`, await send('S2'))
      await go('S1'); await flush(2500); expect(row(`${M}|Y4-回S1`, await send('S1'))).toBe('一致')
      expect(app.get().intents[CASE.case_id]).toBeUndefined()
    })
    it('Y4b 首页胶囊意向：S1 取走后切 S2，不带入 S2', async () => {
      await unmount(); forgetDockSyncs(); app.set((s) => ({ ...s, selections: {}, intents: {}, inputChanged: {}, staleServer: {} }))
      setIntent(CASE.case_id, { capsuleId: A, skill: A, params: null, inputs: [] })
      await go('S1'); await flush(700); await go('S2'); await flush(700)
      expect(svc.cur('S2')).toBeUndefined(); expect(svc.cur('S1')?.entry).toBe(A)
      expect(row(`${M}|Y4b-S2`, await send('S2'))).toBe('一致')
    })
    it('Y5 写失败 → 改回 → 再改 → 服务恢复（不可用）', async () => {
      await pick(A); await flush(600); svc.mode = 'unavailable'
      await pick(B); await flush(600); expect(row(`${M}|Y5-B失败`, begin('S1'))).not.toBe('不一致')
      await pick(A); await flush(600); expect(row(`${M}|Y5-改回A`, begin('S1'))).not.toBe('不一致')
      await pick(B); await flush(600); expect(row(`${M}|Y5-再改B`, begin('S1'))).not.toBe('不一致')
      svc.mode = 'ok'; await turnEnded('S1'); expect(row(`${M}|Y5-恢复未重试`, begin('S1'))).not.toBe('不一致')
      await click('重试'); await flush(600); expect(row(`${M}|Y5-重试后`, await send('S1'))).toBe('一致')
    })
    it('Y5b 写失败 → 改回 → 再改 → 服务恢复（超时但已建单）', async () => {
      await pick(A); await flush(600); svc.mode = 'timeout-after-write'
      await pick(B); await flush(600); await pick(A); await flush(600); await pick(B); await flush(600)
      svc.mode = 'ok'; expect(row(`${M}|Y5b-恢复未重试`, await send('S1'))).not.toBe('不一致')
      await pick(A); await flush(600); expect(row(`${M}|Y5b-再改A`, await send('S1'))).toBe('一致')
    })
    it('Y6a INPUT_CHANGED 后 0.5 秒内切走又切回同一胶囊', async () => {
      await pick(A); await act(async () => { setIntent(CASE.case_id, { inputs: [X] }) }); await flush(700)
      expect(svc.cur('S1')).toMatchObject({ entry: A, inputs: [X] })
      svc.versions[X] = 1
      row(`${M}|Y6a-材料变后发`, await send('S1')); const st1 = status()
      const n = svc.creates.length
      await pick(B); await flush(200); await pick(A); await flush(700)
      expect(row(`${M}|Y6a-重选后发`, await send('S1'))).toBe('一致')
    })
    it('Y6b INPUT_CHANGED 后点"恢复默认"（参数本来就是默认）', async () => {
      await pick(A); await act(async () => { setIntent(CASE.case_id, { inputs: [X] }) }); await flush(700)
      svc.versions[X] = 1
      row(`${M}|Y6b-材料变后发`, await send('S1'))
      const n = svc.creates.length
      await click('参数'); await click('恢复默认'); await flush(700)
      expect(row(`${M}|Y6b-恢复默认后发`, await send('S1'))).toBe('一致')
    })
    it('Y6c INPUT_CHANGED 后在成果区对 X 取消选用再选用（0.5 秒内）', async () => {
      await pick(A); await act(async () => { setIntent(CASE.case_id, { inputs: [X] }) }); await flush(700)
      svc.versions[X] = 1
      row(`${M}|Y6c-材料变后发`, await send('S1'))
      const n = svc.creates.length
      await act(async () => { setIntent(CASE.case_id, { inputs: [] }) }); await flush(200)
      await act(async () => { setIntent(CASE.case_id, { inputs: [X] }) }); await flush(700)
      expect(row(`${M}|Y6c-重选后发`, await send('S1'))).toBe('一致')
    })
    it('Y6d INPUT_CHANGED 后改选 B（真写一次）', async () => {
      await pick(A); await act(async () => { setIntent(CASE.case_id, { inputs: [X] }) }); await flush(700)
      svc.versions[X] = 1
      row(`${M}|Y6d-材料变后发`, await send('S1'))
      await pick(B); await flush(700)
      expect(row(`${M}|Y6d-改B后发`, await send('S1'))).toBe('一致')
    })
    it('Y8 被拦下后切到 S2（S2 也被拦下）再回 S1；或插槽重挂：S1 的提示是否还在', async () => {
      await pick(A); await act(async () => { setIntent(CASE.case_id, { inputs: [X] }) }); await flush(700)
      await go('S2'); await pick(A); await act(async () => { setIntent(CASE.case_id, { inputs: [X] }) }); await flush(700)
      await go('S1'); await flush(100)
      svc.versions[X] = 1
      await send('S1'); const s1 = status()
      await go('S2'); await flush(100); const s2before = status(); await send('S2'); const s2 = status()
      await go('S1'); await flush(100)
      expect(status()).toBe('输入材料已变化，请重新选择') // S1 的提示还在（按会话存在 store 里）
      expect(row(`${M}|Y8-回S1发`, await send('S1'))).not.toBe('不一致')
    })
    it('Y7 被拦下的一轮发生在别的会话显示时：回来后的提示与之后成功一轮的误报', async () => {
      await pick(A); await act(async () => { setIntent(CASE.case_id, { inputs: [X] }) }); await flush(700)
      await go('S2'); await flush(100)
      svc.versions[X] = 1
      const r = svc.run('S1'); await turnEnded('S1') // S1 在后台被拦下（显示的是 S2）
      await go('S1'); await flush(100)
      expect(status()).toBe(INPUT_CHANGED_TEXT) // 第三轮复核 NOTE Y7：直接断言显示的就是提示
      seen = { shown: shown(), status: status() }; expect(row(`${M}|Y7-回S1时(后台那轮${r})`, svc.run('S1'))).not.toBe('不一致')
      svc.notices.take('S1') // 上一行模拟的 run 又记了一次，清掉，只留后台那轮的
      svc.notices.note('S1', 'INPUT_CHANGED')
      await click('参数'); const think = [...container.querySelectorAll('select')].find((s) => [...s.options].some((o) => o.value === '高'))!
      const set = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value')!.set!
      await act(async () => { set.call(think, '高'); think.dispatchEvent(new Event('change', { bubbles: true })) }); await flush(700)
      const ok = await send('S1')
      expect(ok).toBe(A)
      expect(status()).not.toContain('输入材料已变化') // 成功一轮之后不误报
    })
  })
}

