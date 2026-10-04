// 侧栏"案件"一块点开的页面（原首页，PRD 6.3、7.9；Spec U-11、U-12）：最近案件、新建 / 打开 / 切换案件；"发票整理"在这里换成发票页（U-13）。
// 用户 10-04 改版（执行令 1156 第 3 条）：两层胶囊和分流提示挪到输入框上方（dock.tsx），胶囊管理挪到设置页（CapsuleSettings）。
import { useEffect, useMemo, useState, type DragEvent } from 'react'
import { Modal } from '@deepseek-ai/dsh-client-ui-primitives'
import { addCapsule, checkBeforeSave, moveCapsule, moveGroup, newCapsules, rename, toggleHidden, TOOL_WORD, type Capsules } from './capsules.ts'
import { loadRecent, openCase, startImport } from './cases.ts'
import { Badge, Button, C, CONNECTING_TEXT, Empty, getNav, ErrorLine, Loading, S, useLoad, useRetryLoad } from './kit.tsx'
import { app, call, confirm, lb, MODE_AGENT, notice, type CaseRef, type SkillInfo } from './state.ts'
import { useStore } from './store.ts'
import { errorText, lawyerMessage } from './format.ts'
import { forgetDockCache } from './dock.tsx'
import { homeView } from './invoice-logic.ts'
import { InvoicePage } from './invoice.tsx'

export function HomePage() {
  const view = useStore(homeView, (v) => v)
  return view === 'invoice' ? <InvoicePage /> : <CasesPage />
}

/**
 * 侧栏"案件"一块点开的页面（执行令 1156 第 3 条：取消单独首页，胶囊放到输入框上方、胶囊管理放到设置页）：
 * 启动检查提示、最近案件、新建 / 打开 / 切换案件。服务还没就绪时每 2 秒自动重读、最多 30 秒，之后给"重试"（T14 第二次实跑派修 1）。
 */
function CasesPage() {
  const [recent, reload] = useRetryLoad(async () => {
    const r = await loadRecent()
    return Array.isArray(r) ? { ok: true as const, value: r } : { ok: false as const, error: r }
  }, [])
  return (
    <div style={S.page}>
      <div style={{ maxWidth: 980, margin: '0 auto', padding: '28px 24px', display: 'flex', flexDirection: 'column', gap: 22 }}>
        <SelfCheckBanner />
        {recent.state === 'loading' ? <Empty>读取中…</Empty> : null}
        {recent.state === 'connecting' ? <Empty>{CONNECTING_TEXT}</Empty> : null}
        {recent.state === 'fail' ? (
          <div style={S.row}><ErrorLine error={recent.error} /><Button size="sm" variant="outline" onClick={() => void reload()}>重试</Button></div>
        ) : null}
        {recent.state === 'ok' ? <RecentCases /> : null}
      </div>
    </div>
  )
}

/** 设置页"胶囊"一节（U-11 保留在设置页）：点"管理胶囊"进入排序、改名、隐藏、新增；保存后输入区重读。 */
export function CapsuleSettings() {
  const [caps, reload] = useLoad(() => call<Capsules>('getCapsules'), [])
  const [skills] = useLoad(async () => { try { return await lb().listSkills() } catch (e) { return { ok: false as const, error: { code: 'SERVICE_UNAVAILABLE', message: lawyerMessage((e as Error).message) } } } }, [])
  const [managing, setManaging] = useState(false)
  const skillList = skills.state === 'ok' ? skills.value.skills : []
  if (!managing) {
    const fresh = caps.state === 'ok' ? newCapsules(caps.value) : []
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {fresh.length ? <div role="note" style={{ color: C.text }}>有新功能，可在管理胶囊中显示：{fresh.map((x) => x.name).join('、')}</div> : null}
        <div><Button size="sm" variant="outline" disabled={caps.state !== 'ok'} onClick={() => setManaging(true)}>管理胶囊</Button></div>
        {caps.state === 'fail' ? <ErrorLine error={caps.error} /> : null}
      </div>
    )
  }
  return (
    <Loading data={caps}>{(c) => <CapsuleManager initial={c} skills={skillList} onDone={() => { setManaging(false); forgetDockCache(); void reload() }} />}</Loading>
  )
}

