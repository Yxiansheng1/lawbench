// 我方测试命令：用 dsh 依赖环境里的 vitest 跑 dsh-ext\tests。退出码即测试结果。
import { spawnSync } from 'node:child_process'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const vitest = join(root, '..', 'dsh', 'node_modules', 'vitest', 'vitest.mjs')
const r = spawnSync(process.execPath, [vitest, 'run', '--config', 'vitest.config.mjs', ...process.argv.slice(2)], {
  cwd: root,
  stdio: 'inherit',
  env: { ...process.env, NO_COLOR: '1', FORCE_COLOR: '0' },
})
process.exit(r.status ?? 1)
