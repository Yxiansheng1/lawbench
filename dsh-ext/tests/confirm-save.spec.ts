// @vitest-environment jsdom
// 令 0405（用户真机 2026-10-11）：草稿卡片"确认保存…"误灰——一轮结束后、新一轮开始后、停止后都是灰的（悬停"这一轮还在进行"）。
// 原来按服务那边任务记录的状态判断；那个任务没被登记结束时它永远是"进行中"。
// 改后：只在产生这张草稿的那一轮还在进行时灰（看这一轮自己在会话记录里结束了没有、这个会话此刻有没有一轮在跑）；
// Agent 插件所有结束路径都登记任务结束，没成重试一次，仍没成让界面提示；已经卡在"进行中"的旧任务不再挡。
import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { BUDGET_STOPPED, LegalAgent, TASK_END_FAILED } from '../agent/index.ts'
import type { CoreClient } from '../shared/core-client.ts'
import { TASK_END_FAILED as UI_TASK_END_FAILED, TASK_END_FAILED_TITLE } from '../ui/dock.tsx'
import { resetCaseResults, STALE_RUNNING_NOTE, TURN_DATA_KEY, turnInProgress, TurnResultCards, type SavedDraft } from '../ui/result-cards.tsx'
import { app, setApi, type CaseRef, type LawbenchApi } from '../ui/state.ts'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const T = 'T-20261011040500-ab12'
const CASE: CaseRef = { case_id: 'c-1', name: '张某甲诈骗案', root: 'D:\\案件\\张某甲诈骗案' }
const PATH = `工作区/任务/${T}/草稿/刑事阅卷笔录-v4.md`
const DRAFT: SavedDraft = { seq: 5, title: '刑事阅卷笔录', path: PATH, version: 4, coverage: null, citation_check: null }

describe('只在产生这张草稿的那一轮还在进行时灰', () => {
  it('判断只看这一轮自己：它还没结束、而且这个会话此刻有一轮在跑', () => {
    expect(turnInProgress({ status: 'open' }, true)).toBe(true)
    // 这一轮已经结束：会话里新一轮在跑也不灰
    expect(turnInProgress({ status: 'closed' }, true)).toBe(false)
    // 会话已经不在跑（停止、到顶、出错后没有结束事件的轮）：不灰
    expect(turnInProgress({ status: 'open' }, false)).toBe(false)
    expect(turnInProgress({ status: 'unknown' }, true)).toBe(false)
    expect(turnInProgress(undefined, true)).toBe(false)
  })

  let root: Root | undefined
  let box: HTMLDivElement
  let taskStatus = 'running'
  let confirmed: unknown[] = []
  beforeEach(() => {
    box = document.createElement('div'); document.body.appendChild(box)
    taskStatus = 'running'; confirmed = []
    resetCaseResults(); localStorage.clear()
    app.set((s) => ({ ...s, cases: [CASE], intents: {}, selections: {}, runningSessions: [], dialogs: [] }))
    setApi({
      // 服务那边这个任务一直是"进行中"（没被登记结束）——用户机器上现有的状态
      tasksList: async () => ({ ok: true, value: { tasks: [{ task_id: T, skill: 'criminal-reading-notes', status: taskStatus, drafts: [{ title: DRAFT.title, path: PATH, version: 4 }] }] } }),
      outputsList: async () => ({ ok: true, value: { outputs: [] } }),
      outputsConfirm: async (r: unknown) => { confirmed.push(r); return { ok: true, value: { outputs: [{ format: 'docx', path: '成果/刑事阅卷笔录-v1.docx', version: 1 }] } } },
    } as unknown as LawbenchApi)
  })
  afterEach(async () => { await act(async () => { root?.unmount() }); root = undefined; box.remove(); setApi(undefined); document.body.innerHTML = ''; app.set((s) => ({ ...s, cases: [], runningSessions: [] })) })

  const props = (status: 'open' | 'closed') => ({
    turn: { status, data: new Map([[TURN_DATA_KEY, { drafts: [DRAFT] }]]) }, seq: 10, sessionId: 's-1',
    useSessions: <R>(sel: (s: { byId: Record<string, { cwd?: string }> }) => R) => sel({ byId: { 's-1': { cwd: CASE.root } } }),
  })
  const flush = async () => { await act(async () => { for (let i = 0; i < 5; i++) await Promise.resolve() }) }
  const render = async (status: 'open' | 'closed') => { root ??= createRoot(box); await act(async () => { root!.render(createElement(TurnResultCards, props(status) as never)) }); await flush() }
  const save = () => [...document.querySelectorAll('button')].find((b) => b.textContent === '确认保存…') as HTMLButtonElement

  it('轮中灰（提示"这一轮还在进行"）→ 这一轮结束即可点，不用等别的刷新', async () => {
    app.set((s) => ({ ...s, runningSessions: ['s-1'] }))
    await render('open')
    expect(save().disabled).toBe(true)
    expect(save().title).toBe('这一轮还在进行')
    // 会话记录里这一轮结束了（"用时…"行出现的时刻）：卡片按新的轮次状态重算
    await render('closed')
    expect(save().disabled).toBe(false)
    expect(save().title).toBe('')
  })

  it('新一轮开始后（会话又在跑），旧草稿仍可点，点了能保存', async () => {
    app.set((s) => ({ ...s, runningSessions: ['s-1'] }))
    await render('closed')
    expect(save().disabled).toBe(false)
    await act(async () => { save().click() })
    await act(async () => { [...document.querySelectorAll('button')].find((b) => b.textContent === '保存到成果')!.click() })
    await flush()
    expect(confirmed).toMatchObject([{ case_id: 'c-1', task_id: T, draft: PATH }])
  })

  it('停止、到顶结束（会话不在跑了）：即使这一轮在会话记录里没有结束事件，也可点；会话状态一变卡片就跟着变', async () => {
    app.set((s) => ({ ...s, runningSessions: ['s-1'] }))
    await render('open')
    expect(save().disabled).toBe(true)
    await act(async () => { app.set((s) => ({ ...s, runningSessions: [] })) })
    expect(save().disabled).toBe(false)
  })

  it('已经卡在"进行中"的旧任务：不再灰，只多一句"（上一轮未正常登记结束）"；任务记录正常结束的没有这句', async () => {
    await render('closed')
    expect(save().disabled).toBe(false)
    expect(box.textContent).toContain(STALE_RUNNING_NOTE)
    await act(async () => { root!.unmount() }); root = undefined
    taskStatus = 'completed'; resetCaseResults()
    await render('closed')
    expect(save().disabled).toBe(false)
    expect(box.textContent).not.toContain(STALE_RUNNING_NOTE)
  })

  it('别的会话在跑不影响这个会话的卡片', async () => {
    app.set((s) => ({ ...s, runningSessions: ['s-2'] }))
    await render('open')
    expect(save().disabled).toBe(false)
  })
})

