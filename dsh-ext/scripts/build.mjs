// 构建我方插件：每个入口打成一个自包含的 ESM 文件（ajv、契约数据都打进去），运行时不依赖模块解析。
// esbuild 取自 dsh 的依赖环境（不另装）。用法：node scripts/build.mjs
import { createRequire } from 'node:module'
import { readdirSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { VIRTUAL_ID, contractsModuleSource } from './contracts-source.mjs'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const pnpmDir = join(root, '..', 'dsh', 'node_modules', '.pnpm')
const esbuildDir = readdirSync(pnpmDir).filter((d) => d.startsWith('esbuild@')).sort().pop()
if (!esbuildDir) throw new Error('dsh 依赖环境里找不到 esbuild；先在 dsh\\ 下 pnpm install')
const esbuild = await import(pathToFileURL(createRequire(join(pnpmDir, esbuildDir, 'node_modules', 'esbuild', 'package.json')).resolve('esbuild')).href)

const contractsPlugin = {
  name: 'lawbench-contracts',
  setup(build) {
    build.onResolve({ filter: /^lawbench:contracts$/ }, () => ({ path: VIRTUAL_ID, namespace: 'lawbench' }))
    build.onLoad({ filter: /.*/, namespace: 'lawbench' }, () => ({ contents: contractsModuleSource(), loader: 'js' }))
  },
}

await esbuild.build({
  absWorkingDir: root,
  entryPoints: { agent: 'agent/index.ts', host: 'host/index.ts', credentials: 'credentials/index.ts' },
  outdir: 'lib',
  bundle: true,
  format: 'esm',
  platform: 'node',
  target: 'node22',
  sourcemap: false,
  legalComments: 'none',
  plugins: [contractsPlugin],
  logLevel: 'info',
})
