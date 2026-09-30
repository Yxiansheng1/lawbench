// 发一条指定文字的消息（第三步验收用），等 10 秒，报会话标题和最后一条回答的开头。
const text = process.argv[2]
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
const pos = JSON.parse(await evalv(`(() => { const r = document.querySelector('[data-composer-input]').getBoundingClientRect(); return JSON.stringify([r.x + r.width / 2, r.y + r.height / 2]) })()`))
for (const type of ['mouseMoved', 'mousePressed', 'mouseReleased']) await send('Input.dispatchMouseEvent', { type, x: pos[0], y: pos[1], button: 'left', clickCount: type === 'mouseMoved' ? 0 : 1 })
await send('Input.insertText', { text })
for (const type of ['rawKeyDown', 'keyUp']) await send('Input.dispatchKeyEvent', { type, key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13 })
await sleep(10000)
console.log(await evalv(`JSON.stringify({ answer: [...document.querySelectorAll('[data-chat-flow-kind="assistant-step"]')].at(-1)?.innerText.slice(0, 60) })`))
ws.close()
