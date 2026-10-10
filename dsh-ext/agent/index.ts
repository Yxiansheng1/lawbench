// Agent 插件 legal-agent（Spec 1.2、9.2、20.3、20.4；T7 步骤 2、执行令 Q5/Q6/Q9/Q10/Q11）。挂在 preset-lawbench 里。
import { randomUUID } from 'node:crypto'
import { TOOL_NAMES, toolDescription, toolId, toolParameters, validate } from '../shared/contracts.ts'
import { CoreClient, type Endpoint, type Logger } from '../shared/core-client.ts'
import { defaultAppData, makeLogger } from '../shared/file-log.ts'
import { ALLOWED_OTHER_TOOLS, ASK_USER_TOOL, BUDGET_EXEMPT_TOOL, SKILL_TOOL, TaskState, UNFINISHED_TITLE, reasoningEffort, type Budget, type Params } from './task-state.ts'

export const name = 'lawbench-agent'
export const inject = ['tools', 'lawbenchCore']

export interface Config {
  /** 开发模式按契约校验 /core/* 的请求和返回（T7 步骤 3）。默认开。 */
  validateContracts?: boolean
  /** 应用数据目录（日志写在其下 logs\）；不给时用 %LOCALAPPDATA%\lawbench。 */
  appData?: string
}

// ── DSH 运行时形状（只写用到的字段；来源见 dsh-patches\PATCHES.md 与交付说明）─────────────
type TextBlock = { type: 'text'; text: string }
type UserMessage = { id: string; role: 'user'; content: TextBlock[]; source: unknown }
type AgentLike = { id: string; session?: { header?: { cwd?: string } } }
type PreStepDecision = { kind: 'reject' } | { kind: 'enter'; messages: UserMessage[]; startsRequestSeries?: true }
type LlmCallConfig = { provider: string; model: string; reasoningEffort?: string; temperature?: number; maxTokens?: number; stop?: string[] }
type PreToolDecision = { kind: 'allow' } | { kind: 'deny'; reason: string } | { kind: 'cancel' }
type SessionEvent = { type: string; data?: { message?: { content?: Array<{ type: string; text?: string }> }; reason?: { kind?: string } } }

const notice = (source: string, summary: string, text: string): UserMessage => Object.freeze({
  id: randomUUID(), role: 'user' as const, content: [{ type: 'text' as const, text }],
  source: { kind: source, form: 'notice', summary: summary.slice(0, 120) },
})
const snapshot = (sections: Array<{ name: string; text: string }>): UserMessage => Object.freeze({
  id: randomUUID(), role: 'user' as const,
  content: [{ type: 'text' as const, text: sections.map((s) => `## ${s.name}\n\n${s.text}`).join('\n\n') }],
  source: { kind: 'lawbench-context', form: 'snapshot', sections },
})

export const DENY_NOT_ALLOWED = '该工具在律师工作台不可用'
export const DENY_BUDGET = '已达到本次任务的上限，已保存草稿'
/** 同一个任务里同一个技能加载次数到了上限（令 0329 P0，防"加载 → 压缩 → 又加载"）。 */
export const DENY_SKILL_RELOAD = '这个技能在本次任务里已经加载过多次，内容没有变化。请不要再加载，直接按已知的步骤继续；内容记不全时用 case_save_draft 先保存已有成果'
/** 最后一次模型调用发起了存草稿以外的案件工具（令 0321）。 */
export const DENY_WRAP_UP = '这是本次任务的最后一次调用：只能用 case_save_draft 保存草稿，或直接写出回答'
/** 到达用量上限（模型调用次数或时间）整轮收尾时记的提示码，见 shared/turn-notices.ts。 */
export const BUDGET_STOPPED = 'BUDGET_STOPPED'
/** 输入区写任务单明确失败、还没重写成（T14 第二次实跑派修 2）：整轮拒绝，不拿上一张任务单发。 */
export const TASK_SHEET_FAILED = 'TASK_SHEET_FAILED'
/** 一轮结束了但 /core/task/end 重试一次仍没成（令 0405 追加）：界面提示"任务结束状态未能登记"。 */
export const TASK_END_FAILED = 'TASK_END_FAILED'
export const DENY_NO_TASK = '工作台服务未启动，请稍后重试'

