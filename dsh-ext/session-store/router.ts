// 会话存储路由（T17 第三步，执行令 2026-09-30 15:16 第二节，12:57 注记路 ②）。
// 对外是 DSH 的 sessionPersistence 服务（create / open / flush / stat / list）；内部按根各起一个原版 JSONL 实例：
// 默认根（$DSH_HOME\sessions，不在案件里的会话）一个，每个已登记案件 <案件>\工作区\会话 一个。
// - 新建：按 cwd 选实例（cwd 在哪个案件根里就进哪个；都不在的按开关放默认根或拒绝）。
// - 打开、stat：按"编号 → 实例"表；表里没有的逐个实例找。
// - 列表：合并各实例；某个案件根读不出来（盘拔了、路径不在、没权限）只跳过它、记一条元数据日志，不连累整体。
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
  /** 不在案件里的会话是否允许新建（N46 候定，默认允许）。 */
  allowOutsideCase: boolean
  /** 刷新案件根名单（问工作台服务）；服务不在时什么也不做。 */
  refresh?: (force?: boolean) => Promise<void>
  log?: LogFn
}

/** 案件里存会话记录的子目录（相对案件根）。 */
export const CASE_SESSION_DIR = join('工作区', '会话')
export const OUTSIDE_CASE = '这个文件夹还没有作为案件打开，不能在这里新建对话。请先从首页打开案件。'

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
    let s: Store
    if (caseRoot) s = this.caseStore(caseRoot)
    else if (this.opts.allowOutsideCase) s = this.defaultStore
    else throw new Error(OUTSIDE_CASE)
    const h = await s.backend.create(header, options)
    this.owner.set(header.id, s)
    return this.handle(s, h)
  }

  /** 会话在哪个实例：先查表，再逐个实例 stat。 */
  private async locate(id: string, options?: Opts): Promise<Store | undefined> {
    const known = this.owner.get(id)
    if (known) return known
    for (const s of this.all()) {
      try {
        if (await s.backend.stat(id, options)) { this.owner.set(id, s); return s }
      } catch (error) {
        if (!s.caseRoot) throw error
        this.skip(s, error)
      }
    }
    return undefined
  }

  async open(id: string, access: 'read' | 'write', options?: Opts): Promise<Handle> {
    const s = await this.locate(id, options)
    // 哪里都没有：交给默认实例，由它按原样报"不存在"
    if (!s) return this.defaultStore.backend.open(id, access, options)
    return this.handle(s, await s.backend.open(id, access, options))
  }

  async stat(id: string, options?: Opts): Promise<Snapshot | undefined> {
    const s = await this.locate(id, options)
    if (!s) return undefined
    const snap = await s.backend.stat(id, options)
    return snap && this.snapshot(s, snap)
  }

  async list(options?: Opts): Promise<readonly Snapshot[]> {
    await this.opts.refresh?.().catch(() => undefined)
    const out: Snapshot[] = []
    const seen = new Set<string>()
    for (const s of this.all()) {
      let rows: readonly Snapshot[]
      try {
        rows = await s.backend.list(options)
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

  /** 测试用：某会话此刻归哪个根（默认根为 null）。 */
  ownerOf(id: string): string | null | undefined { return this.owner.get(id)?.caseRoot }
}

export { inside }
