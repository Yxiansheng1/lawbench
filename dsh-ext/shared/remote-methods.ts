// lawbench 远程命名空间的方法表：Host（host/index.ts 的 LawbenchRemote）和界面（ui 手写的 $mount 描述）共用这一份。
// T13 执行令 Q1：界面插件自己 $mount 手写描述，不改 DSH 源码；tests/remote-methods.spec.ts 守着两边一致（方法名、参数名）。
// Q6 命名：契约文件名驼峰；一个文件对应两个 HTTP 方法时加 get / put / post 前缀；T7 的旧名保留。

export interface RemoteMethodSpec {
  /** 方法名（界面调用 ctx.remote.lawbench.<method>）。 */
  readonly method: string
  /** 参数名，顺序即 Host 方法的形参顺序（网关按形参名取 payload.args）。 */
  readonly params: readonly string[]
}

export const LAWBENCH_NAMESPACE = 'lawbench'
export const LAWBENCH_SERVICE = 'lawbenchRemote'

export const REMOTE_METHODS: readonly RemoteMethodSpec[] = [
  // T7：首次配置页用
  { method: 'setupState', params: [] },
  { method: 'getSettings', params: [] },
  { method: 'putSettings', params: ['settings'] },
  { method: 'testConnection', params: ['server'] },
  { method: 'trialConnection', params: ['servers', 'key'] },
]
