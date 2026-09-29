import { CoreClient } from '../shared/core-client.ts'
import { startFake, type Fake } from './helpers/fake.ts'

let fake: Fake
const logs: Array<[string, string, Record<string, unknown> | undefined]> = []
const log = (level: string, event: string, meta?: Record<string, unknown>) => { logs.push([level, event, meta]) }

beforeAll(async () => { fake = await startFake(18802) })
afterAll(() => fake.stop())

describe('CoreClient 对假服务', () => {
  it('task/begin → context → tool → progress → task/end 走通且都过契约校验', async () => {
    const c = new CoreClient(() => ({ port: fake.port, token: fake.token }), log)
    const b = await c.call<{ task_id: string }>('task/begin', { session_id: 's-1', cwd: 'D:\\案件\\测试' })
    expect(b.ok).toBe(true)
    const task_id = (b as { value: { task_id: string } }).value.task_id
    expect((await c.call('context', { task_id })).ok).toBe(true)
    const t = await c.call<{ materials: unknown[] }>('tool', { task_id, tool: 'case_list_materials', args: {} })
    expect(t.ok).toBe(true)
    expect((await c.call('progress', { task_id, text: '进行中', model_calls: 1, tool_calls: 1 })).ok).toBe(true)
    const e = await c.call<{ status: string }>('task/end', { task_id, reason: 'budget', model_calls: 1, tool_calls: 1, elapsed_s: 3 })
    expect(e).toEqual({ ok: true, value: { status: 'budget_stopped' } })
    expect(logs.filter(([l]) => l === 'error')).toEqual([])
  })

  it('请求不合契约时不发出，返回 INVALID_ARGUMENT', async () => {
    const c = new CoreClient(() => ({ port: fake.port, token: fake.token }), log)
    const r = await c.call('progress', { task_id: 'bad', text: 'x', model_calls: 0, tool_calls: 0 })
    expect(r).toEqual({ ok: false, error: { code: 'INVALID_ARGUMENT', message: '请求参数有误' } })
  })

  it('令牌错误（401）、没有端点、端口不通：都返回 SERVICE_UNAVAILABLE', async () => {
    const want = { ok: false, error: { code: 'SERVICE_UNAVAILABLE', message: '工作台服务未启动，请稍后重试' } }
    expect(await new CoreClient(() => ({ port: fake.port, token: 'wrong' }), log).call('task/begin', { session_id: 's', cwd: 'x' })).toEqual(want)
    expect(await new CoreClient(() => undefined, log).call('task/begin', { session_id: 's', cwd: 'x' })).toEqual(want)
    expect(await new CoreClient(() => ({ port: 18809, token: 'x' }), log).call('task/begin', { session_id: 's', cwd: 'x' })).toEqual(want)
  })

  it('日志只有元数据：不含 cwd、正文', () => {
    const text = JSON.stringify(logs)
    expect(text).not.toContain('案件')
    expect(text).not.toContain('进行中')
  })
})