type ContextValue = { l0: { text: string }; l1: { text: string; truncated: boolean; toc: Array<{ index: number; title: string; tokens: number }> } }

/** 与 DSH 无关的核心逻辑；apply() 只把它接到 DSH 的挂载点上。 */
export class LegalAgent {
  /** 以会话 ID（= agent.id）为键的当前任务。 */
  readonly tasks = new Map<string, TaskState>()

  /** @param noteBlocked - 拒绝整轮时记下错误码，界面经 Host 的 turnNotice 取走（DSH 的 reject 带不了消息）。 */
  /**
   * @param noteBlocked - 拒绝整轮时记下错误码，界面经 Host 的 turnNotice 取走（DSH 的 reject 带不了消息）。
   * @param clearBlocked - 这一轮顺利开始时清掉该会话没被取走的旧记录（复核 P3-C ①）。
   * @param caseMoved - 这个会话所在的案件文件夹是否已不在原位置（N55 ②；见会话存储 router.ts）。
   * @param sheetHeld - 这个会话的任务单是否没写成（输入区经 Host 的 sheetHold 记；T14 第二次实跑派修 2）。
   */
  constructor(private readonly core: CoreClient, private readonly log: Logger, private readonly noteBlocked: (sessionId: string, code: string, taskId?: string) => void = () => {}, private readonly clearBlocked: (sessionId: string) => void = () => {}, private readonly caseMoved: (sessionId: string) => boolean = () => false, private readonly sheetHeld: (sessionId: string) => boolean = () => false) {}

  /**
   * 案件文件夹已不在原处（N55 ②）：整轮拒绝，不写旧处；界面提示重启软件后在这个对话里继续，或新开一个对话。
   * 排在最前的那个 pre-step 和下面的 preStep 都走这一处（第九轮复核 B-NOTE）。
   */
  rejectMoved(sessionId: string): PreStepDecision {
    this.log('warn', 'agent.case_moved', {})
    this.noteBlocked(sessionId, 'CASE_MOVED')
    this.tasks.delete(sessionId)
    return { kind: 'reject' }
  }

