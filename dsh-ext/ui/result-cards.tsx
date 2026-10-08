// 聊天里交代成果（令 1321 C，第七版待办 13）：模型保存草稿（case_save_draft 成功）后，在那一轮答复下方插一张草稿卡片——
// 标题、版本、"确认保存…""选作下一步输入"（原右栏"成果"那张卡的功能原样搬来），自检结果、没读全/待识别明细在卡片里折叠；
// 律师确认保存生成 Word 后，同一位置变成成果卡片：文件名、"打开"（默认程序打开，限案件根内）、"打开所在文件夹"。
// 数据：哪一轮存了哪些草稿，按 DSH 的会话事件收（同 DSH 自己的 ui-deliverables：conversation.chat.turnTail + 每轮数据），
// 草稿属于哪个任务、确认了没有，走现有的 /api/tasks、/api/outputs（原右栏用的那套），按草稿路径对上。
// 关联不上的（历史任务）在案件概览卡"已确认的成果"里仍能看到（overview.tsx）。
import { useEffect, useState, useSyncExternalStore } from 'react'
import { Modal } from '@deepseek-ai/dsh-client-ui-primitives'
import { citationSummary, coverageLines, errorText, type CitationCheck, type Coverage } from './format.ts'
import { Badge, Button, C, S } from './kit.tsx'
import { app, call, notice, setIntent, type CaseRef } from './state.ts'
import { useStore } from './store.ts'
import { useSessionCase, type SessionProps } from './session-case.tsx'
import { openCaseFile, openCaseFolder } from './folder-actions.ts'
import { ARCHIVE_SKILL, ArchiveDialog } from './archive.tsx'

export const DRAFT_TOOL = 'case_save_draft'
export const TURN_DATA_KEY = 'lawbenchDrafts'

/** 一轮里存下的一份草稿（tool/result 的 seq、调用参数里的标题、返回里的路径、版本、自检、覆盖）。 */
export interface SavedDraft {
  readonly seq: number
  readonly title: string
  readonly path: string
  readonly version: number
  readonly coverage: Coverage | null
  readonly citation_check: CitationCheck | null
}

interface DraftsState { readonly turn: number; readonly calls: ReadonlyMap<string, string | null>; readonly drafts: readonly SavedDraft[] }

// DSH 会话事件里用到的几样（ui-conversation 的 ConversationNodeDefinition；这里只按形状取，不引 DSH 类型）
type Ev = { type: string; seq: number; surfaceOp?: string; data: Record<string, unknown> }
type Match = { event: Ev }
type Context = { state: DraftsState }

/** case_save_draft 调用参数里的标题；不是这个工具为 null。 */
export function draftTitle(name: unknown, argsRaw: unknown): string | null {
  if (name !== DRAFT_TOOL) return null
  try {
    const a = JSON.parse(String(argsRaw)) as { title?: unknown }
    return typeof a.title === 'string' && a.title.trim() ? a.title.trim() : ''
  } catch { return '' }
}

/** tool/result 的内容（文本块里的 JSON）→ 草稿；不是合规的草稿返回为 null。 */
export function parseDraftResult(content: unknown): Omit<SavedDraft, 'seq' | 'title'> | null {
  const text = Array.isArray(content)
    ? content.map((b) => (b && typeof b === 'object' && (b as { type?: unknown }).type === 'text' ? String((b as { text?: unknown }).text ?? '') : '')).join('')
    : typeof content === 'string' ? content : ''
  let v: unknown
  try { v = JSON.parse(text) } catch { return null }
  if (!v || typeof v !== 'object') return null
  const r = v as { path?: unknown; version?: unknown; coverage?: unknown; citation_check?: unknown }
  if (typeof r.path !== 'string' || !r.path || typeof r.version !== 'number') return null
  return {
    path: r.path, version: r.version,
    coverage: r.coverage && typeof r.coverage === 'object' ? r.coverage as Coverage : null,
    citation_check: r.citation_check && typeof r.citation_check === 'object' ? r.citation_check as CitationCheck : null,
  }
}

