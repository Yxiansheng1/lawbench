// 我方测试配置。vitest 取自 dsh 的依赖环境，这里不 import 它（dsh-ext 不在 dsh 的模块树里），测试用全局 API。
import { VIRTUAL_ID, contractsModuleSource } from './scripts/contracts-source.mjs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

// 界面代码 import 的 react 运行时由 DSH 提供；测试里指向 dsh 依赖环境中的同一版本
const REACT = join(dirname(fileURLToPath(import.meta.url)), '..', 'dsh', 'node_modules', '.pnpm', 'react@18.3.1', 'node_modules', 'react')
const REACT_DOM = join(dirname(fileURLToPath(import.meta.url)), '..', 'dsh', 'node_modules', '.pnpm', 'react-dom@18.3.1_react@18.3.1', 'node_modules', 'react-dom')
// 输入区组件测试（tests\dock.spec.ts）：DSH 的界面原件换成一个只有 Button 的替身，别的测试不引用它
const PRIMITIVES_STUB = join(dirname(fileURLToPath(import.meta.url)), 'tests', 'helpers', 'primitives-stub.ts')

export default {
  plugins: [{
    name: 'lawbench-contracts',
    resolveId: (id) => (id === VIRTUAL_ID ? '\0' + VIRTUAL_ID : null),
    load: (id) => (id === '\0' + VIRTUAL_ID ? contractsModuleSource() : null),
  }],
  resolve: { alias: { react: REACT, 'react-dom': REACT_DOM, '@deepseek-ai/dsh-client-ui-primitives': PRIMITIVES_STUB } },
  test: {
    include: ['tests/**/*.spec.ts'],
    environment: 'node',
    globals: true,
    testTimeout: 30000,
  },
}
