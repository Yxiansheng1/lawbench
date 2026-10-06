// 右侧栏"成果"标签（PRD 7.9）：任务和草稿、自检结果、确认保存、导出格式、选作下一步输入。
// 契约 1.2（N35，执行令 1134）：任务项用 coverage 显示"没读全的材料"、用 citation_check 显示自检结果
// （为 null 时"尚未统计""尚未核对"，不显示"通过"）；"已确认的成果"用 GET /api/outputs（成果/索引.json）。
// citation_passed（任务项、成果项里的布尔值）仍不单独显示，自检结果以 citation_check 为准。
import { useEffect, useState } from 'react'
import { Modal } from '@deepseek-ai/dsh-client-ui-primitives'
import { citationSummary, coverageLines, errorText, type CitationCheck, type Coverage } from './format.ts'
import { Badge, Button, C, Empty, getNav, Loading, S, useLoad } from './kit.tsx'
import { app, call, lb, notice, setIntent, showTaskAnswer, type CaseRef } from './state.ts'
import type { TaskAnswerView } from './answer.tsx'
import { useStore } from './store.ts'
import { WithCase, type SessionProps } from './session-case.tsx'
import { openCaseFolder } from './folder-actions.ts'
import { ARCHIVE_SKILL, ArchiveDialog } from './archive.tsx'

const NO_INPUTS: string[] = []

interface Draft { title: string; path: string; version: number }
interface Task { task_id: string; skill: string | null; status: string; drafts: Draft[]; finished_at: string | null; coverage: Coverage | null; citation_check: CitationCheck | null }
interface Output { title: string; version: number; files: Array<{ format: string; path: string }>; task_id: string; confirmed_at: string }

const TASK_WORD: Record<string, [string, 'ok' | 'warn' | 'err' | 'info' | 'faint']> = {
  running: ['进行中', 'info'], completed: ['已完成', 'ok'], cancelled: ['已停止', 'faint'], interrupted: ['中断', 'warn'],
  failed: ['失败', 'err'], budget_stopped: ['到达用量上限', 'warn'], output_limit: ['输出过长被截断', 'warn'],
}

export function ResultsTab(p: SessionProps) {
  return <WithCase p={p}>{(c) => <Results caseRef={c} sessionId={p.sessionId} />}</WithCase>
}

