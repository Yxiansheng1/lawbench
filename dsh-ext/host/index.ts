// Host 插件 legal-host（Spec 1.2、1.3；T7 步骤 1、执行令 Q3/Q4）。全局行，不在 preset 里。
// - 用 ctx.subprocess.spawn 启动并看护工作台服务（supervisor.ts）；
// - 提供 Cordis 服务 lawbenchCore：Agent 插件经它拿端口和令牌；
// - 提供远程命名空间 lawbench（最小集：设置读写、测试连接、首次配置状态），首次配置页经 Host 的 /api 调用。
import { randomBytes } from 'node:crypto'
import { existsSync, rmSync } from 'node:fs'
import { createServer } from 'node:net'
import { join } from 'node:path'
import { CONTRACT_VERSION, validate } from '../shared/contracts.ts'
import { makeLogger } from '../shared/file-log.ts'
import { Supervisor, type ChildHandle, type SupervisorState } from './supervisor.ts'

export const name = 'lawbench-host'
export const inject = ['subprocess']

export interface Config {
  /** 启动命令（不含端口、令牌，它们经环境变量传）。开发期如 [python.exe, -m, lawbench] 或 [node, dev/fake-service.mjs]。 */
  command: string[]
  /** 服务进程的工作目录。 */
  cwd: string
  /** 应用数据目录，经 LB_APPDATA 传给服务；Host 也据此判断 settings.json 是否存在。 */
  appData: string
  /** 本机转发端口（Spec 15），经 LB_FORWARD_PORT 传。 */
  forwardPort?: number
  /** 服务端口的挑选范围；不给时由系统分配空闲端口。 */
  portRange?: [number, number]
  /** 其余透传给服务的环境变量（如 LB_SKILLS_DIRS、LB_CONTRACTS_DIR、LB_VALIDATE_RESPONSES）。 */
  env?: Record<string, string>
}

type Ctx = {
  subprocess: { spawn(spec: unknown): { done: Promise<{ exitCode: number | null }>; terminate(): void } }
  provide(name: string, value: unknown): () => void
  get(name: string): unknown
  effect(fn: () => () => void, label?: string): void
  logger?(name: string): { info(...a: unknown[]): void; warn(...a: unknown[]): void; error(...a: unknown[]): void }
}

/** Windows 需要原样传入的系统变量（Spec 1.3），外加所有 OneDrive* 变量（云同步目录检测用）。 */
export function passThroughEnv(source: NodeJS.ProcessEnv): Record<string, string> {
  const out: Record<string, string> = {}
  const keep = new Set(['SYSTEMROOT', 'LOCALAPPDATA', 'APPDATA', 'USERPROFILE', 'TEMP', 'TMP', 'PATH', 'PATHEXT', 'COMSPEC', 'WINDIR'])
  for (const [k, v] of Object.entries(source)) {
    if (v === undefined) continue
    if (keep.has(k.toUpperCase()) || /^onedrive/i.test(k)) out[k] = v
  }
  return out
}

async function freePort(range?: [number, number]): Promise<number> {
  const tryPort = (p: number) => new Promise<number | undefined>((resolve) => {
    const s = createServer()
    s.once('error', () => resolve(undefined))
    s.listen(p, '127.0.0.1', () => { const a = s.address(); s.close(() => resolve(typeof a === 'object' && a ? a.port : undefined)) })
  })
  if (range) {
    for (let p = range[0]; p <= range[1]; p++) { const got = await tryPort(p); if (got) return got }
    throw new Error('服务端口范围内没有空闲端口')
  }
  const got = await tryPort(0)
  if (!got) throw new Error('无法取得空闲端口')
  return got
}

async function probeHealth(port: number): Promise<string | undefined> {
  try {
    const r = await fetch(`http://127.0.0.1:${port}/health`, { signal: AbortSignal.timeout(2000), redirect: 'error' })
    if (!r.ok) return undefined
    const j = (await r.json()) as { status?: string; contract_version?: string }
    return j.status === 'ok' ? j.contract_version : undefined
  } catch { return undefined }
}

const REMOTE_METHODS = '@deepseek-ai/dsh-typert-protocol/remote-methods'

/** Host 用到的凭据服务方法（由 legal-credentials 提供）。 */
export type CredentialsLike = {
  describe(ref: string): Promise<{ configured: boolean }>
  resolve(ref: string): Promise<{ value: string } | undefined>
  set(ref: string, value: string): Promise<void>
  unset(ref: string): Promise<void>
}

