import { readFileSync } from 'node:fs'
const svc = JSON.parse(readFileSync('D:/lawbench-T18/svc.json', 'utf8'))
const call = async (m, p, b) => (await (await fetch(`http://127.0.0.1:${svc.port}${p}`, { method: m, headers: { Authorization: 'Bearer ' + svc.token, 'Content-Type': 'application/json' }, body: b ? JSON.stringify(b) : undefined })).json())
const cs = (await call('GET', '/api/case/recent')).value.cases
const c = cs.find((x) => x.name === 'case-wiki-build')
const st = (await call('GET', '/api/settings')).value
const params = st.skill_presets?.['case-wiki-build'] ?? st.defaults
const r = await call('POST', '/api/pipeline/run', { case_id: c.case_id, step: 'wiki_build', use_prep: false, params })
console.log('run', JSON.stringify(r))
const tid = r.value?.task_id
const t0 = Date.now()
while (tid && Date.now() - t0 < 50 * 60e3) {
  await new Promise((s) => setTimeout(s, 15000))
  const st = (await call('GET', `/api/pipeline/${tid}`)).value
  if (st && !['running', 'queued', 'pending'].includes(st.status)) { console.log('done', JSON.stringify({ status: st.status, min: ((Date.now() - t0) / 60e3).toFixed(1) })); break }
}
