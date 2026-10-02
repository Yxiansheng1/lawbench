// INPUT_CHANGED 返修后桌面端：被拦下 → 切到另一个会话 → 切回，提示仍在（按会话存在 store）。输出 JSON 写文件（避免控制台编码乱码）。
import { writeFileSync } from 'node:fs'
const out = process.argv[2]
const list = await (await fetch('http://127.0.0.1:9222/json/list')).json()
const target = list.find((t) => t.type === 'page' && t.url.startsWith('dsh-app://app'))
const ws = new WebSocket(target.webSocketDebuggerUrl)
await new Promise((r) => ws.addEventListener('open', r))
let id = 0
const send = (method, params = {}) => new Promise((res, rej) => {
  const my = ++id
  const on = (ev) => { const m = JSON.parse(ev.data); if (m.id === my) { ws.removeEventListener('message', on); m.error ? rej(new Error(m.error.message)) : res(m.result) } }
  ws.addEventListener('message', on)
  ws.send(JSON.stringify({ id: my, method, params }))
})
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const evalv = async (expr) => (await send('Runtime.evaluate', { expression: expr, returnByValue: true })).result.value
await send('Page.bringToFront')
await send('Emulation.setFocusEmulationEnabled', { enabled: true })
const dockStatus = `(() => { const s = document.querySelector('select[aria-label="胶囊"]'); return s?.closest('div')?.parentElement?.querySelector('[role=status]')?.textContent ?? null })()`
const clickSession = (prefix) => evalv(`(() => { const items = [...document.querySelectorAll('[role=treeitem]')].filter(e => e.innerText.trim().startsWith(${JSON.stringify(prefix)}) && /分钟|刚刚|小时/.test(e.innerText)); const el = items.at(-1); if (!el) return 'no'; el.click(); return 'ok ' + items.length })()`)
const res = []
const pos = JSON.parse(await evalv(`(() => { const r = document.querySelector('[data-composer-input]').getBoundingClientRect(); return JSON.stringify([r.x + r.width / 2, r.y + r.height / 2]) })()`))
for (const type of ['mouseMoved', 'mousePressed', 'mouseReleased']) await send('Input.dispatchMouseEvent', { type, x: pos[0], y: pos[1], button: 'left', clickCount: type === 'mouseMoved' ? 0 : 1 })
await send('Input.insertText', { text: '请只回复"收到"。' })
for (const type of ['rawKeyDown', 'keyUp']) await send('Input.dispatchKeyEvent', { type, key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13 })
await sleep(2500)
res.push({ step: '被拦下后', status: await evalv(dockStatus) })
res.push({ step: '切到另一个会话', click: await clickSession('criminal-01') })
await sleep(2500)
res.push({ step: '另一个会话里', title: await evalv('document.querySelector(\'[data-composer-input]\') ? document.title : null'), status: await evalv(dockStatus) })
{ const s = await send('Page.captureScreenshot', { format: 'png' }); writeFileSync(out.replace(/\.json$/, '-other.png'), Buffer.from(s.data, 'base64')) }
res.push({ step: '切回', click: await clickSession('请阅卷（虚构测试）') })
await sleep(2500)
res.push({ step: '切回后', status: await evalv(dockStatus) })
const shot = await send('Page.captureScreenshot', { format: 'png' })
writeFileSync(out.replace(/\.json$/, '.png'), Buffer.from(shot.data, 'base64'))
writeFileSync(out, JSON.stringify(res, null, 1), 'utf8')
ws.close()
