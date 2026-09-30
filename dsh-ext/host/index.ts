// Host 插件 legal-host（Spec 1.2、1.3；T7 步骤 1、执行令 Q3/Q4）。全局行，不在 preset 里。
// - 用 ctx.subprocess.spawn 启动并看护工作台服务（supervisor.ts）；
// - 提供 Cordis 服务 lawbenchCore：Agent 插件经它拿端口和令牌；
// - 提供远程命名空间 lawbench（最小集：设置读写、测试连接、首次配置状态），首次配置页经 Host 的 /api 调用。
import { randomBytes, randomUUID } from 'node:crypto'
import { existsSync, rmSync } from 'node:fs'
import { mkdir, readdir, rm, writeFile } from 'node:fs/promises'
import { createServer } from 'node:net'
import { join } from 'node:path'
import { CONTRACT_VERSION, validate } from '../shared/contracts.ts'
import { makeLogger } from '../shared/file-log.ts'
import { Supervisor, type ChildHandle, type SupervisorState } from './supervisor.ts'
import { LAWBENCH_NAMESPACE, LAWBENCH_SERVICE, REMOTE_METHODS } from '../shared/remote-methods.ts'
import { API_ROUTES, buildRequest, type ApiRoute } from '../shared/api-routes.ts'
import { listSkills, type SkillInfo } from './skills.ts'
import { TurnNotices } from '../shared/turn-notices.ts'

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
  /** Skill 目录，先后顺序与服务一致（管理员目录在前）；listSkills 读这些目录（T13 执行令 Q4）。 */
  skillDirs?: string[]
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

const REMOTE_METHODS_KEY = '@deepseek-ai/dsh-typert-protocol/remote-methods'

/** Host 用到的凭据服务方法（由 legal-credentials 提供）。 */
export type CredentialsLike = {
  describe(ref: string): Promise<{ configured: boolean }>
  resolve(ref: string): Promise<{ value: string } | undefined>
  set(ref: string, value: string): Promise<void>
  unset(ref: string): Promise<void>
}

/** /api 接口的统一返回（契约 common.schema.json 的 fail，或 {ok: true, value}）。 */
export type ApiResult = { ok: true; value: unknown } | { ok: false; error: { code: string; message: string } }
type LogFn = (level: 'info' | 'warn' | 'error', event: string, meta?: Record<string, unknown>) => void

const fail = (code: string, message: string): ApiResult => ({ ok: false, error: { code, message } })
const BAD_ARGS = '请求参数有误'
const BAD_RESPONSE = '工作台服务返回的内容不符合约定，请重试；多次出现请联系技术支持'
const PASTE_MAX_BYTES = 20 * 1024 * 1024
/** base64 长度上限：解码前先按长度拦（返修 P3-4），4/3 倍再留一点换行余量。 */
const PASTE_MAX_BASE64 = Math.ceil(PASTE_MAX_BYTES / 3) * 4 + 1024
const PASTE_TOO_BIG = '只能粘贴 PNG 或 JPEG 图片，且不超过 20 MB'
/** 粘贴截图的导入位置（T13 执行令 Q3②）。 */
export const PASTE_TARGET = '02案件材料/粘贴图片'

/**
 * 远程命名空间 lawbench：首次配置页（Electron 主进程）经 Host 的 POST /api/lawbench/<方法> 调用；
 * 界面插件经 ctx.remote.lawbench.<方法>() 调用（T13）。
 */
export class LawbenchRemote {
  readonly typertRemote: unknown
  constructor(
    private readonly supervisor: Supervisor,
    private readonly appData: string,
    private readonly credentials: () => CredentialsLike | undefined,
    private readonly skillDirs: readonly string[] = [],
    private readonly log: LogFn = () => {},
    private readonly notices: TurnNotices = new TurnNotices(),
  ) {
    this.typertRemote = Object.freeze({ service: this, serviceKey: LAWBENCH_SERVICE, namespace: LAWBENCH_NAMESPACE })
  }

