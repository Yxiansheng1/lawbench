// 会话存储路由（T17 第三步，执行令 2026-09-30 15:16 第二节，12:57 注记路 ②）。
// 对外是 DSH 的 sessionPersistence 服务（create / open / flush / stat / list）；内部按根各起一个原版 JSONL 实例：
// 默认根（$DSH_HOME\sessions，不在案件里的会话）一个，每个已登记案件 <案件>\工作区\会话 一个。
// - 新建：按 cwd 选实例（cwd 在哪个案件根里就进哪个；都不在的按开关放默认根或拒绝）。
// - 打开、stat：按"编号 → 实例"表；表里没有的、表里那个实例说没有（同一进程里案件搬了家）的、或表里那个实例的
//   案件根已不在名单上的（名单刷新后，第四轮复核 A-P2-2），逐个实例找；哪里都没有时强制刷新一次名单再找（B-F1 第一次打开）。
// - 列表：合并各实例；某个案件根读不出来（盘拔了、路径不在、没权限）或 3 秒没回应（网络盘挂住）只跳过它、
//   记一条元数据日志，不连累整体。
// - 不在案件里的旧会话（默认根）：N46 ② 下只读，续写拒绝（第三轮裁决 A-P3-3）。
// - 活着的写入者跟着案件走（第五轮复核 F1）：DSH 的会话一旦起过 Agent，Agent 一直攥着打开时拿到的写句柄，
//   也没有公开的办法让它放下；而且会话的事件不经句柄的 append——原版实例监听全局 session/event，按编号投给
//   自己实例里登记的写入者。所以这里记下路由交出去的每个案件写句柄；名单刷新后由会话存储插件调 relocate()：
//   关掉旧句柄（原版把缓冲的事件落进旧文件、注销旧实例里的写入者），在新位置的实例上以写方式打开；新位置的记录若是
//   旧处的前缀（复制之后旧处又写过：比如复制时正在跑的那一轮、复制后点开会话 resume 补的事件），把差的那几条从旧处
//   补到新位置，再核对与内存里的会话一样长——此后事件投到新实例。搬不了（新位置找不到、两处各自写过）就记为"已失效"，
//   由我方 Agent 插件在下一轮开始时整轮拒绝并给中文说明（不写旧处，也不静默丢）。
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
/** 交出去的一个案件写句柄：现在属于哪个实例、真正的句柄是哪个、是否已失效。 */
interface Writer { readonly id: string; at: Store; cur: Handle; lost: boolean }

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
    if (s.caseRoot && h.access === 'write') return this.movingWriter(s, h, header)
    if (header === h.header) return h
    return new Proxy(h, {
      get: (target, prop) => {
        if (prop === 'header') return header
        const v = Reflect.get(target, prop, target)
        return typeof v === 'function' ? v.bind(target) : v
      },
    })
  }

  /** 路由交出去、还没关的案件写句柄（按会话编号）。 */
  private readonly writers = new Map<string, Writer>()

  /**
   * 案件里的写句柄：记下它属于哪个实例，以便名单变了以后 relocate() 把写入者搬到新位置。
   * 交出去的是代理：header 是改写过的；关闭时从记录里去掉；其余转给当前真正的句柄（搬过之后是新位置那个）。
   */
  private movingWriter(s: Store, h: Handle, header: Header): Handle {
    const w: Writer = { id: h.id, at: s, cur: h, lost: false }
    this.writers.set(h.id, w)
    const close = async (): Promise<void> => {
      if (this.writers.get(h.id) === w) this.writers.delete(h.id)
      await (w.cur.close as () => Promise<void>).call(w.cur)
    }
    return new Proxy(h, {
      get: (_target, prop) => {
        if (prop === 'header') return header
        if (prop === 'close' || prop === Symbol.asyncDispose) return close
        const v = Reflect.get(w.cur, prop, w.cur)
        return typeof v === 'function' ? v.bind(w.cur) : v
      },
    })
  }

  /** 所属案件根已不在名单上、或已不在盘上的写入者（会话编号）。已失效的不再列。 */
  staleWriters(): string[] {
    return [...this.writers.values()].filter((w) => !w.lost && this.writerStale(w)).map((w) => w.id)
  }

  private writerStale(w: Writer): boolean {
    return !this.current(w.at) || !existsSync(w.at.caseRoot!)
  }

  /**
   * 把一个会话的写入者搬到它现在所在的实例（调用方保证这个会话的 Agent 空闲，见会话存储插件）。
   * @param expectedEvents - 内存里这个会话的事件数（DSH 会话的 seq）；新位置的记录（补齐之后）必须正好这么长才接着写。不知道时不核对。
   * @returns moved：已搬；kept：不需要搬；lost：搬不了（新位置找不到、记录对不上、打开失败），写入者已注销，记为已失效。
   */
  relocate(id: string, expectedEvents?: number): Promise<'moved' | 'kept' | 'lost'> {
    // 同一会话同时只搬一次（打开案件后的刷新与后台刷新可能同时触发）；后来的等前一次做完再判
    const prev = this.relocating.get(id) ?? Promise.resolve('kept' as const)
    const run = prev.catch(() => 'kept' as const).then(() => this.relocateOnce(id, expectedEvents))
    this.relocating.set(id, run)
    void run.finally(() => { if (this.relocating.get(id) === run) this.relocating.delete(id) }).catch(() => undefined)
    return run
  }

  private readonly relocating = new Map<string, Promise<'moved' | 'kept' | 'lost'>>()

  private async relocateOnce(id: string, expectedEvents?: number): Promise<'moved' | 'kept' | 'lost'> {
    const w = this.writers.get(id)
    if (!w || w.lost || !this.writerStale(w)) return 'kept'
    const from = w.at
    // 先关旧句柄：把缓冲的事件落进旧处、注销旧实例里的写入者（搬家时旧目录已不在，落不进去就丢在旧处，与不搬一样）
    await (w.cur.close as () => Promise<void>).call(w.cur).catch(() => undefined)
    const lose = (reason: string): 'lost' => {
      w.lost = true
      this.opts.log?.('warn', 'session_store.writer_lost', { index: from.index, reason })
      return 'lost'
    }
    const next = await this.locate(id, undefined, from).catch(() => undefined)
    if (!next?.caseRoot || next === from) return lose('not_found')
    let fresh: Handle
    try {
      fresh = await next.backend.open(id, 'write')
    } catch (error) {
      return lose((error as Error)?.name ?? 'open_failed')
    }
    const read = async (h: Handle): Promise<unknown[]> => (await (h.read as () => Promise<{ events: unknown[] }>).call(h)).events
    // 新位置的记录要与这个会话一致：旧处还在盘上（复制）时逐条比对旧处——新位置是旧处的前缀就把旧处多出来的补过去
    // （复制之后旧处又写过：复制时正在跑的那一轮、复制后点开会话 resume 补的事件），补完必须与旧处完全相同；
    // 两处各自写过（同样长也算）就不搬。旧处已不在（搬家）时两处本来是同一份，只核对长度。最后都要与内存里的会话一样长。
    let same = false
    try {
      let events = await read(fresh)
      if (existsSync(from.caseRoot!)) {
        const old = await from.backend.open(id, 'read')
        try {
          const all = await read(old)
          const prefix = events.length <= all.length && JSON.stringify(all.slice(0, events.length)) === JSON.stringify(events)
          if (prefix && events.length < all.length) {
            const added = all.length - events.length
            await (fresh.append as (e: unknown[]) => Promise<void>).call(fresh, all.slice(events.length))
            events = await read(fresh)
            this.opts.log?.('info', 'session_store.writer_caught_up', { count: added })
          }
          same = prefix && JSON.stringify(events) === JSON.stringify(all)
        } finally {
          await (old.close as () => Promise<void>).call(old).catch(() => undefined)
        }
      } else {
        same = true
      }
      if (expectedEvents !== undefined && events.length !== expectedEvents) same = false
    } catch { /* 当对不上 */ }
    if (!same) {
      await (fresh.close as () => Promise<void>).call(fresh).catch(() => undefined)
      return lose('diverged')
    }
    w.cur = fresh
    w.at = next
    this.owner.set(id, next)
    this.opts.log?.('info', 'session_store.writer_moved', { index: next.index })
    return 'moved'
  }

  /** 这个会话的写入位置已失效（搬不了），下一轮要拒绝。 */
  writerLost(id: string): boolean {
    return this.writers.get(id)?.lost === true
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
