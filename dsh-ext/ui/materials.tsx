// 右侧栏"材料"标签（PRD 7.9；Spec U-12、F-MAT-*）：材料列表与状态、导入和拖入、提交识别、识别进度、生成 / 更新 wiki、wiki 建议确认。
// 发往服务器的操作（提交识别、生成 wiki、勾选 395 抽取）都先弹确认框（工单第 3 步、Q10）。不显示"去水印"（第 5a 步）。
import { useEffect, useRef, useState, type DragEvent } from 'react'
import { Modal } from '@deepseek-ai/dsh-client-ui-primitives'
import { DEFAULT_TARGET, startImport, TABS } from './cases.ts'
import { citationTargets, errorText, ocrConfirmText, pageRanges, parsePageRanges, STATUS_WORD, TYPE_WORD, UNIT_WORD, wikiConfirmText, type Material } from './format.ts'
import { Badge, Button, C, Empty, ErrorLine, getNav, Loading, S, Section, useLoad } from './kit.tsx'
import { app, call, confirm, notice, type CaseRef, type Params } from './state.ts'
import { WithCase, type SessionProps } from './session-case.tsx'

const POLL_MS = 3000
const FALLBACK_PARAMS: Params = { thinking: '中', window: '128K', max_tokens: 16384 }

/** 系统通知（U-7）：只写"识别任务已完成 / 整理任务已完成"，不带材料名、案件名。 */
export function osNotify(text: '识别任务已完成' | '整理任务已完成'): void {
  try {
    if (typeof Notification === 'undefined') return
    if (Notification.permission === 'granted') new Notification(text)
    else if (Notification.permission !== 'denied') void Notification.requestPermission().then((p) => { if (p === 'granted') new Notification(text) })
  } catch { /* 系统不支持通知时不提示 */ }
}

export function MaterialsTab(p: SessionProps) {
  return <WithCase p={p}>{(c) => <Materials caseRef={c} />}</WithCase>
}

interface OcrJob { job_id: string; material_id: string; name: string; status: 'queued' | 'running' | 'paused' | 'done' | 'cancelled' | 'partial_failed'; pause_reason: string | null; total: number; done: number; failed: number }
interface Task { task_id: string; skill: string | null; status: string }
interface Suggestion { id: string; field: string; value: string; source: string; reason: string | null; status: string }

const JOB_WORD: Record<OcrJob['status'], string> = { queued: '排队中', running: '识别中', paused: '已暂停', done: '已完成', cancelled: '已取消', partial_failed: '部分页失败' }
const PAUSE_WORD: Record<string, string> = { offline: '网络断开', prep_down: '识别服务器不可用', key_invalid: 'Key 无效', app_exit: '软件关闭' }

