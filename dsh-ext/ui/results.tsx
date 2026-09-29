// 右侧栏"成果"标签（PRD 7.9）：任务和草稿、自检结果、确认保存、导出格式、选作下一步输入。
// T13 执行令 Q8：只显示 tasks_list 现有内容；"自检结果""没读全的材料"放占位"暂未提供"；
// T10 接入之前不显示"出处核对通过"——citation_passed 一律不显示。
import { useEffect, useState } from 'react'
import { Modal } from '@deepseek-ai/dsh-client-ui-primitives'
import { errorText } from './format.ts'
import { Badge, Button, C, Empty, Loading, S, useLoad } from './kit.tsx'
import { app, call, lb, notice, setSelection, type CaseRef } from './state.ts'
import { useStore } from './store.ts'
import { WithCase, type SessionProps } from './session-case.tsx'

interface Draft { title: string; path: string; version: number }
interface Task { task_id: string; skill: string | null; status: string; drafts: Draft[]; finished_at: string | null }

const TASK_WORD: Record<string, [string, 'ok' | 'warn' | 'err' | 'info' | 'faint']> = {
  running: ['进行中', 'info'], completed: ['已完成', 'ok'], cancelled: ['已停止', 'faint'], interrupted: ['中断', 'warn'],
  failed: ['失败', 'err'], budget_stopped: ['到达用量上限', 'warn'], output_limit: ['输出过长被截断', 'warn'],
}

export function ResultsTab(p: SessionProps) {
  return <WithCase p={p}>{(c) => <Results caseRef={c} />}</WithCase>
}

function Results({ caseRef }: { caseRef: CaseRef }) {
  const id = caseRef.case_id
  const [tasks, reload] = useLoad(() => call<{ tasks: Task[] }>('tasksList', { case_id: id }), [id], 5000)
  const [titles, setTitles] = useState<Record<string, string>>({})
  const inputs = useStore(app, (s) => s.selections[id]?.inputs ?? [])
  const [confirming, setConfirming] = useState<{ task: Task; draft: Draft } | null>(null)
  useEffect(() => { void lb().listSkills().then((r) => setTitles(Object.fromEntries(r.value.skills.map((s) => [s.name, s.title])))).catch(() => undefined) }, [])
  const skillName = (t: Task) => t.task_id.startsWith('P-') ? '案件 wiki 整理' : t.skill ? titles[t.skill] ?? t.skill : '自由对话'
  const toggleInput = (path: string) => setSelection(id, { inputs: inputs.includes(path) ? inputs.filter((x) => x !== path) : [...inputs, path] })

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
              <div style={{ ...S.sub, color: C.faint }}>自检结果：暂未提供</div>
              <div style={{ ...S.sub, color: C.faint }}>没读全的材料：暂未提供</div>
            </li>
          )
        })}</ul>
      )}</Loading>
      {confirming ? <ConfirmDialog caseRef={caseRef} task={confirming.task} draft={confirming.draft} onClose={() => setConfirming(null)} onDone={() => { setConfirming(null); void reload() }} /> : null}
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
