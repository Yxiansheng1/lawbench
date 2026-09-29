// 我方测试配置。vitest 取自 dsh 的依赖环境，这里不 import 它（dsh-ext 不在 dsh 的模块树里），测试用全局 API。
import { VIRTUAL_ID, contractsModuleSource } from './scripts/contracts-source.mjs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

// 界面代码 import 的 react 运行时由 DSH 提供；测试里指向 dsh 依赖环境中的同一版本
const REACT = join(dirname(fileURLToPath(import.meta.url)), '..', 'dsh', 'node_modules', '.pnpm', 'react@18.3.1', 'node_modules', 'react')

export default {
  plugins: [{
    name: 'lawbench-contracts',
    resolveId: (id) => (id === VIRTUAL_ID ? '\0' + VIRTUAL_ID : null),
    load: (id) => (id === '\0' + VIRTUAL_ID ? contractsModuleSource() : null),
  }],
  resolve: { alias: { react: REACT } },
  test: {
    include: ['tests/**/*.spec.ts'],
    environment: 'node',
    globals: true,
    testTimeout: 30000,
  },
}
