// 案件根名单（T17 第三步，执行令 2026-09-30 15:16 第二节第 3 条）：会话存储路由按它决定"哪个 cwd 属于哪个案件"。
// 不取自 DSH 的工作区登记（工作区服务启动时要先 list 会话，会循环依赖）。Host 自己缓存一份：
// <应用数据>\案件根名单.json，只存路径；启动时先用缓存，工作台服务起来后按 GET /api/case/recent 刷新并写回。
// 刷新成功时名单以服务为准整个换掉（第三轮复核 B-F1）：服务按案件编号去重、只列现在的位置，案件文件夹复制到别处
// 再打开后旧位置不再列出；原先"没列出的保留"会让旧副本留在名单里且排在前面，续写落进旧文件夹。
import { mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'

export const CACHE_FILE = '案件根名单.json'

type LogFn = (level: 'info' | 'warn' | 'error', event: string, meta?: Record<string, unknown>) => void

/** 路径比较用的键：绝对路径、反斜杠、去掉末尾分隔符、不分大小写（Windows）。 */
export const pathKey = (p: string): string => resolve(p).replace(/\//g, '\\').replace(/\\+$/, '').toLowerCase()

/** cwd 是否就是这个案件根或在它里面。 */
export function inside(cwd: string, root: string): boolean {
  const c = pathKey(cwd)
  const r = pathKey(root)
  return c === r || c.startsWith(r + '\\')
}

const errorCode = (error: unknown): string => (error as NodeJS.ErrnoException)?.code ?? (error as Error)?.name ?? 'Error'

export class CaseRoots {
  private roots: string[] = []

  /**
   * @param cacheDir - 缓存文件所在目录（应用数据目录）；不给时只在内存里。
   * @param log - 缓存读写出错时记一条元数据日志，只记错误码（第三轮复核 A-P3-5）。
   */
  constructor(private readonly cacheDir?: string, private readonly log?: LogFn) {}

  /** 读缓存；文件不在或内容不对就当空名单（不报错，服务起来后会刷新）。文件在却读不出来时记一条日志。 */
  load(): this {
    if (!this.cacheDir) return this
    try {
      const v = JSON.parse(readFileSync(join(this.cacheDir, CACHE_FILE), 'utf8')) as { roots?: unknown }
      this.roots = Array.isArray(v.roots) ? v.roots.filter((x): x is string => typeof x === 'string' && x.length > 0) : []
    } catch (error) {
      this.roots = []
      if ((error as NodeJS.ErrnoException)?.code !== 'ENOENT') this.log?.('warn', 'session_store.case_roots_cache_unreadable', { code: errorCode(error) })
    }
    return this
  }

  list(): readonly string[] { return this.roots }

  /** cwd 所属的案件根（最长的那个）；不在任何案件里返回 undefined。 */
  match(cwd: string | undefined): string | undefined {
    if (!cwd) return undefined
    let best: string | undefined
    for (const r of this.roots) if (inside(cwd, r) && (!best || pathKey(r).length > pathKey(best).length)) best = r
    return best
  }

  /**
   * 按 /api/case/recent 的结果把名单整个换掉：只留 exists 为真的根，路径以服务为准、按路径键去重、保持服务给的顺序。
   * 盘拔了（exists 为假）就不在名单里，插回来服务再报 exists 为真时加回。只在刷新成功时调用；刷新失败保留旧名单。
   * 有变化才写回缓存。
   * @returns 名单是否有变化。
   */
  replace(cases: ReadonlyArray<{ root: string; exists: boolean }>): boolean {
    const byKey = new Map<string, string>()
    for (const c of cases) {
      if (typeof c.root !== 'string' || !c.root || !c.exists) continue
      if (!byKey.has(pathKey(c.root))) byKey.set(pathKey(c.root), c.root)
    }
    const next = [...byKey.values()]
    const changed = next.length !== this.roots.length || next.some((r, i) => r !== this.roots[i])
    this.roots = next
    if (changed) this.save()
    return changed
  }

  private save(): void {
    if (!this.cacheDir) return
    try {
      const file = join(this.cacheDir, CACHE_FILE)
      mkdirSync(dirname(file), { recursive: true })
      const tmp = `${file}.${process.pid}.tmp`
      writeFileSync(tmp, JSON.stringify({ roots: this.roots }, null, 1), 'utf8')
      renameSync(tmp, file)
    } catch (error) {
      // 缓存写不进去只影响下次启动的初值，不影响本次；记一条日志好查
      this.log?.('warn', 'session_store.case_roots_cache_write_failed', { code: errorCode(error) })
    }
  }
}
