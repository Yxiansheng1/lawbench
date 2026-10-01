// 会话存储路由（T17 第三步，执行令 2026-09-30 15:16 第二节，12:57 注记路 ②）。
// 对外是 DSH 的 sessionPersistence 服务（create / open / flush / stat / list）；内部按根各起一个原版 JSONL 实例：
// 默认根（$DSH_HOME\sessions，不在案件里的会话）一个，每个已登记案件 <案件>\工作区\会话 一个。
// - 新建：按 cwd 选实例（cwd 在哪个案件根里就进哪个；都不在的按开关放默认根或拒绝）。
// - 打开、stat：按"编号 → 实例"表；表里没有的、或表里那个实例说没有（同一进程里案件搬了家）的，逐个实例找。
// - 列表：合并各实例；某个案件根读不出来（盘拔了、路径不在、没权限）或 3 秒没回应（网络盘挂住）只跳过它、
//   记一条元数据日志，不连累整体。
// - 不在案件里的旧会话（默认根）：N46 ② 下只读，续写拒绝（第三轮裁决 A-P3-3）。
// - 搬家（F-CASE-04，方案甲）：记录头里的 cwd 是建会话时的旧路径；从案件实例读出的会话，交给 DSH 的记录头里
//   cwd 一律换成该案件现在的根，DSH 和工作区登记据此认得它。原版实例的身份核对按"根 + 旧 cwd 的编码"找文件，
//   整个案件目录一起搬走时这条相对路径不变，所以不需要改原版包（见交付说明第 5 节）。
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

export class SessionRouter {
  private readonly stores = new Map<string, Store>()
  private readonly owner = new Map<string, Store>()
  private readonly defaultStore: Store

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
    if (header === h.header) return h
    return new Proxy(h, {
      get: (target, prop) => {
        if (prop === 'header') return header
        const v = Reflect.get(target, prop, target)
        return typeof v === 'function' ? v.bind(target) : v
      },
    })
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

  /** 会话在哪个实例：先查表，再逐个实例 stat。miss 是表里记的、已知没有这个会话的实例，跳过它。 */
  private async locate(id: string, options?: Opts, miss?: Store): Promise<Store | undefined> {
    const known = this.owner.get(id)
    if (known && known !== miss) return known
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
    // 哪里都没有：交给默认实例，由它按原样报"不存在"
    if (!s) return this.defaultStore.backend.open(id, access, options)
    this.checkAccess(s, access)
    try {
      return this.handle(s, await s.backend.open(id, access, options))
    } catch (error) {
      // 表里记的实例说没有（同一进程里案件搬了家，第三轮复核 B-F6）：去掉这条，换别的实例找
      if (!known || !isNotFound(error)) throw error
      s = await this.locate(id, options, s)
      if (!s) throw error
      this.checkAccess(s, access)
      return this.handle(s, await s.backend.open(id, access, options))
    }
  }

  async stat(id: string, options?: Opts): Promise<Snapshot | undefined> {
    const known = this.owner.has(id)
    let s = await this.locate(id, options)
    if (!s) return undefined
    let snap = await this.bounded(s, s.backend.stat(id, options))
    if (!snap && known) {
      // 同上：表里记的实例说没有，换别的实例找
      s = await this.locate(id, options, s)
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

  /** 某会话此刻归哪个案件根（默认根为 null，不知道为 undefined）；投影缓存按它决定落盘位置。 */
  ownerOf(id: string): string | null | undefined { return this.owner.get(id)?.caseRoot }
}

export { inside }
