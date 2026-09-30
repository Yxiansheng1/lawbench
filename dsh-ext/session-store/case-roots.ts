// 案件根名单（T17 第三步，执行令 2026-09-30 15:16 第二节第 3 条）：会话存储路由按它决定"哪个 cwd 属于哪个案件"。
// 不取自 DSH 的工作区登记（工作区服务启动时要先 list 会话，会循环依赖）。Host 自己缓存一份：
// <应用数据>\案件根名单.json，只存路径；启动时先用缓存，工作台服务起来后按 GET /api/case/recent 刷新并写回。
import { mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'

export const CACHE_FILE = '案件根名单.json'

/** 路径比较用的键：绝对路径、反斜杠、去掉末尾分隔符、不分大小写（Windows）。 */
export const pathKey = (p: string): string => resolve(p).replace(/\//g, '\\').replace(/\\+$/, '').toLowerCase()

/** cwd 是否就是这个案件根或在它里面。 */
export function inside(cwd: string, root: string): boolean {
  const c = pathKey(cwd)
  const r = pathKey(root)
  return c === r || c.startsWith(r + '\\')
}

export class CaseRoots {
  private roots: string[] = []

  /** @param cacheDir - 缓存文件所在目录（应用数据目录）；不给时只在内存里。 */
  constructor(private readonly cacheDir?: string) {}

  /** 读缓存；文件不在或内容不对就当空名单（不报错，服务起来后会刷新）。 */
  load(): this {
    if (!this.cacheDir) return this
    try {
      const v = JSON.parse(readFileSync(join(this.cacheDir, CACHE_FILE), 'utf8')) as { roots?: unknown }
      this.roots = Array.isArray(v.roots) ? v.roots.filter((x): x is string => typeof x === 'string' && x.length > 0) : []
    } catch { this.roots = [] }
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
   * 按 /api/case/recent 的结果更新：还在的加入（路径以服务为准），标明不在了的去掉（案件搬家后旧路径就是这样），
   * 其余缓存里有、这次没列出的保留（最近案件列表不保证列全）。有变化才写回缓存。
   * @returns 名单是否有变化。
   */
  merge(cases: ReadonlyArray<{ root: string; exists: boolean }>): boolean {
    const byKey = new Map(this.roots.map((r) => [pathKey(r), r]))
    for (const c of cases) {
      if (typeof c.root !== 'string' || !c.root) continue
      if (c.exists) byKey.set(pathKey(c.root), c.root)
      else byKey.delete(pathKey(c.root))
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
    } catch { /* 缓存写不进去只影响下次启动的初值，不影响本次 */ }
  }
}