/** 远程命名空间 lawbench：首次配置页（Electron 主进程）经 Host 的 POST /api/lawbench/<方法> 调用。 */
export class LawbenchRemote {
  readonly typertRemote: unknown
  constructor(
    private readonly supervisor: Supervisor,
    private readonly appData: string,
    private readonly credentials: () => CredentialsLike | undefined,
  ) {
    this.typertRemote = Object.freeze({ service: this, serviceKey: 'lawbenchRemote', namespace: 'lawbench' })
  }

  private async api(method: 'GET' | 'PUT' | 'POST', path: string, body?: unknown): Promise<unknown> {
    const ep = this.supervisor.endpoint()
    if (!ep) throw new Error('工作台服务未启动，请稍后重试')
    const r = await fetch(`http://127.0.0.1:${ep.port}${path}`, {
      method, redirect: 'error', signal: AbortSignal.timeout(30_000),
      headers: { authorization: `Bearer ${ep.token}`, ...(body === undefined ? {} : { 'content-type': 'application/json' }) },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
    const j = (await r.json()) as { ok: boolean; value?: unknown; error?: { message: string } }
    if (!j.ok) throw new Error(j.error?.message ?? '内部错误，请重试；多次出现请联系技术支持')
    return j.value
  }

  /** 首次配置状态（执行令 Q3：settings.json 不存在，或凭据管理器没有 Key，就算没配置过）。Host 自己看文件，不经服务。 */
  async setupState(): Promise<{ configured: boolean; hasSettings: boolean; hasKey: boolean; service: SupervisorState }> {
    const hasSettings = existsSync(join(this.appData, 'settings.json'))
    const cred = this.credentials()
    const hasKey = cred ? (await cred.describe('LAWFIRM_KEY')).configured : false
    return { configured: hasSettings && hasKey, hasSettings, hasKey, service: this.supervisor.state }
  }

  async getSettings(): Promise<unknown> { return this.api('GET', '/api/settings') }

  async putSettings(settings: unknown): Promise<unknown> {
    const errs = validate('lawbench://contracts/api/settings.schema.json', 'request', settings)
    if (errs.length) throw new Error('请求参数有误')
    return this.api('PUT', '/api/settings', settings)
  }

  async testConnection(server: unknown): Promise<unknown> {
    if (server !== 'llm' && server !== 'prep') throw new Error('请求参数有误')
    return this.api('POST', '/api/connection/test', { server })
  }

  /** 串行执行"测试连接"（T7 第二次返修 F2）：两次并发时，后一次必须等前一次（含恢复）做完再取"旧值"。 */
  private trialQueue: Promise<unknown> = Promise.resolve()

  /**
   * 首次配置页的"测试连接"（T7 返修 P3-5、第二次返修 F1/F2/F6）：先保存页面上的地址（和 Key），再测两台服务器；
   * 测试没通过（任一台连不上、Key 被判无效，或过程中出错）就恢复成测试之前的地址和 Key——之前没有设置文件的删掉，
   * 之前没有 Key 的删掉 Key；没改 Key 的不碰 Key。地址和 Key 各自恢复，一个失败不影响另一个；
   * 任一步恢复失败（含凭据写入超时后读回核对不符）就抛出 RESTORE_FAILED。旧 Key 只在本进程内存里过一下，不写日志、不落盘。
   * 每一步抛错后的状态见 T7 交付说明第 9 节的表。
   * @param servers - 四个地址（servers 对象）。@param key - 新 Key；不改 Key 时为 null。
   * @returns 测试完成时的两项结果；没通过且已恢复时 restored 为 true。过程中出错且已恢复时抛出"……；已恢复为测试前的配置"。
   */
  trialConnection(servers: unknown, key: unknown): Promise<{ llm: unknown; prep: unknown; restored: boolean }> {
    const run = this.trialQueue.then(() => this.trialOnce(servers, key), () => this.trialOnce(servers, key))
    this.trialQueue = run.catch(() => undefined)
    return run
  }

  private async trialOnce(servers: unknown, key: unknown): Promise<{ llm: unknown; prep: unknown; restored: boolean }> {
    // ① 参数与前置条件：抛错时什么都没改
    if (key !== null && (typeof key !== 'string' || !/^[\x21-\x7e]{8,512}$/.test(key))) throw new Error('请求参数有误')
    const cred = this.credentials()
    if (!cred) throw new Error(UNAVAILABLE)
    // ② 快照：抛错时什么都没改
    const settingsFile = join(this.appData, 'settings.json')
    const hadSettings = existsSync(settingsFile)
    const oldSettings = (await this.getSettings()) as Record<string, unknown>
    const changeKey = typeof key === 'string'
    const oldKey = changeKey ? (await cred.resolve('LAWFIRM_KEY'))?.value : undefined
    // ③ 试写与测试：写之前先记"可能已写"（超时可能发生在写成功之后）
    let settingsTouched = false
    let keyTouched = false
    let llm: { reachable?: boolean; key_valid?: boolean | null } | undefined
    let prep: { reachable?: boolean } | undefined
    let failure: unknown
    try {
      settingsTouched = true
      await this.putSettings({ ...oldSettings, servers })
      if (changeKey) {
        keyTouched = true
        await cred.set('LAWFIRM_KEY', key as string)
      }
      llm = (await this.testConnection('llm')) as typeof llm
      prep = (await this.testConnection('prep')) as typeof prep
      if (llm?.reachable === true && llm.key_valid !== false && prep?.reachable === true) return { llm, prep, restored: false }
    } catch (e) {
      failure = e
    }
    // ④ 恢复：地址、Key 各自独立
    let restoreFailed = false
    if (settingsTouched) {
      try {
        if (hadSettings) await this.putSettings(oldSettings)
        else rmSync(settingsFile, { force: true })
      } catch { restoreFailed = true }
    }
    if (keyTouched) {
      try {
        if (oldKey !== undefined) await cred.set('LAWFIRM_KEY', oldKey)
        else await cred.unset('LAWFIRM_KEY')
      } catch {
        // 凭据写入超时时写入可能已经成功：读一次核对，读不到或不符都算未能恢复
        try { if ((await cred.resolve('LAWFIRM_KEY'))?.value !== oldKey) restoreFailed = true } catch { restoreFailed = true }
      }
    }
    if (restoreFailed) throw new Error(RESTORE_FAILED)
    if (failure !== undefined) {
      const msg = failure instanceof Error && /[一-鿿]/.test(failure.message) ? failure.message : UNAVAILABLE
      throw new Error(`${msg}；已恢复为测试前的配置`)
    }
    return { llm, prep, restored: true }
  }
}

const UNAVAILABLE = '工作台服务未启动，请稍后重试'
export const RESTORE_FAILED = '测试未通过，且未能恢复原配置，请重新填写后保存'
Object.defineProperty(LawbenchRemote.prototype, REMOTE_METHODS, {
  configurable: true,
  value: Object.freeze({
    version: 1,
    methods: ['setupState', 'getSettings', 'putSettings', 'testConnection', 'trialConnection'].map((method) => Object.freeze({ method, invocation: Object.freeze({ kind: 'direct' }) })),
  }),
})

export function apply(ctx: Ctx, config: Config): void {
  // 只记元数据（Spec 4.5）：事件名、状态、端口、退出码、次数
  const log = makeLogger('host', config.appData, ctx.logger?.('lawbench-host'))
  if (!Array.isArray(config.command) || config.command.length === 0) {
    log('error', 'config.missing_command')
    return
  }
  const baseEnv = { ...passThroughEnv(process.env), ...(config.env ?? {}) }
  const supervisor = new Supervisor({
    spawn(port: number, token: string): ChildHandle {
      const handle = ctx.subprocess.spawn({
        argv: config.command,
        cwd: config.cwd,
        stdio: { stdin: 'ignore', stdout: { maxBytes: 65536 }, stderr: { maxBytes: 65536 } },
        graceMs: 3000,
        env: {
          ...baseEnv,
          LB_PORT: String(port),
          LB_TOKEN: token, // 名字含 TOKEN，DSH 默认会从继承环境里清掉，所以必须显式传
          LB_APPDATA: config.appData,
          LB_FORWARD_PORT: String(config.forwardPort ?? 18765),
        },
      })
      return { pid: undefined, exited: handle.done.then((d) => d.exitCode, () => null), kill: () => handle.terminate() }
    },
    probe: probeHealth,
    pickPort: () => freePort(config.portRange),
    newToken: () => randomBytes(32).toString('hex'),
    expectedVersion: CONTRACT_VERSION,
    log,
  })

  ctx.provide('lawbenchCore', Object.freeze({
    endpoint: () => supervisor.endpoint(),
    state: () => supervisor.state,
    onState: (fn: (s: SupervisorState) => void) => supervisor.onState(fn),
  }))
  ctx.provide('lawbenchRemote', new LawbenchRemote(supervisor, config.appData, () => ctx.get('credentials') as never))
  ctx.effect(() => {
    void supervisor.start().catch((e: unknown) => log('error', 'service.start_failed', { error: String((e as Error)?.message ?? e) }))
    return () => supervisor.stop()
  }, 'lawbench-host: workbench service')
}
