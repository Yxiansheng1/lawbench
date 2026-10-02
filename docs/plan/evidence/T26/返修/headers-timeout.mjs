// T26 复核 P2-1 复现与修后对照：本机服务回响应头前等 310 秒（模拟大批量发票 run 等引擎跑完），
// 分别用原来的 fetch + AbortSignal.timeout(35 分钟) 和现在的 requestJson（node:http，总时限 35 分钟）去调。
// 用法（dsh-ext 下）：node --experimental-strip-types ../docs/plan/evidence/T26/返修/headers-timeout.mjs
import { createServer } from 'node:http'
import { requestJson } from '../../../../../dsh-ext/host/http-json.ts'

const DELAY = 310_000
const server = createServer((req, res) => { setTimeout(() => { res.writeHead(200, { 'content-type': 'application/json' }); res.end('{"ok":true,"value":{}}') }, DELAY) })
await new Promise((r) => server.listen(0, '127.0.0.1', r))
const port = server.address().port
const t0 = Date.now()
const s = () => `${((Date.now() - t0) / 1000).toFixed(0)} 秒`
const old = fetch(`http://127.0.0.1:${port}/api/invoice/run`, { method: 'POST', body: '{}', signal: AbortSignal.timeout(35 * 60_000) })
  .then(async (r) => `原来（fetch）：${s()} 拿到回答 ${JSON.stringify(await r.json())}`, (e) => `原来（fetch）：${s()} 失败 ${e?.cause?.code ?? e?.name}`)
const now = requestJson({ method: 'POST', port, path: '/api/invoice/run', headers: {}, body: '{}', timeoutMs: 35 * 60_000 })
  .then((j) => `现在（requestJson）：${s()} 拿到回答 ${JSON.stringify(j)}`, (e) => `现在（requestJson）：${s()} 失败 ${e?.name}`)
console.log(`服务回头部前等 ${DELAY / 1000} 秒；${new Date().toISOString()} 开始`)
for (const line of await Promise.all([old, now])) console.log(line)
server.close()