/** 最近案件（首页读成功之后才显示）；案件卡片接受拖入文件和文件夹（U-12）。 */
function RecentCases() {
  const cases = useStore(app, (s) => s.cases) // 首页读成功时 loadRecent 已写进界面状态
  const [over, setOver] = useState<string | null>(null)
  const drop = (c: CaseRef) => (e: DragEvent) => {
    e.preventDefault(); e.stopPropagation(); setOver(null) // 不冒泡到 DSH 的 document 拖入监听（否则会被当成聊天附件）
    // 文件夹不在原处的卡片：拦下默认行为（Electron 里可能跳到 file://），不导入
    if (c.exists === false) return
    const paths = [...e.dataTransfer.files].map((f) => getNav().pathFor(f))
    startImport(c, paths, '案件卡片')
  }
  return (
    <section style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div style={S.between}>
        <h3 style={S.h3}>最近案件</h3>
        <div style={S.row}>
          <Button variant="outline" size="sm" onClick={() => void openCase(null, null)}>打开案件…</Button>
          <Button variant="outline" size="sm" onClick={() => void openCase(null, 'civil')}>新建案件（民商事目录）…</Button>
          <Button variant="outline" size="sm" onClick={() => void openCase(null, 'criminal')}>新建案件（刑事目录）…</Button>
        </div>
      </div>
      {cases.length === 0 ? <Empty>还没有案件。打开或新建一个案件文件夹开始。</Empty> : null}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 10 }}>
        {cases.map((c) => (
          <div key={c.case_id} data-lawbench-drop='' onDragEnter={(e) => e.stopPropagation()} onDragOver={(e) => { e.stopPropagation(); e.preventDefault(); if (c.exists === false) e.dataTransfer.dropEffect = 'none'; else setOver(c.case_id) }} onDragLeave={(e) => { e.stopPropagation(); setOver(null) }} onDrop={drop(c)}
            style={{ ...S.card, borderColor: over === c.case_id ? C.brand : C.border, display: 'flex', flexDirection: 'column', gap: 6 }}>
            <div style={S.between}>
              <span style={{ fontWeight: 600 }}>{c.name}</span>
              {c.exists === false ? <Badge tone="warn">文件夹不在原处</Badge> : null}
            </div>
            <div style={{ ...S.sub, wordBreak: 'break-all' }}>{c.root}</div>
            <div style={S.between}>
              <span style={{ ...S.sub, color: C.faint }}>{over === c.case_id ? '松开即导入到这个案件' : '可把文件拖到这里导入'}</span>
              <Button size="sm" variant="ghost" disabled={c.exists === false} onClick={() => void openCase(c.root, null)}>进入</Button>
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}

/** 胶囊管理（U-11、F-CAP-02）：拖动排序（同组、跨组）、点名字改名、眼睛图标隐藏 / 显示、新增、恢复默认。没有删除。 */
function CapsuleManager({ initial, skills, onDone }: { initial: Capsules; skills: SkillInfo[]; onDone: () => void }) {
  const [c, setC] = useState(initial)
  const [editing, setEditing] = useState<string | null>(null)
  const [dragging, setDragging] = useState<{ kind: 'item' | 'group'; id: string } | null>(null)
  const [adding, setAdding] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const installed = useMemo(() => new Set(skills.map((s) => s.name)), [skills])
  const title = (name: string) => skills.find((s) => s.name === name)?.title ?? name
  const dirty = JSON.stringify(c) !== JSON.stringify(initial)

  const doRename = (id: string, name: string) => {
    const r = rename(c, id, name)
    if (typeof r === 'string') { setErr(r); return }
    setErr(null); setC(r); setEditing(null)
  }
  const dropOn = (groupId: string, index: number) => (e: DragEvent) => {
    e.preventDefault(); e.stopPropagation()
    if (!dragging) return
    if (dragging.kind === 'item') setC(moveCapsule(c, dragging.id, groupId, index))
    else setC(moveGroup(c, dragging.id, c.groups.findIndex((g) => g.id === groupId)))
    setDragging(null)
  }
  const save = async () => {
    const problems = checkBeforeSave(c, initial)
    if (problems.length) { setErr(problems.join('；')); return }
    const r = await call<Capsules>('putCapsules', c)
    if (!r.ok) { setErr(errorText(r.error)); return }
    onDone()
  }
  const reset = async () => {
    if (!await confirm('恢复默认胶囊', '用默认配置覆盖你对胶囊做的排序、改名、隐藏和新增。恢复后不能撤销。', '恢复默认')) return
    const r = await call<Capsules>('capsulesReset', {})
    if (!r.ok) { setErr(errorText(r.error)); return }
    onDone()
  }
  const cancel = async () => { if (!dirty || await confirm('放弃修改', '刚才对胶囊做的修改还没保存，要放弃吗？', '放弃')) onDone() }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <div style={S.between}>
        <div>
          <h2 style={S.h2}>管理胶囊</h2>
          <div style={S.sub}>拖动胶囊或分组调整顺序；点名字改名；点"隐藏 / 显示"切换首页是否显示。只影响这台电脑。</div>
        </div>
        <div style={S.row}>
          <Button variant="outline" size="sm" onClick={() => setAdding(true)}>新增胶囊</Button>
          <Button variant="outline" size="sm" onClick={() => void reset()}>恢复默认</Button>
          <Button variant="outline" size="sm" onClick={() => void cancel()}>取消</Button>
          <Button variant="primary" size="sm" disabled={!dirty} onClick={() => void save()}>保存</Button>
        </div>
      </div>
      {err ? <div role="alert" style={{ color: C.err, fontSize: 12 }}>{err}</div> : null}
      <div style={{ ...S.card, color: C.faint, fontSize: 12 }}>分流提示（不能修改）：{c.hint}</div>
      {c.groups.map((g) => (
        <div key={g.id} draggable onDragStart={(e) => { e.stopPropagation(); setDragging({ kind: 'group', id: g.id }) }}
          onDragOver={(e) => e.preventDefault()} onDrop={dropOn(g.id, g.items.length)}
          style={{ ...S.card, opacity: g.hidden ? 0.55 : 1, display: 'flex', flexDirection: 'column', gap: 8 }}>
          <div style={S.between}>
            <NameEdit id={g.id} name={g.name} editing={editing === g.id} onEdit={setEditing} onSave={doRename} strong />
            <HideToggle hidden={g.hidden} onClick={() => setC(toggleHidden(c, g.id))} />
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {g.items.map((item, i) => (
              <div key={item.id} draggable onDragStart={(e) => { e.stopPropagation(); setDragging({ kind: 'item', id: item.id }) }}
                onDragOver={(e) => e.preventDefault()} onDrop={dropOn(g.id, i)}
                title="拖动调整顺序"
                style={{ border: `1px dashed ${C.border}`, borderRadius: C.rMd, padding: '6px 10px', minWidth: 170, cursor: 'grab', opacity: item.hidden ? 0.55 : 1, display: 'flex', flexDirection: 'column', gap: 4 }}>
                <div style={S.between}>
                  <span style={S.row}>
                    <NameEdit id={item.id} name={item.name} editing={editing === item.id} onEdit={setEditing} onSave={doRename} />
                    {item.new ? <Badge tone="info">新</Badge> : null}
                  </span>
                  <HideToggle hidden={item.hidden} onClick={() => setC(toggleHidden(c, item.id))} />
                </div>
                <span style={S.sub}>{item.kind === 'skill' ? item.skills.map(title).join(' → ') : `内置工具：${TOOL_WORD[item.tool]}`}{item.custom ? '（自己新增的）' : ''}</span>
              </div>
            ))}
          </div>
        </div>
      ))}
      {adding ? <AddCapsule c={c} skills={skills} installed={installed} onClose={() => setAdding(false)} onAdd={(next) => { setC(next); setAdding(false) }} /> : null}
    </div>
  )
}

function NameEdit({ id, name, editing, onEdit, onSave, strong }: { id: string; name: string; editing: boolean; onEdit: (id: string | null) => void; onSave: (id: string, name: string) => void; strong?: boolean }) {
  const [v, setV] = useState(name)
  useEffect(() => setV(name), [name, editing])
  if (!editing) {
    return <button type="button" title="点击改名" onClick={() => onEdit(id)} style={{ font: 'inherit', fontWeight: strong ? 600 : 500, color: C.text, background: 'none', border: 'none', padding: 0, cursor: 'text' }}>{name}</button>
  }
  return (
    <input autoFocus aria-label="新名称" style={{ ...S.input, width: 140 }} value={v} onChange={(e) => setV(e.target.value)}
      onKeyDown={(e) => { if (e.key === 'Enter') onSave(id, v); if (e.key === 'Escape') onEdit(null) }} onBlur={() => onSave(id, v)} />
  )
}

function HideToggle({ hidden, onClick }: { hidden: boolean; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} aria-pressed={hidden} title={hidden ? '现在隐藏，点击显示' : '现在显示，点击隐藏'}
      style={{ font: 'inherit', fontSize: 12, color: hidden ? C.faint : C.sub, background: 'none', border: `1px solid ${C.border}`, borderRadius: 999, padding: '0 8px', cursor: 'pointer' }}>
      {hidden ? '◌ 已隐藏' : '◉ 显示中'}
    </button>
  )
}

