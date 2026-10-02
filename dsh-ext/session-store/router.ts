// 会话存储路由（T17 第三步，执行令 2026-09-30 15:16 第二节，12:57 注记路 ②）。
// 对外是 DSH 的 sessionPersistence 服务（create / open / flush / stat / list）；内部按根各起一个原版 JSONL 实例：
// 默认根（$DSH_HOME\sessions，不在案件里的会话）一个，每个已登记案件 <案件>\工作区\会话 一个。
// - 新建：按 cwd 选实例（cwd 在哪个案件根里就进哪个；都不在的按开关放默认根或拒绝）。
// - 打开、stat：按"编号 → 实例"表；表里没有的、表里那个实例说没有（同一进程里案件搬了家）的、或表里那个实例的
//   案件根已不在名单上的（名单刷新后，第四轮复核 A-P2-2），逐个实例找；哪里都没有时强制刷新一次名单再找（B-F1 第一次打开）。
// - 列表：合并各实例；某个案件根读不出来（盘拔了、路径不在、没权限）或 3 秒没回应（网络盘挂住）只跳过它、
//   记一条元数据日志，不连累整体。
// - 不在案件里的旧会话（默认根）：N46 ② 下只读，续写拒绝（第三轮裁决 A-P3-3）。
// - 活着的会话所在的案件挪走了（N55 用户定 ②，不搬写入者）：DSH 的会话一旦起过 Agent，Agent 一直攥着打开时拿到的写句柄，
//   会话的事件经原版实例投给它登记的写入者，路由换不了它的去处。所以这里记下路由交出去的每个案件写句柄属于哪个案件根；
//   那个根已不在当前名单上、或已不在盘上，这个会话就算"位置失效"（只在内存里判，不落盘、不改登记），由我方 Agent 插件
//   在下一轮开始时整轮拒绝并提示重启软件。名单刷新后根已不在名单上的，Agent 空闲时放下写入者，旧处不再变（recheck）。
//   重启后会话从新位置打开（见下一条），照常续写。
// - 搬家（F-CASE-04，方案甲）：记录头里的 cwd 是建会话时的旧路径；从案件实例读出的会话，交给 DSH 的记录头里
//   cwd 一律换成该案件现在的根，DSH 和工作区登记据此认得它。原版实例的身份核对按"根 + 旧 cwd 的编码"找文件，
//   整个案件目录一起搬走时这条相对路径不变，所以不需要改原版包（见交付说明第 5 节）。
import { existsSync } from 'node:fs'
import { join } from 'node:path'
import { inside, pathKey, type CaseRoots } from './case-roots.ts'

/** 会话记录头（只写用到的字段）。 */
export interface Header { readonly id: string; readonly cwd?: string; readonly [k: string]: unknown }
export interface Snapshot { readonly header: Header; readonly [k: string]: unknown }
export interface Handle { readonly id: string; readonly header: Header; readonly [k: string]: unknown }
type Opts = { readonly signal?: AbortSignal; readonly [k: string]: unknown } | undefined

/** 原版 JSONL 实例的对外方法（与 DSH 的 SessionPersistence 相同）。 */
export interface Backend {
  create(header: Header, options?: Opts): Promise<Handle>
  open(id: string, access: 'read' | 'write', options?: Opts): Promise<Handle>
  flush(): Promise<void>
  stat(id: string, options?: Opts): Promise<Snapshot | undefined>
  list(options?: Opts): Promise<readonly Snapshot[]>
}

export type LogFn = (level: 'info' | 'warn' | 'error', event: string, meta?: Record<string, unknown>) => void