// —— Agent 插件：每种结束都登记任务结束 ——
function fakeCore(endAnswers: Array<'ok' | 'fail' | 'throw'> = []) {
  const calls: Array<{ cmd: string; body: Record<string, unknown> }> = []
  let n = 0
  const core = {
    call: async (cmd: string, body: Record<string, unknown>) => {
      calls.push({ cmd, body })
      if (cmd === 'task/begin') return { ok: true, value: { task_id: `${T.slice(0, -1)}${n++}`, params: { thinking: '低', window: '64K', max_tokens: 16384 }, budget: { model_calls: 2, tool_calls: 24, minutes: 45 } } }
      if (cmd === 'context') return { ok: true, value: { l0: { text: '案件卡片' }, l1: { text: '', truncated: false, toc: [] } } }
      if (cmd === 'task/end') {
        const a = endAnswers.shift() ?? 'ok'
        if (a === 'throw') throw new Error('socket hang up')
        return a === 'ok' ? { ok: true, value: {} } : { ok: false, error: { code: 'SERVICE_UNAVAILABLE', message: 'x' } }
      }
      return { ok: true, value: {} }
    },
  } as unknown as CoreClient
  return { core, calls, ends: () => calls.filter((c) => c.cmd === 'task/end').map((c) => c.body) }
}
const agentObj = (id: string) => ({ id, session: { header: { cwd: CASE.root } } })
const enter = () => ({ kind: 'enter' as const, messages: [] })
const turnEnd = (kind: string) => ({ type: 'turn/end', data: { reason: { kind } } })

