// 我方测试配置。vitest 取自 dsh 的依赖环境，这里不 import 它（dsh-ext 不在 dsh 的模块树里），测试用全局 API。
import { VIRTUAL_ID, contractsModuleSource } from './scripts/contracts-source.mjs'

export default {
  plugins: [{
    name: 'lawbench-contracts',
    resolveId: (id) => (id === VIRTUAL_ID ? '\0' + VIRTUAL_ID : null),
    load: (id) => (id === '\0' + VIRTUAL_ID ? contractsModuleSource() : null),
  }],
  test: {
    include: ['tests/**/*.spec.ts'],
    environment: 'node',
    globals: true,
    testTimeout: 30000,
  },
}
