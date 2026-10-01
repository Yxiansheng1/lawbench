// lawbench 远程命名空间的方法表：Host（host/index.ts 的 LawbenchRemote）和界面（ui 手写的 $mount 描述）共用这一份。
// T13 执行令 Q1：界面插件自己 $mount 手写描述，不改 DSH 源码；tests/remote-methods.spec.ts 守着两边一致（方法名、参数名）。
// Q6 命名：契约文件名驼峰；一个文件对应两个 HTTP 方法时加 get / put / post 前缀；T7 的旧名保留。

export interface RemoteMethodSpec {
  /** 方法名（界面调用 ctx.remote.lawbench.<method>）。 */
  readonly method: string
  /** 参数名，顺序即 Host 方法的形参顺序（网关按形参名取 payload.args）。 */
  readonly params: readonly string[]
}

import { API_ROUTES } from './api-routes.ts'

export const LAWBENCH_NAMESPACE = 'lawbench'
export const LAWBENCH_SERVICE = 'lawbenchRemote'

export const REMOTE_METHODS: readonly RemoteMethodSpec[] = [
  // T7：首次配置页用（抛中文错误，不带错误码；N34 定之前不动）
  { method: 'setupState', params: [] },
  { method: 'getSettings', params: [] },
  { method: 'putSettings', params: ['settings'] },
  { method: 'testConnection', params: ['server'] },
  { method: 'trialConnection', params: ['servers', 'key'] },
  // T13 执行令 Q4：Host 自己读 Skill 目录的 SKILL.md 头部，不是 /api 契约接口
  { method: 'listSkills', params: [] },
  // T13 执行令 Q3②：粘贴的截图由 Host 存临时文件后经 /api/materials/import 导入
  { method: 'importPastedImage', params: ['request'] },
  // ORCH 注记 2026-09-30 13:18：上一轮被拦下的原因（INPUT_CHANGED 等），输入区在一轮结束后取
  { method: 'turnNotice', params: ['request'] },
  // T17 第三轮复核 B-F2：打开案件后把 cwd 是该案件根、不在任何工作区里的会话挂回该案件工作区
  { method: 'attachCaseSessions', params: ['request'] },
  // T20 准备：启动自检里有问题的项（内置 Python、tokenizer、LibreOffice、pandoc、管理员 Skill 目录、缓存路径长度）
  { method: 'selfCheck', params: [] },
  // T13 执行令 Q6：/api/* 各接口，返回完整的 {ok, value} 或 {ok: false, error: {code, message}}
  ...API_ROUTES.map(({ method }) => ({ method, params: ['request'] })),
]