function Materials({ caseRef }: { caseRef: CaseRef }) {
  const id = caseRef.case_id
  const [mats, reloadMats] = useLoad(() => call<{ materials: Material[] }>('materialsList', { case_id: id }), [id])
  const [jobs, reloadJobs] = useLoad(() => call<{ jobs: OcrJob[] }>('ocrList', { case_id: id }), [id], POLL_MS)
  const [over, setOver] = useState(false)
  const [ocrFor, setOcrFor] = useState<Material[] | null>(null)
  const [wikiOpen, setWikiOpen] = useState(false)
  const fileInput = useRef<HTMLInputElement>(null)

  // 导入完成后刷新；识别任务从进行中变成完成时刷新材料并发系统通知
  useEffect(() => {
    const on = (e: Event) => { if ((e as CustomEvent).detail === id) { void reloadMats(); void reloadJobs() } }
    window.addEventListener('lawbench:materials-changed', on)
    return () => window.removeEventListener('lawbench:materials-changed', on)
  }, [id, reloadMats, reloadJobs])
  const prevJobs = useRef<Map<string, string>>(new Map())
  useEffect(() => {
    if (jobs.state !== 'ok') return
    const before = prevJobs.current
    let finished = false
    for (const j of jobs.value.jobs) {
      const was = before.get(j.job_id)
      if ((was === 'running' || was === 'queued') && (j.status === 'done' || j.status === 'partial_failed')) finished = true
    }
    prevJobs.current = new Map(jobs.value.jobs.map((j) => [j.job_id, j.status]))
    if (finished) { osNotify('识别任务已完成'); void reloadMats() }
  }, [jobs, reloadMats])

  const importPaths = (paths: string[]) => startImport(caseRef, paths, '材料面板')
  // 拦在这里、不再冒泡：DSH 在 document 上监听拖入，放过去会被当成聊天附件收下（D13 不允许）
  const onDrop = (e: DragEvent) => { e.preventDefault(); e.stopPropagation(); setOver(false); importPaths([...e.dataTransfer.files].map((f) => getNav().pathFor(f))) }
  const pickFolder = async () => { const d = await getNav().pickDirectory(); if (d) importPaths([d]) }
  const rescan = async () => {
    const r = await call<{ added: number; changed: number; removed: number; failed: number; review_needed: boolean }>('materialsScan', { case_id: id })
    if (!r.ok) { notice('扫描没有完成', errorText(r.error)); return }
    notice('扫描完成', `新增 ${r.value.added}、变化 ${r.value.changed}、移除 ${r.value.removed}、失败 ${r.value.failed}。${r.value.review_needed ? '材料有变化，案件 wiki 和已有成果需要复核。' : ''}`)
    void reloadMats()
  }

  return (
    <div style={{ ...S.pane, outline: over ? `2px dashed ${C.brand}` : 'none', outlineOffset: -4 }}
      onDragEnter={(e) => e.stopPropagation()} onDragOver={(e) => { e.preventDefault(); e.stopPropagation(); setOver(true) }} onDragLeave={(e) => { e.stopPropagation(); setOver(false) }} onDrop={onDrop}>
      <div style={S.between}>
        <div style={{ minWidth: 0 }}><div style={{ fontWeight: 600 }}>{caseRef.name}</div><div style={S.sub}>拖入文件或文件夹即导入到"{DEFAULT_TARGET}"（可在确认框里改）</div></div>
      </div>
      <div style={{ ...S.row, flexWrap: 'wrap' }}>
        <Button size="sm" variant="primary" onClick={() => fileInput.current?.click()}>导入文件…</Button>
        <Button size="sm" variant="outline" onClick={() => void pickFolder()}>导入文件夹…</Button>
        <Button size="sm" variant="ghost" onClick={() => void rescan()}>重新扫描</Button>
        <input ref={fileInput} type="file" multiple hidden onChange={(e) => { importPaths([...(e.target.files ?? [])].map((f) => getNav().pathFor(f))); e.target.value = '' }} />
      </div>

      <Section title="材料" extra={mats.state === 'ok' && mats.value.materials.some((m) => m.pages_need_ocr.length) ? (
        <Button size="sm" variant="outline" onClick={() => mats.state === 'ok' && setOcrFor(mats.value.materials.filter((m) => m.pages_need_ocr.length))}>待识别页全部提交…</Button>
      ) : null}>
        <Loading data={mats}>{(v) => v.materials.length === 0 ? <Empty>还没有材料。点"导入文件"或把文件拖进来。</Empty> : (
          <ul style={S.list}>{v.materials.map((m) => <MaterialRow key={m.material_id} m={m} onOcr={() => setOcrFor([m])} />)}</ul>
        )}</Loading>
      </Section>

      <Section title="识别进度">
        <Loading data={jobs}>{(v) => v.jobs.length === 0 ? <Empty>没有识别任务</Empty> : (
          <ul style={S.list}>{v.jobs.map((j) => <JobRow key={j.job_id} j={j} onChanged={() => void reloadJobs()} />)}</ul>
        )}</Loading>
      </Section>

      <WikiSection caseRef={caseRef} materials={mats.state === 'ok' ? mats.value.materials : []} onOpen={() => setWikiOpen(true)} />

      {ocrFor ? <OcrDialog caseRef={caseRef} materials={ocrFor} onClose={() => setOcrFor(null)} onDone={() => { setOcrFor(null); void reloadJobs(); void reloadMats() }} /> : null}
      {wikiOpen && mats.state === 'ok' ? <WikiDialog caseRef={caseRef} materials={mats.value.materials} onClose={() => setWikiOpen(false)} /> : null}
    </div>
  )
}

