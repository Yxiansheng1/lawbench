import { TaskState, reasoningEffort } from '../agent/task-state.ts'

const params = { thinking: '中', window: '64K', max_tokens: 16384 } as const
const mk = (b = { model_calls: 8, tool_calls: 24, minutes: 45 }, now = 0) => new TaskState('T-20260929230000-abcd', b, params, now)

describe('工具预算（Spec 9.2，Q10）', () => {
  it('第 25 次 case_* 被拒绝，case_save_draft 仍可调用', () => {
    const s = mk()
    for (let i = 0; i < 24; i++) expect(s.beforeTool('case_read_material')).toEqual({ allow: true })
    expect(s.beforeTool('case_search')).toEqual({ allow: false, reason: 'tool_budget' })
    expect(s.beforeTool('case_save_draft')).toEqual({ allow: true })
    expect(s.beforeTool('case_save_draft')).toEqual({ allow: true })
    expect(s.toolCalls).toBe(24)
  })

  it('case_save_draft、skill、ask_user_question 不计数', () => {
    const s = mk()
    s.beforeTool('case_save_draft'); s.beforeTool('skill'); s.beforeTool('ask_user_question')
    expect(s.toolCalls).toBe(0)
  })

  it('白名单以外的工具拒绝且不计数', () => {
    const s = mk()
    for (const t of ['run_code', 'bash', 'fs_read', 'web_fetch', 'Case_x', 'case-x']) {
      expect(s.beforeTool(t)).toEqual({ allow: false, reason: 'not_allowed' })
    }
    expect(s.toolCalls).toBe(0)
    expect(s.budgetHit).toBe(false)
  })

  it('被拒绝的调用不计数', () => {
    const s = mk({ model_calls: 8, tool_calls: 2, minutes: 45 })
    s.beforeTool('case_search'); s.beforeTool('case_search'); s.beforeTool('case_search'); s.beforeTool('case_search')
    expect(s.toolCalls).toBe(2)
  })
})

describe('模型调用预算与立即收尾', () => {
  it('8 次后拒绝；第 8 次前要求注入立即收尾，且只注一次', () => {
    const s = mk()
    const wraps: boolean[] = []
    for (let i = 0; i < 8; i++) {
      const d = s.beforeModelCall(1000)
      expect(d.kind).toBe('continue')
      wraps.push(d.kind === 'continue' && d.wrapUp)
    }
    expect(wraps).toEqual([false, false, false, false, false, false, false, true])
    expect(s.beforeModelCall(1000)).toEqual({ kind: 'reject', reason: 'model_calls' })
    expect(s.modelCalls).toBe(8)
  })

  it('超时拒绝；最后 5 分钟内要求收尾', () => {
    const s = mk({ model_calls: 8, tool_calls: 24, minutes: 45 }, 0)
    expect(s.beforeModelCall(41 * 60_000)).toEqual({ kind: 'continue', wrapUp: true })
    expect(s.beforeModelCall(45 * 60_000)).toEqual({ kind: 'reject', reason: 'time' })
  })
})

describe('结束原因', () => {
  it('碰到过上限一律报 budget', () => {
    const s = mk({ model_calls: 1, tool_calls: 1, minutes: 45 })
    s.beforeModelCall(0); s.beforeModelCall(0)
    expect(s.endReason('completed')).toBe('budget')
    expect(s.endReason('blocked')).toBe('budget')
  })
  it('没碰到上限时原样传；未知类别报 error', () => {
    const s = mk()
    for (const k of ['completed', 'aborted', 'blocked', 'error', 'max-tokens', 'interrupted']) expect(s.endReason(k)).toBe(k)
    expect(s.endReason('something-new')).toBe('error')
  })
})

describe('进度文本（Q9）', () => {
  it('传到目前为止的全部回复拼接；空文本不传', () => {
    const s = mk()
    expect(s.addReply('第一段')).toBe('第一段')
    expect(s.addReply('  ')).toBeUndefined()
    expect(s.addReply('第二段')).toBe('第一段\n\n第二段')
  })
})

describe('思考档映射', () => {
  it('关闭/低/中/高 → off/low/medium/high', () => {
    expect(['关闭', '低', '中', '高'].map((t) => reasoningEffort(t as '中'))).toEqual(['off', 'low', 'medium', 'high'])
  })
})
