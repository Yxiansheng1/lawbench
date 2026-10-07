// Answer a pending required-question form (one or several questions, "下一题" between them, "提交" at the end):
// each question gets the "(推荐)" radio (else the first), or a fixed free-text reply.
import { connect, sleep } from './cdp.mjs'
export const FREE = '按任务说明里已经给出的办；没给的你按常规处理，并在草稿里标出待补。'
const state = (c) => c.evalv(`(() => {
  const vis = (e) => e.offsetParent !== null
  const btn = (t) => [...document.querySelectorAll('button')].filter((b) => vis(b) && b.innerText.trim() === t && !b.disabled).length
  const rs = [...document.querySelectorAll('button[role=radio]')].filter(vis)
  const ta = [...document.querySelectorAll('textarea')].filter((e) => vis(e) && e.placeholder === '输入你的答案')
  const q = [...document.querySelectorAll('button')].filter((b) => vis(b) && b.innerText.startsWith('等待你的操作')).map((b) => b.innerText.replace('等待你的操作 · ', '').slice(0, 120)).at(-1) ?? ''
  const any = [...document.querySelectorAll('button')].filter((b) => vis(b) && ['提交', '下一题'].includes(b.innerText.trim())).length
  return JSON.stringify({ q, radios: rs.map((r) => r.innerText.slice(0, 80)), ta: ta.length, ta_empty: ta.length ? !ta[0].value : false, next: btn('下一题'), sub: btn('提交'), any })
})()`).then(JSON.parse)

export async function answerOnce(c) {
  let s = await state(c)
  if (!s.any) return null
  const out = []
  const q0 = s.q
  for (let k = 0; k < 10; k++) {
    for (let w = 0; w < 6 && !s.radios.length && !(s.ta && s.ta_empty); w++) { await sleep(500); s = await state(c) }
    if (s.radios.length) {
      let i = s.radios.findIndex((t) => t.includes('推荐'))
      if (i < 0) i = 0
      const pos = await c.evalv(`(() => { const r = [...document.querySelectorAll('button[role=radio]')].filter((e) => e.offsetParent !== null)[${i}]; r.scrollIntoView({ block: 'center' }); const b = r.getBoundingClientRect(); return [b.x + b.width / 2, b.y + b.height / 2] })()`)
      await c.clickAt(pos[0], pos[1])
      out.push('radio:' + s.radios[i].replace(/\n/g, ' ').slice(0, 50))
    } else if (s.ta && s.ta_empty) {
      await c.click('textarea[placeholder="输入你的答案"]')
      await c.type(FREE)
      out.push('text')
    }
    await sleep(500)
    s = await state(c)
    if (s.next) { await c.clickText('下一题'); await sleep(800); s = await state(c); continue }
    if (s.sub) { await c.clickText('提交'); break }
    break
  }
  return 'Q[' + q0 + '] ' + out.join(' / ')
}
if (process.argv[1]?.endsWith('answer.mjs')) { const c = await connect(); console.log(await answerOnce(c)); c.close() }
