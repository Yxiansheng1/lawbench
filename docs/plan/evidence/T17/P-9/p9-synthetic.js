(async () => {
  const B = 'http://192.168.8.191:18999'
  const out = {}
  const img = new Image(); img.src = B + '/syn-image.png'
  const box = document.createElement('div'); box.setAttribute('data-chat-flow-kind', 'assistant-step'); box.innerHTML = '<p>合成回答块 <img src="' + B + '/syn-answer.png"></p>'; document.body.appendChild(box)
  const link = document.createElement('link'); link.rel = 'stylesheet'; link.href = B + '/syn-style.css'; document.head.appendChild(link)
  const s = document.createElement('script'); s.src = B + '/syn-script.js'; document.head.appendChild(s)
  const st = document.createElement('style'); st.textContent = '@font-face{font-family:p9;src:url(' + B + '/syn-font.woff2)} .p9{font-family:p9;background:url(' + B + '/syn-bg.png)}'; document.head.appendChild(st)
  const d = document.createElement('div'); d.className = 'p9'; d.textContent = 'x'; document.body.appendChild(d)
  try { await fetch(B + '/syn-fetch'); out.fetch = 'ok' } catch (e) { out.fetch = String(e) }
  try { const w = new WebSocket('ws://192.168.8.191:18999/syn-ws'); await new Promise((r) => { w.onerror = () => { out.ws = 'error'; r() }; w.onopen = () => { out.ws = 'open'; r() }; setTimeout(r, 2000) }) } catch (e) { out.ws = String(e) }
  const f = document.createElement('iframe'); f.src = B + '/syn-iframe'; document.body.appendChild(f)
  await new Promise((r) => setTimeout(r, 2500))
  // 应用自己的资源照常：data: 图片、Host
  const di = new Image(); di.src = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=='
  await new Promise((r) => { di.onload = () => { out.dataImage = 'loaded'; r() }; di.onerror = () => { out.dataImage = 'error'; r() }; setTimeout(r, 1000) })
  out.img = img.complete && img.naturalWidth > 0 ? 'loaded' : 'not loaded'
  for (const el of [box, link, s, st, d, f]) el.remove()
  return JSON.stringify(out)
})()
