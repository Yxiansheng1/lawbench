// @vitest-environment jsdom
// 令 0321（用户 2026-10-11 定；真机"刑期计算"16/16 用完没存草稿）：预算到顶前强制存草稿。
// 1. "立即收尾"提前到模型调用还剩两次时注入，并说清"先存草稿，再用最后一次写回答"；
// 2. 最后一次调用发起的工具里，case_* 只放行 case_save_draft；
// 3. 真到顶还没有草稿：把最后一条回复的文字代存成"（未完成）"草稿；提示改说"已把做到的部分存为草稿"，并给一张草稿卡片。
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { BUDGET_STOPPED, DENY_BUDGET, DENY_WRAP_UP, LegalAgent } from '../agent/index.ts'
import { TaskState, UNFINISHED_SUFFIX, UNFINISHED_TITLE, WRAP_UP_TEXT, WRAP_UP_TWO_LEFT, type Budget } from '../agent/task-state.ts'
import { validate } from '../shared/contracts.ts'
import type { CoreClient } from '../shared/core-client.ts'
import { answerNotice, isUnfinished } from '../ui/answer.tsx'

const T = 'T-20261011032100-ab12'
const PARAMS = { thinking: '低' as const, window: '64K' as const, max_tokens: 16384 }
const mk = (budget: Partial<Budget> = {}, now = 0) => new TaskState(T, { model_calls: 4, tool_calls: 24, minutes: 45, ...budget }, PARAMS, now)

describe('还剩两次时提醒', () => {
  it('预算 4 次：第 3 次调用前注入，说"只剩两次机会：先存草稿，再用最后一次写回答"；第 4 次前不再注', () => {
    const s = mk()
    const seen: Array<string | false> = []
    for (let i = 0; i < 4; i++) { const d = s.beforeModelCall(1000); seen.push(d.kind === 'continue' && d.wrapUp ? s.wrapUpNotice : false) }
    expect(seen).toEqual([false, false, WRAP_UP_TWO_LEFT, false])
    expect(WRAP_UP_TWO_LEFT).toContain('你只剩两次机会：先调用 case_save_draft 把已有内容存为草稿，再用最后一次写回答')
    expect(WRAP_UP_TWO_LEFT.startsWith(WRAP_UP_TEXT)).toBe(true)
    expect(s.beforeModelCall(1000)).toEqual({ kind: 'reject', reason: 'model_calls' })
  })

  it('预算只有 1 次、2 次：1 次时在唯一一次前提醒（不说"两次"）；2 次时第一次前就提醒', () => {
    const one = mk({ model_calls: 1 })
    expect(one.beforeModelCall(0)).toEqual({ kind: 'continue', wrapUp: true })
    expect(one.wrapUpNotice).toBe(WRAP_UP_TEXT)
    const two = mk({ model_calls: 2 })
    expect(two.beforeModelCall(0)).toEqual({ kind: 'continue', wrapUp: true })
    expect(two.wrapUpNotice).toBe(WRAP_UP_TWO_LEFT)
    expect(two.beforeModelCall(0)).toEqual({ kind: 'continue', wrapUp: false })
  })

  it('时长只剩 5 分钟的提醒照旧；次数的提醒已经说过收尾后，时长那句不再重复；时长先到时次数的提醒仍会说', () => {
    const a = mk({ model_calls: 8 }, 0)
    expect(a.beforeModelCall(41 * 60_000)).toEqual({ kind: 'continue', wrapUp: true }) // 第 1 次：时长
    expect(a.wrapUpNotice).toBe(WRAP_UP_TEXT)
    for (let i = 2; i <= 6; i++) expect(a.beforeModelCall(41 * 60_000)).toEqual({ kind: 'continue', wrapUp: false })
    expect(a.beforeModelCall(41 * 60_000)).toEqual({ kind: 'continue', wrapUp: true }) // 第 7 次：还剩两次
    expect(a.wrapUpNotice).toBe(WRAP_UP_TWO_LEFT)
    const b = mk({ model_calls: 2 }, 0)
    expect(b.beforeModelCall(0)).toEqual({ kind: 'continue', wrapUp: true })
    expect(b.beforeModelCall(41 * 60_000)).toEqual({ kind: 'continue', wrapUp: false })
  })
})