  /**
   * 调一个 /api 接口（T13 执行令 Q6）：按契约校验请求和完整的返回，失败时带错误码和中文提示返回，不抛出。
   * 日志只记方法名、结果、错误码、耗时（Spec 4.5），不记请求和返回内容。
   */
  async callApi(route: ApiRoute, request: unknown): Promise<ApiResult> {
    const t0 = Date.now()
    const done = (r: ApiResult, extra: Record<string, unknown> = {}): ApiResult => {
      this.log(r.ok ? 'info' : 'warn', 'api.call', { method: route.method, ok: r.ok, code: r.ok ? undefined : r.error.code, ms: Date.now() - t0, ...extra })
      return r
    }
    const id = `lawbench://contracts/api/${route.contract}.schema.json`
    const req = (request ?? {}) as Record<string, unknown>
    if (!route.noRequest) {
      if (typeof request !== 'object' || request === null || Array.isArray(request)) return done(fail('INVALID_ARGUMENT', BAD_ARGS))
      if (validate(id, 'request', req).length) return done(fail('INVALID_ARGUMENT', BAD_ARGS))
      if (route.require?.some((k) => req[k] === undefined)) return done(fail('INVALID_ARGUMENT', BAD_ARGS))
    }
    const built = buildRequest(route, req)
    if (!built) return done(fail('INVALID_ARGUMENT', BAD_ARGS))
    const ep = this.supervisor.endpoint()
    if (!ep) return done(fail('SERVICE_UNAVAILABLE', UNAVAILABLE))
    let json: unknown
    try {
      const r = await fetch(`http://127.0.0.1:${ep.port}${built.path}`, {
        method: route.http, redirect: 'error', signal: AbortSignal.timeout(route.timeoutMs ?? 30_000),
        headers: { authorization: `Bearer ${ep.token}`, ...(built.body === undefined ? {} : { 'content-type': 'application/json' }) },
        body: built.body === undefined ? undefined : JSON.stringify(built.body),
      })
      json = await r.json()
    } catch (e) {
      const timeout = (e as Error)?.name === 'TimeoutError'
      return done(timeout ? fail('TIMEOUT', '工作台服务响应超时，请稍后重试') : fail('SERVICE_UNAVAILABLE', UNAVAILABLE))
    }
    const errs = validate(id, 'response', json)
    if (errs.length) return done(fail('INTERNAL', BAD_RESPONSE), { invalid: errs.length })
    return done(json as ApiResult)
  }

  /** Skill 列表（T13 执行令 Q4）：读 SKILL.md 头部并按契约校验；同名时先读到的目录（管理员目录）为准。 */
  /**
   * 某会话上一轮被 Agent 插件拦下的原因（错误码，取一次即删；没有为 null）。ORCH 注记 2026-09-30 13:18：
   * 1.2 语义下输入材料变了，/core/context 报 INPUT_CHANGED、整轮被拒，DSH 的 reject 带不了消息，输入区经这里知道。
   */
  async turnNotice(request: unknown): Promise<{ ok: true; value: { code: string | null } }> {
    const sessionId = (request as { session_id?: unknown } | null)?.session_id
    return { ok: true, value: { code: typeof sessionId === 'string' ? this.notices.take(sessionId) : null } }
  }

  async listSkills(): Promise<{ ok: true; value: { skills: SkillInfo[] } }> {
    const { skills, invalid } = await listSkills(this.skillDirs)
    if (invalid) this.log('warn', 'skills.invalid_frontmatter', { count: invalid })
    return { ok: true, value: { skills } }
  }

