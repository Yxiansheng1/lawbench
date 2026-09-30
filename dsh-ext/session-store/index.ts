// 我方会话存储插件 legal-session-store（T17 第三步，执行令 2026-09-30 15:16 第二节）：提供 DSH 的服务 sessionPersistence，
// 顶替原 session-persistence-jsonl 行（配置补丁里关掉它）。按案件把会话记录存进 <案件>\工作区\会话，路由见 router.ts。
// 原版 JSONL 实例用 DSH 自己装的那份（补丁里按 DSH 的模块解析求出入口文件再 import），不打进我方包：
// 这样 cordis 的 Service 基类、SessionPersistence 基类与 DSH 是同一份。每个实例放在自己隔离的服务作用域里，
// 互不覆盖，也不占用对外的 sessionPersistence。
import { pathToFileURL } from 'node:url'
import { defaultAppData, makeLogger } from '../shared/file-log.ts'
import { CaseRoots } from './case-roots.ts'
import { SessionRouter, type Backend, type Header, type LogFn } from './router.ts'

export const name = 'lawbench-session-store'

export interface Config {
  /** 原版存储包 @deepseek-ai/dsh-session-persistence-jsonl 的入口文件（绝对路径）。 */
  backendModule?: string
  /** 测试用：直接给原版存储类（与测试里引用的是同一份模块），给了就不按 backendModule 导入。 */
  backend?: unknown
  /** 不在案件里的会话的记录根（原行的 root：$DSH_HOME\sessions）。 */
  defaultRoot: string
  /** 应用数据目录（案件根名单缓存、日志）；不给时用 %LOCALAPPDATA%\lawbench。 */
  appData?: string
  /** 不在案件里的会话是否允许新建（N46 用户定 ②：不允许，默认 false；已有的照常可读）。 */
  allowOutsideCase?: boolean
  /** 原版的物理编码（不给时用原版默认）。 */
  compression?: string
}

type Ctx = {
  isolate(name: string): Ctx
  get(name: string): unknown
  inject(deps: string[], apply: (ctx: Ctx) => void): unknown
  effect(fn: () => () => void, label?: string): void
  logger?(name: string): { info(...a: unknown[]): void; warn(...a: unknown[]): void; error(...a: unknown[]): void }
  lawbenchCore?: LawbenchCore
}
type LawbenchCore = { endpoint(): { port: number; token: string } | undefined; onState(fn: (s: string) => void): () => void }
type BackendClass = (new (ctx: Ctx, config: { root: string; compression?: string }) => Backend)

/** 问工作台服务要最近案件，更新名单。服务不在、超时、返回不对都当没有新消息。 */
async function refreshFromService(core: LawbenchCore | undefined, roots: CaseRoots, log: LogFn): Promise<void> {
  const ep = core?.endpoint()
  if (!ep) return
  try {
    const r = await fetch(`http://127.0.0.1:${ep.port}/api/case/recent`, {
      method: 'GET', redirect: 'error', signal: AbortSignal.timeout(3000),
      headers: { authorization: `Bearer ${ep.token}` },
    })
    const j = (await r.json()) as { ok?: boolean; value?: { cases?: unknown } }
    const cases = j.ok === true && Array.isArray(j.value?.cases) ? j.value.cases : undefined
    if (!cases) return
    const changed = roots.merge(cases.filter((c): c is { root: string; exists: boolean } =>
      !!c && typeof (c as { root?: unknown }).root === 'string' && typeof (c as { exists?: unknown }).exists === 'boolean'))
    if (changed) log('info', 'session_store.case_roots_refreshed', { count: roots.list().length })
  } catch (e) {
    log('warn', 'session_store.case_roots_refresh_failed', { error: (e as Error)?.name ?? 'Error' })
  }
}

export async function apply(ctx: Ctx, config: Config): Promise<void> {
  const appData = config.appData ?? defaultAppData()
  const log: LogFn = makeLogger('session-store', appData, ctx.logger?.('lawbench-session-store'))
  if (!config.backend && !config.backendModule) throw new Error('lawbench-session-store: 没有给原版存储包的位置（backendModule）')
  const Jsonl = (config.backend as BackendClass | undefined)
    ?? ((await import(pathToFileURL(config.backendModule!).href)) as { default: BackendClass }).default
  // DSH 的 SessionPersistence 抽象基类（原版类的父类）：继承它，构造时即以 sessionPersistence 注册到本插件的上下文
  const Base = Object.getPrototypeOf(Jsonl) as new (ctx: Ctx) => object
  const roots = new CaseRoots(appData).load()
  const core = (): LawbenchCore | undefined => ctx.get('lawbenchCore') as LawbenchCore | undefined
  // 同一时间只问一次，5 秒内不重复问（list 可能被频繁调用）
  let inFlight: Promise<void> | undefined
  let lastAt = 0
  const refresh = (force = false): Promise<void> => {
    if (inFlight) return inFlight
    if (!force && Date.now() - lastAt < 5000) return Promise.resolve()
    inFlight = refreshFromService(core(), roots, log).finally(() => { lastAt = Date.now(); inFlight = undefined })
    return inFlight
  }
  const router = new SessionRouter(
    (root) => new Jsonl(ctx.isolate('sessionPersistence'), { root, ...(config.compression ? { compression: config.compression } : {}) }),
    roots,
    { defaultRoot: config.defaultRoot, allowOutsideCase: config.allowOutsideCase ?? false, refresh, log },
  )

  class LawbenchSessionPersistence extends Base {
    readonly name = 'lawbench-session-store'
    create(header: Header, options?: never) { return router.create(header, options) }
    open(id: string, access: 'read' | 'write', options?: never) { return router.open(id, access, options) }
    flush() { return router.flush() }
    stat(id: string, options?: never) { return router.stat(id, options) }
    list(options?: never) { return router.list(options) }
  }
  new LawbenchSessionPersistence(ctx)
  log('info', 'session_store.started', { case_roots: roots.list().length, allow_outside_case: config.allowOutsideCase ?? false })

  // 工作台服务起来（或重启）后刷新一次名单；lawbenchCore 由 legal-host 提供，不是硬依赖（会话存储要比它先可用）
  ctx.inject(['lawbenchCore'], (c) => {
    const off = (c.lawbenchCore as LawbenchCore).onState((s) => { if (s === 'running') void refresh() })
    c.effect(() => off, 'lawbench-session-store: refresh case roots when the service runs')
    void refresh()
  })
}
