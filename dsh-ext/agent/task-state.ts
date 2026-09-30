// 单个任务（律师发起的一次请求）的计数、预算和进度文本（Spec 9.2；T7 执行令 Q9、Q10 裁决）。
// 纯逻辑，不依赖 DSH，便于测试。

export interface Budget { model_calls: number; tool_calls: number; minutes: number }
export interface Params { thinking: '关闭' | '低' | '中' | '高'; window: '32K' | '64K' | '128K'; max_tokens: number; temperature?: number }

/** 不计入工具预算、也不受其限制的工具（Spec 9.2）。 */
export const BUDGET_EXEMPT_TOOL = 'case_save_draft'
/** 放行但不计数的非 case_* 工具（Q10：只数 case_*）。 */
export const ALLOWED_OTHER_TOOLS: ReadonlySet<string> = new Set(['skill', 'ask_user_question'])

export const WRAP_UP_TEXT = '【立即收尾】本次任务的调用次数或时长即将用完。请停止新的查找，立即用 case_save_draft 保存已有成果。'

export type ToolDecision = { allow: true } | { allow: false; reason: string }
export type StepDecision = { kind: 'continue'; wrapUp: boolean } | { kind: 'reject'; reason: string }

export class TaskState {
  modelCalls = 0
  toolCalls = 0
  /** Q10：碰到过任一上限，结束原因一律报 budget。 */
  budgetHit = false
  private readonly texts: string[] = []
  private readonly startedAt: number
  private wrapUpSent = false

  constructor(
    readonly taskId: string,
    readonly budget: Budget,
    readonly params: Params,
    now: number = Date.now(),
  ) { this.startedAt = now }

  elapsedSeconds(now: number = Date.now()): number {
    return Math.max(0, Math.floor((now - this.startedAt) / 1000))
  }

  /**
   * 每步模型调用前（agent/pre-step）：超限拒绝；最后一次调用前要求注入"立即收尾"（只注一次）。
   * 通过时计一次模型调用。
   */
  beforeModelCall(now: number = Date.now()): StepDecision {
    const overTime = now - this.startedAt >= this.budget.minutes * 60_000
    if (this.modelCalls >= this.budget.model_calls || overTime) {
      this.budgetHit = true
      return { kind: 'reject', reason: overTime ? 'time' : 'model_calls' }
    }
    this.modelCalls += 1
    const lastCall = this.modelCalls === this.budget.model_calls
    const nearTime = now - this.startedAt >= (this.budget.minutes - 5) * 60_000
    const wrapUp = !this.wrapUpSent && (lastCall || nearTime)
    if (wrapUp) this.wrapUpSent = true
    return { kind: 'continue', wrapUp }
  }

  /**
   * 工具执行前（tools/pre-execute）：白名单 + 工具预算。
   * Q10：只数 case_*（case_save_draft 除外）；被拒绝的不计数。
   */
  beforeTool(name: string): ToolDecision {
    if (ALLOWED_OTHER_TOOLS.has(name)) return { allow: true }
    if (!/^case_[a-z_]+$/.test(name)) return { allow: false, reason: 'not_allowed' }
    if (name === BUDGET_EXEMPT_TOOL) return { allow: true }
    if (this.toolCalls >= this.budget.tool_calls) {
      this.budgetHit = true
      return { allow: false, reason: 'tool_budget' }
    }
    this.toolCalls += 1
    return { allow: true }
  }

  /**
   * 收到一条模型回复（session/event assistant/message）。
   * Q9：返回本任务到目前为止所有回复文本的拼接；这条回复没有正文时返回 undefined（不传）。
   */
  addReply(text: string): string | undefined {
    if (!text.trim()) return undefined
    this.texts.push(text)
    return this.texts.join('\n\n')
  }

  /** turn/end 的 reason.kind → /core/task/end 的 reason（Q10：碰到过上限报 budget）。 */
  endReason(kind: string): 'completed' | 'aborted' | 'blocked' | 'error' | 'max-tokens' | 'interrupted' | 'budget' {
    if (this.budgetHit) return 'budget'
    const known = ['completed', 'aborted', 'blocked', 'error', 'max-tokens', 'interrupted'] as const
    return (known as readonly string[]).includes(kind) ? (kind as (typeof known)[number]) : 'error'
  }
}

/** 界面思考档 → DSH reasoningEffort（路由里"高"再映射成 xhigh 发给 6000D）。 */
export function reasoningEffort(thinking: Params['thinking']): 'off' | 'low' | 'medium' | 'high' {
  return ({ 关闭: 'off', 低: 'low', 中: 'medium', 高: 'high' } as const)[thinking]
}
