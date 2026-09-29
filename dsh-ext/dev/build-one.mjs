// 开发脚本用：把一个 .ts 模块即时打包成临时 ESM 再导入（esbuild 取自 dsh 依赖环境）。
import { createRequire } from 'node:module'
import { readdirSync, mkdtempSync, writeFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { tmpdir } from 'node:os'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { contractsModuleSource } from '../scripts/contracts-source.mjs'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const pnpmDir = join(root, '..', 'dsh', 'node_modules', '.pnpm')
const esbuildDir = readdirSync(pnpmDir).filter((d) => d.startsWith('esbuild@')).sort().pop()
const esbuild = await import(pathToFileURL(createRequire(join(pnpmDir, esbuildDir, 'node_modules', 'esbuild', 'package.json')).resolve('esbuild')).href)

export async function build(entry) {
  const r = await esbuild.build({
    absWorkingDir: root, entryPoints: [entry], bundle: true, format: 'esm', platform: 'node', write: false,
    plugins: [{ name: 'c', setup(b) {
      b.onResolve({ filter: /^lawbench:contracts$/ }, () => ({ path: 'c', namespace: 'lb' }))
      b.onLoad({ filter: /.*/, namespace: 'lb' }, () => ({ contents: contractsModuleSource(), loader: 'js' }))
    } }],
  })
  const file = join(mkdtempSync(join(tmpdir(), 'lb-')), 'm.mjs')
  writeFileSync(file, r.outputFiles[0].text)
  return import(pathToFileURL(file).href)
}
