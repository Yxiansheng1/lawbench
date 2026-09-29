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

// 界面插件（T13）：DSH 界面模块格式——CommonJS 包在 window.__ModuleLoader__.load({ id, factory: (require) => … }) 里，
// react、cordis 等从 DSH 的共享模块表 require（packages/client/web/src/seed.ts），不自带 React。
const CLIENT_ID = 'lawbench-dsh'
const SHARED = ['react', 'react/jsx-runtime', 'react-dom', 'react-dom/client', '@deepseek-ai/*']
await esbuild.build({
  absWorkingDir: root,
  entryPoints: { client: 'ui/index.tsx' },
  outdir: 'lib',
  bundle: true,
  format: 'cjs',
  platform: 'browser',
  target: 'es2022',
  jsx: 'automatic',
  external: SHARED,
  banner: { js: `window.__ModuleLoader__.load({\n  id: ${JSON.stringify(CLIENT_ID)},\n  factory: (require) => {\n    var module = { exports: {} };\n    var exports = module.exports;` },
  footer: { js: '    return module.exports;\n  }\n});' },
  plugins: [contractsPlugin],
  logLevel: 'info',
})

await esbuild.build({
  absWorkingDir: root,
  entryPoints: { agent: 'agent/index.ts', host: 'host/index.ts', credentials: 'credentials/index.ts', index: 'ui/host.ts' },
  outdir: 'lib',
  bundle: true,
  format: 'esm',
  platform: 'node',
  target: 'node22',
  sourcemap: false,
  legalComments: 'none',
  // 打进来的 CommonJS 依赖（如 yaml）会 require('process') 等内置模块；纯 ESM 里没有 require，给一个
  banner: { js: "import { createRequire as __lbCreateRequire } from 'node:module'; const require = __lbCreateRequire(import.meta.url);" },
  plugins: [contractsPlugin],
  logLevel: 'info',
})

// 构建后在纯 ESM 进程里逐个导入（不能用 node -e：那是 CommonJS，有全局 require，会掩盖上面这类问题）
for (const name of ['agent', 'host', 'credentials', 'index']) {
  const url = pathToFileURL(join(root, 'lib', `${name}.js`)).href
  const { spawnSync } = await import('node:child_process')
  const r = spawnSync(process.execPath, ['--input-type=module', '-e', `await import(${JSON.stringify(url)})`], { encoding: 'utf8' })
  if (r.status !== 0) throw new Error(`lib/${name}.js 在纯 ESM 下导入失败：${(r.stderr || '').split(/\r?\n/).slice(0, 3).join(' ')}`)
}
console.log('lib/*.js 纯 ESM 导入检查通过')
