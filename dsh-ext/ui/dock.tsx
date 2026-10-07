// 会话输入区上方（DSH 插槽 conversation.input.dock）：当前胶囊和 Skill 选择、必问问题、参数、选用的前序成果（PRD 7.9）。
// 契约 1.2（N37）：服务管该会话"当前的选择"，管到律师改掉为止（执行时不消耗）。界面按会话存（与服务同口径），不另记：
// 挂上、切换会话、每轮结束之后从 GET /api/task/current 读，下拉框和状态行都设成服务返回的；律师改动时 POST /api/task，
// 写成功之前状态行显示"正在保存选择…"，写失败显示"任务单没有写成，请重试"并保留下拉框的值，此时发送被拦下（执行令 1751）。entry 填胶囊 id（T13 执行令 Q5）。
// 运行状态和停止沿用 DSH 对话区自带的。
// 用户 10-04 改版（执行令 1156 第 3 条）：两层胶囊放到输入框上方——空会话时从上到下是分流提示一行、第二层"<分类> · 选要做什么"、
// 第一层"能力入口"，选中的能力显示成输入框上方的小标签【证据整理】（× 取消）；会话里有内容后两层收起，点"选能力"再展开。
// 只此一套选择器（原先的胶囊下拉框并进来）；工具胶囊（发票、委托材料）点了仍打开 T26 的页面。
import { useEffect, useMemo, useRef, useState } from 'react'
import { TOOL_WORD, visible, type Capsule, type Capsules, type SkillCapsule } from './capsules.ts'
import { statusErrorText } from './format.ts'
import { Badge, Button, C, getNav, S } from './kit.tsx'
import { TaskAnswerSlot } from './answer.tsx'
import { app, applyServerSelection, call, clearInputChanged, clearStaleServer, isDaily, lb, markInputChanged, samePath, markSelectionSaved, MODE_AGENT, notice as showNotice, setSelection, showTaskAnswer, takeIntent, type CaseRef, type Params, type SkillInfo } from './state.ts'
import { useStore } from './store.ts'
import { useSessionCase, type SessionProps } from './session-case.tsx'
import { CaseOverview, type SessionBrief } from './overview.tsx'
import { homeView } from './invoice-logic.ts'
import { openRetainer } from './retainer.ts'
import { confirmScope } from './estimate.ts'
import { fromServer, SelectionSync, selectionKey, statusOf, statusText, type ApiError, type CurrentResult, type ServerSelection, type UiSelection, type WriteResult } from './tasksheet.ts'

const THINKING: Params['thinking'][] = ['关闭', '低', '中', '高']
const WINDOWS: Params['window'][] = ['32K', '64K', '128K']
const WRITE_DELAY_MS = 500
/** 上一轮因输入材料变化被拦下（/core/context 报 INPUT_CHANGED）时状态行的话（ORCH 注记 2026-09-30 13:18）。 */
export const INPUT_CHANGED_TEXT = '输入材料已变化，请重新选择'
/** 上一轮因会话所在的案件文件夹已不在原处被拒（N55 ②，Agent 插件记 CASE_MOVED）。 */
export const CASE_MOVED_TITLE = '这条消息没有发出'
export const CASE_MOVED_TEXT = '这个对话所在的案件文件夹已经不在原来的位置。刚才这句没有发出，重启软件后请在这个对话里重新发送这句话，或新开一个对话。'
/** 上一轮取任务时服务说这个对话不属于任何已打开的案件（/core/task/begin 报 CASE_NOT_FOUND，第六轮复核 A-P2-3 / B-F2）。 */
export const CASE_NOT_FOUND_TEXT = '没有找到这个对话所在的案件。请回到首页重新打开案件；如果案件文件夹刚挪过位置，请重启软件后在这个对话里继续，或新开一个对话。'
/** 写任务单（POST /api/task）明确失败时状态行的话（T14 第二次实跑派修 2，执行令 1751）；此时发送被 Agent 插件拦下。 */
export const SHEET_FAILED_TEXT = '任务单没有写成，请重试'
/** 任务单没写成时律师仍点了发送：这一轮被拒（Agent 插件记 TASK_SHEET_FAILED）。 */
export const SHEET_FAILED_SEND_TEXT = '输入区的任务单没有写成，刚才这句没有发出。请先点输入区的"重试"，写成之后再发送。'
export const TASK_SHEET_FAILED = 'TASK_SHEET_FAILED'
/** 一轮结束的事件名（index.tsx 按会话列表的 running 由真变假发出，detail 为会话 id）。 */
/** Agent 插件到达用量上限时记的提示码（agent/index.ts 的 BUDGET_STOPPED；界面不引 Agent 插件，照写一份）。 */
export const BUDGET_STOPPED = 'BUDGET_STOPPED'
export const TURN_ENDED = 'lawbench:turn-ended'