export interface RouterOptions {
  /** 不在案件里的会话的记录根（$DSH_HOME\sessions）。 */
  defaultRoot: string
  /** 不在案件里的会话是否允许新建、续写（N46 用户定 ②：不允许）。 */
  allowOutsideCase: boolean
  /** 刷新案件根名单（问工作台服务）；服务不在时什么也不做。 */
  refresh?: (force?: boolean) => Promise<void>
  /**
   * 名单是否已按服务刷新成功过一次，以及有上限地等第一次刷新（第三轮复核 B-F4）。不给时当作已刷新过。
   * wait 在已刷新过时立刻返回 true；最多等 3 秒，到时还没刷新成功返回 false。
   */
  firstRefresh?: { done(): boolean; wait(): Promise<boolean> }
  /** 单个案件根 list、stat 的上限（毫秒），超时就跳过（第三轮复核 B-F5）。默认 3000。 */
  caseRootTimeoutMs?: number
  log?: LogFn
}

/** 案件里存会话记录的子目录（相对案件根）。 */
export const CASE_SESSION_DIR = join('工作区', '会话')
export const OUTSIDE_CASE = '这个文件夹还没有作为案件打开，不能在这里新建对话。请先从首页打开案件。'
/** 名单还没拿到（缓存为空且工作台服务还没起来）时新建的说明（第三轮复核 B-F4）。 */
export const NOT_READY = '工作台服务还没就绪，稍后再试。'

const isNotFound = (error: unknown): boolean => (error as Error)?.name === 'SessionPersistenceNotFoundError'

/** 给一次读取加上限：到时没回来就按"超时"失败（原来那次读取不取消，结果丢掉）。 */
function within<T>(p: Promise<T>, ms: number): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined
  const timeout = new Promise<never>((_, reject) => {
    timer = setTimeout(() => reject(Object.assign(new Error('case root timed out'), { code: 'ETIMEDOUT' })), ms)
  })
  return Promise.race([p, timeout]).finally(() => clearTimeout(timer))
}

interface Store { readonly root: string; readonly caseRoot: string | null; readonly backend: Backend; readonly index: number }
/** 交出去的一个案件写句柄：属于哪个实例、真正的句柄是哪个、是否已放下（见 recheck）。 */
interface Writer { readonly id: string; readonly at: Store; cur: Handle; detached: boolean }
const closeHandle = (h: Handle): Promise<void> => (h.close as () => Promise<void>).call(h)

export class SessionRouter {
  private readonly stores = new Map<string, Store>()
  private readonly owner = new Map<string, Store>()
  private readonly defaultStore: Store
  private lastMissRefresh = 0

  constructor(private readonly make: (root: string) => Backend, private readonly roots: CaseRoots, private readonly opts: RouterOptions) {
    this.defaultStore = { root: opts.defaultRoot, caseRoot: null, backend: make(opts.defaultRoot), index: 0 }
  }

  /** 某案件的实例（没有就建）。 */
  private caseStore(caseRoot: string): Store {
    const k = pathKey(caseRoot)
    let s = this.stores.get(k)
    if (!s) {
      const root = join(caseRoot, CASE_SESSION_DIR)
      s = { root, caseRoot, backend: this.make(root), index: this.stores.size + 1 }
      this.stores.set(k, s)
    }
    return s
  }

  /** 此刻名单上的全部实例：默认根在前，再是各案件。建不起来的案件实例（根读不了）跳过。 */
  private all(): Store[] {
    const out = [this.defaultStore]
    for (const r of this.roots.list()) {
      try {
        out.push(this.caseStore(r))
      } catch (error) {
        this.skip({ root: r, caseRoot: r, backend: undefined as never, index: this.stores.size + 1 }, error)
      }
    }
    return out
  }

  /** 案件实例的读取加上限；默认根不加（它在本机软件目录里，出错照原样报）。 */
  private bounded<T>(s: Store, p: Promise<T>): Promise<T> {
    return s.caseRoot ? within(p, this.opts.caseRootTimeoutMs ?? 3000) : p
  }

  private skip(s: Store, error: unknown): void {
    // 只记元数据：第几个案件根、错误码；不记路径（路径里有当事人名）
    this.opts.log?.('warn', 'session_store.case_root_skipped', { index: s.index, code: (error as NodeJS.ErrnoException)?.code ?? 'ERROR' })
  }