describe('所有结束路径都登记任务结束（/core/task/end）', () => {
  for (const [kind, reason] of [['completed', 'completed'], ['aborted', 'aborted'], ['error', 'error'], ['interrupted', 'interrupted'], ['max-tokens', 'max-tokens'], ['blocked', 'blocked'], ['没见过的原因', 'error']] as const) {
    it(`一轮以"${kind}"结束：登记一次，原因 ${reason}（律师点停止是 aborted）`, async () => {
      const f = fakeCore()
      const a = new LegalAgent(f.core, (() => {}) as never)
      await a.preStep(agentObj('s'), 1, enter())
      await a.onSessionEvent('s', turnEnd(kind))
      expect(f.ends()).toMatchObject([{ reason, model_calls: 1 }])
      expect(a.tasks.has('s')).toBe(false)
    })
  }

  it('到顶结束：原因报 budget', async () => {
    const f = fakeCore()
    const noted: string[] = []
    const a = new LegalAgent(f.core, (() => {}) as never, (_id, code) => { noted.push(code) })
    for (let step = 1; step <= 2; step++) await a.preStep(agentObj('s'), step, enter())
    expect(await a.preStep(agentObj('s'), 3, enter())).toEqual({ kind: 'reject' })
    await a.onSessionEvent('s', turnEnd('completed'))
    expect(f.ends()).toMatchObject([{ reason: 'budget', model_calls: 2 }])
    expect(noted).toEqual([BUDGET_STOPPED])
  })

  it('压缩循环收尾：原因报 budget', async () => {
    const f = fakeCore()
    const a = new LegalAgent(f.core, (() => {}) as never)
    await a.preStep(agentObj('s'), 1, enter())
    for (let i = 0; i < 4; i++) await a.onSessionEvent('s', { type: 'compaction/summary' })
    expect(await a.preStep(agentObj('s'), 2, enter())).toEqual({ kind: 'reject' })
    await a.onSessionEvent('s', turnEnd('completed'))
    expect(f.ends()).toMatchObject([{ reason: 'budget' }])
  })

  it('没收到结束事件、Agent 已经空闲：按中断登记；这期间换成了新一轮的任务就不动它；正常结束后空闲什么都不做', async () => {
    const f = fakeCore()
    const logs: string[] = []
    const a = new LegalAgent(f.core, ((_l: string, e: string) => { logs.push(e) }) as never)
    await a.preStep(agentObj('s'), 1, enter())
    const first = a.tasks.get('s')!
    await a.onIdle('s', first)
    expect(f.ends()).toMatchObject([{ task_id: first.taskId, reason: 'interrupted' }])
    expect(logs).toContain('agent.task_left_open')
    await a.onIdle('s', first)
    expect(f.ends().length).toBe(1)
    // 空闲之后马上开了新一轮：迟到的空闲处理不能把新任务结束掉
    await a.preStep(agentObj('s'), 1, enter())
    await a.onIdle('s', first)
    expect(f.ends().length).toBe(1)
    await a.onSessionEvent('s', turnEnd('completed'))
    await a.onIdle('s')
    expect(f.ends().length).toBe(2)
  })

  it('上一轮的任务还挂着就开始了新一轮：先把旧的按中断登记结束，再取新任务', async () => {
    const f = fakeCore()
    const a = new LegalAgent(f.core, (() => {}) as never)
    await a.preStep(agentObj('s'), 1, enter())
    const old = a.tasks.get('s')!.taskId
    await a.preStep(agentObj('s'), 1, enter())
    expect(f.calls.map((c) => c.cmd)).toEqual(['task/begin', 'context', 'task/end', 'task/begin', 'context'])
    expect(f.ends()).toMatchObject([{ task_id: old, reason: 'interrupted' }])
    expect(a.tasks.get('s')!.taskId).not.toBe(old)
  })

  it('登记没成：重试一次；第二次成了不提示', async () => {
    const f = fakeCore(['fail', 'ok'])
    const noted: string[] = []
    const a = new LegalAgent(f.core, (() => {}) as never, (_id, code) => { noted.push(code) })
    await a.preStep(agentObj('s'), 1, enter())
    await a.onSessionEvent('s', turnEnd('completed'))
    expect(f.ends().length).toBe(2)
    expect(noted).toEqual([])
  })

  it('两次都没成（返回失败或抛错）：记日志，记 TASK_END_FAILED 让界面提示"任务结束状态未能登记"；不再重试第三次', async () => {
    const f = fakeCore(['throw', 'fail'])
    const noted: Array<[string, string]> = []
    const logs: Array<[string, string, unknown]> = []
    const a = new LegalAgent(f.core, ((l: string, e: string, m?: unknown) => { logs.push([l, e, m]) }) as never, (id, code) => { noted.push([id, code]) })
    await a.preStep(agentObj('s'), 1, enter())
    await a.onSessionEvent('s', turnEnd('aborted'))
    expect(f.ends().length).toBe(2)
    expect(noted).toEqual([['s', TASK_END_FAILED]])
    expect(logs.filter((l) => l[1] === 'agent.task_end_failed').map((l) => l[2])).toEqual([{ attempt: 1, code: undefined, reason: 'aborted' }, { attempt: 2, code: 'SERVICE_UNAVAILABLE', reason: 'aborted' }])
    expect(UI_TASK_END_FAILED).toBe(TASK_END_FAILED)
    expect(TASK_END_FAILED_TITLE).toBe('任务结束状态未能登记')
  })
})
