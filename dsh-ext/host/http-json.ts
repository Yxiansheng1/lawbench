// Host 调本机工作台服务 /api 的请求（T26 复核 P2-1）。不用全局 fetch：Node 的 fetch（undici）默认等响应头最多 300 秒
// （headersTimeout），服务要等引擎跑完才回头部，发票 run、env_check --deep --ocr、归档、大批导入超过 5 分钟就被掐断，
// 界面报"工作台服务不可用"而服务照跑、结果丢。这里用 node:http，只有调用方给的总时限（路由表的 timeoutMs），没有另外的头部时限。
// 只连 127.0.0.1；不跟随重定向（3xx 当失败，同 fetch 的 redirect: 'error'）。
// 别名导入：打包时顶层有了名为 request 的绑定，esbuild 会把 Host 方法的形参 request 改名成 request2，DSH 网关按形参名
// 取参数，所有带 request 的方法都对不上（T26 第 3 步桌面端实测；scripts/build.mjs 构建后核对形参名）
import { request as httpRequest } from 'node:http'

/** 超过总时限（name 同 AbortSignal.timeout 抛的 TimeoutError，调用方据此报 TIMEOUT）。 */
export class RequestTimeout extends Error {
  override name = 'TimeoutError'
  constructor() { super('request timed out') }
}

export interface JsonRequest {
  method: 'GET' | 'PUT' | 'POST'
  port: number
  path: string
  headers: Record<string, string>
  body?: string
  /** 从发出到读完回答的总时限（毫秒）。 */
  timeoutMs: number
}

/** 发一次请求，读完回答按 JSON 解析（不看状态码，服务的失败也是 JSON）。 */
export function requestJson(req: JsonRequest): Promise<unknown> {
  return new Promise((resolve, reject) => {
    let settled = false
    const finish = (fn: () => void) => { if (!settled) { settled = true; clearTimeout(timer); fn() } }
    const r = httpRequest({ host: '127.0.0.1', port: req.port, path: req.path, method: req.method, headers: req.headers }, (res) => {
      if ((res.statusCode ?? 0) >= 300 && (res.statusCode ?? 0) < 400) { res.resume(); finish(() => reject(new Error('redirect refused'))); return }
      const chunks: Buffer[] = []
      res.on('data', (c: Buffer) => chunks.push(c))
      res.on('error', (e) => finish(() => reject(e)))
      res.on('end', () => finish(() => {
        try { resolve(JSON.parse(Buffer.concat(chunks).toString('utf8'))) } catch (e) { reject(e) }
      }))
    })
    const timer = setTimeout(() => { finish(() => reject(new RequestTimeout())); r.destroy() }, req.timeoutMs)
    r.on('error', (e) => finish(() => reject(e)))
    if (req.body !== undefined) r.write(req.body)
    r.end()
  })
}