  /** agent/pre-step。step 1 取任务和上下文；每步检查模型调用预算。 */
  async preStep(agent: AgentLike, step: number, decision: PreStepDecision): Promise<PreStepDecision> {
    if (decision.kind === 'reject') return decision
    let state = this.tasks.get(agent.id)
    const added: UserMessage[] = []
    // 案件卡片和任务输入放在律师这条消息的前面（令 0329 P0 追加线索）：模型看到的最后一条用户消息应当是律师刚发的那句，
    // 不是我方注入的背景——否则上下文一长，模型容易把背景或摘要里的旧事当成这一轮要办的
    const lead: UserMessage[] = []
    if (step === 1 && this.caseMoved(agent.id)) return this.rejectMoved(agent.id)
    // 律师改了选择、写任务单明确失败还没重写成：服务那边还是上一张，整轮拒绝（不在第 2 步之后拦：一轮已按取到的任务单开始）
    if (step === 1 && this.sheetHeld(agent.id)) {
      this.log('warn', 'agent.sheet_held', {})
      this.noteBlocked(agent.id, TASK_SHEET_FAILED)
      this.tasks.delete(agent.id)
      return { kind: 'reject' }
    }
    if (step === 1 || !state) {
      // 上一轮的任务还挂着（它的结束事件没收到）：先登记结束再开新的，不让它在服务里永远是"进行中"（令 0405 追加）
      if (state) await this.endTask(agent.id, state, 'interrupted')
      const begin = await this.core.call<{ task_id: string; params: Params; budget: Budget }>('task/begin', {
        session_id: agent.id, cwd: agent.session?.header?.cwd ?? '',
      })
      if (!begin.ok) {
        // Q11：取任务失败拒绝整轮（DSH 的 reject 不能附带消息，界面提示由 T13 做）
        this.log('warn', 'agent.task_begin_failed', { code: begin.error.code })
        this.noteBlocked(agent.id, begin.error.code)
        this.tasks.delete(agent.id)
        return { kind: 'reject' }
      }
      state = new TaskState(begin.value.task_id, begin.value.budget, begin.value.params)
      this.tasks.set(agent.id, state)
      const ctxRes = await this.core.call<ContextValue>('context', { task_id: state.taskId })
      if (!ctxRes.ok) {
        this.log('warn', 'agent.context_failed', { code: ctxRes.error.code })
        this.noteBlocked(agent.id, ctxRes.error.code)
        this.tasks.delete(agent.id)
        return { kind: 'reject' }
      }
      this.clearBlocked(agent.id)
      const { l0, l1 } = ctxRes.value
      const sections = [{ name: '案件卡片（L0）', text: l0.text }, { name: '任务输入（L1）', text: l1.text }]
      if (l1.toc.length) {
        sections.push({ name: '未放入 L1 的输入（用 case_read_input 按序号读取）', text: l1.toc.map((t) => `${t.index}. ${t.title}（约 ${t.tokens} token）`).join('\n') })
      }
      lead.push(snapshot(sections))
    }
    // 令 0329 P0：这个任务里上下文已经压缩了太多次（模型在"读 → 压缩 → 再读"里打转）：不再继续，存稿收尾（同到顶的处理）
    if (state.compactionLoop) {
      state.budgetHit = true
      this.log('warn', 'agent.compaction_loop', { compactions: state.compactions, model_calls: state.modelCalls, stopped: true })
      await this.saveUnfinished(state)
      this.noteBlocked(agent.id, BUDGET_STOPPED, state.taskId)
      return { kind: 'reject' }
    }
    const d = state.beforeModelCall()
    if (d.kind === 'reject') {
      this.log('info', 'agent.model_budget', { reason: d.reason, model_calls: state.modelCalls })
      // 令 0321：到顶时这个任务还没有草稿，就把最后一条回复的文字代存成"未完成"的草稿，律师不至于一无所有
      await this.saveUnfinished(state)
      // 到达用量上限：模型这时往往刚存完草稿、没写文字回答（T14 实跑）。记下任务编号，输入区据此在对话区显示
      // 提示和刚存的草稿（出处可点；T14 派修 2，用户选"对话区显示草稿"）
      this.noteBlocked(agent.id, BUDGET_STOPPED, state.taskId)
      return { kind: 'reject' }
    }
    if (d.wrapUp) added.push(notice('lawbench-budget', '立即收尾', state.wrapUpNotice))
    return lead.length || added.length ? { ...decision, messages: [...lead, ...decision.messages, ...added] } : decision
  }

  /**
   * 预算到顶、这个任务还没有草稿：把最后一条回复的文字按存草稿的口径存一次（经 /core/tool 的 case_save_draft，标题以"（未完成）"结尾）。
   * 没有文字可存、存不成都不拦收尾（界面照旧说"没有存下草稿"）。日志只记结果，不记标题和正文。
   * @returns 存成了为 true。
   */
  async saveUnfinished(state: TaskState): Promise<boolean> {
    if (state.draftSaved) return false
    const text = state.lastReply()?.trim()
    if (!text) return false
    const r = await this.core.call('tool', { task_id: state.taskId, tool: BUDGET_EXEMPT_TOOL, args: { title: UNFINISHED_TITLE, content: text } }).catch(() => undefined)
    const ok = r?.ok === true
    if (ok) state.draftSaved = true
    this.log(ok ? 'info' : 'warn', 'agent.unfinished_draft', { saved: ok, code: r && !r.ok ? r.error.code : undefined })
    return ok
  }