function MaterialRow({ m, onOcr }: { m: Material; onOcr: () => void }) {
  const tone = m.status === 'parsed' ? 'ok' : m.status === 'failed' || m.status === 'source_deleted' ? 'err' : m.status === 'ocr_running' ? 'info' : 'warn'
  return (
    <li style={{ ...S.card, padding: 8, display: 'flex', flexDirection: 'column', gap: 4 }}>
      <div style={S.between}>
        <span style={{ fontWeight: 500, wordBreak: 'break-all' }}>{m.name}</span>
        <Badge tone={tone}>{STATUS_WORD[m.status]}</Badge>
      </div>
      <div style={S.sub}>{TYPE_WORD[m.type] ?? m.type} · {m.unit_count} {UNIT_WORD[m.unit]} · {m.rel_path}</div>
      {m.error ? <div style={{ color: C.err, fontSize: 12 }}>原因：{m.error}</div> : null}
      {m.stale_ocr ? <div style={{ color: C.warn, fontSize: 12 }}>原件变了，识别结果需要重新识别</div> : null}
      {m.pages_mixed.length ? <div style={S.sub}>图文混排页：第 {pageRanges(m.pages_mixed)} 页</div> : null}
      {m.pages_need_ocr.length ? (
        <div style={S.between}>
          <span style={{ color: C.warn, fontSize: 12 }}>第 {pageRanges(m.pages_need_ocr)} 页待识别</span>
          <Button size="sm" variant="outline" disabled={m.status === 'ocr_running'} onClick={onOcr}>提交识别…</Button>
        </div>
      ) : null}
    </li>
  )
}

function JobRow({ j, onChanged }: { j: OcrJob; onChanged: () => void }) {
  const [err, setErr] = useState<{ code: string; message: string } | null>(null)
  const cancellable = j.status === 'queued' || j.status === 'running' || j.status === 'paused'
  const cancel = async () => {
    if (!await confirm('取消识别', `取消"${j.name}"还没识别的页？已识别的页保留。`, '取消识别')) return
    const r = await call('ocrCancel', { job_id: j.job_id })
    if (!r.ok) setErr(r.error); else onChanged()
  }
  const pct = j.total ? Math.round((j.done / j.total) * 100) : 0
  return (
    <li style={{ ...S.card, padding: 8, display: 'flex', flexDirection: 'column', gap: 4 }}>
      <div style={S.between}><span style={{ wordBreak: 'break-all' }}>{j.name}</span><Badge tone={j.status === 'done' ? 'ok' : j.status === 'partial_failed' ? 'err' : j.status === 'paused' ? 'warn' : 'info'}>{JOB_WORD[j.status]}</Badge></div>
      <div role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} style={{ height: 4, background: C.border, borderRadius: 2 }}>
        <div style={{ width: `${pct}%`, height: '100%', background: C.brand, borderRadius: 2 }} />
      </div>
      <div style={S.between}>
        <span style={S.sub}>{j.done} / {j.total} 页{j.failed ? `，失败 ${j.failed} 页` : ''}{j.pause_reason ? `（${PAUSE_WORD[j.pause_reason] ?? '暂停'}，恢复后继续）` : ''}</span>
        {cancellable ? <Button size="sm" variant="ghost" onClick={() => void cancel()}>取消</Button> : null}
      </div>
      <ErrorLine error={err} />
    </li>
  )
}

