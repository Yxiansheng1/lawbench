// T7 返修 P2-1：/core/* 返回和工具结果不合契约时必须被拦下（去掉校验时本文件应当变红）。
import { LegalAgent } from '../agent/index.ts'
import { TaskState } from '../agent/task-state.ts'
import { CoreClient } from '../shared/core-client.ts'
import { startFake, type Fake } from './helpers/fake.ts'

let bad: Fake
const logs: Array<[string, string, Record<string, unknown> | undefined]> = []
const log = (level: 'info' | 'warn' | 'error', event: string, meta?: Record<string, unknown>) => { logs.push([level, event, meta]) }

beforeAll(async () => { bad = await startFake(18809, ['--bad-response']) })
afterAll(() => bad.stop())
beforeEach(() => { logs.length = 0 })

const client = () => new CoreClient(() => ({ port: bad.port, token: bad.token }), log)
const INTERNAL = { ok: false, error: { code: 'INTERNAL', message: '内部错误，请重试；多次出现请联系技术支持' } }

describe('CoreClient：返回不合契约', () => {
  it('task/begin 返回缺 task_id → INTERNAL，并记 core.response_contract', async () => {
    expect(await client().call('task/begin', { session_id: 's', cwd: 'x' })).toEqual(INTERNAL)
    expect(logs.some(([l, e, m]) => l === 'error' && e === 'core.response_contract' && m?.command === 'task/begin')).toBe(true)
  })

  it('progress 返回多出契约没有的字段 → INTERNAL', async () => {
    expect(await client().call('progress', { task_id: 'T-20260930010000-abcd', text: 'x', model_calls: 1, tool_calls: 0 })).toEqual(INTERNAL)
    expect(logs.some(([, e, m]) => e === 'core.response_contract' && m?.command === 'progress')).toBe(true)
  })

  it('日志里只有路径和规则，没有返回的内容', async () => {
    await client().call('task/begin', { session_id: 's', cwd: 'D:\\案件\\某某' })
    expect(JSON.stringify(logs)).not.toContain('案件')
  })
})

describe('executeTool：工具结果不合工具契约', () => {
  it('case_list_materials 结果缺 materials → 抛内部错误，并记 agent.tool_result_contract', async () => {
    const a = new LegalAgent(client(), log)
    a.tasks.set('s-bad', new TaskState('T-20260930010000-abcd', { model_calls: 8, tool_calls: 24, minutes: 45 }, { thinking: '中', window: '64K', max_tokens: 16384 }))
    await expect(a.executeTool('s-bad', 'case_list_materials', {})).rejects.toThrow('内部错误')
    expect(logs.some(([l, e, m]) => l === 'error' && e === 'agent.tool_result_contract' && m?.tool === 'case_list_materials')).toBe(true)
  })
})