describe('最后一次调用只许存稿', () => {
  it('最后一次模型调用之前照常；之后 case_* 只放行 case_save_draft，别的回 wrap_up_only 且不计数；提问等非 case 工具照常', () => {
    const s = mk()
    for (let i = 0; i < 3; i++) s.beforeModelCall(0)
    expect(s.lastCall).toBe(false)
    expect(s.beforeTool('case_read_material')).toEqual({ allow: true })
    s.beforeModelCall(0) // 第 4 次，也是最后一次
    expect(s.lastCall).toBe(true)
    const before = s.toolCalls
    expect(s.beforeTool('case_read_material')).toEqual({ allow: false, reason: 'wrap_up_only' })
    expect(s.beforeTool('case_search')).toEqual({ allow: false, reason: 'wrap_up_only' })
    expect(s.toolCalls).toBe(before)
    expect(s.beforeTool('case_save_draft')).toEqual({ allow: true })
    expect(s.beforeTool('ask_user_question')).toEqual({ allow: true })
    expect(s.beforeTool('skill')).toEqual({ allow: true })
    expect(s.beforeTool('bash')).toEqual({ allow: false, reason: 'not_allowed' })
  })
})

// —— Agent 插件：对一个假的工作台服务（只记调用） ——
/** 存草稿的返回用契约样例（Agent 插件按契约校验工具返回）。 */
const SAVED = JSON.parse(readFileSync(join(__dirname, '..', '..', 'contracts', 'examples', 'tool_save_draft.result.json'), 'utf8')) as unknown
type Call = { cmd: string; body: Record<string, unknown> }
function fakeCore(opts: { budget?: Partial<Budget>; saveOk?: boolean } = {}) {
  const calls: Call[] = []
  const core = {
    call: async (cmd: string, body: Record<string, unknown>) => {
      calls.push({ cmd, body })
      if (cmd === 'task/begin') return { ok: true, value: { task_id: T, params: PARAMS, budget: { model_calls: 4, tool_calls: 24, minutes: 45, ...opts.budget } } }
      if (cmd === 'context') return { ok: true, value: { l0: { text: '案件卡片' }, l1: { text: '任务输入', truncated: false, toc: [] } } }
      if (cmd === 'tool' && body.tool === 'case_save_draft') {
        return opts.saveOk === false ? { ok: false, error: { code: 'INTERNAL', message: '内部错误' } }
          : { ok: true, value: SAVED }
      }
      return { ok: true, value: {} }
    },
  } as unknown as CoreClient
  return { core, calls, saves: () => calls.filter((c) => c.cmd === 'tool' && c.body.tool === 'case_save_draft') }
}
const logs: Array<[string, string, unknown]> = []
const log = (level: string, event: string, meta?: unknown) => { logs.push([level, event, meta]) }
const agentObj = (id: string) => ({ id, session: { header: { cwd: 'D:\\案件\\张某甲诈骗案' } } })
const enter = () => ({ kind: 'enter' as const, messages: [] })
const say = (a: LegalAgent, id: string, text: string) => a.onSessionEvent(id, { type: 'assistant/message', data: { message: { content: [{ type: 'text', text }] } } })
const texts = (d: unknown) => ((d as { messages?: Array<{ content: Array<{ text: string }> }> }).messages ?? []).map((m) => m.content[0]!.text)

