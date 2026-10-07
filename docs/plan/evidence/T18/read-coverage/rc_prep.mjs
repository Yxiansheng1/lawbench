// read-coverage 复现：登记两个案件、扫描；rc-ocr 把所有待识别页提交 395 并等完成。只打印元数据。
import { readFileSync } from 'node:fs'
const svc = JSON.parse(readFileSync('D:/lawbench-T18/svc.json', 'utf8'))
const call = async (m, p, b) => (await (await fetch(`http://127.0.0.1:${svc.port}${p}`, { method: m, headers: { Authorization: 'Bearer ' + svc.token, 'Content-Type': 'application/json' }, body: b ? JSON.stringify(b) : undefined })).json())
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
for (const name of ['rc-noocr', 'rc-ocr']) {
  const root = `D:\\lawbench-T18\\cases\\${name}`
  const c = (await call('POST', '/api/case/open', { path: root })).value
  const scan = (await call('POST', '/api/materials/scan', { case_id: c.case_id })).value
  const list = (await call('GET', `/api/materials?case_id=${c.case_id}`)).value
  console.log(name, c.case_id, JSON.stringify(scan))
  for (const m of list.materials) console.log('  ', m.material_id, m.type, m.status, m.unit, m.unit_count, 'need_ocr', JSON.stringify(m.pages_need_ocr), 'mixed', JSON.stringify(m.pages_mixed))
  if (name !== 'rc-ocr') continue
  const jobs = []
  for (const m of list.materials) {
    const pages = [...new Set([...(m.pages_need_ocr ?? []), ...(m.pages_mixed ?? [])])]
    if (!pages.length) continue
    const r = await call('POST', '/api/ocr/jobs', { case_id: c.case_id, material_id: m.material_id, pages, dewatermark: false })
    console.log('  ocr', m.material_id, pages.length, r.ok ? r.value.job_id : JSON.stringify(r.error))
    if (r.ok) jobs.push(r.value.job_id)
  }
  const t0 = Date.now()
  while (Date.now() - t0 < 20 * 60e3) {
    await sleep(10000)
    const js = (await call('GET', `/api/ocr/jobs?case_id=${c.case_id}`)).value.jobs.filter((j) => jobs.includes(j.job_id))
    if (js.every((j) => ['done', 'failed', 'cancelled'].includes(j.status))) { console.log('  ocr done', JSON.stringify(js.map((j) => [j.status, j.done, j.total, j.failed])), Math.round((Date.now() - t0) / 1000) + 's'); break }
  }
  const after = (await call('GET', `/api/materials?case_id=${c.case_id}`)).value
  for (const m of after.materials) console.log('  after', m.material_id, m.status, m.is_ocr, 'need_ocr', JSON.stringify(m.pages_need_ocr))
}
