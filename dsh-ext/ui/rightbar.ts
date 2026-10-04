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

export function loadSeeded(): Set<string> {
  try { return new Set(JSON.parse(localStorage.getItem(SEEDED_KEY) ?? '[]') as string[]) } catch { return new Set() }
}
export function saveSeeded(ids: string[]): void {
  try { localStorage.setItem(SEEDED_KEY, JSON.stringify(ids)) } catch { /* 记不下就下次再开一次 */ }
}