describe('Agent 插件', () => {
  beforeEach(() => { logs.length = 0 })

  it('第 3 步（还剩两次）注入的就是那句提醒；最后一步发起的 case_read_material 被拒并告诉模型只能存稿或作答，case_save_draft 放行', async () => {
    const f = fakeCore()
    const a = new LegalAgent(f.core, log as never)
    const injected: string[] = []
    for (let step = 1; step <= 4; step++) injected.push(...texts(await a.preStep(agentObj('s'), step, enter())).filter((t) => t.includes('立即收尾')))
    expect(injected).toEqual([WRAP_UP_TWO_LEFT])
    expect(a.preTool('s', 'case_read_material')).toEqual({ kind: 'deny', reason: DENY_WRAP_UP })
    expect(DENY_WRAP_UP).toContain('case_save_draft')
    expect(DENY_WRAP_UP).not.toBe(DENY_BUDGET)
    expect(a.preTool('s', 'case_save_draft')).toEqual({ kind: 'allow' })
    expect(a.preTool('s', 'ask_user_question')).toEqual({ kind: 'allow' })
  })

  it('到顶时还没有草稿：把最后一条回复的文字代存成"（未完成）"草稿（请求合 case_save_draft 的契约），再记 BUDGET_STOPPED', async () => {
    const f = fakeCore()
    const noted: Array<[string, string, string | undefined]> = []
    const a = new LegalAgent(f.core, log as never, (id, code, taskId) => { noted.push([id, code, taskId]) })
    for (let step = 1; step <= 4; step++) await a.preStep(agentObj('s'), step, enter())
    await say(a, 's', '先读材料。')
    await say(a, 's', '  ') // 没有正文的回复不算
    await say(a, 's', '初步意见：借款事实清楚〔借条 第1页〕。')
    expect(f.saves()).toEqual([])
    expect(await a.preStep(agentObj('s'), 5, enter())).toEqual({ kind: 'reject' })
    expect(f.saves().map((c) => c.body)).toEqual([{ task_id: T, tool: 'case_save_draft', args: { title: UNFINISHED_TITLE, content: '初步意见：借款事实清楚〔借条 第1页〕。' } }])
    expect(UNFINISHED_TITLE.endsWith(UNFINISHED_SUFFIX)).toBe(true)
    expect(validate('lawbench://contracts/tools/case_save_draft.schema.json', 'args', f.saves()[0]!.body.args)).toEqual([])
    expect(noted).toEqual([['s', BUDGET_STOPPED, T]])
    // 存稿在记提示之前：界面取提示时草稿已经在了
    expect(f.calls.at(-1)).toMatchObject({ cmd: 'tool' })
    // 日志只有结果，没有标题、正文
    expect(logs.filter((l) => l[1] === 'agent.unfinished_draft')).toEqual([['info', 'agent.unfinished_draft', { saved: true, code: undefined }]])
    expect(JSON.stringify(logs)).not.toMatch(/初步意见|未完成/)
  })

  it('模型自己存过草稿：到顶时不再代存', async () => {
    const f = fakeCore()
    const a = new LegalAgent(f.core, log as never)
    for (let step = 1; step <= 4; step++) await a.preStep(agentObj('s'), step, enter())
    await say(a, 's', '审查意见正文。')
    await a.executeTool('s', 'case_save_draft', { title: '审查意见', content: '审查意见正文。' })
    expect(f.saves().length).toBe(1)
    expect(await a.preStep(agentObj('s'), 5, enter())).toEqual({ kind: 'reject' })
    expect(f.saves().length).toBe(1)
    expect(logs.some((l) => l[1] === 'agent.unfinished_draft')).toBe(false)
  })

  it('没有任何文字可存：不调存草稿，照旧收尾；存不成也不拦收尾', async () => {
    const none = fakeCore()
    const a = new LegalAgent(none.core, log as never)
    for (let step = 1; step <= 4; step++) await a.preStep(agentObj('s'), step, enter())
    expect(await a.preStep(agentObj('s'), 5, enter())).toEqual({ kind: 'reject' })
    expect(none.saves()).toEqual([])

    const bad = fakeCore({ saveOk: false })
    const noted: string[] = []
    const b = new LegalAgent(bad.core, log as never, (_id, code) => { noted.push(code) })
    for (let step = 1; step <= 4; step++) await b.preStep(agentObj('t'), step, enter())
    await say(b, 't', '做到一半。')
    expect(await b.preStep(agentObj('t'), 5, enter())).toEqual({ kind: 'reject' })
    expect(bad.saves().length).toBe(1)
    expect(noted).toEqual([BUDGET_STOPPED])
    expect(logs.filter((l) => l[1] === 'agent.unfinished_draft').at(-1)).toEqual(['warn', 'agent.unfinished_draft', { saved: false, code: 'INTERNAL' }])
  })

  it('时长用完、第一步就到顶（还没有任何回复）：没有可存的，不调存草稿', async () => {
    const f = fakeCore({ budget: { minutes: 0 } })
    const a = new LegalAgent(f.core, log as never)
    // 时长为 0：第一步就到顶，此时还没有回复，没有可存的
    expect(await a.preStep(agentObj('s'), 1, enter())).toEqual({ kind: 'reject' })
    expect(f.saves()).toEqual([])
  })
})

describe('界面：提示和草稿卡片', () => {
  it('有草稿说"已把做到的部分存为草稿"；没有任何文字可存时保留原来的话', () => {
    const d = { title: UNFINISHED_TITLE, version: 1, path: 'x', text: 'x', truncated: false }
    expect(answerNotice({ used: 16, limit: 16, draft: d })).toBe('已用完本次运行的模型调用次数（16/16），已把做到的部分存为草稿')
    expect(answerNotice({ used: 16, limit: 16, draft: null })).toBe('已用完本次运行的模型调用次数（16/16），没有存下草稿；做到哪里请看成果里的"未完成"')
  })

  it('代存的草稿（标题以"（未完成）"结尾）认得出来，模型自己存的不算', () => {
    expect(isUnfinished(UNFINISHED_TITLE)).toBe(true)
    expect(isUnfinished('刑期计算笔录')).toBe(false)
  })
})

