// 会话投影缓存按案件存（T17 第三轮综合裁决 A-P2-1 = B-F3，选 ①）。
// DSH 的投影缓存（session-projection-cache）把每个会话的投影（标题、最近活动、是否空白……其中含律师发的原话）
// 存进 $DSH_HOME\storages\session_projcache，不跟案件走，所以第三步把它关了；关掉后没打开过的会话在侧栏没有标题、
// 不按最后发言排序、也不算空白（列表里冷会话的这几项只从这份缓存取，不重放记录）。
// 这里把它接回来：原版缓存类原样用（它的逻辑、写入时机、身份核对都不动），只给它一个替身"存储域"，
// 让每个会话的那一条记录落在该会话所在案件的 <案件>\工作区\会话缓存\<编号>.json，与会话记录一样跟着案件走。
// - 会话在哪个案件由会话存储路由决定（新建、列表、打开时记下的"编号 → 案件根"）；
// - 不在案件里的旧会话（默认根）和还不知道在哪的会话：只放内存，不落盘，$DSH_HOME 里不留原话；
// - 案件搬家：记录里的身份核对含建会话时的 cwd，路由交给 DSH 的记录头 cwd 已换成现根，这里读出时一并换成现根，
//   记录本来就在这个案件的文件夹里，是同一个会话；
// - 读坏、版本不对的记录当没有（缓存只是加速，没有就重放记录或不显示标题）；写失败只记元数据日志，不抛错。
import { mkdir, rename, writeFile } from 'node:fs/promises'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { pathKey } from './case-roots.ts'
import type { LogFn } from './router.ts'

/** 案件里存投影缓存的子目录（相对案件根）。 */
export const CASE_CACHE_DIR = join('工作区', '会话缓存')

/** 能当文件名的会话编号（DSH 的编号是 UUID）；别的写法只放内存。 */
const SAFE_ID = /^[A-Za-z0-9_-][A-Za-z0-9._-]{0,199}$/

type Identity = { cwd?: string; [k: string]: unknown }
export type CacheRecord = { identity: Identity; rows: Record<string, unknown> }

export interface ProjectionTableOptions {
  /** 会话所在的案件根：在案件里返回根，在默认根返回 null，不知道返回 undefined。 */
  caseRootOf(id: string): string | null | undefined
  /** 校验一条记录（原版的 checkpointRecord 模式）；不合格返回 undefined。 */
  parse(value: unknown): CacheRecord | undefined
  log?: LogFn
}

/**
 * 原版缓存用到的那张表（DSH KvTable 的形状）：get 同步、put 先落盘再改内存。
 * 键是会话编号；落盘位置按会话所在案件决定。
 */
export class CaseProjectionTable {
  private readonly memo = new Map<string, CacheRecord | null>()
  private tail: Promise<void> = Promise.resolve()

  constructor(private readonly opts: ProjectionTableOptions) {}

  /** 这条会话的缓存文件；不落盘（默认根、不知道在哪、编号不能当文件名）时返回 undefined。 */
  private where(id: string): { caseRoot: string; file: string; key: string } | undefined {
    const caseRoot = this.opts.caseRootOf(id)
    if (!caseRoot || !SAFE_ID.test(id)) return undefined
    const dir = join(caseRoot, CASE_CACHE_DIR)
    return { caseRoot, file: join(dir, `${id}.json`), key: `${pathKey(dir)}|${id}` }
  }

  private memoKey(id: string): string { return this.where(id)?.key ?? `mem|${id}` }

  get(id: string): CacheRecord | undefined {
    const at = this.where(id)
    const key = at?.key ?? `mem|${id}`
    let rec = this.memo.get(key)
    if (rec === undefined && at) {
      rec = null
      try {
        rec = this.opts.parse(JSON.parse(readFileSync(at.file, 'utf8'))) ?? null
        if (!rec) this.opts.log?.('warn', 'session_store.projection_cache_invalid', {})
      } catch (error) {
        if ((error as NodeJS.ErrnoException)?.code !== 'ENOENT') {
          this.opts.log?.('warn', 'session_store.projection_cache_unreadable', { code: (error as NodeJS.ErrnoException)?.code ?? (error as Error)?.name ?? 'Error' })
        }
      }
      this.memo.set(key, rec)
    }
    if (!rec) return undefined
    // 搬家后：身份里的 cwd 是建会话时的旧路径，换成现根（与路由交给 DSH 的记录头一致）
    const cwd = rec.identity.cwd
    if (at && cwd !== undefined && pathKey(cwd) !== pathKey(at.caseRoot)) return { ...rec, identity: { ...rec.identity, cwd: at.caseRoot } }
    return rec
  }

  /** 先落盘再改内存；落盘失败只记日志（不抛错，缓存下次再写），内存也不改。 */
  put(id: string, value: CacheRecord): Promise<void> {
    const run = this.tail.then(async () => {
      const at = this.where(id)
      if (at) {
        try {
          await mkdir(join(at.caseRoot, CASE_CACHE_DIR), { recursive: true })
          const tmp = `${at.file}.${process.pid}.tmp`
          await writeFile(tmp, JSON.stringify(value), 'utf8')
          await rename(tmp, at.file)
        } catch (error) {
          this.opts.log?.('warn', 'session_store.projection_cache_write_failed', { code: (error as NodeJS.ErrnoException)?.code ?? (error as Error)?.name ?? 'Error' })
          return
        }
      }
      this.memo.set(this.memoKey(id), value)
    })
    this.tail = run.catch(() => undefined)
    return run
  }

  async delete(id: string): Promise<boolean> {
    const had = this.get(id) !== undefined
    // 原版缓存不删记录；这里只从内存去掉（文件随案件文件夹，留着无害）
    this.memo.set(this.memoKey(id), null)
    return had
  }

  async update(id: string, fn: (current: CacheRecord) => CacheRecord): Promise<CacheRecord> {
    const current = this.get(id)
    if (current === undefined) throw new Error('missing-key')
    const next = fn(current)
    await this.put(id, next)
    return next
  }

  /** 只列内存里已读到的（原版缓存不遍历这张表）。 */
  *entries(): IterableIterator<[string, CacheRecord]> {
    for (const [key, rec] of [...this.memo]) if (rec) yield [key.slice(key.lastIndexOf('|') + 1), rec]
  }

  *keys(): IterableIterator<string> { for (const [k] of this.entries()) yield k }

  get size(): number { return [...this.entries()].length }

  /** 等排队的写入做完。 */
  drain(): Promise<void> { return this.tail }
}

/** 给原版缓存的替身存储域：open 任何域都返回同一张表；关闭时等写入做完。 */
export function caseProjectionDomain(table: CaseProjectionTable): { open(spec: { name: string }): Promise<unknown> } {
  return {
    async open(spec) {
      return { name: spec.name, global: undefined, table: () => table, close: () => table.drain() }
    },
  }
}
