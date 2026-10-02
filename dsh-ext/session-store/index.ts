// 我方会话存储插件 legal-session-store（T17 第三步，执行令 2026-09-30 15:16 第二节）：提供 DSH 的服务 sessionPersistence，
// 顶替原 session-persistence-jsonl 行（配置补丁里关掉它）。按案件把会话记录存进 <案件>\工作区\会话，路由见 router.ts。
// 原版 JSONL 实例用 DSH 自己装的那份（补丁里按 DSH 的模块解析求出入口文件再 import），不打进我方包：
// 这样 cordis 的 Service 基类、SessionPersistence 基类与 DSH 是同一份。每个实例放在自己隔离的服务作用域里，
// 互不覆盖，也不占用对外的 sessionPersistence。
// 会话投影缓存（原 session-projection-cache 行，配置补丁里关掉）也由这里接回来，按案件存，见 projection-cache.ts。
import { pathToFileURL } from 'node:url'
import { defaultAppData, makeLogger } from '../shared/file-log.ts'
import { CaseRoots } from './case-roots.ts'
import { CaseProjectionTable, caseProjectionDomain, type CacheRecord } from './projection-cache.ts'
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
  /**
   * 会话投影缓存（第三轮裁决 A-P2-1 ①）：原版包 @deepseek-ai/dsh-session-projection-cache 的入口文件与它的两项写入节奏
   * （同 base 原行）。不给时不提供投影缓存（侧栏冷会话没有标题）。
   */
  projectionCache?: { module?: string; impl?: unknown; writeEveryEvents: number; writeIntervalMs: number }
}

type Ctx = {
  on(event: string, listener: (...args: any[]) => unknown): () => void
  isolate(name: string): Ctx
  get(name: string): unknown
  provide(name: string, value: unknown): unknown
  plugin(plugin: unknown, config?: unknown): unknown
  inject(deps: string[], apply: (ctx: Ctx) => void): unknown
  effect(fn: () => () => void, label?: string): void
  logger?(name: string): { info(...a: unknown[]): void; warn(...a: unknown[]): void; error(...a: unknown[]): void }
  lawbenchCore?: LawbenchCore
}
type LawbenchCore = { endpoint(): { port: number; token: string } | undefined; onState(fn: (s: string) => void): () => void }
type BackendClass = (new (ctx: Ctx, config: { root: string; compression?: string }) => Backend)

/**
 * 问工作台服务要最近案件，名单以它为准整个换掉。服务不在、超时、返回不对都当没有新消息、名单不动。
 * @returns 是否刷新成功。
 */
async function refreshFromService(core: LawbenchCore | undefined, roots: CaseRoots, log: LogFn): Promise<boolean> {
  const ep = core?.endpoint()
  if (!ep) return false
  try {
    const r = await fetch(`http://127.0.0.1:${ep.port}/api/case/recent`, {
      method: 'GET', redirect: 'error', signal: AbortSignal.timeout(3000),
      headers: { authorization: `Bearer ${ep.token}` },
    })
    const j = (await r.json()) as { ok?: boolean; value?: { cases?: unknown } }
    const cases = j.ok === true && Array.isArray(j.value?.cases) ? j.value.cases : undefined
    if (!cases) return false
    const changed = roots.replace(cases.filter((c): c is { root: string; exists: boolean } =>
      !!c && typeof (c as { root?: unknown }).root === 'string' && typeof (c as { exists?: unknown }).exists === 'boolean'))
    if (changed) log('info', 'session_store.case_roots_refreshed', { count: roots.list().length })
    return true
  } catch (e) {
    log('warn', 'session_store.case_roots_refresh_failed', { error: (e as Error)?.name ?? 'Error' })
    return false
  }
}

/**
 * 第一次刷新成功的标记与有上限的等待（第三轮复核 B-F4）。只等一次：等满一次还没刷新成功（服务一直起不来），
 * 之后的列表、新建都不再等（第四轮复核 B-F4），同时等的几处共用这一次。
 */
