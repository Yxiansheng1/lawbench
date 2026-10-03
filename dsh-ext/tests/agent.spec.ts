import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { BUDGET_STOPPED, DENY_BUDGET, DENY_NOT_ALLOWED, LegalAgent } from '../agent/index.ts'
import { CoreClient } from '../shared/core-client.ts'
import { startFake, type Fake } from './helpers/fake.ts'

let fake: Fake
let failing: Fake
let changed: Fake
const events: string[] = []
const log = (_l: string, e: string) => { events.push(e) }
const calls = join(require('node:os').tmpdir(), `lb-agent-calls-${process.pid}.jsonl`)

beforeAll(async () => {
  fake = await startFake(18807, ['--calls', calls])
  failing = await startFake(18808, ['--fail-begin'])
  changed = await startFake(18809, ['--fail-context', 'INPUT_CHANGED'])
})
afterAll(() => { fake.stop(); failing.stop(); changed.stop(); require('node:fs').rmSync(calls, { force: true }) })

const mk = (f = () => fake) => new LegalAgent(new CoreClient(() => ({ port: f().port, token: f().token }), log), log)
const agentObj = (id: string) => ({ id, session: { header: { cwd: 'D:\\案件\\张三诉李四' } } })
const enter = () => ({ kind: 'enter' as const, messages: [] })

describe('一轮完整对话（对假服务）', () => {
  it('step 1 注入 L0/L1；工具调用走 /core/tool 并过契约；进度与结束都发出', async () => {
    const a = mk()
    const d = await a.preStep(agentObj('s-1'), 1, enter())
    expect(d.kind).toBe('enter')
    const msgs = (d as { messages: Array<{ role: string; content: Array<{ text: string }>; source: { form: string } }> }).messages
    expect(msgs).toHaveLength(1)
    expect(msgs[0].role).toBe('user')
    expect(msgs[0].source.form).toBe('snapshot')
    expect(msgs[0].content[0].text).toContain('案件卡片（L0）')

    const cfg = a.request('s-1', { provider: 'lawfirm', model: 'qwen38-27b' })
    expect(cfg).toMatchObject({ provider: 'lawfirm', model: 'qwen38-27b', reasoningEffort: 'low', maxTokens: 16384 })

    expect(a.preTool('s-1', 'case_list_materials')).toEqual({ kind: 'allow' })
    const v = (await a.executeTool('s-1', 'case_list_materials', {})) as { materials: unknown[] }
    expect(Array.isArray(v.materials)).toBe(true)

    await a.onSessionEvent('s-1', { type: 'assistant/message', data: { message: { content: [{ type: 'text', text: '第一段' }] } } })
    await a.onSessionEvent('s-1', { type: 'turn/end', data: { reason: { kind: 'completed' } } })
    expect(a.tasks.has('s-1')).toBe(false)

    const recs = readFileSync(calls, 'utf8').trim().split('\n').map((l) => JSON.parse(l))
      .filter((r: { path: string }) => r.path.startsWith('/core/'))
    expect(recs.map((r: { path: string }) => r.path)).toEqual(['/core/task/begin', '/core/context', '/core/tool', '/core/progress', '/core/task/end'])
    expect(recs.every((r: { violations?: unknown; response_violations?: unknown }) => !r.violations && !r.response_violations)).toBe(true)
  })

  it('工具失败时抛出中文 message（T23/T24 的工具返回 SERVICE_UNAVAILABLE）', async () => {
    const a = mk()
    await a.preStep(agentObj('s-2'), 1, enter())
    await expect(a.executeTool('s-2', 'case_calc_sentence', { penalty: 'x' })).rejects.toThrow()
    await expect(a.executeTool('s-2', 'case_archive_match', {})).rejects.toThrow(/./)
  })
})

describe('会话的写入位置已失效（T17 第五轮复核 F1）', () => {
  it('step 1 整轮拒绝、记 CASE_MOVED 给界面，不取任务；位置正常时照常', async () => {
    const blocked: Array<[string, string]> = []
    const lost = new Set(['s-moved'])
    const a = new LegalAgent(new CoreClient(() => ({ port: fake.port, token: fake.token }), log), log, (id, code) => { blocked.push([id, code]) }, () => {}, (id) => lost.has(id))
    expect(await a.preStep(agentObj('s-moved'), 1, enter())).toEqual({ kind: 'reject' })
    expect(blocked).toEqual([['s-moved', 'CASE_MOVED']])
    expect(a.tasks.has('s-moved')).toBe(false)
    expect(events).toContain('agent.case_moved')
    expect((await a.preStep(agentObj('s-ok'), 1, enter())).kind).toBe('enter')
  })
})

