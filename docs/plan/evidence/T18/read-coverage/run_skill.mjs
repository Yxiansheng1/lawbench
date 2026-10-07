// T18 runner: one skill end to end through the desktop UI (real DSH agent, real 6000D).
// node run_skill.mjs <skill> <capsule> <case_root> <task text file> [--no-open]
// Opens the case from 首页, picks capsule + Skill, sends the task, answers required questions
// (recommended option, else first; free text gets a fixed reply), waits until the service reports the
// task finished (or 50 min). Prints a JSON summary (no material text).
import { readFileSync, writeFileSync } from 'node:fs'
import { connect, sleep } from './cdp.mjs'
import { answerOnce } from './answer.mjs'

const [skill, capsule, rootArg, taskFile, flag] = process.argv.slice(2)
const root = rootArg.replaceAll('/', String.fromCharCode(92))
const text = readFileSync(taskFile, 'utf8').trim()
const svc = JSON.parse(readFileSync('D:/lawbench-T18/svc.json', 'utf8'))
const api = async (path) => (await (await fetch(`http://127.0.0.1:${svc.port}${path}`, { headers: { Authorization: `Bearer ${svc.token}` } })).json())
const caseId = (await api('/api/case/recent')).value.cases.find((x) => x.root.toLowerCase() === root.toLowerCase())?.case_id
if (!caseId) throw new Error('case not registered: ' + root)

let c = await connect()
const t0 = Date.now()
const log = []
const note = (m) => { const s = `${((Date.now() - t0) / 1000).toFixed(0)}s ${m}`; log.push(s); console.error(s) }
const attach = flag === '--attach'
if (flag !== '--no-open' && !attach) {
  await c.send('Page.reload'); c.close(); await sleep(7000); c = await connect()
  await c.clickText('首页')
  const waitFor = async (expr, ms = 30000) => { const end = Date.now() + ms; while (Date.now() < end) { const v = await c.evalv(expr); if (v) return v; await sleep(500) } return null }
  const pos = await waitFor(`(() => { const name = ${JSON.stringify(root.split(String.fromCharCode(92)).pop())}; const b = document.querySelector('[role=button][aria-label="进入' + name + '"]'); if (!b) return null; b.scrollIntoView({block: 'center'}); const r = b.getBoundingClientRect(); return [r.x + 30, r.y + 15] })()`)
  if (!pos) throw new Error('no 进入 for ' + root)
  await c.clickAt(pos[0], pos[1])
  if (!await waitFor(`!!document.querySelector('[data-composer-input]')`)) throw new Error('session page not ready')
  await sleep(1500)
  note('case opened')
}
const setSel = (label, value) => c.evalv(`(() => { const s = document.querySelector('select[aria-label="${label}"]'); if (!s) return 'no select'; const set = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set; set.call(s, ${JSON.stringify(value)}); s.dispatchEvent(new Event('change', { bubbles: true })); return s.value })()`)
const before = new Set(attach ? [] : ((await api(`/api/tasks?case_id=${caseId}`)).value?.tasks ?? []).map((t) => t.task_id))
if (!attach) {
  // 2026-10 起胶囊是"分组标签 ▾ → 胶囊按钮"（线 A 第一批反馈改版）
  const CAPS = { 'contract-review': ['民事与商事 ▾', '合同审查'], 'contract-draft': ['民事与商事 ▾', '合同起草'], 'litigation-docs': ['民事与商事 ▾', '诉讼文书起草'],
    'case-analysis': ['刑事案件 ▾', '案卷分析'], 'sentence-calc': ['刑事案件 ▾', '刑期计算'], 'bail-application': ['刑事案件 ▾', '取保候审/不予逮捕申请'],
    'defense-opinion': ['刑事案件 ▾', '辩护词起草'], 'cross-exam': ['刑事案件 ▾', '质证意见起草'], 'lawyer-letter': ['日常办公 ▾', '律师函起草'],
    'bidding': ['日常办公 ▾', '招投标材料处理'], 'archiving': ['日常办公 ▾', '案卷归档'], 'general-docs': ['日常办公 ▾', '通用文书'] }
  const [grp, label] = CAPS[capsule]
  await c.clickText(grp, 'button,[role=tab]'); await sleep(800)
  await c.clickText(label, 'button,[role=button]'); await sleep(1200)
  note('capsule ' + label)
  for (let i = 0; i < 40 && await setSel('Skill', skill) !== skill; i++) await sleep(500)
  note('skill ' + await setSel('Skill', skill)); await sleep(2000)
  await c.click('[data-composer-input]'); await c.type(text); await c.key('Enter')
  note('sent')
}
const answers = []
let task = null
const deadline = t0 + 30 * 60 * 1000
while (Date.now() < deadline) {
  await sleep(10000)
  try { const a = await answerOnce(c); if (a) { answers.push(a); note('answered ' + a) } } catch (e) { note('answer err ' + e.message); try { c.close() } catch {} ; c = await connect() }
  const tasks = ((await api(`/api/tasks?case_id=${caseId}`)).value?.tasks ?? []).filter((t) => !before.has(t.task_id))
  task = tasks[0] ?? null
  if (task && task.status !== 'running') {
    // let the UI settle (final answer render), then stop
    await sleep(8000)
    break
  }
}
note('done ' + (task ? task.status : 'no task'))
await c.shot(`D:/lawbench-T18/shots/${skill}.png`).catch(() => {})
const summary = { skill, capsule, case_id: caseId, root, task_id: task?.task_id ?? null, status: task?.status ?? null,
  drafts: task?.drafts ?? [], citation_check: task?.citation_check ?? null, answers, wall_s: Math.round((Date.now() - t0) / 1000), log }
writeFileSync(`D:/lawbench-T18/runs/${skill}.json`, JSON.stringify(summary, null, 1))
console.log(JSON.stringify({ skill, status: summary.status, drafts: summary.drafts.map((d) => d.path), answers, wall_s: summary.wall_s }))
c.close()
