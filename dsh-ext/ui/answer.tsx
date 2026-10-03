// 输入区上方的任务结果（T14 派修 2，执行令 2026-10-03 15:41；用户原话件 OWNER-T14预算到顶对话区显示草稿-20261003-1549）：
// 到达用量上限那一轮，模型最后一次调用是"存草稿"、没写出文字回答，对话区只剩"已完成工作"，律师无处点出处。
// 这时在对话区（输入区上方）显示一句提示和刚存的草稿正文，正文用 DSH 的 MarkdownText 画，出处是可点按钮（同对话区的出处）。
// 草稿正文每次经 Host 的 taskAnswer 从案件里读（只读该任务目录），界面不留副本。成果页本轮不加草稿预览（候 owner N65）。
import { MarkdownText } from '@deepseek-ai/dsh-client-ui-primitives'
import { useMemo } from 'react'
import { citationInlineMarks } from './citation.ts'
import { citationDeps } from './citation-deps.ts'
import { Button, C, Loading, useLoad } from './kit.tsx'
import { app, call, hideTaskAnswer, type CaseRef } from './state.ts'
import { useStore } from './store.ts'

export interface TaskAnswerView {
  status: string
  session_id: string | null
  used: number | null
  limit: number | null
  draft: { title: string; version: number; path: string; text: string; truncated: boolean } | null
}

/**
 * 提示那一句（纯函数，测试守着）。
 * - 用完模型调用次数：已用完本次运行的模型调用次数（8/8），结果已保存到成果
 * - 没到次数上限却停了（时间到）：已到本次运行的时间上限，……
 * - 没存过草稿：……，没有存下草稿；做到哪里请看成果里的"未完成"
 */
export function answerNotice(v: Pick<TaskAnswerView, 'status' | 'used' | 'limit' | 'draft'>): string {
  const byCalls = v.used !== null && v.limit !== null && v.used >= v.limit
  const head = v.status !== 'budget_stopped' ? '本次运行已结束'
    : byCalls ? `已用完本次运行的模型调用次数（${v.used}/${v.limit}）` : '已到本次运行的时间上限'
  return v.draft ? `${head}，结果已保存到成果` : `${head}，没有存下草稿；做到哪里请看成果里的"未完成"`
}

const LABELS = { code: { copyLabel: '复制', copiedLabel: '已复制' }, footnotes: '注释' }

/** 某会话输入区上方的任务结果；没有要显示的为空。 */
export function TaskAnswerSlot({ caseRef, sessionId }: { caseRef: CaseRef; sessionId: string }) {
  const taskId = useStore(app, (s) => s.answers[sessionId])
  if (!taskId) return null
  return <TaskAnswerPanel key={taskId} caseRef={caseRef} sessionId={sessionId} taskId={taskId} />
}

function TaskAnswerPanel({ caseRef, sessionId, taskId }: { caseRef: CaseRef; sessionId: string; taskId: string }) {
  const [data] = useLoad(() => call<TaskAnswerView>('taskAnswer', { root: caseRef.root, task_id: taskId }), [caseRef.root, taskId])
  const marks = useMemo(() => citationInlineMarks(citationDeps), [])
  return (
    <section aria-label="本次运行的结果" style={{ border: `1px solid ${C.warn}`, borderRadius: C.rMd, padding: '6px 10px', margin: '0 0 6px', fontSize: 13, color: C.text, maxHeight: '45vh', overflow: 'auto' }}>
      <Loading data={data}>{(v) => (
        <>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', justifyContent: 'space-between' }}>
            <strong style={{ color: C.warn }}>{answerNotice(v)}</strong>
            <Button size="sm" variant="ghost" style={{ flexShrink: 0, whiteSpace: 'nowrap' }} onClick={() => hideTaskAnswer(sessionId)}>收起</Button>
          </div>
          {v.draft ? (
            <>
              <div style={{ color: C.sub, fontSize: 12, margin: '4px 0' }}>草稿"{v.draft.title}"（第 {v.draft.version} 版）。点出处打开原文；到"成果"里确认保存、导出。</div>
              <MarkdownText text={v.draft.text} labels={LABELS} inlineMarks={marks} />
              {v.draft.truncated ? <div style={{ color: C.sub, fontSize: 12 }}>草稿较长，这里只显示前一部分。</div> : null}
            </>
          ) : null}
        </>
      )}</Loading>
    </section>
  )
}