/** 新增胶囊：选一组 Skill（按顺序）或一个内置工具，并起名（F-CAP-02）。 */
function AddCapsule({ c, skills, installed, onClose, onAdd }: { c: Capsules; skills: SkillInfo[]; installed: ReadonlySet<string>; onClose: () => void; onAdd: (c: Capsules) => void }) {
  const [name, setName] = useState('')
  const [groupId, setGroupId] = useState(c.groups[0]?.id ?? '')
  const [kind, setKind] = useState<'skill' | 'tool'>('skill')
  const [picked, setPicked] = useState<string[]>([])
  const [tool, setTool] = useState<'invoice' | 'retainer'>('invoice')
  const [err, setErr] = useState<string | null>(null)
  const toggle = (n: string) => setPicked((p) => p.includes(n) ? p.filter((x) => x !== n) : [...p, n])
  const add = () => {
    const r = addCapsule(c, groupId, name, kind === 'skill' ? { kind, skills: picked } : { kind, tool }, installed)
    if (typeof r === 'string') setErr(r); else onAdd(r)
  }
  return (
    <Modal open onClose={onClose} title="新增胶囊" closeLabel="关闭"
      footer={<><Button variant="outline" onClick={onClose}>取消</Button><Button variant="primary" onClick={add}>加入</Button></>}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        <label style={S.row}>名称<input style={{ ...S.input, flex: 1 }} maxLength={12} value={name} onChange={(e) => setName(e.target.value)} placeholder="最多 12 个字" /></label>
        <label style={S.row}>放在
          <select style={S.input} value={groupId} onChange={(e) => setGroupId(e.target.value)}>
            {c.groups.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
          </select>
        </label>
        <div style={S.row}>
          <label style={S.row}><input type="radio" checked={kind === 'skill'} onChange={() => setKind('skill')} />一组 Skill</label>
          <label style={S.row}><input type="radio" checked={kind === 'tool'} onChange={() => setKind('tool')} />内置工具</label>
        </div>
        {kind === 'skill' ? (
          <div style={{ maxHeight: 240, overflow: 'auto', display: 'flex', flexDirection: 'column', gap: 4 }}>
            <div style={S.sub}>按勾选顺序排列，第一个是点胶囊后默认选中的。</div>
            {skills.filter((s) => s.mode === MODE_AGENT).map((s) => (
              <label key={s.name} style={S.row}>
                <input type="checkbox" checked={picked.includes(s.name)} onChange={() => toggle(s.name)} />
                {s.title}{picked.includes(s.name) ? <Badge tone="info">第 {picked.indexOf(s.name) + 1}</Badge> : null}
              </label>
            ))}
            {skills.length === 0 ? <Empty>没有读到已安装的 Skill</Empty> : null}
          </div>
        ) : (
          <div style={S.row}>
            {(['invoice', 'retainer'] as const).map((t) => (
              <label key={t} style={S.row}><input type="radio" checked={tool === t} onChange={() => setTool(t)} />{TOOL_WORD[t]}</label>
            ))}
          </div>
        )}
        {err ? <div role="alert" style={{ color: C.err, fontSize: 12 }}>{err}</div> : null}
      </div>
    </Modal>
  )
}

export { notice }

type CheckItem = { id: string; level: 'ok' | 'warn' | 'error'; message: string }
/** 律师点过"知道了"就不再显示（本次运行内）。 */
let selfCheckDismissed = false

/** 启动自检（T20 准备）：内置 Python、分词文件、LibreOffice、pandoc、管理员 Skill 目录、缓存路径有问题时在首页提示，不拦使用。 */
export function SelfCheckBanner() {
  const [items, setItems] = useState<CheckItem[]>([])
  const [hidden, setHidden] = useState(selfCheckDismissed)
  useEffect(() => { void call<{ items: CheckItem[] }>('selfCheck').then((r) => { if (r.ok) setItems(r.value.items) }) }, [])
  if (hidden || items.length === 0) return null
  return (
    <div role="alert" style={{ ...S.card, borderColor: items.some((i) => i.level === 'error') ? C.err : C.warn, display: 'flex', flexDirection: 'column', gap: 6 }}>
      <div style={S.between}>
        <span style={{ fontWeight: 600 }}>启动检查发现 {items.length} 个问题</span>
        <Button size="sm" variant="outline" onClick={() => { selfCheckDismissed = true; setHidden(true) }}>知道了</Button>
      </div>
      <ul style={{ ...S.list, fontSize: 12 }}>
        {items.map((i) => <li key={i.id} style={{ color: i.level === 'error' ? C.err : C.text }}>{i.message}</li>)}
      </ul>
    </div>
  )
}
