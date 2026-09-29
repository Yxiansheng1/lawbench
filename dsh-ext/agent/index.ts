// Agent 插件 legal-agent（Spec 1.2、9.2、20.3、20.4；T7 步骤 2、执行令 Q5/Q6/Q9/Q10/Q11）。挂在 preset-lawbench 里。
import { randomUUID } from 'node:crypto'
import { TOOL_NAMES, toolDescription, toolId, toolParameters, validate } from '../shared/contracts.ts'
import { CoreClient, type Endpoint, type Logger } from '../shared/core-client.ts'
import { defaultAppData, makeLogger } from '../shared/file-log.ts'
import { ALLOWED_OTHER_TOOLS, TaskState, WRAP_UP_TEXT, reasoningEffort, type Budget, type Params } from './task-state.ts'

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
export const DENY_NO_TASK = '工作台服务未启动，请稍后重试'

type ContextValue = { l0: { text: string }; l1: { text: string; truncated: boolean; toc: Array<{ index: number; title: string; tokens: number }> } }

/** 与 DSH 无关的核心逻辑；apply() 只把它接到 DSH 的挂载点上。 */
export class LegalAgent {
  /** 以会话 ID（= agent.id）为键的当前任务。 */
  readonly tasks = new Map<string, TaskState>()

  constructor(private readonly core: CoreClient, private readonly log: Logger) {}

  /** agent/pre-step。step 1 取任务和上下文；每步检查模型调用预算。 */
  async preStep(agent: AgentLike, step: number, decision: PreStepDecision): Promise<PreStepDecision> {
    if (decision.kind === 'reject') return decision
    let state = this.tasks.get(agent.id)
    const added: UserMessage[] = []
    if (step === 1 || !state) {
      const begin = await this.core.call<{ task_id: string; params: Params; budget: Budget }>('task/begin', {
        session_id: agent.id, cwd: agent.session?.header?.cwd ?? '',
      })
      if (!begin.ok) {
        // Q11：取任务失败拒绝整轮（DSH 的 reject 不能附带消息，界面提示由 T13 做）
        this.log('warn', 'agent.task_begin_failed', { code: begin.error.code })
        this.tasks.delete(agent.id)
        return { kind: 'reject' }
      }
      state = new TaskState(begin.value.task_id, begin.value.budget, begin.value.params)
      this.tasks.set(agent.id, state)
      const ctxRes = await this.core.call<ContextValue>('context', { task_id: state.taskId })
      if (!ctxRes.ok) {
        this.log('warn', 'agent.context_failed', { code: ctxRes.error.code })
        this.tasks.delete(agent.id)
        return { kind: 'reject' }
      }
      const { l0, l1 } = ctxRes.value
      const sections = [{ name: '案件卡片（L0）', text: l0.text }, { name: '任务输入（L1）', text: l1.text }]
      if (l1.toc.length) {
        sections.push({ name: '未放入 L1 的输入（用 case_read_input 按序号读取）', text: l1.toc.map((t) => `${t.index}. ${t.title}（约 ${t.tokens} token）`).join('\n') })
      }
      added.push(snapshot(sections))
    }
    const d = state.beforeModelCall()
    if (d.kind === 'reject') {
      this.log('info', 'agent.model_budget', { reason: d.reason, model_calls: state.modelCalls })
      return { kind: 'reject' }
    }
    if (d.wrapUp) added.push(notice('lawbench-budget', '立即收尾', WRAP_UP_TEXT))
    return added.length ? { ...decision, messages: [...decision.messages, ...added] } : decision
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
  preTool(agentId: string | undefined, toolName: string): PreToolDecision {
    if (!ALLOWED_OTHER_TOOLS.has(toolName) && !/^case_[a-z_]+$/.test(toolName)) {
      this.log('warn', 'agent.tool_not_allowed', { tool: toolName }) // Spec 3.1：出现这条日志说明有工具漏进来
      return { kind: 'deny', reason: DENY_NOT_ALLOWED }
    }
    if (ALLOWED_OTHER_TOOLS.has(toolName)) return { kind: 'allow' }
    const state = agentId ? this.tasks.get(agentId) : undefined
    if (!state) return { kind: 'deny', reason: DENY_NO_TASK }
    const d = state.beforeTool(toolName)
    if (d.allow) return { kind: 'allow' }
    if (d.reason === 'tool_budget') this.log('info', 'agent.tool_budget', { tool_calls: state.toolCalls })
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
    return r.value
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
    } else if (event.type === 'turn/end') {
      this.tasks.delete(sessionId)
      await this.core.call('task/end', {
        task_id: state.taskId,
        reason: state.endReason(event.data?.reason?.kind ?? 'error'),
        model_calls: state.modelCalls,
        tool_calls: state.toolCalls,
        elapsed_s: state.elapsedSeconds(),
      })
    }
  }
}

type Ctx = {
  on(event: string, fn: (...a: never[]) => unknown, opts?: { prepend?: boolean }): void
  tools: { register(def: unknown): () => void }
  lawbenchCore: { endpoint(): Endpoint | undefined }
  effect(fn: () => () => void, label?: string): void
  logger?(name: string): { info(...a: unknown[]): void; warn(...a: unknown[]): void; error(...a: unknown[]): void }
}

export function apply(ctx: Ctx, config: Config = {}): void {
  const log: Logger = makeLogger('agent', config.appData ?? defaultAppData(), ctx.logger?.('lawbench-agent'))
  const core = new CoreClient(() => ctx.lawbenchCore.endpoint(), log, config.validateContracts ?? true)
  const agent = new LegalAgent(core, log)

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

  ctx.on('agent/request', (async (payload: { agent: AgentLike }, next: () => Promise<LlmCallConfig>) =>
    agent.request(payload.agent.id, await next())) as never)

  ctx.on('tools/pre-execute', (async (exec: { name: string; agent?: { id: string } }, next: () => Promise<PreToolDecision>) => {
    const mine = agent.preTool(exec.agent?.id, exec.name)
    return mine.kind === 'allow' ? next() : mine
  }) as never, { prepend: true })

  ctx.on('session/event', ((session: { id: string }, event: SessionEvent) => {
    void agent.onSessionEvent(session.id, event).catch((e: unknown) => log('error', 'agent.session_event_failed', { error: String((e as Error)?.message ?? e) }))
  }) as never)
}
