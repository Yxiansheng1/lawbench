// CDP helper for T18 runs (line B). Port 9322. Usage: node cdp.mjs <cmd> [args]
//   eval "<js>"            evaluate in the first dsh-app page, print JSON
//   shot <file.png>        screenshot
//   click "<css>" [index]  click element center
//   type "<text>"          insert text at focus
//   key Enter
import { writeFileSync, readFileSync } from 'node:fs'
const PORT = process.env.CDP_PORT ?? '9322'
export async function connect(match = (t) => t.type === 'page' && t.url.startsWith('dsh-app://app')) {
  const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json()
  const target = list.find(match)
  if (!target) throw new Error('no target: ' + JSON.stringify(list.map((t) => t.url)))
  const ws = new WebSocket(target.webSocketDebuggerUrl)
  await new Promise((r) => ws.addEventListener('open', r))
  let id = 0
  const send = (method, params = {}) => new Promise((res, rej) => {
    const my = ++id
    const on = (ev) => { const m = JSON.parse(ev.data); if (m.id === my) { ws.removeEventListener('message', on); m.error ? rej(new Error(m.error.message)) : res(m.result) } }
    ws.addEventListener('message', on)
    ws.send(JSON.stringify({ id: my, method, params }))
  })
  const evalv = async (expr, awaitPromise = true) => {
    const r = await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise })
    if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description ?? r.exceptionDetails.text)
    return r.result.value
  }
  const clickAt = async (x, y) => {
    for (const type of ['mouseMoved', 'mousePressed', 'mouseReleased']) await send('Input.dispatchMouseEvent', { type, x, y, button: 'left', clickCount: type === 'mouseMoved' ? 0 : 1 })
  }
  const click = async (css, index = 0) => {
    const pos = await evalv(`(() => { const e = document.querySelectorAll(${JSON.stringify(css)})[${index}]; if (!e) return null; e.scrollIntoView({block:'center'}); const r = e.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2] })()`)
    if (!pos) throw new Error('not found: ' + css)
    await clickAt(pos[0], pos[1])
  }
  const clickText = async (text, sel = 'button,[role=button],[role=option],[role=menuitem],[role=tab],a,label') => {
    const pos = await evalv(`(() => { const want = ${JSON.stringify(text)}; const els = [...document.querySelectorAll(${JSON.stringify(sel)})].filter((e) => e.offsetParent !== null && e.innerText.trim() === want); const e = els.at(-1); if (!e) return null; e.scrollIntoView({block:'center'}); const r = e.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2] })()`)
    if (!pos) throw new Error('no element with text: ' + text)
    await clickAt(pos[0], pos[1])
  }
  const type = (text) => send('Input.insertText', { text })
  const key = async (k) => { for (const t of ['rawKeyDown', 'keyUp']) await send('Input.dispatchKeyEvent', { type: t, key: k, code: k, windowsVirtualKeyCode: k === 'Enter' ? 13 : k === 'Escape' ? 27 : 0 }) }
  const shot = async (file) => { const r = await send('Page.captureScreenshot', { format: 'png' }); writeFileSync(file, Buffer.from(r.data, 'base64')) }
  await send('Emulation.setFocusEmulationEnabled', { enabled: true })
  return { send, evalv, click, clickAt, clickText, type, key, shot, close: () => ws.close() }
}
export const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

if (process.argv[1] && import.meta.url === `file:///${process.argv[1].replace(/\\/g, '/')}`) {
  const [cmd, a, b] = process.argv.slice(2)
  const c = await connect()
  if (cmd === 'eval') console.log(JSON.stringify(await c.evalv(a), null, 1))
  else if (cmd === 'shot') await c.shot(a)
  else if (cmd === 'click') await c.click(a, Number(b ?? 0))
  else if (cmd === 'clickText') await c.clickText(a)
  else if (cmd === 'type') await c.type(a)
  else if (cmd === 'key') await c.key(a)
  c.close()
}