function Results({ caseRef, sessionId }: { caseRef: CaseRef; sessionId: string }) {
  const id = caseRef.case_id
  const [tasks, reload] = useLoad(() => call<{ tasks: Task[] }>('tasksList', { case_id: id }), [id], 5000)
  const [outputs, reloadOutputs] = useLoad(() => call<{ outputs: Output[] }>('outputsList', { case_id: id }), [id])
  const [titles, setTitles] = useState<Record<string, string>>({})
  // 选择器必须返回稳定的引用：每次新建 [] 会让 useSyncExternalStore 无限重渲染（React #185）
  // 显示的是本会话的选择；还有没取走的待带入意向时以它为准（T13 返修 P2-2）
  const inputs = useStore(app, (s) => s.intents[id]?.inputs ?? s.selections[sessionId]?.inputs) ?? NO_INPUTS
  const [confirming, setConfirming] = useState<{ task: Task; draft: Draft } | null>(null)
  const [archiving, setArchiving] = useState<string | null>(null)
  useEffect(() => { void lb().listSkills().then((r) => setTitles(Object.fromEntries(r.value.skills.map((s) => [s.name, s.title])))).catch(() => undefined) }, [])
  const skillName = (t: Task) => t.task_id.startsWith('P-') ? '案件 wiki 整理' : t.skill ? titles[t.skill] ?? t.skill : '自由对话'
  const toggleInput = (path: string) => setIntent(id, { inputs: inputs.includes(path) ? inputs.filter((x) => x !== path) : [...inputs, path] })

  return (
    <div style={S.pane}>
      <div style={{ fontWeight: 600 }}>{caseRef.name}</div>
      <Loading data={tasks}>{(v) => v.tasks.length === 0 ? <Empty>还没有任务。在对话里运行一个 Skill 后，草稿会出现在这里。</Empty> : (
        <ul style={S.list}>{v.tasks.map((t) => {
          const [word, tone] = TASK_WORD[t.status] ?? [t.status, 'faint']
          return (
            <li key={t.task_id} style={{ ...S.card, padding: 8, display: 'flex', flexDirection: 'column', gap: 6 }}>
              <div style={S.between}><span style={{ fontWeight: 500 }}>{skillName(t)}</span><Badge tone={tone}>{word}</Badge></div>
              {t.finished_at ? <div style={S.sub}>完成于 {new Date(t.finished_at).toLocaleString('zh-CN')}</div> : null}
              {t.drafts.length === 0 ? <div style={S.sub}>没有草稿</div> : t.drafts.map((d) => (
                <div key={d.path} style={{ borderTop: `1px solid ${C.border}`, paddingTop: 6, display: 'flex', flexDirection: 'column', gap: 4 }}>
                  <div style={S.between}><span>{d.title}</span><span style={S.sub}>第 {d.version} 版</span></div>
                  <div style={{ ...S.row, flexWrap: 'wrap' }}>
                    <Button size="sm" variant="outline" disabled={t.status === 'running'} onClick={() => setConfirming({ task: t, draft: d })}>确认保存…</Button>
                    <Button size="sm" variant={inputs.includes(d.path) ? 'primary' : 'ghost'} aria-pressed={inputs.includes(d.path)} onClick={() => toggleInput(d.path)}>
                      {inputs.includes(d.path) ? '已选作下一步输入' : '选作下一步输入'}
                    </Button>
                  </div>
                </div>
              ))}
              {t.status === 'budget_stopped' ? (
                <div style={S.row}>
                  <Button size="sm" variant="outline" onClick={() => void openAnswer(caseRef, sessionId, t.task_id)}>在对话区查看</Button>
                </div>
              ) : null}
              {t.skill === ARCHIVE_SKILL ? (
                <div style={S.row}>
                  <Button size="sm" variant="outline" disabled={t.status === 'running'} onClick={() => setArchiving(t.task_id)}>核对归档方案并生成归档文件…</Button>
                </div>
              ) : null}
              <CheckLine title="自检结果" {...citationSummary(t.citation_check)} />
              {(() => { const cov = coverageLines(t.coverage); return <CheckLine title="没读全的材料" tone={cov.ok ? 'ok' : cov.lines.length ? 'err' : 'faint'} summary={cov.summary} lines={cov.lines} /> })()}
            </li>
          )
        })}</ul>
      )}</Loading>
      <div style={{ ...S.between, marginTop: 8 }}>
        <span style={{ fontWeight: 600 }}>已确认的成果</span>
        <Button size="sm" variant="ghost" onClick={() => void openCaseFolder(caseRef, 'outputs')}>打开所在文件夹</Button>
      </div>
      <Loading data={outputs}>{(v) => v.outputs.length === 0 ? <Empty>还没有确认保存的成果。</Empty> : (
        <ul style={S.list}>{v.outputs.map((o) => (
          <li key={`${o.title}-${o.version}`} style={{ ...S.card, padding: 8, display: 'flex', flexDirection: 'column', gap: 4 }}>
            <div style={S.between}><span style={{ fontWeight: 500 }}>{o.title}</span><span style={S.sub}>第 {o.version} 版</span></div>
            <div style={S.sub}>确认于 {new Date(o.confirmed_at).toLocaleString('zh-CN')}</div>
            {o.files.map((f) => <div key={f.path} style={{ ...S.sub, wordBreak: 'break-all' }}>{f.path}</div>)}
          </li>
        ))}</ul>
      )}</Loading>
      {archiving ? <ArchiveDialog caseRef={caseRef} taskId={archiving} onClose={() => { setArchiving(null); void reload() }} /> : null}
      {confirming ? <ConfirmDialog caseRef={caseRef} task={confirming.task} draft={confirming.draft} onClose={() => setConfirming(null)} onDone={() => { setConfirming(null); void reload(); void reloadOutputs() }} /> : null}
    </div>
  )
}

