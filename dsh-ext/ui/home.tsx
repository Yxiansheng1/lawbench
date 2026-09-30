// 首页（PRD 6.3、7.9；Spec U-11、U-12）：分流提示、两级胶囊、右上角"管理胶囊"、最近案件、新建 / 打开案件。
import { useEffect, useMemo, useState, type DragEvent } from 'react'
import { Modal } from '@deepseek-ai/dsh-client-ui-primitives'
import { addCapsule, checkBeforeSave, moveCapsule, moveGroup, rename, toggleHidden, TOOL_WORD, visible, type Capsule, type Capsules } from './capsules.ts'
import { loadRecent, openCase, startImport, withCase } from './cases.ts'
import { Badge, Button, C, Empty, ErrorLine, getNav, Loading, S, useLoad } from './kit.tsx'
import { app, call, confirm, currentCase, lb, MODE_AGENT, notice, pushDialog, setSelection, type CaseRef, type SkillInfo } from './state.ts'
import { useStore } from './store.ts'
import { errorText, lawyerMessage } from './format.ts'

export function HomePage() {
  const [caps, reload] = useLoad(() => call<Capsules>('getCapsules'), [])
  const [skills] = useLoad(async () => { try { return await lb().listSkills() } catch (e) { return { ok: false as const, error: { code: 'SERVICE_UNAVAILABLE', message: lawyerMessage((e as Error).message) } } } }, [])
  const [managing, setManaging] = useState(false)
  const skillList = skills.state === 'ok' ? skills.value.skills : []
  return (
    <div style={S.page}>
      <div style={{ maxWidth: 980, margin: '0 auto', padding: '28px 24px', display: 'flex', flexDirection: 'column', gap: 22 }}>
        <Loading data={caps}>{(c) => managing
          ? <CapsuleManager initial={c} skills={skillList} onDone={() => { setManaging(false); void reload() }} />
          : <CapsuleHome caps={c} skills={skillList} onManage={() => setManaging(true)} />}
        </Loading>
        {!managing ? <RecentCases /> : null}
      </div>
    </div>
  )
}

function CapsuleHome({ caps, skills, onManage }: { caps: Capsules; skills: SkillInfo[]; onManage: () => void }) {
  const groups = visible(caps)
  const [groupId, setGroupId] = useState(groups[0]?.id)
  const group = groups.find((g) => g.id === groupId) ?? groups[0]
  const current = useStore(app, currentCase)
  const title = (name: string) => skills.find((s) => s.name === name)?.title ?? name
  const open = (item: Capsule) => {
    if (item.kind === 'tool') {
      pushDialog({ kind: 'placeholder', title: item.name, text: `${TOOL_WORD[item.tool]}的页面在后续版本提供（工单 T26），本版先占位。` })
      return
    }
    withCase(current, (c) => {
      setSelection(c.case_id, { capsuleId: item.id, skill: item.skills[0] ?? null, params: null, inputs: [] })
      if (current && c.case_id === current.case_id) void getNav().openCaseWorkspace(c.root)
    })
  }
  return (
    <>
      <div style={{ ...S.card, color: C.sub, lineHeight: 1.7 }}>{caps.hint}</div>
      <div style={S.between}>
        <div role="tablist" aria-label="业务分组" style={{ ...S.row, flexWrap: 'wrap' }}>
          {groups.map((g) => (
            <button key={g.id} role="tab" aria-selected={g.id === group?.id} type="button" onClick={() => setGroupId(g.id)}
              style={{ font: 'inherit', fontSize: 15, padding: '8px 18px', borderRadius: 999, cursor: 'pointer',
                border: `1px solid ${g.id === group?.id ? C.brand : C.border}`, color: g.id === group?.id ? C.brand : C.text, background: 'transparent' }}>
              {g.name}
            </button>
          ))}
        </div>
        <Button variant="outline" size="sm" onClick={onManage}>管理胶囊</Button>
      </div>
      {group ? (
        <div role="tabpanel" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 12 }}>
          {group.items.map((item) => (
            <button key={item.id} type="button" onClick={() => open(item)}
              style={{ ...S.card, textAlign: 'left', cursor: 'pointer', color: C.text, font: 'inherit', display: 'flex', flexDirection: 'column', gap: 6, minHeight: 84 }}>
              <span style={{ fontSize: 15, fontWeight: 600 }}>{item.name}</span>
              <span style={S.sub}>{item.kind === 'skill' ? item.skills.map(title).join(' → ') : `内置工具：${TOOL_WORD[item.tool]}`}</span>
              {item.kind === 'skill' && item.outputs.length ? <span style={{ ...S.sub, color: C.faint }}>产出：{item.outputs.join('、')}</span> : null}
            </button>
          ))}
          {group.items.length === 0 ? <Empty>这一组的胶囊都隐藏了，可在"管理胶囊"里显示。</Empty> : null}
        </div>
      ) : <Empty>胶囊都隐藏了，可在"管理胶囊"里显示。</Empty>}
    </>
  )
}

/** 最近案件；案件卡片接受拖入文件和文件夹（U-12）。 */
function RecentCases() {
  const cases = useStore(app, (s) => s.cases)
  const [err, setErr] = useState<{ code: string; message: string } | null>(null)
  const [over, setOver] = useState<string | null>(null)
  useEffect(() => { void loadRecent().then((r) => { if (!Array.isArray(r)) setErr(r) }) }, [])
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
      <ErrorLine error={err} />
      {cases.length === 0 && !err ? <Empty>还没有案件。打开或新建一个案件文件夹开始。</Empty> : null}
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
                  <NameEdit id={item.id} name={item.name} editing={editing === item.id} onEdit={setEditing} onSave={doRename} />
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