  /** agent/request：按任务单设思考档、最大生成量、温度。Q5：不切换 model。 */
  request(agentId: string, cfg: LlmCallConfig): LlmCallConfig {
    const state = this.tasks.get(agentId)
    if (!state) return cfg
    const p = state.params
    return {
      ...cfg,
      reasoningEffort: reasoningEffort(p.thinking),
      maxTokens: p.max_tokens,
      ...(p.temperature === undefined ? {} : { temperature: p.temperature }),
    }
  }

  /** tools/pre-execute：白名单 + 工具预算（Spec 9.2、Q10）。 */
  preTool(agentId: string | undefined, toolName: string, args?: unknown): PreToolDecision {
    if (!ALLOWED_OTHER_TOOLS.has(toolName) && !/^case_[a-z_]+$/.test(toolName)) {
      this.log('warn', 'agent.tool_not_allowed', { tool: toolName }) // Spec 3.1：出现这条日志说明有工具漏进来
      return { kind: 'deny', reason: DENY_NOT_ALLOWED }
    }
    // 等律师回答必问问题：暂停本任务的时长计时，下一次模型调用时恢复（PRD F-RUN-05、Spec 9.2；令 1117 注记 11:28）
    if (toolName === ASK_USER_TOOL) { if (agentId) this.tasks.get(agentId)?.pause() }
    // 令 0329 P0：同一个任务里反复加载同一个技能（压缩把它剪掉、摘要掉后模型又去加载）——到上限后拒绝，让模型往下走
    if (toolName === SKILL_TOOL) {
      const task = agentId ? this.tasks.get(agentId) : undefined
      const skill = (args as { name?: unknown } | null | undefined)?.name
      if (task && !task.beforeSkillLoad(typeof skill === 'string' ? skill : '').allow) {
        this.log('warn', 'agent.skill_reload_loop', { model_calls: task.modelCalls, compactions: task.compactions })
        return { kind: 'deny', reason: DENY_SKILL_RELOAD }
      }
    }
    if (ALLOWED_OTHER_TOOLS.has(toolName)) return { kind: 'allow' }
    const state = agentId ? this.tasks.get(agentId) : undefined
    if (!state) return { kind: 'deny', reason: DENY_NO_TASK }
    const d = state.beforeTool(toolName)
    if (d.allow) return { kind: 'allow' }
    if (d.reason === 'tool_budget') this.log('info', 'agent.tool_budget', { tool_calls: state.toolCalls })
    if (d.reason === 'wrap_up_only') { this.log('info', 'agent.wrap_up_only', { tool: toolName }); return { kind: 'deny', reason: DENY_WRAP_UP } }
    return { kind: 'deny', reason: d.reason === 'tool_budget' ? DENY_BUDGET : DENY_NOT_ALLOWED }
  }

  /** 工具执行：转发 /core/tool。Q6：失败抛错，把中文 message 给模型；成功时按契约校验 value。 */
  async executeTool(agentId: string | undefined, tool: string, args: unknown): Promise<unknown> {
    const state = agentId ? this.tasks.get(agentId) : undefined
    if (!state) throw new Error(DENY_NO_TASK)
    const r = await this.core.call('tool', { task_id: state.taskId, tool, args: (args ?? {}) as Record<string, unknown> })
    if (!r.ok) throw new Error(r.error.message)
    const errs = validate(toolId(tool), 'result', r.value)
    if (errs.length) {
      this.log('error', 'agent.tool_result_contract', { tool, errors: errs })
      throw new Error('内部错误，请重试；多次出现请联系技术支持')
    }
    if (tool === BUDGET_EXEMPT_TOOL) state.draftSaved = true
    return r.value
  }