  /** 交给 DSH 的记录头：案件实例里的会话，cwd 换成该案件现在的根（搬家后旧路径不再有效）。 */
  private header(s: Store, h: Header): Header {
    if (!s.caseRoot || (h.cwd !== undefined && pathKey(h.cwd) === pathKey(s.caseRoot))) return h
    return Object.freeze({ ...h, cwd: s.caseRoot })
  }

  private snapshot(s: Store, snap: Snapshot): Snapshot {
    const header = this.header(s, snap.header)
    return header === snap.header ? snap : { ...snap, header }
  }

  private handle(s: Store, h: Handle): Handle {
    const header = this.header(s, h.header)
    const writer = s.caseRoot && h.access === 'write'
    if (!writer && header === h.header) return h
    let w: Writer | undefined
    if (writer) {
      // 记下这个写句柄属于哪个案件根，关闭时去掉（同一会话只记最新交出去的那个）
      w = { id: h.id, at: s, cur: h, detached: false }
      this.writers.set(h.id, w)
    }
    const close = async (): Promise<void> => {
      if (this.writers.get(w!.id) === w) this.writers.delete(w!.id)
      await closeHandle(w!.cur)
    }
    return new Proxy(h, {
      get: (target, prop) => {
        if (prop === 'header') return header
        if (w && (prop === 'close' || prop === Symbol.asyncDispose)) return close
        const v = Reflect.get(target, prop, target)
        return typeof v === 'function' ? v.bind(target) : v
      },
    })
  }

  /** 路由交出去、还没关的案件写句柄（按会话编号）。 */
  private readonly writers = new Map<string, Writer>()

  private invalid(w: Writer): boolean {
    return !this.current(w.at) || !existsSync(w.at.caseRoot!)
  }

  /**
   * 这个会话的写句柄所属案件根已不在当前名单上、或已不在盘上，或写入者已放下（N55 ②"位置失效"）：我方 Agent 插件据此拒绝下一轮。
   * 名单只在刷新成功时换，所以刷新失败不会误判；根回到名单、盘插回后解除（放下过的见 recheck）。
   */
  caseMoved(id: string): boolean {
    const w = this.writers.get(id)
    return !!w && (w.detached || this.invalid(w))
  }

  /** 名单刷新后要 recheck 的会话：根已不在名单上、还没放下的；放下了、根又回到名单且在盘上的。 */
  writersToRecheck(): string[] {
    return [...this.writers.values()].filter((w) => (w.detached ? !this.invalid(w) : !this.current(w.at))).map((w) => w.id)
  }

  /**
   * 名单刷新成功后由会话存储插件调（这个会话的 Agent 空闲时）。DSH 被拒的一轮也会把律师那句话和"一轮被拦下"记进会话
   * （桌面端实测与 live-writer.spec），活着的写入者会把它们写进旧处；所以根已不在名单上时先放下写入者：关掉真正的句柄
   * （原版把缓冲的事件落完、注销写入者），之后这个会话的事件哪里都不写，旧处不再变。根回到名单（重新打开原位置、盘插回）
   * 且盘上记录与内存里的会话一样长时，在原处重新以写方式打开接着写；不一样长（放下期间又被拒过一轮，这几条只在内存里）
   * 就一直算位置失效，重启后从盘上读。只是盘暂时不在、名单没变时不放下：原版写不进去会留着缓冲下次再写，插回后接上。
   * @param eventCount - 内存里这个会话的事件数（DSH 会话的 seq）；不知道时不重新打开。
   */
  recheck(id: string, eventCount: number | undefined): Promise<void> {
    // 同一会话同时只做一次（打开案件后的刷新与后台刷新可能同时触发），后来的排在后面
    const run = (this.rechecking.get(id) ?? Promise.resolve()).then(() => this.recheckOnce(id, eventCount))
    const tail = run.catch(() => undefined)
    this.rechecking.set(id, tail)
    void tail.then(() => { if (this.rechecking.get(id) === tail) this.rechecking.delete(id) })
    return run
  }

