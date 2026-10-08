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
  // T14 第二次实跑派修 3：设置页"更换 Key"（写凭据管理器后测一次连接；不回显 Key）
  { method: 'changeKey', params: ['key'] },
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
  // T26 第 3 步：归档面板读 <案件>\工作区\任务\<任务ID>\归档方案.json（服务没有读它的接口；只读）
  { method: 'archivePlan', params: ['request'] },
  // T14 派修 2：到达用量上限时对话区显示刚存的草稿（只读该任务的 task.json、result.json、最新一版草稿）
  { method: 'taskAnswer', params: ['request'] },
  // T14 第二次实跑派修 2：写任务单明确失败时记上、写成时去掉；记着的会话 Agent 插件整轮拒绝
  { method: 'sheetHold', params: ['request'] },
  // 执行令 1156 第 4 条：纯聊天的默认工作区"日常事务"（首次配置后第一次问到时建好并登记）
  { method: 'dailyCase', params: [] },
  // 1612 复核 P1：侧栏移除旧位置那一项之前，问 Host 这个文件夹是不是确实不在了
  { method: 'pathState', params: ['request'] },
  // 令 2043（律师第一批反馈）：首页工具栏打开小工具；右栏"打开所在文件夹"；"移除此材料"（删文件后重新扫描）；云同步被拒时在本机建案件文件夹
  { method: 'openTool', params: ['request'] },
  { method: 'openFolder', params: ['request'] },
  // 令 1321 C.2：成果卡片"打开"（默认程序打开案件根里的成果文件）
  { method: 'openFile', params: ['request'] },
  { method: 'materialRemove', params: ['request'] },
  { method: 'localCaseFolder', params: ['request'] },
  // T13 执行令 Q6：/api/* 各接口，返回完整的 {ok, value} 或 {ok: false, error: {code, message}}
  ...API_ROUTES.map(({ method }) => ({ method, params: ['request'] })),
]