  /**
   * 登记任务结束（/core/task/end）。所有结束路径都走这里（令 0405 追加）：正常结束、律师停止、到顶、出错、中断、压缩循环收尾；
   * 没成重试一次，仍没成记日志并记 TASK_END_FAILED 让界面提示——否则服务里这个任务永远是"进行中"。
   * @param kind - DSH turn/end 的 reason.kind；任务碰到过上限的一律报 budget（见 TaskState.endReason）。
   */
  async endTask(sessionId: string, state: TaskState, kind: string): Promise<boolean> {
    if (this.tasks.get(sessionId) === state) this.tasks.delete(sessionId)
    const body = { task_id: state.taskId, reason: state.endReason(kind), model_calls: state.modelCalls, tool_calls: state.toolCalls, elapsed_s: state.elapsedSeconds() }
    for (let attempt = 1; attempt <= 2; attempt++) {
      const r = await this.core.call('task/end', body).catch(() => undefined)
      if (r?.ok) return true
      this.log('warn', 'agent.task_end_failed', { attempt, code: r && !r.ok ? r.error.code : undefined, reason: body.reason })
    }
    this.noteBlocked(sessionId, TASK_END_FAILED)
    return false
  }

  /**
   * 会话的 Agent 空闲了（agent/status idle）：这一轮已经不在跑。任务还挂着说明没收到它的结束事件——按中断登记结束（令 0405 追加，兜底）。
   */
  async onIdle(sessionId: string, expected?: TaskState): Promise<void> {
    const state = this.tasks.get(sessionId)
    // expected：空闲那一刻挂着的任务；这期间已经换成新一轮的任务就不动它
    if (!state || (expected !== undefined && state !== expected)) return
    this.log('warn', 'agent.task_left_open', {})
    await this.endTask(sessionId, state, 'interrupted')
  }

  /** session/event：assistant/message → /core/progress；turn/end → /core/task/end。 */
  async onSessionEvent(sessionId: string, event: SessionEvent): Promise<void> {
    const state = this.tasks.get(sessionId)
    if (!state) return
    if (event.type === 'assistant/message') {
      const text = (event.data?.message?.content ?? []).filter((b) => b.type === 'text').map((b) => b.text ?? '').join('')
      const all = state.addReply(text)
      if (all === undefined) return
      await this.core.call('progress', { task_id: state.taskId, text: all, model_calls: state.modelCalls, tool_calls: state.toolCalls })
    } else if (event.type === 'compaction/summary') {
      // 上下文被压缩了一次（令 0329 P0）：记数；超过上限时记一条，下一步收尾
      if (state.noteCompaction()) this.log('warn', 'agent.compaction_loop', { compactions: state.compactions, model_calls: state.modelCalls })
    } else if (event.type === 'turn/end') {
      await this.endTask(sessionId, state, event.data?.reason?.kind ?? 'error')
    }
  }
}

type Ctx = {
  on(event: string, fn: (...a: never[]) => unknown, opts?: { prepend?: boolean }): void
  get?(name: string): unknown
  tools: { register(def: unknown): () => void }
  lawbenchCore: { endpoint(): Endpoint | undefined; noteTurnBlocked?(sessionId: string, code: string, taskId?: string): void; clearTurnBlocked?(sessionId: string): void; sheetHeld?(sessionId: string): boolean }
  effect(fn: () => () => void, label?: string): void
  logger?(name: string): { info(...a: unknown[]): void; warn(...a: unknown[]): void; error(...a: unknown[]): void }
}