  private readonly rechecking = new Map<string, Promise<void>>()

  private async recheckOnce(id: string, eventCount: number | undefined): Promise<void> {
    const w = this.writers.get(id)
    if (!w) return
    if (!w.detached && !this.current(w.at)) {
      // 关完再记"已放下"：同时来的另一次 recheck 排在这次后面，看到的是关完之后的状态（打开案件后要等它关完再返回）
      await closeHandle(w.cur).catch(() => undefined)
      w.detached = true
      this.opts.log?.('info', 'session_store.writer_detached', { index: w.at.index })
    } else if (w.detached && !this.invalid(w) && eventCount !== undefined) {
      const fresh = await w.at.backend.open(id, 'write').catch(() => undefined)
      if (!fresh) return
      const n = await (fresh.read as () => Promise<{ events: unknown[] }>).call(fresh).then((r) => r.events.length, () => -1)
      if (n !== eventCount || this.writers.get(id) !== w) { await closeHandle(fresh).catch(() => undefined); return }
      w.cur = fresh
      w.detached = false
      this.opts.log?.('info', 'session_store.writer_reattached', { index: w.at.index })
    }
  }

  async create(header: Header, options?: Opts): Promise<Handle> {
    let caseRoot = this.roots.match(header.cwd)
    if (!caseRoot && header.cwd && this.opts.refresh) {
      // 刚登记的案件可能还不在名单里：问一次服务再判
      await this.opts.refresh(true).catch(() => undefined)
      caseRoot = this.roots.match(header.cwd)
    }
    const first = this.opts.firstRefresh
    if (!caseRoot && header.cwd && first && !first.done()) {
      // 服务还没起来、名单一次也没刷新过：有上限地等第一次刷新再判
      await first.wait()
      caseRoot = this.roots.match(header.cwd)
    }
    let s: Store
    if (caseRoot) s = this.caseStore(caseRoot)
    else if (this.opts.allowOutsideCase) s = this.defaultStore
    else if (header.cwd && first && !first.done()) throw new Error(NOT_READY)
    else throw new Error(OUTSIDE_CASE)
    const h = await s.backend.create(header, options)
    this.owner.set(header.id, s)
    return this.handle(s, h)
  }

  /** 实例还在当前名单上（默认根总在）。名单换掉后，表里指向旧根的条目当作没有。 */
  private current(s: Store): boolean {
    return !s.caseRoot || this.roots.has(s.caseRoot)
  }

  /**
   * 哪里都找不到时强制刷新一次名单（刚复制、搬家的案件在律师打开之后服务才只列新位置）。
   * 2 秒内只刷一次：DSH 对不存在的编号也会 stat，不能每次都问服务。
   * @returns 是否刷新过（刷新过才值得再找一遍）。
   */
  private async refreshOnMiss(): Promise<boolean> {
    if (!this.opts.refresh || Date.now() - this.lastMissRefresh < 2000) return false
    this.lastMissRefresh = Date.now()
    await this.opts.refresh(true).catch(() => undefined)
    return true
  }

  /** 会话在哪个实例：先查表，再逐个实例 stat。miss 是表里记的、已知没有这个会话的实例，跳过它。 */
  private async locate(id: string, options?: Opts, miss?: Store): Promise<Store | undefined> {
    const known = this.owner.get(id)
    if (known && known !== miss && this.current(known)) return known
    if (known) this.owner.delete(id)
    for (const s of this.all()) {
      if (s === miss) continue
      try {
        if (await this.bounded(s, s.backend.stat(id, options))) { this.owner.set(id, s); return s }
      } catch (error) {
        if (!s.caseRoot) throw error
        this.skip(s, error)
      }
    }
    return undefined
  }