/**
 * 每轮的草稿（DSH ui-conversation 的会话事件定义，形状同 ui-deliverables 的 deliverablesDefinition）：
 * turn/start 开始；tool/call 记下 case_save_draft 的调用和标题；tool/result（追加、非出错）解析返回，记成一份草稿。
 */
export const draftsDefinition = {
  // DSH 要求每轮数据的 key 就是定义的 kind（不同就整条会话事件都不收，聊天区全空——真机核出来的）
  kind: TURN_DATA_KEY,
  match: (event: Ev) => {
    if (event.type === 'turn/start') return { id: String(event.data.turn), role: 'start' }
    if (event.type === 'tool/call') return { id: String(event.data.turn), role: 'update' }
    if (event.type === 'tool/result' && event.surfaceOp === 'append') return { id: String(event.data.turn), role: 'update' }
    return null
  },
  start: (_context: unknown, match: Match): DraftsState => {
    if (match.event.type !== 'turn/start') throw new Error('lawbenchDrafts start requires turn/start')
    return { turn: Number(match.event.data.turn), calls: new Map(), drafts: [] }
  },
  update: (context: Context, match: Match): DraftsState => {
    const e = match.event
    if (e.type === 'tool/call') {
      const title = draftTitle(e.data.name, e.data.arguments)
      if (title === null) return context.state
      const calls = new Map(context.state.calls)
      calls.set(String(e.data.callId), title)
      return { ...context.state, calls }
    }
    if (e.type !== 'tool/result') return context.state
    const message = e.data.message as { isError?: boolean; source?: { callId?: unknown }; content?: unknown } | undefined
    if (!message || message.isError === true) return context.state
    const title = context.state.calls.get(String(message.source?.callId))
    if (title === undefined || title === null) return context.state
    const d = parseDraftResult(message.content)
    if (!d) return context.state
    return { ...context.state, drafts: [...context.state.drafts, { seq: e.seq, title: title || d.path.split('/').pop()!.replace(/-v\d+\.md$/, ''), ...d }] }
  },
  buildLocationData: (context: { state?: DraftsState }, scope: string, previous?: { kind: string; turn?: number; key?: string; value?: { drafts?: unknown } }) => {
    if (scope !== 'turn' || context.state === undefined) return null
    if (previous?.kind === 'turn' && previous.turn === context.state.turn && previous.key === TURN_DATA_KEY && previous.value?.drafts === context.state.drafts) return previous
    return { kind: 'turn', turn: context.state.turn, key: TURN_DATA_KEY, value: { drafts: context.state.drafts } }
  },
}

/** 答复收尾时要显示的草稿：这一轮 seq 不晚于收尾消息的；同一路径只留一份；同名草稿只留最新一版。 */
export function draftsForClosing(drafts: readonly SavedDraft[] | undefined, seq = Number.POSITIVE_INFINITY): SavedDraft[] {
  const byTitle = new Map<string, SavedDraft>()
  for (const d of drafts ?? []) {
    if (d.seq > seq) continue
    const prev = byTitle.get(d.title)
    if (!prev || d.version >= prev.version) byTitle.set(d.title, d)
  }
  return [...byTitle.values()]
}

// —— 任务与成果（按案件缓存，几张卡片共用一次读取） ——

interface Task { task_id: string; skill: string | null; status: string; drafts: Array<{ title: string; path: string; version: number }> }
export interface Output { title: string; version: number; files: Array<{ format: string; path: string }>; task_id: string; confirmed_at: string }
interface CaseData { tasks: Task[] | null; outputs: Output[] | null; confirmed: ConfirmedRecord }
/** 确认保存时记下的"草稿路径 → 那次生成的成果文件"（复核 rv-A52 P1：成果版本按案件同标题最大 +1，与草稿版本对不上，只能靠这份记录）。 */
export type ConfirmedRecord = Readonly<Record<string, { version: number; files: Array<{ format: string; path: string }> }>>
const CONFIRMED_KEY = (caseId: string) => `lawbench.confirmed.${caseId}`
function loadConfirmed(caseId: string): ConfirmedRecord {
  try { const v = JSON.parse(localStorage.getItem(CONFIRMED_KEY(caseId)) ?? '{}') as unknown; return v && typeof v === 'object' ? v as ConfirmedRecord : {} } catch { return {} }
}

