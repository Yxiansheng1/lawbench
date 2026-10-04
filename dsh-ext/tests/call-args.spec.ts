// 界面调 Host 方法时的参数个数（改版第 4 条真机截图时发现）：DSH 网关客户端按方法表核对个数，没有参数的方法多传一个 undefined
// 就报"expected 0 argument(s), got 1"——启动检查提示条（selfCheck）和日常事务（dailyCase）一直取不到。这里照网关的核对做假接口。
import { REMOTE_METHODS } from '../shared/remote-methods.ts'
import { call, setApi, type LawbenchApi } from '../ui/state.ts'

afterEach(() => setApi(undefined))

/** 照 dsh api-gateway client 的 prepare：个数不对就抛英文错误。 */
function gatewayLike(): LawbenchApi {
  const api: Record<string, (...a: unknown[]) => Promise<unknown>> = {}
  for (const { method, params } of REMOTE_METHODS) {
    api[method] = async (...values: unknown[]) => {
      if (values.length !== params.length) throw new Error(`client api: lawbench/${method} expected ${params.length} argument(s), got ${values.length}`)
      return { ok: true, value: { method } }
    }
  }
  return api as unknown as LawbenchApi
}

describe('call 的参数个数与方法表一致', () => {
  it('没有参数的方法不多传 undefined；带 request 的照传', async () => {
    setApi(gatewayLike())
    for (const m of ['selfCheck', 'dailyCase']) expect(await call(m)).toEqual({ ok: true, value: { method: m } })
    expect(await call('getCapsules')).toEqual({ ok: true, value: { method: 'getCapsules' } })
    expect(await call('caseRecent', {})).toEqual({ ok: true, value: { method: 'caseRecent' } })
  })
})