let capsCache: Promise<Capsules | undefined> | undefined
let skillsCache: Promise<SkillInfo[]> | undefined
// 读失败不缓存（令 1347 一并做 P3-4）：下次挂上输入区再读
const loadCaps = () => (capsCache ??= call<Capsules>('getCapsules').then((r) => {
  if (r.ok) return r.value
  capsCache = undefined
  return undefined
}))
const loadSkills = () => (skillsCache ??= lb().listSkills().then((r) => r.value.skills, () => { skillsCache = undefined; return [] }))
/** 胶囊改动后首页调用，让输入区重新读。 */
export const forgetDockCache = (): void => { capsCache = undefined }

const syncs = new Map<string, SelectionSync>()
/** 测试用：丢掉各会话的读写队列（上一个用例假时钟里没走完的请求不带到下一个）。 */
export const forgetDockSyncs = (): void => { syncs.clear() }
function syncFor(sessionId: string, caseId: string): SelectionSync {
  const k = JSON.stringify([sessionId, caseId])
  let s = syncs.get(k)
  if (!s) {
    s = new SelectionSync({
      write: (req) => call<{ task_id: string }>('taskCreate', { case_id: caseId, session_id: sessionId, ...req }) as Promise<WriteResult>,
      current: () => call<{ selection: ServerSelection | null }>('taskCurrent', { session_id: sessionId }) as Promise<CurrentResult>,
    })
    syncs.set(k, s)
  }
  return s
}

/** 会话不在已登记案件里时输入区上方的提示（N46 用户定 ②：没有打开案件就不能发消息；发了也会被会话存储拒绝）。 */
export const NO_CASE_TEXT = '先打开或新建一个案件，再在这里发消息。'

/**
 * 输入区上方各行共用的外框（令 1347 第 1 条"没有对齐，看着挺难受"）：与 DSH 的输入框同一左右边缘、同一宽度——
 * 输入框宽 = 容器宽减两侧留白（--dsh-composer-side-clearance），最多 --dsh-composer-card-max-width，居中。
 */
export const DOCK_BOX = {
  boxSizing: 'border-box' as const, width: 'calc(100% - 2 * var(--dsh-composer-side-clearance, 16px))', maxWidth: 'var(--dsh-composer-card-max-width, 952px)',
  margin: '0 auto 4px', display: 'flex', flexDirection: 'column' as const, gap: 10,
}

type SessionRow = { cwd?: string; blank?: boolean; parentId?: string; displayTitle?: string; title?: string; updatedAt?: number }

export function ComposerDock(p: SessionProps) {
  const { root, caseRef } = useSessionCase(p)
  // 空会话（DSH 的会话摘要 blank）显示概览卡和两层胶囊；有内容后收起
  const hero = p.useSessions?.((s) => (s.byId[p.sessionId] as SessionRow | undefined)?.blank === true) ?? false
  const daily = useStore(app, (s) => isDaily(s, caseRef))
  // 同一案件里别的、有内容的会话（概览卡"最近对话"）；选成字符串，免得每次都是新数组
  const briefsKey = p.useSessions?.((s) => JSON.stringify(Object.entries(s.byId)
    .filter(([id, x]) => id !== p.sessionId && x && !(x as SessionRow).blank && !(x as SessionRow).parentId && root && x.cwd && samePath(x.cwd, root))
    .map(([id, x]) => ({ id, title: (x as SessionRow).displayTitle ?? (x as SessionRow).title ?? '未命名对话', updatedAt: (x as SessionRow).updatedAt ?? 0 })))) ?? '[]'
  const briefs = useMemo(() => JSON.parse(briefsKey) as SessionBrief[], [briefsKey])
  if (!caseRef) {
    return (
      <div style={DOCK_BOX}>
        <div style={{ border: `1px solid ${C.border}`, borderRadius: C.rMd, padding: '6px 10px', fontSize: 14, color: C.err, display: 'flex', gap: 8, alignItems: 'center' }}>
          <span role="status">{NO_CASE_TEXT}</span>
          <Button size="sm" variant="ghost" onClick={() => getNav().goHome()}>选择案件</Button>
        </div>
      </div>
    )
  }
  return (
    <div style={DOCK_BOX}>
      {hero ? <CaseOverview caseRef={caseRef} daily={daily} sessions={briefs} /> : null}
      <TaskAnswerSlot caseRef={caseRef} sessionId={p.sessionId} />
      <Dock caseRef={caseRef} sessionId={p.sessionId} hero={hero} />
    </div>
  )
}