/** 提交识别：律师选定页码范围后确认（F-MAT-03）；dewatermark 固定为 false，界面不出现（第 5a 步）。 */
function OcrDialog({ caseRef, materials, onClose, onDone }: { caseRef: CaseRef; materials: Material[]; onClose: () => void; onDone: () => void }) {
  const [ranges, setRanges] = useState<Record<string, string>>(() => Object.fromEntries(materials.map((m) => [m.material_id, pageRanges(m.pages_need_ocr).replace(/、/g, ', ')])))
  const [err, setErr] = useState<string | null>(null)
  const picks = materials.map((m) => ({ m, pages: parsePageRanges(ranges[m.material_id] ?? '', Math.max(m.unit_count, ...m.pages_need_ocr)) }))
  const bad = picks.filter((x) => !x.pages)
  const submit = async () => {
    if (bad.length) return
    const ready = picks as Array<{ m: Material; pages: number[] }>
    if (!await confirm('发往识别服务器', ocrConfirmText(ready.map((x) => ({ name: x.m.name, pages: x.pages }))), '提交识别')) return
    const failed: string[] = []
    for (const x of ready) {
      const r = await call('ocrSubmit', { case_id: caseRef.case_id, material_id: x.m.material_id, pages: x.pages, dewatermark: false })
      if (!r.ok) failed.push(`${x.m.name}：${errorText(r.error)}`)
    }
    if (failed.length) setErr(failed.join('；')); else onDone()
  }
  return (
    <Modal open onClose={onClose} title="提交识别" closeLabel="关闭"
      footer={<><Button variant="outline" onClick={onClose}>取消</Button><Button variant="primary" disabled={bad.length > 0} onClick={() => void submit()}>下一步</Button></>}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        <div style={S.sub}>选定要识别的页（如 3-6, 9）。识别结果按页合并回文本，标注"识别所得"。</div>
        {picks.map(({ m, pages }) => (
          <label key={m.material_id} style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <span>{m.name}（共 {m.unit_count} 页）</span>
            <input style={S.input} value={ranges[m.material_id] ?? ''} onChange={(e) => setRanges({ ...ranges, [m.material_id]: e.target.value })} aria-invalid={!pages} />
            {!pages ? <span style={{ color: C.err, fontSize: 12 }}>页码写法不对或超出范围</span> : <span style={S.sub}>{pages.length} 页</span>}
          </label>
        ))}
        {err ? <div role="alert" style={{ color: C.err, fontSize: 12 }}>{err}</div> : null}
      </div>
    </Modal>
  )
}

/** 生成 / 更新案件 wiki（流水线 case-wiki-build，Spec 10.3 第 977 行）：选模式、是否用 395 抽取，确认后 /api/pipeline/run。 */
function WikiDialog({ caseRef, materials, onClose }: { caseRef: CaseRef; materials: Material[]; onClose: () => void }) {
  const [update, setUpdate] = useState(false)
  const [usePrep, setUsePrep] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const run = async () => {
    if (!await confirm('发往律所服务器', wikiConfirmText(materials, usePrep, update), update ? '更新 wiki' : '生成 wiki')) return
    const s = app.get()
    const params = s.presets['case-wiki-build'] ?? s.defaults ?? FALLBACK_PARAMS
    const r = await call<{ task_id: string }>('pipelineRun', { case_id: caseRef.case_id, step: update ? 'wiki_update' : 'wiki_build', use_prep: usePrep, params })
    if (!r.ok) { setErr(errorText(r.error)); return }
    window.dispatchEvent(new CustomEvent('lawbench:tasks-changed', { detail: caseRef.case_id }))
    onClose()
  }
  return (
    <Modal open onClose={onClose} title="案件 wiki" closeLabel="关闭"
      footer={<><Button variant="outline" onClick={onClose}>取消</Button><Button variant="primary" onClick={() => void run()}>下一步</Button></>}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        <label style={S.row}><input type="radio" checked={!update} onChange={() => setUpdate(false)} />生成（按全部材料重新整理）</label>
        <label style={S.row}><input type="radio" checked={update} onChange={() => setUpdate(true)} />更新（只重新整理有变化的材料，保留你改过的内容）</label>
        <label style={S.row}><input type="checkbox" checked={usePrep} onChange={(e) => setUsePrep(e.target.checked)} />字段抽取和材料分类使用 395 小模型</label>
        <div style={S.sub}>不勾选时全部由律所模型服务器完成。</div>
        {err ? <div role="alert" style={{ color: C.err, fontSize: 12 }}>{err}</div> : null}
      </div>
    </Modal>
  )
}

interface PipelineStatus { status: string; step_index: number; step_total: number; current: string | null; queue_wait_ms: number | null }

