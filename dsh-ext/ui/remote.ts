// 界面端手写的 lawbench 远程描述（T13 执行令 Q1）：替代 Typert 代码生成的 /remote 产物，界面插件启动时 $mount。
// 参数与返回的编解码器按网关要求 mode 为 'strict'；这里只透传，内容校验在 Host 端按契约做（Q6）。
import { LAWBENCH_NAMESPACE, LAWBENCH_SERVICE, REMOTE_METHODS } from '../shared/remote-methods.ts'

const PACKAGE = 'lawbench-dsh'
const passThrough = (typeSymbol: string) => ({
  mode: 'strict' as const,
  typeSymbol,
  create: () => ({ parse: (value: unknown) => value }),
})

/** 供 ctx.remote.$mount 使用的描述（结构同 DSH 生成的 TYPERT_REMOTE）。 */
export const LAWBENCH_REMOTE = {
  package: PACKAGE,
  descriptors: REMOTE_METHODS.map(({ method, params }) => ({
    id: `${PACKAGE}#${LAWBENCH_NAMESPACE}/${method}`,
    service: LAWBENCH_SERVICE,
    namespace: LAWBENCH_NAMESPACE,
    method,
    invocation: { kind: 'direct' as const },
    parameters: params.map((name) => ({
      name,
      wire: name,
      source: 'json' as const,
      acceptsUndefined: true,
      codec: passThrough(`${PACKAGE}#${LAWBENCH_NAMESPACE}/${method}:${name}`),
    })),
    result: passThrough(`${PACKAGE}#${LAWBENCH_NAMESPACE}/${method}:result`),
  })),
}
