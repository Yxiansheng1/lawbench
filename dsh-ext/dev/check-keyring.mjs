// Spec 8.1〔待验证〕：Node 侧写入的凭据，Python keyring 能否按 (目标名, 用户名) 读到同一个值。
// 只打印"一致 / 不一致 / 读不到"，不打印 Key。
// 用法：node dev/check-keyring.mjs --python <带 keyring 的 python.exe> [--target <目标名>]
//   不给 --target 时：临时写一个随机假 Key 到独立的测试目标名，比对后删除。
//   给 --target lawbench/LAWFIRM_KEY 时：只读现有条目（验收时核对界面填入的值），不写不删。
import { spawnSync } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { build } from './build-one.mjs'

const arg = (n) => { const i = process.argv.indexOf(n); return i > 0 ? process.argv[i + 1] : undefined }
const python = arg('--python')
if (!python) throw new Error('需要 --python')
const given = arg('--target')
const { readKey, writeKey, deleteKey, USER } = await build('credentials/credman.ts')

const target = given ?? `lawbench/T7-KEYRING-${randomBytes(4).toString('hex')}`
let expected
if (given) {
  expected = await readKey(target)
  if (expected === undefined) { console.log('凭据管理器中没有该条目'); process.exit(1) }
} else {
  expected = `sk-fake-${randomBytes(12).toString('hex')}`
  await writeKey(expected, target)
}
try {
  const py = 'import sys, keyring\nv = keyring.get_password(sys.argv[1], sys.argv[2])\nexp = sys.stdin.read()\nprint("读不到" if v is None else ("一致" if v == exp else "不一致"))'
  const r = spawnSync(python, ['-c', py, target, USER], { input: expected, encoding: 'utf8', env: { ...process.env, PYTHONIOENCODING: 'utf-8' } })
  console.log(`python keyring.get_password("${given ? target : '<临时测试目标名>'}", "${USER}")：${(r.stdout || '').trim() || '无输出'}${r.status ? `（退出码 ${r.status}）` : ''}`)
  process.exitCode = (r.stdout || '').trim() === '一致' ? 0 : 1
} finally {
  if (!given) await deleteKey(target)
}
