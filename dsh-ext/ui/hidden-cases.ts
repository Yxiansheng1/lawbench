// 左栏"从列表移除案件"后，首页的案件卡片和"切换案件"也不再列它（令 2125）。
// 记录在 Host（应用数据目录，见 host/hidden-cases.ts）；界面这边：盯着左栏的案件列表，少了一项就告诉 Host，
// 首页、"切换案件"、"先选择案件"按 Host 记着的案件过滤。再次打开、拖入、从左栏添加同一文件夹就恢复显示。
// 案件本身不动：登记、文件夹、会话都在；还开着的会话照样认得出它属于哪个案件（所以只过滤列表，不从 cases 里去掉）。
import { app, call, samePath, type CaseRef } from './state.ts'

type Item = { workspaceId: string; path: string }
type Snapshot = { items: readonly Item[]; state?: string }

/** 列出来给律师选的案件：去掉已从列表移除的。 */
export function visibleCases(cases: CaseRef[], hidden: readonly string[]): CaseRef[] {
  return hidden.length ? cases.filter((c) => !hidden.includes(c.case_id)) : cases
}

/**
 * 左栏列表里这次少了哪些位置。同一位置还有别的项留着的不算（左栏里还看得到它）。
 * @returns 被移除的各项的文件夹。
 */
export function removedPaths(prev: readonly Item[], next: readonly Item[]): string[] {
  const left = new Set(next.map((w) => w.workspaceId))
  return prev.filter((w) => !left.has(w.workspaceId) && !next.some((n) => samePath(n.path, w.path))).map((w) => w.path)
}

/** 告诉 Host 这个位置的案件已从列表移除，并按它回的名单更新界面。没有对应登记的 Host 会忽略。 */
export async function hideCaseAt(root: string): Promise<void> {
  const r = await call<{ hidden: boolean; case_ids: string[] }>('caseHide', { root })
  if (r.ok) app.set((s) => ({ ...s, hiddenCases: r.value.case_ids }))
}

/**
 * 盯着左栏的案件列表：律师从列表移除一项，就把对应的案件记为已移除。
 * 只比两次都读全了的列表（连接断开重连中的不比、也不当成基准）；程序自己撤掉的项（案件换了位置后撤旧位置那一项）
 * 和"日常事务"不记——日常事务不是律师建的案件，下次启动还会自己打开。
 * @param list - DSH 的工作区列表。
 * @param own - 程序自己撤掉的项的 id（撤之前放进去）。
 * @returns 停止盯着。
 */
export function watchRemovedCases(list: { getSnapshot(): Snapshot; subscribe(fn: () => void): () => void }, own: ReadonlySet<string>, hide: (root: string) => Promise<void> = hideCaseAt): () => void {
  const settled = (s: Snapshot) => s.state === undefined || s.state === 'idle'
  const first = list.getSnapshot()
  let prev: readonly Item[] | undefined = settled(first) ? first.items : undefined
  return list.subscribe(() => {
    const snap = list.getSnapshot()
    if (!settled(snap)) return
    const before = prev
    prev = snap.items
    if (!before) return
    const gone = before.filter((w) => !own.has(w.workspaceId))
    const daily = app.get().dailyRoot
    for (const root of removedPaths(gone, snap.items)) {
      if (daily && samePath(root, daily)) continue
      void hide(root).catch(() => undefined)
    }
  })
}