/** 确认保存：草稿进成果目录并导出（/api/outputs/confirm）；选导出格式和 Word 模板。本机生成，不发服务器。 */
function ConfirmDialog({ caseRef, task, draft, onClose, onDone }: { caseRef: CaseRef; task: Task; draft: Draft; onClose: () => void; onDone: () => void }) {
  const [md, setMd] = useState(false)
  const [docx, setDocx] = useState(true)
  const [template, setTemplate] = useState<'文书' | '合同' | ''>('文书')
  const [busy, setBusy] = useState(false)
  const save = async () => {
    setBusy(true)
    const formats = [...(md ? ['md'] : []), ...(docx ? ['docx'] : [])]
    const r = await call<{ outputs: Array<{ format: string; path: string; version: number }> }>('outputsConfirm', {
      case_id: caseRef.case_id, task_id: task.task_id, draft: draft.path, formats, template: docx && template ? template : null,
    })
    setBusy(false)
    if (!r.ok) { notice('没有保存成功', errorText(r.error)); return }
    notice('已保存到成果', `"${draft.title}"已确认保存。`, r.value.outputs.map((o) => `${o.path}（第 ${o.version} 版）`))
    onDone()
  }
  return (
    <Modal open onClose={onClose} title="确认保存" closeLabel="关闭"
      footer={<><Button variant="outline" onClick={onClose}>取消</Button><Button variant="primary" disabled={busy || (!md && !docx)} onClick={() => void save()}>保存到成果</Button></>}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        <div>把草稿"{draft.title}"（第 {draft.version} 版）确认保存到案件的"成果"文件夹。</div>
        <div style={S.row}>导出格式
          <label style={S.row}><input type="checkbox" checked={docx} onChange={(e) => setDocx(e.target.checked)} />Word</label>
          <label style={S.row}><input type="checkbox" checked={md} onChange={(e) => setMd(e.target.checked)} />Markdown</label>
        </div>
        {docx ? (
          <label style={S.row}>Word 模板
            <select style={S.input} value={template} onChange={(e) => setTemplate(e.target.value as typeof template)}>
              <option value="文书">文书</option><option value="合同">合同</option><option value="">不用模板</option>
            </select>
          </label>
        ) : null}
        {!md && !docx ? <div style={{ color: C.err, fontSize: 12 }}>至少选一种格式</div> : null}
      </div>
    </Modal>
  )
}

/** 自检结果、没读全的材料：一行结论，有明细时可展开。 */
function CheckLine({ title, tone, summary, lines }: { title: string; tone: 'ok' | 'err' | 'faint'; summary: string; lines: string[] }) {
  const color = tone === 'ok' ? C.ok : tone === 'err' ? C.err : C.faint
  if (!lines.length) return <div style={{ ...S.sub, color }}>{title}：{summary}</div>
  return (
    <details>
      <summary style={{ ...S.sub, color, cursor: 'pointer' }}>{title}：{summary}</summary>
      <ul style={{ margin: '4px 0 0', paddingLeft: 18, fontSize: 12, color: C.sub }}>{lines.map((l, i) => <li key={i}>{l}</li>)}</ul>
    </details>
  )
}

/**
 * 成果页"在对话区查看"（T14 派修 2）：到达用量上限的任务，转到它所在的会话，在输入区上方显示提示和草稿（出处可点）。
 * 任务记下的会话读不到（旧任务、会话已删）就显示在当前会话。
 */
export async function openAnswer(caseRef: CaseRef, currentSession: string, taskId: string): Promise<void> {
  const r = await call<TaskAnswerView>('taskAnswer', { root: caseRef.root, task_id: taskId })
  if (!r.ok) { notice('没能打开这次运行的结果', errorText(r.error)); return }
  const target = r.value.session_id ?? currentSession
  showTaskAnswer(target, taskId)
  if (target !== currentSession) getNav().openSession(target)
}