const cache = new Map<string, CaseData>()
const loading = new Set<string>()
const listeners = new Set<() => void>()
const emit = () => { for (const l of listeners) l() }

/** 重新读这个案件的任务和成果（确认保存后、一轮结束后）。 */
export async function refreshCaseResults(caseId: string): Promise<void> {
  if (loading.has(caseId)) return
  loading.add(caseId)
  try {
    const [t, o] = await Promise.all([call<{ tasks: Task[] }>('tasksList', { case_id: caseId }), call<{ outputs: Output[] }>('outputsList', { case_id: caseId })])
    const prev = cache.get(caseId)
    cache.set(caseId, { tasks: t.ok ? t.value.tasks : prev?.tasks ?? null, outputs: o.ok ? o.value.outputs : prev?.outputs ?? null, confirmed: prev?.confirmed ?? loadConfirmed(caseId) })
  } finally { loading.delete(caseId); emit() }
}

function useCaseResults(caseId: string | undefined): CaseData | undefined {
  const data = useSyncExternalStore((fn) => { listeners.add(fn); return () => listeners.delete(fn) }, () => (caseId ? cache.get(caseId) : undefined))
  useEffect(() => { if (caseId && !cache.has(caseId)) void refreshCaseResults(caseId) }, [caseId])
  return data
}

/** 确认保存成功：记下这份草稿生成了哪些成果文件（本机记住，重启后卡片仍是成果卡片）。 */
export function recordConfirmed(caseId: string, draftPath: string, outputs: ReadonlyArray<{ format: string; path: string; version: number }>): void {
  const prev = cache.get(caseId)
  const confirmed = { ...(prev?.confirmed ?? loadConfirmed(caseId)), [draftPath]: { version: outputs[0]?.version ?? 0, files: outputs.map(({ format, path }) => ({ format, path })) } }
  try { localStorage.setItem(CONFIRMED_KEY(caseId), JSON.stringify(confirmed)) } catch { /* 记不下：本次运行内仍对 */ }
  cache.set(caseId, { tasks: prev?.tasks ?? null, outputs: prev?.outputs ?? null, confirmed })
  emit()
}

/** 测试用：清空缓存。 */
export function resetCaseResults(): void { cache.clear(); loading.clear(); emit() }

/** 草稿所在的任务：按路径对上（服务记的草稿路径与工具返回的同一个）。 */
export function taskOfDraft(tasks: readonly Task[] | null | undefined, path: string): Task | undefined {
  return tasks?.find((t) => t.drafts.some((d) => d.path === path))
}

/**
 * 这份草稿确认保存后的成果（复核 rv-A52 P1）：
 * 1. 确认保存时记下的（ConfirmedRecord）为准；
 * 2. 没有记录（别的机器、清过本机记录的历史卡片）：只在能唯一对上时才算——这个任务里同标题的草稿只有这一份、
 *    成果里这个任务同标题的也只有一条。成果版本按案件同标题最大 +1，与草稿版本无关，不能按版本对。
 */
export function outputOfDraft(outputs: readonly Output[] | null | undefined, task: Task | undefined, d: Pick<SavedDraft, 'title' | 'version' | 'path'>, confirmed: ConfirmedRecord = {}): Output | undefined {
  const rec = confirmed[d.path]
  if (rec) return { title: d.title, version: rec.version, files: rec.files, task_id: task?.task_id ?? '', confirmed_at: '' }
  if (!task) return undefined
  if (task.drafts.filter((x) => x.title === d.title).length !== 1) return undefined
  const mine = outputs?.filter((o) => o.task_id === task.task_id && o.title === d.title) ?? []
  return mine.length === 1 ? mine[0] : undefined
}

