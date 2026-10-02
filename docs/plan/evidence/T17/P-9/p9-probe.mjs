// P-9 实测用：只在本机局域网地址上监听（不是 127.0.0.1，回环会被白名单放行，测不出来），记下每个收到的请求（方法、路径），回一张 1x1 PNG。
// 用法：node p9-probe.mjs <局域网 IP> <端口> <记录文件>
import http from 'node:http'
import { appendFileSync } from 'node:fs'
const [, , ip, port, out] = process.argv
const PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==', 'base64')
http.createServer((req, res) => {
  appendFileSync(out, JSON.stringify({ time: new Date().toISOString(), method: req.method, url: req.url }) + '\n')
  if (req.url.includes('.png')) { res.writeHead(200, { 'content-type': 'image/png' }); res.end(PNG); return }
  if (req.url.includes('.css')) { res.writeHead(200, { 'content-type': 'text/css' }); res.end('body{}'); return }
  if (req.url.includes('.js')) { res.writeHead(200, { 'content-type': 'text/javascript' }); res.end(''); return }
  res.writeHead(200, { 'content-type': 'text/plain' }); res.end('ok')
}).listen(Number(port), ip, () => console.log(`probe on ${ip}:${port}`))
