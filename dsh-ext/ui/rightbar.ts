// 右侧栏默认展开（令 1347 第 3 条）：案件（含日常事务）的会话第一次显示时开好成果、原文查看、材料三个标签，停在"材料"
// （最后开的为当前）；每个会话只做一次（记在本机，最多 500 个），之后折叠、关标签都由 DSH 按会话记住。
import { TABS } from './cases.ts'

/** 依次打开的标签：最后一个是停留的。 */
export const RIGHTBAR_TABS = [TABS.results, TABS.source, TABS.materials] as const
export const SEEDED_KEY = 'lawbench.rightbar.seeded'

/**
 * @param seen - 已经开过的会话（读自本机）。@param persist - 记下（最多 500 个）。@param open - 开一个标签。
 * @returns seed(会话 id, 是不是案件会话)：这次开了返回 true。
 */
export function createRightbarSeeder(seen: Set<string>, persist: (ids: string[]) => void, open: (kind: string) => void) {
  return (sid: string | undefined, isCase: boolean): boolean => {
    if (!sid || !isCase || seen.has(sid)) return false
    seen.add(sid)
    persist([...seen].slice(-500))
    for (const kind of RIGHTBAR_TABS) open(kind)
    return true
  }
}

/**
 * 侧栏里旧位置那一项（令 1515 第 3 条；1612 复核 P1）：路径写法对得上、且不是刚打开的那一项。
 * 律师选的写法（映射盘、subst 盘、经过目录联接）和服务 realpath 后的写法可能不同，字符串比对会认错——所以刚打开的那一项永远排除，
 * 调用方移除前还要问 Host 这个文件夹是不是确实不在了。
 */
export function forgettableWorkspace(items: Array<{ workspaceId: string; path: string }>, root: string, except: string | undefined, same: (a: string, b: string) => boolean): string | undefined {
  return items.find((w) => w.workspaceId !== except && same(w.path, root))?.workspaceId
}

export function loadSeeded(): Set<string> {
  try { return new Set(JSON.parse(localStorage.getItem(SEEDED_KEY) ?? '[]') as string[]) } catch { return new Set() }
}
export function saveSeeded(ids: string[]): void {
  try { localStorage.setItem(SEEDED_KEY, JSON.stringify(ids)) } catch { /* 记不下就下次再开一次 */ }
}
