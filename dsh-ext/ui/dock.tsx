// 会话输入区上方（DSH 插槽 conversation.input.dock）：当前胶囊和 Skill 选择、必问问题、参数、选用的前序成果（PRD 7.9）。
// 选定后写任务单 /api/task（Spec 9.2：界面事先为该会话写待执行的任务单，Agent 插件在该会话下一次请求时使用）。
// entry 填胶囊 id（T13 执行令 Q5）。一张任务单管一条消息，写入与复位规则见 tasksheet.ts（返修 P2-1、P2-3，第二次返修 F1、F4）。
// 运行状态和停止沿用 DSH 对话区自带的。
import { useEffect, useMemo, useRef, useState } from 'react'
import { visible, type Capsules, type SkillCapsule } from './capsules.ts'
import { errorText } from './format.ts'
import { Badge, Button, C, S } from './kit.tsx'
import { app, call, lb, MODE_AGENT, setSelection, type CaseRef, type Params, type Selection, type SkillInfo } from './state.ts'
import { useStore } from './store.ts'
import { useSessionCase, type SessionProps } from './session-case.tsx'
import { afterConsumed, FREE_KEY, selectionKey, sheetFor, type Selection as TaskSelection, type SheetStatus } from './tasksheet.ts'

const THINKING: Params['thinking'][] = ['关闭', '低', '中', '高']
const WINDOWS: Params['window'][] = ['32K', '64K', '128K']
const WRITE_DELAY_MS = 500
const POLL_MS = 3000

let capsCache: Promise<Capsules | undefined> | undefined
let skillsCache: Promise<SkillInfo[]> | undefined
const loadCaps = () => (capsCache ??= call<Capsules>('getCapsules').then((r) => (r.ok ? r.value : undefined)))
const loadSkills = () => (skillsCache ??= lb().listSkills().then((r) => r.value.skills, () => []))
/** 胶囊改动后首页调用，让输入区重新读。 */
export const forgetDockCache = (): void => { capsCache = undefined }

export function ComposerDock(p: SessionProps) {
  const { caseRef } = useSessionCase(p)
  if (!caseRef) return null
  return <Dock caseRef={caseRef} sessionId={p.sessionId} />
}