describe('T14 派修 2：模型调用次数用完整轮收尾时记下 BUDGET_STOPPED 和任务编号（对话区据此显示草稿）', () => {
  it('前 N 步照常；第 N+1 步拒绝并记 [会话, BUDGET_STOPPED, 任务编号]；未到上限时不记', async () => {
    const noted: Array<[string, string, string | undefined]> = []
    const a = new LegalAgent(new CoreClient(() => ({ port: fake.port, token: fake.token }), log), log, (id, code, taskId) => { noted.push([id, code, taskId]) })
    expect((await a.preStep(agentObj('s-b'), 1, enter())).kind).toBe('enter')
    const state = a.tasks.get('s-b')!
    for (let step = 2; step <= state.budget.model_calls; step++) expect((await a.preStep(agentObj('s-b'), step, enter())).kind).toBe('enter')
    expect(noted).toEqual([])
    expect(await a.preStep(agentObj('s-b'), state.budget.model_calls + 1, enter())).toEqual({ kind: 'reject' })
    expect(noted).toEqual([['s-b', BUDGET_STOPPED, state.taskId]])
  })
})

describe('预算（验收：第 25 次被拒绝，case_save_draft 仍可调用）', () => {
  it('24 次后拒绝 case_*，case_save_draft 放行；结束原因报 budget', async () => {
    const a = mk()
    await a.preStep(agentObj('s-3'), 1, enter())
    for (let i = 0; i < 24; i++) expect(a.preTool('s-3', 'case_search')).toEqual({ kind: 'allow' })
    expect(a.preTool('s-3', 'case_search')).toEqual({ kind: 'deny', reason: DENY_BUDGET })
    expect(a.preTool('s-3', 'case_save_draft')).toEqual({ kind: 'allow' })
    expect(a.tasks.get('s-3')!.endReason('completed')).toBe('budget')
  })

  it('模型调用第 8 次前注入立即收尾，第 9 次拒绝', async () => {
    const a = mk()
    const texts: string[] = []
    for (let step = 1; step <= 8; step++) {
      const d = await a.preStep(agentObj('s-4'), step, enter())
      expect(d.kind).toBe('enter')
      for (const m of (d as { messages: Array<{ content: Array<{ text: string }> }> }).messages) texts.push(m.content[0].text)
    }
    expect(texts.filter((t) => t.includes('立即收尾'))).toHaveLength(1)
    expect(await a.preStep(agentObj('s-4'), 9, enter())).toEqual({ kind: 'reject' })
  })
})

describe('白名单', () => {
  it('非 case_* 且不在白名单的工具拒绝并记日志', () => {
    const a = mk()
    for (const t of ['run_code', 'bash', 'load_workspace_dependencies', 'web_search']) expect(a.preTool('s-x', t)).toEqual({ kind: 'deny', reason: DENY_NOT_ALLOWED })
    expect(events).toContain('agent.tool_not_allowed')
  })
  it('skill、ask_user_question 放行', () => {
    const a = mk()
    expect(a.preTool('s-x', 'skill')).toEqual({ kind: 'allow' })
    expect(a.preTool('s-x', 'ask_user_question')).toEqual({ kind: 'allow' })
  })
  it('没有任务时 case_* 拒绝', () => {
    expect(mk().preTool('no-task', 'case_list_materials').kind).toBe('deny')
  })
})

describe('Q11：取任务失败', () => {
  it('task/begin 返回 CASE_NOT_FOUND 时拒绝整轮', async () => {
    const a = mk(() => failing)
    expect(await a.preStep(agentObj('s-5'), 1, enter())).toEqual({ kind: 'reject' })
    expect(events).toContain('agent.task_begin_failed')
  })
  it('拒绝整轮时记下错误码，界面经 Host 的 turnNotice 取走（ORCH 注记 13:18：INPUT_CHANGED）', async () => {
    const noted: Array<[string, string]> = []
    const note = (id: string, code: string) => { noted.push([id, code]) }
    const withNote = (f: () => Fake) => new LegalAgent(new CoreClient(() => ({ port: f().port, token: f().token }), log), log, note)
    expect(await withNote(() => changed).preStep(agentObj('s-7'), 1, enter())).toEqual({ kind: 'reject' })
    expect(await withNote(() => failing).preStep(agentObj('s-8'), 1, enter())).toEqual({ kind: 'reject' })
    expect(noted).toEqual([['s-7', 'INPUT_CHANGED'], ['s-8', 'CASE_NOT_FOUND']])
    expect(events).toContain('agent.context_failed')
  })
  it('取任务、取上下文都成功时清掉该会话没被取走的旧记录（返修 P3-C ①）；被拦下时不清', async () => {
    const cleared: string[] = []
    const mkAgent = (f: () => Fake) => new LegalAgent(new CoreClient(() => ({ port: f().port, token: f().token }), log), log, () => {}, (id) => { cleared.push(id) })
    await mkAgent(() => fake).preStep(agentObj('s-9'), 1, enter())
    await mkAgent(() => changed).preStep(agentObj('s-10'), 1, enter())
    expect(cleared).toEqual(['s-9'])
  })
  it('服务没起来时拒绝整轮', async () => {
    const a = new LegalAgent(new CoreClient(() => undefined, log), log)
    expect(await a.preStep(agentObj('s-6'), 1, enter())).toEqual({ kind: 'reject' })
  })
})