  /** N46 ②：不在案件里的旧会话只读，续写拒绝（开关打开时照常）。 */
  private checkAccess(s: Store, access: 'read' | 'write'): void {
    if (access === 'write' && !s.caseRoot && !this.opts.allowOutsideCase) throw new Error(OUTSIDE_CASE)
  }

  async open(id: string, access: 'read' | 'write', options?: Opts): Promise<Handle> {
    const known = this.owner.has(id)
    let s = await this.locate(id, options)
    if (!s && await this.refreshOnMiss()) s = await this.locate(id, options)
    // 哪里都没有：交给默认实例，由它按原样报"不存在"
    if (!s) return this.defaultStore.backend.open(id, access, options)
    this.checkAccess(s, access)
    try {
      return this.handle(s, await s.backend.open(id, access, options))
    } catch (error) {
      // 表里记的实例说没有（同一进程里案件搬了家，第三轮复核 B-F6）：去掉这条，换别的实例找
      if (!known || !isNotFound(error)) throw error
      const was = s
      s = await this.locate(id, options, was)
      if (!s && await this.refreshOnMiss()) s = await this.locate(id, options, was)
      if (!s) throw error
      this.checkAccess(s, access)
      return this.handle(s, await s.backend.open(id, access, options))
    }
  }

  async stat(id: string, options?: Opts): Promise<Snapshot | undefined> {
    const known = this.owner.has(id)
    let s = await this.locate(id, options)
    if (!s && await this.refreshOnMiss()) s = await this.locate(id, options)
    if (!s) return undefined
    let snap = await this.bounded(s, s.backend.stat(id, options))
    if (!snap && known) {
      // 同上：表里记的实例说没有，换别的实例找
      const was = s
      s = await this.locate(id, options, was)
      if (!s && await this.refreshOnMiss()) s = await this.locate(id, options, was)
      if (!s) return undefined
      snap = await this.bounded(s, s.backend.stat(id, options))
    }
    return snap && this.snapshot(s, snap)
  }

  async list(options?: Opts): Promise<readonly Snapshot[]> {
    const first = this.opts.firstRefresh
    if (first && !first.done() && this.roots.list().length === 0) {
      // 缓存为空、名单一次也没刷新过：有上限地等第一次刷新，免得案件里的会话被漏掉（第三轮复核 B-F4）
      await first.wait()
    } else {
      // 平时列表不等服务（第三轮复核 A-P3-5）：名单在后台刷新，下一次列表用新的
      void this.opts.refresh?.().catch(() => undefined)
    }
    const out: Snapshot[] = []
    const seen = new Set<string>()
    for (const s of this.all()) {
      let rows: readonly Snapshot[]
      try {
        rows = await this.bounded(s, s.backend.list(options))
      } catch (error) {
        if (!s.caseRoot) throw error // 默认根读不出来照原样失败
        this.skip(s, error)
        continue
      }
      for (const row of rows) {
        if (seen.has(row.header.id)) {
          this.opts.log?.('warn', 'session_store.duplicate_id', { index: s.index })
          continue
        }
        seen.add(row.header.id)
        this.owner.set(row.header.id, s)
        out.push(this.snapshot(s, row))
      }
    }
    return out
  }

  async flush(): Promise<void> {
    const stores = [this.defaultStore, ...this.stores.values()]
    const results = await Promise.allSettled(stores.map((s) => s.backend.flush()))
    const errors = results.flatMap((r) => (r.status === 'rejected' ? [r.reason] : []))
    if (errors.length) throw new AggregateError(errors, 'lawbench session store flush failed')
  }

  /** 某会话此刻归哪个案件根（默认根为 null，不知道或表里的根已不在名单上为 undefined）；投影缓存按它决定落盘位置。 */
  ownerOf(id: string): string | null | undefined {
    const s = this.owner.get(id)
    return s && this.current(s) ? s.caseRoot : undefined
  }
}

export { inside }
