// Agent 插件 → 工作台服务 /core/*（Spec 20.3）。
// - 请求头 Authorization: Bearer <LB_TOKEN>；只连 127.0.0.1。
// - 开发模式按契约校验请求和返回（T7 步骤 3）；校验不过记日志并按 INVALID_ARGUMENT / INTERNAL 处理。
// - 连不上、服务未启动：返回 SERVICE_UNAVAILABLE（Spec 20.1）。
import { coreId, validate } from './contracts.ts'

export type CoreCommand = 'task/begin' | 'context' | 'tool' | 'progress' | 'task/end'
export type CoreResult<T = unknown> = { ok: true; value: T } | { ok: false; error: { code: string; message: string } }

export interface Endpoint { port: number; token: string }
export type EndpointSource = () => Endpoint | undefined
export type Logger = (level: 'info' | 'warn' | 'error', event: string, meta?: Record<string, unknown>) => void

export const MESSAGES = {
  SERVICE_UNAVAILABLE: '工作台服务未启动，请稍后重试',
  INVALID_ARGUMENT: '请求参数有误',
  INTERNAL: '内部错误，请重试；多次出现请联系技术支持',
} as const

const SCHEMA_NAME: Record<CoreCommand, string> = {
  'task/begin': 'task_begin', context: 'context', tool: 'tool', progress: 'progress', 'task/end': 'task_end',
}

export class CoreClient {
  constructor(
    private readonly endpoint: EndpointSource,
    private readonly log: Logger,
    private readonly validateContracts = true,
    private readonly timeoutMs = 60_000,
  ) {}

  async call<T = unknown>(command: CoreCommand, body: Record<string, unknown>): Promise<CoreResult<T>> {
    const id = coreId(SCHEMA_NAME[command])
    if (this.validateContracts) {
      const errs = validate(id, 'request', body)
      if (errs.length) {
        this.log('error', 'core.request_contract', { command, errors: errs })
        return { ok: false, error: { code: 'INVALID_ARGUMENT', message: MESSAGES.INVALID_ARGUMENT } }
      }
    }
    const ep = this.endpoint()
    if (!ep) return { ok: false, error: { code: 'SERVICE_UNAVAILABLE', message: MESSAGES.SERVICE_UNAVAILABLE } }
    const started = Date.now()
    let res: Response
    try {
      res = await fetch(`http://127.0.0.1:${ep.port}/core/${command}`, {
        method: 'POST',
        headers: { 'content-type': 'application/json', authorization: `Bearer ${ep.token}` },
        body: JSON.stringify(body),
        redirect: 'error',
        signal: AbortSignal.timeout(this.timeoutMs),
      })
    } catch {
      this.log('warn', 'core.unreachable', { command })
      return { ok: false, error: { code: 'SERVICE_UNAVAILABLE', message: MESSAGES.SERVICE_UNAVAILABLE } }
    }
    let payload: unknown
    try { payload = await res.json() } catch { payload = undefined }
    // 日志只记元数据：命令、状态码、耗时、错误码（Spec 4.5）
    const code = (payload as CoreResult | undefined)?.ok === false ? (payload as { error: { code: string } }).error.code : undefined
    this.log('info', 'core.call', { command, status: res.status, ms: Date.now() - started, ...(code ? { code } : {}) })
    if (res.status === 401) return { ok: false, error: { code: 'SERVICE_UNAVAILABLE', message: MESSAGES.SERVICE_UNAVAILABLE } }
    if (payload === undefined) return { ok: false, error: { code: 'INTERNAL', message: MESSAGES.INTERNAL } }
    if (this.validateContracts) {
      const errs = validate(id, 'response', payload)
      if (errs.length) {
        this.log('error', 'core.response_contract', { command, errors: errs })
        return { ok: false, error: { code: 'INTERNAL', message: MESSAGES.INTERNAL } }
      }
    }
    return payload as CoreResult<T>
  }
}
