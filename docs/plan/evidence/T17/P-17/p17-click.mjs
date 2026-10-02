// P-17 桌面端实测：在最后一个助手回答里，对每个网址文字做左键、Ctrl+左键、中键、右键；再从页面里硬试 window.open、跳转、注入 <a target=_blank> 点击。
// 输出每一步后页面地址、调试目标列表；局域网探针的命中另看记录文件。
const list = async () => (await (await fetch('http://127.0.0.1:9222/json/list')).json())
const target = (await list()).find((t) => t.type === 'page' && t.url.startsWith('dsh-app://app'))
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
const evalv = async (expr) => (await send('Runtime.evaluate', { expression: expr, returnByValue: true, userGesture: true })).result.value
await send('Page.bringToFront')
await send('Emulation.setFocusEmulationEnabled', { enabled: true })
const answer = `[...document.querySelectorAll('[data-chat-flow-kind="assistant-step"]')].at(-1)`
const words = ['/md-link', '/bare-url', '/angle', '/inline-code', 'mailto:someone', 'someone@example.invalid）', '/ref-link']
const where = async (word) => JSON.parse(await evalv(`(() => {
  const root = ${answer}
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const i = n.data.indexOf(${JSON.stringify(word)})
    if (i < 0) continue
    const r = document.createRange(); r.setStart(n, i); r.setEnd(n, Math.min(n.data.length, i + 4))
    const b = r.getBoundingClientRect()
    n.parentElement.scrollIntoView({ block: 'center' })
    const b2 = r.getBoundingClientRect()
    return JSON.stringify({ x: b2.x + b2.width / 2, y: b2.y + b2.height / 2, tag: n.parentElement.tagName })
  }
  return 'null'
})()`))
const click = async (x, y, button, modifiers = 0) => {
  await send('Input.dispatchMouseEvent', { type: 'mouseMoved', x, y })
  await send('Input.dispatchMouseEvent', { type: 'mousePressed', x, y, button, clickCount: 1, modifiers })
  await send('Input.dispatchMouseEvent', { type: 'mouseReleased', x, y, button, clickCount: 1, modifiers })
}
const log = []
for (const word of words) {
  const p = await where(word)
  if (!p) { log.push({ word, found: false }); continue }
  for (const [name, button, mod] of [['左键', 'left', 0], ['Ctrl+左键', 'left', 2], ['中键', 'middle', 0], ['右键', 'right', 0]]) {
    await click(p.x, p.y, button, mod)
    await sleep(700)
    if (button === 'right') { for (const type of ['rawKeyDown', 'keyUp']) await send('Input.dispatchKeyEvent', { type, key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27 }) }
  }
  log.push({ word, tag: p.tag, url: await evalv('location.href') })
}
// 硬试：页面脚本直接开窗、跳转、点一个注入的外链
const forced = {}
forced.windowOpen = await evalv(`String(window.open('http://192.168.8.191:18999/forced-window-open', '_blank'))`)
await sleep(1500)
forced.mailOpen = await evalv(`String(window.open('mailto:someone@example.invalid'))`)
await sleep(1500)
forced.injected = await evalv(`(() => { const a = document.createElement('a'); a.href = 'http://192.168.8.191:18999/forced-anchor'; a.target = '_blank'; a.textContent = 'x'; document.body.appendChild(a); a.click(); a.remove(); return 'clicked' })()`)
await sleep(1500)
forced.navigate = await evalv(`(() => { try { location.assign('http://192.168.8.191:18999/forced-navigate'); return 'assigned' } catch (e) { return String(e) } })()`)
await sleep(2500)
forced.urlAfter = await evalv('location.href')
forced.targets = (await list()).map((t) => `${t.type} ${t.url}`)
console.log(JSON.stringify({ log, forced }, null, 2))
ws.close()
