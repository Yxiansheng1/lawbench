import { readFileSync } from 'node:fs'
const svc = JSON.parse(readFileSync('D:/lawbench-T18/svc.json', 'utf8')); const H = { headers: { Authorization: 'Bearer ' + svc.token } }
const cs = (await (await fetch(`http://127.0.0.1:${svc.port}/api/case/recent`, H)).json()).value.cases
for (const n of process.argv.slice(2)) { const c = cs.find((x) => x.name === n); const t = (await (await fetch(`http://127.0.0.1:${svc.port}/api/tasks?case_id=${c.case_id}`, H)).json()).value.tasks; console.log(n, JSON.stringify(t.map((x) => [x.task_id, x.status, x.drafts.length]))) }