/** 胶囊按钮（两层共用的样子）。 */
const pill = (on: boolean, dashed: boolean) => ({
  font: 'inherit', fontSize: 13, padding: '3px 12px', borderRadius: 999, cursor: 'pointer', background: on ? 'rgba(47,107,255,0.08)' : 'transparent',
  border: `1px ${dashed && !on ? 'dashed' : 'solid'} ${on ? C.brand : C.border}`, color: on ? C.brand : C.text, fontWeight: on ? 600 : 400,
})

function Dock({ caseRef, sessionId, hero }: { caseRef: CaseRef; sessionId: string; hero: boolean }) {
  const [caps, setCaps] = useState<Capsules | undefined>()
  const [skills, setSkills] = useState<SkillInfo[]>([])
  const [open, setOpen] = useState(false)
  /** 第一层选中的分类（null：跟随当前能力所在的分类，没有就第一个）。 */
  const [groupId, setGroupId] = useState<string | null>(null)
  /** 会话里有内容后，两层胶囊默认收起，点"选能力"展开。 */
  const [rowsOpen, setRowsOpen] = useState(false)
  /** 最近一次读或写失败（sessionId：哪个会话的；key：写失败时写的那份选择）。 */
  const [error, setError] = useState<{ sessionId: string; key: string; op: 'read' | 'write'; error: ApiError } | null>(null)
  /** 已经读回过（成败都算）的会话：换会话后、读回之前状态行说"正在读取当前选择…"。 */
  const [loadedFor, setLoadedFor] = useState<string | null>(null)
  const [reload, setReload] = useState(0)
  /**
   * 服务那边此刻的选择（刚读回或刚写成功的）的键；律师选回同一份时不必再写。
   * null 表示不知道：还没读回、换了会话、写失败之后（超时或返回不合契约时服务可能已经建了单，T13 返修 P2-1）。
   */
  const serverKey = useRef<string | null>(null)
  // DSH 换会话时输入区不一定重挂（插槽可能只换属性）：按会话 id 重置"服务那边是什么"（T13 返修 P2-2）
  const shownSession = useRef(sessionId)
  if (shownSession.current !== sessionId) { shownSession.current = sessionId; serverKey.current = null }
  useEffect(() => { void loadCaps().then(setCaps); void loadSkills().then(setSkills) }, [])
  const stored = useStore(app, (s) => s.selections[sessionId])
  const intent = useStore(app, (s) => s.intents[caseRef.case_id])
  const inputChanged = useStore(app, (s) => s.inputChanged[sessionId] === true)
  const sel = stored ?? { capsuleId: null, skill: null, params: null, inputs: [], saved: false }
  const defaults = useStore(app, (s) => s.defaults)
  const presets = useStore(app, (s) => s.presets)

  const capsules = useMemo(() => (caps ? visible(caps).flatMap((g) => g.items.filter((x): x is SkillCapsule => x.kind === 'skill').map((x) => ({ ...x, group: g.name }))) : []), [caps])
  const capsule = capsules.find((c) => c.id === sel.capsuleId)
  const groups = useMemo(() => (caps ? visible(caps) : []), [caps])
  const group = groups.find((g) => g.id === groupId) ?? groups.find((g) => g.items.some((x) => x.id === sel.capsuleId)) ?? groups[0]
  const showRows = hero || rowsOpen
  const agentSkills = skills.filter((s) => s.mode === MODE_AGENT)
  const choices = capsule ? [...new Set([...capsule.skills, ...(caps?.shared ?? [])])].filter((n) => agentSkills.some((s) => s.name === n)) : []
  const skill = agentSkills.find((s) => s.name === sel.skill)
  const params: Params = sel.params ?? (skill ? presets[skill.name] ?? skill.params : defaults) ?? { thinking: '中', window: '128K', max_tokens: 16384 }

  // 同一会话的读、写排成一队（tasksheet.ts）；队列按会话留着，换走再换回时接着排
  const sync = useMemo(() => syncFor(sessionId, caseRef.case_id), [sessionId, caseRef.case_id])
  const label = capsule ? capsule.name : sel.inputs.length ? '自由对话（带选用的成果）' : '自由对话'
  const ui: UiSelection = { capsuleId: sel.capsuleId, skill: sel.skill, inputs: sel.inputs, params }
  const key = selectionKey(ui)

  // 读服务的当前选择：挂上、换会话、每轮结束之后。律师有还没写成功的改动时不覆盖（写完会再读到同样的值）
  useEffect(() => {
    let alive = true
    const sid = sessionId
    const load = () => {
      void sync.current().then((r) => {
        if (!alive) return
        setLoadedFor(sid)
        if (!r.ok) { setError({ sessionId: sid, key: '', op: 'read', error: { code: r.error.code, message: statusErrorText(r.error) } }); return }
        setError((e) => (e?.op === 'read' ? null : e))
        const cur = app.get().selections[sid]
        if (cur && !cur.saved) return
        const s = fromServer(r.value.selection)
        serverKey.current = selectionKey(s.params ? s : { ...s, params })
        applyServerSelection(sid, { capsuleId: s.capsuleId, skill: s.skill, inputs: s.inputs, params: (s.params as Params | null) ?? null })
        setError(null)
      })
    }
    // 问 Host 上一轮是否被拦下（取一次即删）；输入材料变了（INPUT_CHANGED）就记下提示，并退回"正在读取"
    // 提示按会话记进 store，取到了就记，不看 alive：Host 那边取一次即删，途中切走也不能丢（第三轮复核 P3-3）
    // 取提示出错（Host 方法抛错、返回不合形状）不挡读取：两处调用都是取完再读（第四轮复核 N1、N2）
    const notice = async (): Promise<void> => {
      try {
        const r = await call<{ code: string | null; task_id?: string | null }>('turnNotice', { session_id: sid })
        if (r.ok && r.value?.code === 'INPUT_CHANGED') { markInputChanged(sid); if (alive) setLoadedFor(null) }
        if (r.ok && r.value?.code === 'CASE_MOVED') showNotice(CASE_MOVED_TITLE, CASE_MOVED_TEXT)
        if (r.ok && r.value?.code === 'CASE_NOT_FOUND') showNotice(CASE_MOVED_TITLE, CASE_NOT_FOUND_TEXT)
        if (r.ok && r.value?.code === TASK_SHEET_FAILED) showNotice(CASE_MOVED_TITLE, SHEET_FAILED_SEND_TEXT)
        // 到达用量上限：对话区（输入区上方）显示提示和刚存的草稿（T14 派修 2）
        if (r.ok && r.value?.code === BUDGET_STOPPED && typeof r.value.task_id === 'string') showTaskAnswer(sid, r.value.task_id)
      } catch { /* 当没有提示 */ }
    }
    setError(null)
    // 挂上、换会话时也取一次：被拦下的那一轮结束时律师可能正看着别的会话（返修 P3-C ②）。
    // 与一轮结束时一样先取提示再读：并行时提示晚到会把已读完的 loadedFor 清掉，状态行卡在"正在读取"（第三轮复核 P3-1）
    void notice().then(() => { if (alive) load() })
    // 一轮结束：先取提示再重读
    const onTurn = (e: Event) => { if ((e as CustomEvent<string>).detail === sid) void notice().then(() => { if (alive) load() }) }
    window.addEventListener(TURN_ENDED, onTurn)
    return () => { alive = false; window.removeEventListener(TURN_ENDED, onTurn) }
  }, [sync, sessionId, reload]) // eslint-disable-line react-hooks/exhaustive-deps

  // 首页、成果区留给本案件的待带入意向：本会话读回之后取走一次，当作律师在这里改的
  useEffect(() => {
    if (loadedFor !== sessionId || !intent) return
    const patch = takeIntent(caseRef.case_id)
    if (patch) setSelection(sessionId, patch)
  }, [loadedFor, sessionId, intent, caseRef.case_id])

  // 律师改动了（saved 为 false）：防抖后写给服务；写成功且途中没再改才记为已保存；写失败显示错误、保留下拉框的值。
  // 依赖整份 stored：律师再选一次、或点"重试"（setSelection 生成新的一份）都会重新写；依赖 key 见下。
  // 写哪个会话在发起时定下：写完时已换到别的会话的，结果只记到原会话，不动此刻显示的（T13 返修 P2-2）
  // 已保存、但此刻显示的不是服务那份（Skill 列表比写成还晚回来，参数框改显示 Skill 预设）也要重写（第三轮复核 P2-1）；
  // serverKey 为 null（刚换会话还没读到、或写失败）时不据此重写
  useEffect(() => {
    if (!stored || (stored.saved && (serverKey.current === null || key === serverKey.current))) return
    const sid = sessionId
    clearInputChanged(sid)
    // 服务那份的输入快照过期了（INPUT_CHANGED 之后）：选回同一份也要真写，服务才会重算快照（返修 P3-B）
    if (key === serverKey.current && !app.get().staleServer[sid]) { markSelectionSaved(sid, () => true); setError(null); void call('sheetHold', { session_id: sid, hold: false }); return }
    const t = setTimeout(() => {
      const writing = ui
      const writingKey = key
      void sync.save(writing).then((r) => {
        const here = shownSession.current === sid
        // 明确失败就请 Host 记上：律师此时发送，Agent 插件整轮拒绝，不拿服务上一张任务单发；写成了去掉（执行令 1751 必修 2）
        void call('sheetHold', { session_id: sid, hold: !r.ok })
        if (r.ok) {
          // 写成了，服务那份的输入快照已是新的：提示一并清（被拦那一轮前后刚改过选择时，否则红字误报到下次改动，第三轮复核 P3-2）
          clearStaleServer(sid)
          clearInputChanged(sid)
          if (here) serverKey.current = writingKey
          markSelectionSaved(sid, (cur) => selectionKey({ capsuleId: cur.capsuleId, skill: cur.skill, inputs: cur.inputs, params: cur.params ?? writing.params }) === writingKey)
          if (here) setError((e) => (e?.sessionId === sid && e.key === writingKey ? null : e))
        } else if (here) {
          serverKey.current = null
          setError({ sessionId: sid, key: writingKey, op: 'write', error: { code: r.error.code, message: SHEET_FAILED_TEXT } })
        }
      })
    }, WRITE_DELAY_MS)
    return () => clearTimeout(t)
    // 依赖带上 key（N48，复核 P2-A）：刚挂上时 Skill 列表还没回来，参数取的是全局默认；列表回来后参数框改显示 Skill 预设，
    // 这里要重新计时，写出去的才是此刻显示的那份（写失败时错误也按这份记，状态行才有"重试"）
  }, [stored, sync, key]) // eslint-disable-line react-hooks/exhaustive-deps

  // 读错误总显示（T13 返修 P3-1）；写错误只在失败的就是此刻显示的这份时显示
  const shownError = error && error.sessionId === sessionId && (error.op === 'read' || error.key === key) ? error.error : null
  const reading = loadedFor !== sessionId && (!stored || stored.saved)
  const status = inputChanged && !shownError && (!stored || stored.saved)
    ? { kind: 'notice' as const, text: INPUT_CHANGED_TEXT }
    : statusOf(stored && !reading ? ui : undefined, sel.saved, shownError, label)
  const statusColor = status.kind === 'error' || status.kind === 'notice' ? C.err : status.kind === 'ready' ? C.ok : C.sub

  const pickCapsule = (id: string) => {
    const c = capsules.find((x) => x.id === id)
    setSelection(sessionId, { capsuleId: c?.id ?? null, skill: c?.skills[0] ?? null, params: null })
  }
  const setParam = <K extends keyof Params>(k: K, v: Params[K]) => setSelection(sessionId, { params: { ...params, [k]: v } })
  /** 点第二层：Skill 胶囊写进任务单（同下拉框时的写法）；工具胶囊打开 T26 的页面。 */
  const openItem = async (item: Capsule) => {
    if (item.kind === 'tool') {
      if (item.tool === 'invoice') { homeView.set('invoice'); getNav().goHome() } else void openRetainer(caseRef)
      return
    }
    // 令 2043 第 4 条：写任务单之前按材料篇幅估一次，读不全先问（可"仍然开始"）
    if (item.id !== sel.capsuleId && !await confirmScope(caseRef)) return
    pickCapsule(item.id)
    setRowsOpen(false)
  }

  return (
    <div data-lawbench-dock="" data-capsule={sel.capsuleId ?? ''} style={{ fontSize: 14, color: C.text, display: 'flex', flexDirection: 'column', gap: 10 }}>
      {hero && caps?.hint ? <div style={{ fontSize: 13, color: C.faint, lineHeight: 1.6 }}>{caps.hint}</div> : null}
      {showRows && group ? (
        <div role="toolbar" aria-label="选要做什么" style={{ ...S.row, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 13, color: C.sub, minWidth: 76 }}>{group.name} · 选要做什么</span>
          {group.items.map((item) => (
            <button key={item.id} type="button" data-capsule-id={item.id} aria-pressed={item.id === sel.capsuleId} title={item.kind === 'tool' ? `内置工具：${TOOL_WORD[item.tool]}` : undefined}
              onClick={() => void openItem(item)} style={pill(item.id === sel.capsuleId, true)}>{item.name}</button>
          ))}
          {group.items.length === 0 ? <span style={{ fontSize: 12, color: C.faint }}>这一类的胶囊都隐藏了，可在设置里"管理胶囊"显示。</span> : null}
        </div>
      ) : null}
      {showRows && groups.length ? (
        <div role="tablist" aria-label="能力入口" style={{ ...S.row, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 13, color: C.sub, minWidth: 76 }}>能力入口</span>
          {groups.map((g) => (
            <button key={g.id} type="button" role="tab" aria-selected={g.id === group?.id} onClick={() => setGroupId(g.id)} style={pill(g.id === group?.id, false)}>{g.name} ▾</button>
          ))}
        </div>
      ) : null}
      <div style={{ ...S.row, flexWrap: 'wrap', border: `1px solid ${C.border}`, borderRadius: C.rMd, padding: '4px 10px' }}>
        {capsule ? (
          <span data-capsule-tag="" style={{ ...S.row, gap: 4, border: `1px solid ${C.brand}`, color: C.brand, borderRadius: C.rMd, padding: '0 6px' }}>
            【{capsule.name}】
            <button type="button" aria-label="取消这项能力" onClick={() => pickCapsule('')} style={{ background: 'none', border: 'none', color: C.brand, cursor: 'pointer', padding: 0 }}>×</button>
          </span>
        ) : null}
        {capsule ? (
          <label style={S.row}>Skill
            <select style={S.input} value={sel.skill ?? ''} onChange={(e) => setSelection(sessionId, { skill: e.target.value || null, params: null })} aria-label="Skill">
              {choices.map((n) => <option key={n} value={n}>{agentSkills.find((s) => s.name === n)?.title ?? n}</option>)}
            </select>
          </label>
        ) : null}
        {!hero ? <Button size="sm" variant="ghost" aria-expanded={rowsOpen} onClick={() => setRowsOpen(!rowsOpen)}>{rowsOpen ? '收起能力' : '选能力'}</Button> : null}
        <Button size="sm" variant="ghost" aria-expanded={open} onClick={() => setOpen(!open)}>{open ? '收起参数' : '参数'}</Button>
        {sel.inputs.map((path) => (
          <span key={path} style={{ ...S.row, gap: 4, border: `1px solid ${C.border}`, borderRadius: 999, padding: '0 6px', fontSize: 12 }}>
            选用：{path.split('/').pop()}
            <button type="button" aria-label="不再选用" onClick={() => setSelection(sessionId, { inputs: sel.inputs.filter((x) => x !== path) })}
              style={{ background: 'none', border: 'none', color: C.sub, cursor: 'pointer', padding: 0 }}>×</button>
          </span>
        ))}
        <span role="status" style={{ fontSize: 13, color: statusColor }}>{statusText(status)}</span>
        {status.kind === 'error' ? <Button size="sm" variant="ghost" onClick={() => (error?.op === 'write' ? setSelection(sessionId, {}) : setReload((n) => n + 1))}>重试</Button> : null}
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
          <Button size="sm" variant="ghost" onClick={() => setSelection(sessionId, { params: null })}>恢复默认</Button>
        </div>
      ) : null}
      {skill && skill.questions.length ? (
        <details>
          <summary style={{ cursor: 'pointer', color: C.sub, fontSize: 13 }}>开始前会先问你 {skill.questions.length} 个问题（必问问题）</summary>
          <ul style={{ margin: '4px 0 0', paddingLeft: 18, fontSize: 12, color: C.sub }}>
            {skill.questions.map((q) => <li key={q.key}>{q.question}{q.fromMaterials ? <> <Badge tone="faint">能从材料里找的会先填好请你确认</Badge></> : null}</li>)}
          </ul>
        </details>
      ) : null}
    </div>
  )
}