export function apply(ctx: Ctx, config: Config = {}): void {
  const log: Logger = makeLogger('agent', config.appData ?? defaultAppData(), ctx.logger?.('lawbench-agent'))
  const core = new CoreClient(() => ctx.lawbenchCore.endpoint(), log, config.validateContracts ?? true)
  type Store = { caseMoved?(id: string): boolean; releaseMoved?(id: string): Promise<void> } | undefined
  const store = (): Store => ctx.get?.('sessionPersistence') as Store
  const caseMoved = (sessionId: string): boolean => store()?.caseMoved?.(sessionId) === true
  const agent = new LegalAgent(core, log,
    (sessionId, code, taskId) => ctx.lawbenchCore.noteTurnBlocked?.(sessionId, code, taskId),
    (sessionId) => ctx.lawbenchCore.clearTurnBlocked?.(sessionId),
    caseMoved,
    (sessionId) => ctx.lawbenchCore.sheetHeld?.(sessionId) === true)

  for (const tool of TOOL_NAMES) {
    ctx.effect(() => ctx.tools.register({
      name: tool,
      description: toolDescription(tool),
      parameters: toolParameters(tool),
      // Q6：DSH 的 output.schema 只接受受限写法，契约的 result 过不去；这里用宽松写法，结果由 executeTool 按契约校验
      output: { schema: { type: 'object' }, render: (_args: unknown, value: unknown) => [{ type: 'text', text: JSON.stringify(value) }] },
      execute: (args: unknown, exec: { agent?: { id: string } }) => agent.executeTool(exec?.agent?.id, tool, args),
    }), `lawbench-agent: tool ${tool}`)
  }

  ctx.on('agent/pre-step', (async (payload: { agent: AgentLike; step: number }, next: () => Promise<PreStepDecision>) =>
    agent.preStep(payload.agent, payload.step, await next())) as never)

  // 会话所在的案件文件夹已不在原位置（N55 ②）：排在最前，不调 next() 直接整轮拒绝。别的 pre-step 可能先动存储——
  // DSH 生产插件树里的 session-checkpoint-policy 每步前先 sessions.flush，搬家后旧路径写不进去就抛错、整轮按 agent/error
  // 结束，走不到上面那个先 next() 再判的处理，律师只看到含完整路径的英文错（T17 第八轮复核 B-F1）。
  // 拒绝之前请会话存储放下还没落过盘的写入者（第十轮 R10-1：否则被拒这一轮的事件让原版把旧路径整条重建、写进去）
  ctx.on('agent/pre-step', (async (payload: { agent: AgentLike; step: number }, next: () => Promise<PreStepDecision>) => {
    if (payload.step !== 1 || !caseMoved(payload.agent.id)) return next()
    await store()?.releaseMoved?.(payload.agent.id).catch(() => undefined)
    return agent.rejectMoved(payload.agent.id)
  }) as never, { prepend: true })

  ctx.on('agent/request', (async (payload: { agent: AgentLike }, next: () => Promise<LlmCallConfig>) =>
    agent.request(payload.agent.id, await next())) as never)

  ctx.on('tools/pre-execute', (async (exec: { name: string; arguments?: unknown; agent?: { id: string } }, next: () => Promise<PreToolDecision>) => {
    const mine = agent.preTool(exec.agent?.id, exec.name, exec.arguments)
    return mine.kind === 'allow' ? next() : mine
  }) as never, { prepend: true })

  // 兜底：Agent 空闲时任务还挂着（没收到 turn/end）就登记结束。排在 turn/end 的处理之后：正常结束时任务已经摘掉，这里什么都不做
  ctx.on('agent/status', ((payload: { agent: AgentLike; status: string }) => {
    if (payload.status !== 'idle') return
    const left = agent.tasks.get(payload.agent.id)
    if (!left) return
    setTimeout(() => { void agent.onIdle(payload.agent.id, left).catch((e: unknown) => log('error', 'agent.idle_end_failed', { error: String((e as Error)?.message ?? e) })) }, 2000)
  }) as never)

  ctx.on('session/event', ((session: { id: string }, event: SessionEvent) => {
    void agent.onSessionEvent(session.id, event).catch((e: unknown) => log('error', 'agent.session_event_failed', { error: String((e as Error)?.message ?? e) }))
  }) as never)
}
