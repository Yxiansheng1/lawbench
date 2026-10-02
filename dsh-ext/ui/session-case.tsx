// 会话 → 案件：会话的工作目录就是案件文件夹（Spec 1.2）。没登记过的文件夹不会自动登记（登记会建 工作区\），
// 由律师点"作为案件打开"才调 /api/case/open。
import { useEffect, type ReactNode } from 'react'
import { openCase, loadRecent } from './cases.ts'
import { Button, Empty, S } from './kit.tsx'
import { app, samePath, type CaseRef } from './state.ts'
import { useStore } from './store.ts'

export type SessionProps = {
  sessionId: string
  useSessions?: <T>(select: (s: { byId: Record<string, { cwd?: string } | undefined> }) => T) => T
}

let recentLoaded = false

export function useSessionCase(p: SessionProps): { root: string | undefined; caseRef: CaseRef | undefined } {
  const root = p.useSessions?.((s) => s.byId[p.sessionId]?.cwd)
  const caseRef = useStore(app, (s) => (root ? s.cases.find((c) => samePath(c.root, root)) : undefined))
  useEffect(() => { if (!recentLoaded) { recentLoaded = true; void loadRecent() } }, [])
  return { root, caseRef }
}

/** 有案件时渲染 children，否则说明原因并给出"作为案件打开"。 */
export function WithCase({ p, children }: { p: SessionProps; children: (c: CaseRef) => ReactNode }) {
  const { root, caseRef } = useSessionCase(p)
  if (caseRef) return <>{children(caseRef)}</>
  return (
    <div style={S.pane}>
      <Empty>{root ? '这个会话所在的文件夹还没作为案件打开。' : '这个会话没有对应的案件文件夹。请从首页打开案件。'}</Empty>
      {root ? <div style={{ ...S.sub, wordBreak: 'break-all' }}>{root}</div> : null}
      {root ? <div><Button variant="outline" size="sm" onClick={() => void openCase(root, null, false)}>作为案件打开</Button></div> : null}
    </div>
  )
}
