// N41 入口核对（前后对照都用它）：输入 / 列出命令菜单；列出输入区下方的控件、设置导航；可选发一条消息。
// 用法：node n41-probe.mjs [send]
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
const key = async (k, code, vk, text) => { for (const type of ['rawKeyDown', ...(text ? ['char'] : []), 'keyUp']) await send('Input.dispatchKeyEvent', { type, key: k, code, windowsVirtualKeyCode: vk, ...(type === 'char' ? { text } : {}) }) }
await send('Page.bringToFront')
await send('Emulation.setFocusEmulationEnabled', { enabled: true })
const out = {}
const composer = () => evalv(`(() => { const r = document.querySelector('[data-composer-input]').getBoundingClientRect(); return JSON.stringify([r.x + r.width / 2, r.y + r.height / 2]) })()`)
const clickAt = async ([x, y]) => { for (const type of ['mouseMoved', 'mousePressed', 'mouseReleased']) await send('Input.dispatchMouseEvent', { type, x, y, button: 'left', clickCount: type === 'mouseMoved' ? 0 : 1 }) }
await clickAt(JSON.parse(await composer()))
// 输入区下方的按钮（权限、模型、计划、目标等入口）
out.composerControls = JSON.parse(await evalv(`JSON.stringify((() => { const c = document.querySelector('[data-composer-input]'); let box = c; for (let i = 0; i < 6 && box.parentElement; i++) box = box.parentElement; return [...box.querySelectorAll('button, [role=combobox], [role=button]')].map(b => (b.getAttribute('aria-label') || b.textContent || '').trim()).filter(Boolean) })())`))
await send('Input.insertText', { text: '/' })
await sleep(800)
out.slashMenu = JSON.parse(await evalv(`JSON.stringify([...document.querySelectorAll('[role=option], [role=menuitem]')].map(o => o.textContent.trim().replace(/\\s+/g, ' ')).slice(0, 40))`))
await key('Escape', 'Escape', 27)
await key('Backspace', 'Backspace', 8)
if (process.argv[2] === 'send') {
  await clickAt(JSON.parse(await composer()))
  await send('Input.insertText', { text: '请只回复"收到"。' })
  await key('Enter', 'Enter', 13, '\r')
  await sleep(8000)
  out.sent = true
}
console.log(JSON.stringify(out, null, 1))
ws.close()
