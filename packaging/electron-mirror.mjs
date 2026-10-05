// Build-time only (packaging\build.ps1 'package' step): serve the locally cached Electron zip and its SHASUMS256.txt on
// 127.0.0.1 so DSH's prepare-runtime (@electron/get, via ELECTRON_MIRROR) needs no GitHub access. @electron/get fetches
// SHASUMS256.txt fresh on every run even on a cache hit; on a phone hotspot that request stalled (T20, 2026-10-04).
// Usage: node electron-mirror.mjs <root folder holding v<version>\> <port>
import { createReadStream, statSync } from 'node:fs'
import { createServer } from 'node:http'
import { join, normalize, sep } from 'node:path'

const [root, port] = process.argv.slice(2)
if (!root || !port) { console.error('usage: node electron-mirror.mjs <root> <port>'); process.exit(2) }
const base = normalize(root)

createServer((req, res) => {
  const rel = decodeURIComponent(new URL(req.url ?? '/', 'http://127.0.0.1').pathname).replace(/^\/+/, '')
  const file = normalize(join(base, rel))
  let ok = false
  try { ok = file.startsWith(base + sep) && statSync(file).isFile() } catch { ok = false }
  console.log(`[electron-mirror] ${req.method} /${rel} -> ${ok ? 200 : 404}`)
  if (req.method !== 'GET' || !ok) { res.writeHead(404); res.end(); return }
  res.writeHead(200, { 'content-length': statSync(file).size })
  createReadStream(file).pipe(res)
}).listen(Number(port), '127.0.0.1', () => console.log(`[electron-mirror] serving ${base} on 127.0.0.1:${port}`))
