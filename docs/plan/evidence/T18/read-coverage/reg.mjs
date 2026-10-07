import { readFileSync } from 'node:fs'
const svc = JSON.parse(readFileSync('D:/lawbench-T18/svc.json', 'utf8'))
const call = async (m, p, b) => (await (await fetch(`http://127.0.0.1:${svc.port}${p}`, { method: m, headers: { Authorization: 'Bearer ' + svc.token, 'Content-Type': 'application/json' }, body: b ? JSON.stringify(b) : undefined })).json())
const root = ['D:', 'lawbench-T18', 'cases', process.argv[2]].join(String.fromCharCode(92))
const c = (await call('POST', '/api/case/open', { path: root })).value
console.log(c.case_id, JSON.stringify((await call('POST', '/api/materials/scan', { case_id: c.case_id })).value))
const l = (await call('GET', `/api/materials?case_id=${c.case_id}`)).value
console.log(l.materials.map((m) => m.status).join(','))