// —— 卡片 ——

type TurnTailProps = SessionProps & { turn: { data: { get(key: string): unknown } }; seq: number }

/** 登记在 conversation.chat.turnTail：这一轮存过草稿才出现，一份草稿一张卡片。 */
export function TurnResultCards(props: TurnTailProps) {
  const data = props.turn.data.get(TURN_DATA_KEY) as { drafts?: readonly SavedDraft[] } | undefined
  const drafts = draftsForClosing(data?.drafts, props.seq)
  const { caseRef } = useSessionCase(props)
  if (!drafts.length || !caseRef) return null
  return (
    <div data-lawbench-result-cards="" style={{ display: 'flex', flexDirection: 'column', gap: 8, margin: '8px 0' }}>
      {drafts.map((d) => <ResultCard key={d.path} caseRef={caseRef} sessionId={props.sessionId} draft={d} />)}
    </div>
  )
}

const NO_INPUTS: string[] = []
/** 任务列表读到了、却没有这份草稿的任务（运行记录已不在）。 */
export const NO_TASK_TIP = '找不到这份草稿的运行记录，不能在这里确认保存'

export function ResultCard({ caseRef, sessionId, draft }: { caseRef: CaseRef; sessionId: string; draft: SavedDraft }) {
  const data = useCaseResults(caseRef.case_id)
  const task = taskOfDraft(data?.tasks, draft.path)
  const output = outputOfDraft(data?.outputs, task, draft, data?.confirmed)
  const inputs = useStore(app, (s) => s.intents[caseRef.case_id]?.inputs ?? s.selections[sessionId]?.inputs) ?? NO_INPUTS
  const [confirming, setConfirming] = useState(false)
  const [archiving, setArchiving] = useState(false)
  const card = { border: `1px solid ${C.border}`, borderRadius: C.rMd, padding: '10px 12px', display: 'flex', flexDirection: 'column' as const, gap: 6, fontSize: 14, maxWidth: 560 }

  if (output) {
    // 已确认保存：成果卡片
    return (
      <section aria-label="成果" data-result-state="output" style={card}>
        <div style={S.between}><span style={{ fontWeight: 600 }}>{output.title}</span><Badge tone="ok">已保存到成果</Badge></div>
        {output.files.map((f) => (
          <div key={f.path} style={{ ...S.row, flexWrap: 'wrap' }}>
            <span style={{ wordBreak: 'break-all' }}>{f.path}</span>
            <Button size="sm" variant="outline" onClick={() => void openCaseFile(caseRef, f.path)}>打开</Button>
          </div>
        ))}
        <div style={S.row}><Button size="sm" variant="ghost" onClick={() => void openCaseFolder(caseRef, 'outputs')}>打开所在文件夹</Button></div>
        <Checks draft={draft} />
      </section>
    )
  }
  const running = task?.status === 'running'
  const picked = inputs.includes(draft.path)
  const toggleInput = () => setIntent(caseRef.case_id, { inputs: picked ? inputs.filter((x) => x !== draft.path) : [...inputs, draft.path] })
  return (
    <section aria-label="草稿" data-result-state="draft" style={card}>
      <div style={S.between}><span style={{ fontWeight: 600 }}>{draft.title}</span><span style={S.sub}>草稿 · 第 {draft.version} 版</span></div>
      <div style={{ ...S.row, flexWrap: 'wrap' }}>
        <Button size="sm" variant="primary" disabled={!task || running} title={!task ? (data?.tasks ? NO_TASK_TIP : '正在读取任务……') : running ? '这一轮还在进行' : undefined} onClick={() => setConfirming(true)}>确认保存…</Button>
        <Button size="sm" variant={picked ? 'primary' : 'ghost'} aria-pressed={picked} onClick={toggleInput}>{picked ? '已选作下一步输入' : '选作下一步输入'}</Button>
        {task?.skill === ARCHIVE_SKILL ? <Button size="sm" variant="outline" disabled={running} onClick={() => setArchiving(true)}>核对归档方案并生成归档文件…</Button> : null}
      </div>
      <Checks draft={draft} />
      {confirming && task ? <ConfirmDialog caseRef={caseRef} taskId={task.task_id} draft={draft} onClose={() => setConfirming(false)} onDone={(outs) => { setConfirming(false); recordConfirmed(caseRef.case_id, draft.path, outs); void refreshCaseResults(caseRef.case_id) }} /> : null}
      {archiving && task ? <ArchiveDialog caseRef={caseRef} taskId={task.task_id} onClose={() => { setArchiving(false); void refreshCaseResults(caseRef.case_id) }} /> : null}
    </section>
  )
}