function firstRefreshGate(limitMs: number) {
  let done = false
  let open!: () => void
  const opened = new Promise<void>((resolve) => { open = resolve })
  let waiting: Promise<void> | undefined
  return {
    done: () => done,
    mark: () => { if (!done) { done = true; open() } },
    wait: async (): Promise<boolean> => {
      if (done) return true
      waiting ??= new Promise<void>((resolve) => {
        const timer = setTimeout(resolve, limitMs)
        void opened.then(() => { clearTimeout(timer); resolve() })
      })
      await waiting
      return done
    },
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
  const roots = new CaseRoots(appData, log).load()
  const core = (): LawbenchCore | undefined => ctx.get('lawbenchCore') as LawbenchCore | undefined
  // 同一时间只问一次，5 秒内不重复问（list 可能被频繁调用）；服务还不在时不算问过
  const gate = firstRefreshGate(3000)
  let inFlight: Promise<void> | undefined
  let lastAt = 0
  const refresh = (force = false): Promise<void> => {
    if (inFlight) return inFlight
    if (!force && Date.now() - lastAt < 5000) return Promise.resolve()
    if (!core()?.endpoint()) return Promise.resolve()
    inFlight = refreshFromService(core(), roots, log)
      .then((ok) => { if (ok) { gate.mark(); void recheckWriters() } })
      .finally(() => { lastAt = Date.now(); inFlight = undefined })
    return inFlight
  }
  /**
   * 立刻按服务刷新一次名单并等它回来（每次问服务最多 3 秒（途中那次另等），之后放下要放下的写入者，每个最多 3 秒，见 refreshFromService 与 router.ts 的 recheck；第七轮复核 B-F4）。律师打开案件（caseOpen）之后服务才只列新位置，
   * Host 在 caseOpen 成功后、挂回游离会话之前调它（第四轮复核 B-F1）。正在途中的那次可能是打开之前发出的，等它完再问一次。
   */
  const refreshNow = async (): Promise<void> => {
    if (inFlight) await inFlight.catch(() => undefined)
    await refresh(true)
    await recheckWriters()
  }

  /**
   * 名单刷新后放下所属根已不在名单上、且还在盘上（复制）的写入者，或在原处接回（N55 ②，见 router.ts 的 recheck）。会话的 Agent 正在跑一轮的
   * 不打断，这一轮照原处落完，等它结束（agent/status 变 idle）再做。
   */
  const waiting = new Set<string>()
  const recheckOne = async (id: string): Promise<void> => {
    await router.recheck(id).catch((e: unknown) => {
      log('warn', 'session_store.writer_recheck_failed', { error: (e as Error)?.name ?? 'Error' })
    })
  }
  const recheckWriters = async (): Promise<void> => {
    const agents = ctx.get('agents') as { get(id: string): { status?: string } | undefined } | undefined
    for (const id of router.writersToRecheck()) {
      if (agents?.get(id)?.status !== 'running') { await recheckOne(id); continue }
      if (waiting.has(id)) continue
      waiting.add(id)
      const off = ctx.on('agent/status', (payload: { agent?: { id?: string }; status?: string }) => {
        if (payload?.agent?.id !== id || payload.status !== 'idle') return
        off(); waiting.delete(id)
        void recheckOne(id)
      })
    }
  }

  const router = new SessionRouter(
    (root) => new Jsonl(ctx.isolate('sessionPersistence'), { root, ...(config.compression ? { compression: config.compression } : {}) }),
    roots,
    {
      defaultRoot: config.defaultRoot, allowOutsideCase: config.allowOutsideCase ?? false, refresh, firstRefresh: gate, log,
      liveSeq: (id) => {
        const seq = (ctx.get('sessions') as { get(id: string): { seq?: number } | undefined } | undefined)?.get(id)?.seq
        return typeof seq === 'number' ? seq : undefined
      },
    },
  )

  class LawbenchSessionPersistence extends Base {
    readonly name = 'lawbench-session-store'
    create(header: Header, options?: never) { return router.create(header, options) }
    open(id: string, access: 'read' | 'write', options?: never) { return router.open(id, access, options) }
    flush() { return router.flush() }
    stat(id: string, options?: never) { return router.stat(id, options) }
    list(options?: never) { return router.list(options) }
    /** 我方加的（不在 DSH 的接口里）：Host 打开案件后调，见 refreshNow。 */
    refreshCaseRoots() { return refreshNow() }
    /** 我方加的：这个会话所在的案件文件夹已不在原位置（N55 ②，见 router.ts），我方 Agent 插件据此拒绝下一轮。 */
    caseMoved(id: string) { return router.caseMoved(id) }
    /** 我方加的：拒绝一轮之前放下还没落过盘的写入者（第十轮 R10-1，见 router.ts 的 releaseMoved）。 */
    releaseMoved(id: string) { return router.releaseMoved(id) }
    /** 我方加的：案件根名单上有没有这个根（Host 打开案件后核对刷新是否成功）。 */
    hasCaseRoot(root: string) { return roots.has(root) }
  }
  new LawbenchSessionPersistence(ctx)
  log('info', 'session_store.started', { case_roots: roots.list().length, allow_outside_case: config.allowOutsideCase ?? false })

  // 投影缓存：原版类放进一个只隔离 storageDomain 的作用域，交给它按案件落盘的替身存储域；
  // 它对外仍以 sessionProjectionCache 提供。它要等 sessions（而 sessions 要等本插件），所以不等它起来。
  const pc = config.projectionCache
  if (pc && (pc.impl || pc.module)) {
    const mod = (pc.impl ? { default: pc.impl } : await import(pathToFileURL(pc.module!).href)) as {
      default: unknown; checkpointRecord?: { safeParse(v: unknown): { success: boolean; data?: unknown } }
    }
    const schema = mod.checkpointRecord
    const table = new CaseProjectionTable({
      caseRootOf: (id) => router.ownerOf(id),
      parse: (v) => {
        if (schema) { const r = schema.safeParse(v); return r.success ? (r.data as CacheRecord) : undefined }
        const rec = v as CacheRecord | null
        return rec && typeof rec === 'object' && rec.identity && typeof rec.identity === 'object' && rec.rows && typeof rec.rows === 'object' ? rec : undefined
      },
      log,
    })
    // 替身存储域由一个放在隔离作用域里的小插件提供：cordis 在提供者启用时只通知同一隔离作用域里的依赖方
    const cacheConfig = { writeEveryEvents: pc.writeEveryEvents, writeIntervalMs: pc.writeIntervalMs }
    void ctx.isolate('storageDomain').plugin({
      name: 'lawbench-session-projection-cache',
      apply: (scope: Ctx) => {
        scope.provide('storageDomain', caseProjectionDomain(table))
        scope.plugin(mod.default, cacheConfig)
      },
    })
  }

  // 工作台服务起来（或重启）后刷新一次名单；lawbenchCore 由 legal-host 提供，不是硬依赖（会话存储要比它先可用）
  ctx.inject(['lawbenchCore'], (c) => {
    const off = (c.lawbenchCore as LawbenchCore).onState((s) => { if (s === 'running') void refresh() })
    c.effect(() => off, 'lawbench-session-store: refresh case roots when the service runs')
    void refresh()
  })
}
