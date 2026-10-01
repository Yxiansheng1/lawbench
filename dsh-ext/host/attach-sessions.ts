// 打开案件时把游离会话挂回该案件的工作区（T17 第三轮复核 B-F2）。
// DSH 的工作区登记记的是"会话编号 + 建会话时的 cwd"。案件文件夹搬家或复制后再打开，会话存储路由交出的 cwd 已是新位置，
// 旧工作区按 cwd 核对时把它滤掉，新位置的工作区又是空的，于是旧会话在侧栏落进"未分组"。
// 这里在界面打开案件工作区之后，把 cwd 就是这个案件根、又不在这个工作区里的会话逐个 attachSession：
// attach 会重读记录头（路由已换成现根）核对 cwd，并把它记进登记的路径索引，旧工作区随之不再算它。
// 不只看"不在任何工作区里"：启动时名单缓存还是旧位置、服务还没刷新，登记按旧 cwd 把会话算在旧工作区里（桌面端实测），
// 这种也要挂到新位置。同一机制也把"名单缓存丢了、服务还没起时启动"后被剪出工作区的旧会话补回来（W2）。
// 登记启动时把记录头缓存起来，attach 拿缓存的那份核对 cwd；启动时按旧位置读到的记录头（cwd 是旧位置）会让 attach 失败。
// 登记没有公开的刷新方法，这里调它的私有方法 indexHeaders 用现在的记录头重建这几个会话的索引（换 DSH 提交时核对，
// 见 dsh-patches\PATCHES.md"依赖的私有字段"）；方法不在时跳过，这类会话挂不上、只记日志。
// 先从别的工作区 detachSession，再挂到这个案件的工作区（桌面端实测两条）：
// - 同一编号同时记在两个工作区的登记记录里，DSH 下次启动判"登记不一致"，整个工作区服务（连同会话服务）起不来；
//   先去掉再挂，中途断掉最多是这个会话暂时不在任何工作区（进"未分组"），下次打开案件再挂回；
// - 重建索引后旧工作区按 cwd 已不再算它，但它的登记记录不变、不发变更，界面侧栏仍在旧案件下显示它；detach 写一次记录、发出变更。
// 只对登记记录里确实记着这个编号的工作区 detach：DSH 每写一次某个工作区的记录，都会把路径索引里解析不了的编号一并剪掉
// （桌面端实测：对每个工作区都 detach，不在名单上的案件——比如盘拔了——它的会话就被剪出了工作区）。
// 看"记着"要读登记的原始记录（私有字段 table）：sessionIds 是按路径索引过滤过的，纯搬家后旧工作区记录里还有、
// 索引不算，看不出来。私有字段不在时退回看 sessionIds。
import { pathKey } from '../session-store/case-roots.ts'

export interface WorkspaceLike {
  readonly id?: string
  readonly path: string
  readonly sessionIds: readonly string[]
  attachSession(sessionId: string): Promise<void>
  detachSession?(sessionId: string): Promise<void>
}
type HeaderLike = { id: string; cwd?: string }
export interface RegistryLike {
  list(): WorkspaceLike[]
  /** DSH 工作区登记的私有方法：按给的记录头更新它的记录头缓存与路径索引。 */
  indexHeaders?(headers: readonly HeaderLike[]): Promise<void>
  /** DSH 工作区登记的私有字段：工作区编号 → 登记的原始记录（sessionIds 未经路径索引过滤）。 */
  readonly table?: { get(id: string): { sessionIds?: readonly string[] } | undefined }
}
export interface PersistenceLike { list(): Promise<ReadonlyArray<{ header: HeaderLike }>> }
type LogFn = (level: 'info' | 'warn' | 'error', event: string, meta?: Record<string, unknown>) => void

/**
 * @param root - 案件根（界面刚把它作为工作区打开）。
 * @returns 挂回了几个、失败几个；找不到这个案件的工作区时都是 0。
 */
export async function attachCaseSessions(registry: RegistryLike, persistence: PersistenceLike, root: string, log: LogFn = () => {}): Promise<{ attached: number; failed: number }> {
  const key = pathKey(root)
  const workspaces = registry.list()
  const ws = workspaces.find((w) => pathKey(w.path) === key)
  if (!ws) return { attached: 0, failed: 0 }
  const stale = (await persistence.list())
    .map((row) => row.header)
    .filter((h) => h.cwd !== undefined && pathKey(h.cwd) === key && !ws.sessionIds.includes(h.id))
  const todo = stale.map((h) => h.id)
  /** 登记记录里记着 id 的别的工作区（读原始记录；私有字段不在时看过滤后的 sessionIds）。 */
  const recordedIn = (id: string) => workspaces.filter((w) => {
    if (w === ws) return false
    const raw = w.id === undefined ? undefined : registry.table?.get?.(w.id)?.sessionIds
    return (raw ?? w.sessionIds).includes(id)
  })
  if (stale.length && typeof registry.indexHeaders === 'function') {
    try {
      await registry.indexHeaders(stale)
    } catch (error) {
      log('warn', 'workspace.reindex_failed', { error: (error as Error)?.name ?? 'Error' })
    }
  }
  const failedIds = new Set<string>()
  const attach = async (id: string) => {
    try {
      await ws.attachSession(id)
      failedIds.delete(id)
    } catch (error) {
      failedIds.add(id)
      // 只记错误名，不记路径和编号
      log('warn', 'workspace.attach_failed', { error: (error as Error)?.name ?? 'Error' })
    }
  }
  for (const id of todo) {
    for (const w of recordedIn(id)) {
      try {
        await w.detachSession?.(id)
      } catch (error) {
        log('warn', 'workspace.detach_failed', { error: (error as Error)?.name ?? 'Error' })
      }
    }
  }
  for (const id of todo) await attach(id)
  // DSH 的 attachSession 在登记记录里已有这个编号时不重读记录头，写入时又把路径索引里没有的编号剪掉：
  // 名单缓存丢了以后启动的那种情况（记录里还有、索引里没有），第一个挂的会被剪掉。没挂上的再挂一次（这次会重读记录头）。
  for (const id of todo) if (!failedIds.has(id) && !ws.sessionIds.includes(id)) await attach(id)
  const attached = todo.filter((id) => ws.sessionIds.includes(id)).length
  const failed = failedIds.size
  if (attached || failed) log('info', 'workspace.case_sessions_attached', { attached, failed })
  return { attached, failed }
}
