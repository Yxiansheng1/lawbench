// INPUT_CHANGED 桌面端核对：选胶囊 → 等写成 → 发一条（假服务的 /core/context 报 INPUT_CHANGED，整轮被拦下）→ 看输入区状态行。
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
const dockStatus = `(() => { const s = document.querySelector('select[aria-label="胶囊"]'); return s?.closest('div')?.parentElement?.querySelector('[role=status]')?.textContent ?? s?.closest('div')?.querySelector('[role=status]')?.textContent })()`
const pick = (value) => evalv(`(() => { const s = document.querySelector('select[aria-label="胶囊"]'); const set = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set; set.call(s, ${JSON.stringify(value)}); s.dispatchEvent(new Event('change', { bubbles: true })); return s.value })()`)
const out = []
out.push({ step: '挂上', status: await evalv(dockStatus) })
out.push({ step: '选合同审查', value: await pick('contract-review') })
await sleep(1500)
out.push({ step: '写成后', status: await evalv(dockStatus) })
const pos = JSON.parse(await evalv(`(() => { const r = document.querySelector('[data-composer-input]').getBoundingClientRect(); return JSON.stringify([r.x + r.width / 2, r.y + r.height / 2]) })()`))
for (const type of ['mouseMoved', 'mousePressed', 'mouseReleased']) await send('Input.dispatchMouseEvent', { type, x: pos[0], y: pos[1], button: 'left', clickCount: type === 'mouseMoved' ? 0 : 1 })
await send('Input.insertText', { text: '请只回复"收到"。' })
for (const type of ['rawKeyDown', 'keyUp']) await send('Input.dispatchKeyEvent', { type, key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13 })
for (const ms of [300, 1000, 3000, 6000]) { await sleep(ms); out.push({ step: `发送后 ${ms} ms 起`, status: await evalv(dockStatus) }) }
out.push({ step: '改选合同起草', value: await pick('contract-draft') })
await sleep(1500)
out.push({ step: '写成后', status: await evalv(dockStatus) })
console.log(JSON.stringify(out, null, 1))
ws.close()