function WikiSection({ caseRef, materials, onOpen }: { caseRef: CaseRef; materials: Material[]; onOpen: () => void }) {
  const id = caseRef.case_id
  const [tasks, reloadTasks] = useLoad(() => call<{ tasks: Task[] }>('tasksList', { case_id: id }), [id], POLL_MS)
  const running = tasks.state === 'ok' ? tasks.value.tasks.find((t) => t.task_id.startsWith('P-') && t.status === 'running') : undefined
  const [status, setStatus] = useState<PipelineStatus | null>(null)
  const [sugs, reloadSugs] = useLoad(() => call<{ suggestions: Suggestion[] }>('getWikiSuggestions', { case_id: id }), [id])
  const watched = useRef<string | null>(null)

  useEffect(() => {
    const on = (e: Event) => { if ((e as CustomEvent).detail === id) void reloadTasks() }
    window.addEventListener('lawbench:tasks-changed', on)
    return () => window.removeEventListener('lawbench:tasks-changed', on)
  }, [id, reloadTasks])
  useEffect(() => {
    if (!running) {
      // 只在成功完成时通知；被停止、失败的不发"已完成"（返修一并做）
      if (watched.current) {
        const done = tasks.state === 'ok' ? tasks.value.tasks.find((t) => t.task_id === watched.current) : undefined
        if (done?.status === 'completed') osNotify('整理任务已完成')
        watched.current = null
        void reloadSugs()
      }
      setStatus(null)
      return
    }
    watched.current = running.task_id
    let stop = false
    const tick = async () => {
      const r = await call<PipelineStatus>('pipelineStatus', { task_id: running.task_id })
      if (!stop && r.ok) setStatus(r.value)
    }
    void tick()
    const t = setInterval(() => { void tick() }, POLL_MS)
    return () => { stop = true; clearInterval(t) }
  }, [running?.task_id]) // eslint-disable-line react-hooks/exhaustive-deps

  const cancel = async () => {
    if (!running || !await confirm('停止整理', '停止正在进行的案件 wiki 整理？已完成的步骤保留。', '停止')) return
    await call('pipelineCancel', { task_id: running.task_id })
    void reloadTasks()
  }
  const decide = async (s: Suggestion, accept: boolean) => {
    const r = await call('postWikiSuggestions', { case_id: id, id: s.id, accept })
    if (!r.ok) notice('没有处理成功', errorText(r.error))
    void reloadSugs()
  }
  return (
    <Section title="案件 wiki" extra={<Button size="sm" variant="outline" disabled={!!running} onClick={onOpen}>生成 / 更新 wiki…</Button>}>
      {running ? (
        <div style={{ ...S.card, padding: 8, display: 'flex', flexDirection: 'column', gap: 4 }}>
          <div style={S.between}><span>正在整理</span><Button size="sm" variant="ghost" onClick={() => void cancel()}>停止</Button></div>
          <div style={S.sub}>{status ? `第 ${status.step_index} / ${status.step_total} 步${status.current ? `：${status.current}` : ''}${status.queue_wait_ms ? `（服务器排队约 ${Math.ceil(status.queue_wait_ms / 1000)} 秒）` : ''}` : '读取进度中…'}</div>
        </div>
      ) : null}
      <Loading data={sugs}>{(v) => {
        const pending = v.suggestions.filter((s) => s.status === 'pending')
        return pending.length === 0 ? <Empty>没有待确认的 wiki 修改建议</Empty> : (
          <ul style={S.list}>{pending.map((s) => (
            <li key={s.id} style={{ ...S.card, padding: 8, display: 'flex', flexDirection: 'column', gap: 4 }}>
              <div><b>{s.field}</b>：{s.value}</div>
              <div style={S.sub}>出处：{citationTargets(s.source, materials).map((t, i) => t.material_id
                ? <button key={i} type="button" onClick={() => getNav().openTab(TABS.source, { material_id: t.material_id!, citation: t.citation })}
                    style={{ font: 'inherit', color: C.brand, background: 'none', border: 'none', padding: '0 4px 0 0', cursor: 'pointer', textDecoration: 'underline' }}>{t.text}</button>
                : <span key={i}>{t.text} </span>)}</div>
              {s.reason ? <div style={S.sub}>理由：{s.reason}</div> : null}
              <div style={S.row}><Button size="sm" variant="primary" onClick={() => void decide(s, true)}>采纳</Button><Button size="sm" variant="ghost" onClick={() => void decide(s, false)}>不采纳</Button></div>
            </li>
          ))}</ul>
        )
      }}</Loading>
    </Section>
  )
}