function Dock({ caseRef, sessionId }: { caseRef: CaseRef; sessionId: string }) {
  const [caps, setCaps] = useState<Capsules | undefined>()
  const [skills, setSkills] = useState<SkillInfo[]>([])
  const [open, setOpen] = useState(false)
  const [status, setStatus] = useState<{ ok: boolean; text: string } | null>(null)
  useEffect(() => { void loadCaps().then(setCaps); void loadSkills().then(setSkills) }, [])
  const sel: Selection = useStore(app, (s) => s.selections[caseRef.case_id]) ?? { capsuleId: null, skill: null, params: null, inputs: [] }
  const defaults = useStore(app, (s) => s.defaults)
  const presets = useStore(app, (s) => s.presets)

  const capsules = useMemo(() => (caps ? visible(caps).flatMap((g) => g.items.filter((x): x is SkillCapsule => x.kind === 'skill').map((x) => ({ ...x, group: g.name }))) : []), [caps])
  const capsule = capsules.find((c) => c.id === sel.capsuleId)
  const agentSkills = skills.filter((s) => s.mode === MODE_AGENT)
  const choices = capsule ? [...new Set([...capsule.skills, ...(caps?.shared ?? [])])].filter((n) => agentSkills.some((s) => s.name === n)) : []
  const skill = agentSkills.find((s) => s.name === sel.skill)
  const params: Params = sel.params ?? (skill ? presets[skill.name] ?? skill.params : defaults) ?? { thinking: '中', window: '128K', max_tokens: 16384 }

  // 任务单：一张管一条消息（返修 P2-1、P2-3，见 tasksheet.ts）
  const sheet = useMemo(() => sheetFor(sessionId, {
    write: (req) => call<{ task_id: string }>('taskCreate', { case_id: caseRef.case_id, session_id: sessionId, ...req }),
    started: async () => {
      const r = await call<{ tasks: Array<{ task_id: string }> }>('tasksList', { case_id: caseRef.case_id })
      return r.ok ? r.value.tasks.map((t) => t.task_id) : undefined
    },
  }), [sessionId, caseRef.case_id])
  const label = capsule ? capsule.name : sel.inputs.length ? '自由对话（带选用的成果）' : '自由对话'
  const current: TaskSelection = { capsuleId: sel.capsuleId, skill: sel.skill, inputs: sel.inputs, params, label }
  const free = sel.capsuleId === null && sel.inputs.length === 0
  const key = free ? FREE_KEY : selectionKey(current)
  const latest = useRef({ current, key })
  latest.current = { current, key }

  const showApplied = (s: SheetStatus) => {
    if (s.kind === 'ready') setStatus({ ok: true, text: `已就绪：下一条消息按「${s.label}」运行（只管这一条）` })
    else if (s.kind === 'error') setStatus({ ok: false, text: errorText(s.error) })
    else setStatus((cur) => (cur?.ok && cur.text.startsWith('上一条已按') ? cur : null))
  }

  // 选择一变就按新选择写（防抖；同一选择不重复写）；刚挂上时也按当前选择走一遍（重启、重载后"不知道"时会写自由对话单）
  useEffect(() => {
    const t = setTimeout(() => { void sheet.apply(latest.current.current).then(showApplied) }, WRITE_DELAY_MS)
    return () => clearTimeout(t)
  }, [key, sheet]) // eslint-disable-line react-hooks/exhaustive-deps

  // 任务单被一条消息取走后（界面显示 = 下一条实际会用的）：
  // - 用掉的是最后写的那张、且律师还没改选：输入区回到"自由对话"，并写一张自由对话单压住服务那边可能残留的旧单；
  // - 律师已经改选了：保持新的选择（它会照常写）；
  // - 用掉的是更早的一张：最后写的那张仍是下一条要用的，显示不变，只说明上一条按什么跑的。
  useEffect(() => {
    const t = setInterval(() => {
      void sheet.poll().then((c) => {
        if (!c) return
        const d = afterConsumed(c, latest.current.key, latest.current.current.label)
        if (d.resetToFree) setSelection(caseRef.case_id, { capsuleId: null, skill: null, params: null, inputs: [] })
        if (d.writeFree) void sheet.apply({ capsuleId: null, skill: null, inputs: [], params: latest.current.current.params, label: '自由对话' })
        if (d.text) setStatus({ ok: true, text: d.text })
      })
    }, POLL_MS)
    return () => clearInterval(t)
  }, [sheet, caseRef.case_id])

  const pickCapsule = (id: string) => {
    const c = capsules.find((x) => x.id === id)
    setSelection(caseRef.case_id, { capsuleId: c?.id ?? null, skill: c?.skills[0] ?? null, params: null })
  }
  const setParam = <K extends keyof Params>(k: K, v: Params[K]) => setSelection(caseRef.case_id, { params: { ...params, [k]: v } })

  return (
    <div style={{ border: `1px solid ${C.border}`, borderRadius: C.rMd, padding: '6px 10px', margin: '0 0 6px', fontSize: 13, color: C.text, display: 'flex', flexDirection: 'column', gap: 6 }}>
      <div style={{ ...S.row, flexWrap: 'wrap' }}>
        <label style={S.row}>胶囊
          <select style={S.input} value={sel.capsuleId ?? ''} onChange={(e) => pickCapsule(e.target.value)} aria-label="胶囊">
            <option value="">自由对话</option>
            {capsules.map((c) => <option key={c.id} value={c.id}>{c.group} · {c.name}</option>)}
          </select>
        </label>
        {capsule ? (
          <label style={S.row}>Skill
            <select style={S.input} value={sel.skill ?? ''} onChange={(e) => setSelection(caseRef.case_id, { skill: e.target.value || null, params: null })} aria-label="Skill">
              {choices.map((n) => <option key={n} value={n}>{agentSkills.find((s) => s.name === n)?.title ?? n}</option>)}
            </select>
          </label>
        ) : null}
        <Button size="sm" variant="ghost" aria-expanded={open} onClick={() => setOpen(!open)}>{open ? '收起参数' : '参数'}</Button>
        {sel.inputs.map((path) => (
          <span key={path} style={{ ...S.row, gap: 4, border: `1px solid ${C.border}`, borderRadius: 999, padding: '0 6px', fontSize: 12 }}>
            选用：{path.split('/').pop()}
            <button type="button" aria-label="不再选用" onClick={() => setSelection(caseRef.case_id, { inputs: sel.inputs.filter((x) => x !== path) })}
              style={{ background: 'none', border: 'none', color: C.sub, cursor: 'pointer', padding: 0 }}>×</button>
          </span>
        ))}
        {status ? <span style={{ fontSize: 12, color: status.ok ? C.ok : C.err }}>{status.text}</span> : null}
      </div>
      {open ? (
        <div style={{ ...S.row, flexWrap: 'wrap' }}>
          <label style={S.row}>思考
            <select style={S.input} value={params.thinking} onChange={(e) => setParam('thinking', e.target.value as Params['thinking'])}>{THINKING.map((x) => <option key={x}>{x}</option>)}</select>
          </label>
          <label style={S.row}>窗口
            <select style={S.input} value={params.window} onChange={(e) => setParam('window', e.target.value as Params['window'])}>{WINDOWS.map((x) => <option key={x}>{x}</option>)}</select>
          </label>
          <label style={S.row}>最长输出
            <input type="number" min={256} max={262144} step={1024} style={{ ...S.input, width: 100 }} value={params.max_tokens}
              onChange={(e) => { const n = Number(e.target.value); if (n >= 256 && n <= 262144) setParam('max_tokens', n) }} />
          </label>
          <Button size="sm" variant="ghost" onClick={() => setSelection(caseRef.case_id, { params: null })}>恢复默认</Button>
        </div>
      ) : null}
      {skill && skill.questions.length ? (
        <details>
          <summary style={{ cursor: 'pointer', color: C.sub, fontSize: 12 }}>开始前会先问你 {skill.questions.length} 个问题（必问问题）</summary>
          <ul style={{ margin: '4px 0 0', paddingLeft: 18, fontSize: 12, color: C.sub }}>
            {skill.questions.map((q) => <li key={q.key}>{q.question}{q.fromMaterials ? <> <Badge tone="faint">能从材料里找的会先填好请你确认</Badge></> : null}</li>)}
          </ul>
        </details>
      ) : null}
    </div>
  )
}