/** 自检结果、没读全/待识别：卡片里折叠。 */
function Checks({ draft }: { draft: SavedDraft }) {
  const cov = coverageLines(draft.coverage)
  return (
    <>
      <CheckLine title="自检结果" {...citationSummary(draft.citation_check)} />
      <CheckLine title="没读全的材料" tone={cov.ok ? 'ok' : cov.lines.length ? 'err' : 'faint'} summary={cov.summary} lines={cov.lines} />
    </>
  )
}

/** 一行结论，有明细时可展开。 */
export function CheckLine({ title, tone, summary, lines }: { title: string; tone: 'ok' | 'err' | 'faint'; summary: string; lines: string[] }) {
  const color = tone === 'ok' ? C.ok : tone === 'err' ? C.err : C.faint
  if (!lines.length) return <div style={{ ...S.sub, color }}>{title}：{summary}</div>
  return (
    <details>
      <summary style={{ ...S.sub, color, cursor: 'pointer' }}>{title}：{summary}</summary>
      <ul style={{ margin: '4px 0 0', paddingLeft: 18, fontSize: 12, color: C.sub }}>{lines.map((l, i) => <li key={i}>{l}</li>)}</ul>
    </details>
  )
}

/** 确认保存：草稿进成果目录并导出（/api/outputs/confirm）；选导出格式和 Word 模板。本机生成，不发服务器。 */
export function ConfirmDialog({ caseRef, taskId, draft, onClose, onDone }: { caseRef: CaseRef; taskId: string; draft: Pick<SavedDraft, 'title' | 'path' | 'version'>; onClose: () => void; onDone: (outputs: Array<{ format: string; path: string; version: number }>) => void }) {
  const [md, setMd] = useState(false)
  const [docx, setDocx] = useState(true)
  const [template, setTemplate] = useState<'文书' | '合同' | ''>('文书')
  const [busy, setBusy] = useState(false)
  const save = async () => {
    setBusy(true)
    const formats = [...(md ? ['md'] : []), ...(docx ? ['docx'] : [])]
    const r = await call<{ outputs: Array<{ format: string; path: string; version: number }> }>('outputsConfirm', {
      case_id: caseRef.case_id, task_id: taskId, draft: draft.path, formats, template: docx && template ? template : null,
    })
    setBusy(false)
    if (!r.ok) { notice('没有保存成功', errorText(r.error)); return }
    onDone(r.value.outputs)
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

/** 以前右栏的"成果"标签种类（令 1321 D.1 去掉；旧会话可能还开着它）。 */
export const OLD_RESULTS_TAB = 'lawbench-results'
export const OLD_RESULTS_TEXT = '成果已移到对话里每一轮答复下方的卡片，已确认的成果在空会话顶部的案件概览里。这个标签可以关掉。'

/** 旧会话里还开着的"成果"标签：一句话指路（复核 rv-A52 P3-4）。 */
export function OldResultsTab() {
  return <div style={{ ...S.pane }}><div style={S.sub}>{OLD_RESULTS_TEXT}</div></div>
}