  /**
   * 粘贴的截图（T13 执行令 Q3②）：存到 <应用数据>\临时\粘贴\，用绝对路径调 /api/materials/import 导入到
   * 02案件材料\粘贴图片\，不论成败都删掉临时文件。Host 不直接写案件文件夹。
   * @param request - { case_id, image_base64 }；只收 PNG、JPEG，最大 20 MB。
   */
  async importPastedImage(request: unknown): Promise<ApiResult> {
    const r = (request ?? {}) as { case_id?: unknown; image_base64?: unknown }
    if (typeof r.case_id !== 'string' || typeof r.image_base64 !== 'string') return fail('INVALID_ARGUMENT', BAD_ARGS)
    if (r.image_base64.length > PASTE_MAX_BASE64) return fail('INVALID_ARGUMENT', PASTE_TOO_BIG)
    const bytes = Buffer.from(r.image_base64, 'base64')
    const ext = bytes.subarray(0, 8).equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])) ? 'png'
      : bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff ? 'jpg' : undefined
    if (!ext || bytes.length > PASTE_MAX_BYTES) return fail('INVALID_ARGUMENT', PASTE_TOO_BIG)
    const dir = pasteDir(this.appData)
    // 文件名用随机标识（返修 P3-4：原先秒级时间 + 2 字节随机，同一秒两次粘贴可能撞名）
    const stamp = new Date().toISOString().replace(/[-:T]/g, '').slice(0, 14)
    const file = join(dir, `粘贴-${stamp}-${randomUUID()}.${ext}`)
    try {
      await mkdir(dir, { recursive: true })
      await writeFile(file, bytes)
      const route = API_ROUTES.find((x) => x.method === 'materialsImport')!
      return await this.callApi(route, { case_id: r.case_id, paths: [file], target: PASTE_TARGET, unzip: false })
    } catch {
      return fail('INTERNAL', '粘贴的图片没能导入，请重试')
    } finally {
      await rm(file, { force: true }).catch(() => undefined)
    }
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

  /**
   * T7 沿用的三个方法也按契约校验返回（T13 返修 P3-3）：把服务给的 value 装回 {ok: true, value} 按 $defs/response 校验；
   * 不合契约就抛中文错误（这三个方法沿用 T7 的"抛中文错误"约定），日志只记方法名和错误条数。
   */
  private checked(method: string, contract: string, value: unknown): unknown {
    const errs = validate(`lawbench://contracts/api/${contract}.schema.json`, 'response', { ok: true, value })
    if (errs.length) {
      this.log('warn', 'api.call', { method, ok: false, code: 'INTERNAL', invalid: errs.length })
      throw new Error(BAD_RESPONSE)
    }
    return value
  }

  async getSettings(): Promise<unknown> { return this.checked('getSettings', 'settings', await this.api('GET', '/api/settings')) }

  async putSettings(settings: unknown): Promise<unknown> {
    const errs = validate('lawbench://contracts/api/settings.schema.json', 'request', settings)
    if (errs.length) throw new Error('请求参数有误')
    return this.checked('putSettings', 'settings', await this.api('PUT', '/api/settings', settings))
  }

  async testConnection(server: unknown): Promise<unknown> {
    if (server !== 'llm' && server !== 'prep') throw new Error('请求参数有误')
    return this.checked('testConnection', 'connection_test', await this.api('POST', '/api/connection/test', { server }))
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

/** 粘贴截图的临时目录 <应用数据>\临时\粘贴\。 */
export const pasteDir = (appData: string): string => join(appData, '临时', '粘贴')

/** 启动时清掉上次没删成的粘贴临时文件（T13 执行令 Q3②）。只删这个目录里的文件，返回删了几个。 */
export async function cleanPasteDir(appData: string): Promise<number> {
  const dir = pasteDir(appData)
  let names: string[]
  try { names = await readdir(dir) } catch { return 0 }
  let n = 0
  for (const name of names) {
    try { await rm(join(dir, name), { force: true, recursive: true }); n++ } catch { /* 下次启动再删 */ }
  }
  return n
}

// /api 路由表里的每个接口对应一个只收 request 的方法（形参名须与方法表一致，tests/remote-methods.spec.ts 守着）
for (const route of API_ROUTES) {
  Object.defineProperty(LawbenchRemote.prototype, route.method, {
    configurable: true, writable: true,
    value: function (this: LawbenchRemote, request: unknown) { return this.callApi(route, request) },
  })
}

Object.defineProperty(LawbenchRemote.prototype, REMOTE_METHODS_KEY, {
  configurable: true,
  value: Object.freeze({
    version: 1,
    methods: REMOTE_METHODS.map(({ method }) => Object.freeze({ method, invocation: Object.freeze({ kind: 'direct' }) })),
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

  const notices = new TurnNotices()
  ctx.provide('lawbenchCore', Object.freeze({
    endpoint: () => supervisor.endpoint(),
    /** Agent 插件拒绝整轮时记下原因，界面经 turnNotice 取走。 */
    noteTurnBlocked: (sessionId: string, code: string) => notices.note(sessionId, code),
    /** 这一轮顺利开始：清掉该会话没被取走的旧记录。 */
    clearTurnBlocked: (sessionId: string) => notices.clear(sessionId),
    state: () => supervisor.state,
    onState: (fn: (s: SupervisorState) => void) => supervisor.onState(fn),
  }))
  ctx.provide(LAWBENCH_SERVICE, new LawbenchRemote(supervisor, config.appData, () => ctx.get('credentials') as never, config.skillDirs ?? [], log, notices))
  void cleanPasteDir(config.appData).then((n) => { if (n) log('info', 'paste.cleaned', { count: n }) })
  ctx.effect(() => {
    void supervisor.start().catch((e: unknown) => log('error', 'service.start_failed', { error: String((e as Error)?.message ?? e) }))
    return () => supervisor.stop()
  }, 'lawbench-host: workbench service')
}
