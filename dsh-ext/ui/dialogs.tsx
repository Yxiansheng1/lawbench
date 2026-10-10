// 弹框（注册在 DSH 的 shell.overlay）：确认、提示、导入确认、选择案件。一次显示队首一个。
import { useEffect, useState } from 'react'
import { Modal } from '@deepseek-ai/dsh-client-ui-primitives'
import { app, popDialog, type CaseRef, type Dialog } from './state.ts'
import { useStore } from './store.ts'
import { Button, C, Empty, S } from './kit.tsx'
import { DEFAULT_TARGET, loadRecent, openCase, runImport } from './cases.ts'
import { KEEP_LABEL } from './settings-draft.ts'
import { OCR_FIRST, OCR_GO } from './estimate.ts'
import { ASK_OK, ASK_TEXT, askTitle, DROP_KINDS, type DropKind } from './drop-case.ts'
import { visibleCases } from './hidden-cases.ts'
import { CASE_TEMPLATES, customFolderProblem, KIND_WORD, MAX_CUSTOM, type FolderChoice } from '../shared/case-folders.ts'

export function DialogHost() {
  const top = useStore(app, (s) => s.dialogs[0])
  if (!top) return null
  return <OneDialog key={dialogKey(top)} d={top} />
}

const keys = new WeakMap<Dialog, number>()
let seq = 0
const dialogKey = (d: Dialog) => { if (!keys.has(d)) keys.set(d, ++seq); return keys.get(d)! }

function OneDialog({ d }: { d: Dialog }) {
  const close = () => popDialog(d)
  switch (d.kind) {
    case 'confirm': {
      const answer = (yes: boolean) => { popDialog(d); d.resolve(yes) }
      return (
        <Modal open onClose={() => answer(false)} title={d.title} closeLabel="关闭"
          footer={<><Button variant="outline" onClick={() => answer(false)}>取消</Button><Button variant="primary" data-modal-autofocus onClick={() => answer(true)}>{d.ok}</Button></>}>
          <p style={{ margin: 0, lineHeight: 1.7 }}>{d.text}</p>
        </Modal>
      )
    }
    case 'unsaved': {
      const answer = (c: 'save' | 'discard' | 'cancel') => { popDialog(d); d.resolve(c) }
      return (
        <Modal open onClose={() => answer('cancel')} title={d.title} closeLabel="关闭"
          footer={<><Button variant="outline" onClick={() => answer('cancel')}>{KEEP_LABEL}</Button><Button variant="outline" onClick={() => answer('discard')}>不保存</Button><Button variant="primary" data-modal-autofocus onClick={() => answer('save')}>保存</Button></>}>
          <p style={{ margin: 0, lineHeight: 1.7 }}>{d.text}</p>
        </Modal>
      )
    }
    case 'ocrFirst': {
      const answer = (c: 'ocr' | 'go' | 'cancel') => { popDialog(d); d.resolve(c) }
      return (
        <Modal open onClose={() => answer('cancel')} title={d.title} closeLabel="关闭"
          footer={<><Button variant="outline" onClick={() => answer('cancel')}>取消</Button><Button variant="outline" onClick={() => answer('go')}>{OCR_GO}</Button><Button variant="primary" data-modal-autofocus onClick={() => answer('ocr')}>{OCR_FIRST}</Button></>}>
          <p style={{ margin: 0, lineHeight: 1.7 }}>{d.text}</p>
        </Modal>
      )
    }
    case 'notice':
      return (
        <Modal open onClose={close} title={d.title} closeLabel="关闭" footer={<Button variant="primary" data-modal-autofocus onClick={close}>知道了</Button>}>
          <p style={{ margin: 0, lineHeight: 1.7 }}>{d.text}</p>
          {d.lines?.length ? (
            <ul style={{ ...S.list, marginTop: 10, maxHeight: 260, overflow: 'auto', fontSize: 12, color: C.sub }}>
              {d.lines.map((l, i) => <li key={i}>{l}</li>)}
            </ul>
          ) : null}
        </Modal>
      )
    case 'import':
      return <ImportDialog d={d} close={close} />
    case 'casePick':
      return <CasePickDialog then={d.then} close={close} />
    case 'folders':
      return <FoldersDialog d={d} />
    case 'newCase':
      return <NewCaseDialog d={d} />
  }
}

// 常用子文件夹（contracts\formats.md 1.1 两套标准目录）；律师也可以自己填
const TARGETS = [DEFAULT_TARGET, '01委托手续', '03一审/我方证据', '03一审/对方证据', '03一审/法院文书', '02案件材料/会见笔录', '02案件材料/涉案证据', '06法律研究']

/** 导入确认（U-12）：复制到哪个子文件夹（默认 02案件材料，可改）、共几个文件；确认后调 /api/materials/import。 */
function ImportDialog({ d, close }: { d: Extract<Dialog, { kind: 'import' }>; close: () => void }) {
  const [target, setTarget] = useState(DEFAULT_TARGET)
  const hasZip = d.paths.some((p) => /\.zip$/i.test(p))
  const [unzip, setUnzip] = useState(false)
  const [busy, setBusy] = useState(false)
  const bad = !target.trim() || /(^|[\\/])\.\.([\\/]|$)|^[\\/]|:/.test(target.trim())
  const go = async () => {
    setBusy(true)
    close()
    await runImport(d.caseRef, d.paths, target.trim().replace(/\\/g, '/'), hasZip && unzip)
  }
  return (
    <Modal open onClose={close} title="导入材料" closeLabel="关闭"
      footer={<><Button variant="outline" onClick={close}>取消</Button><Button variant="primary" disabled={bad || busy} onClick={go}>复制到案件并解析</Button></>}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        <div>将把 {d.paths.length} 项（文件或文件夹）复制进案件"{d.caseRef.name}"，原文件不动；然后在本机解析，不发服务器。</div>
        <label style={S.row}>放到
          <input list="lawbench-targets" style={{ ...S.input, flex: 1 }} value={target} onChange={(e) => setTarget(e.target.value)} aria-label="目标子文件夹" />
          <datalist id="lawbench-targets">{TARGETS.map((t) => <option key={t} value={t} />)}</datalist>
        </label>
        {bad ? <div style={{ color: C.err, fontSize: 12 }}>请填案件文件夹里的子文件夹名，例如 02案件材料</div> : null}
        {hasZip ? <label style={S.row}><input type="checkbox" checked={unzip} onChange={(e) => setUnzip(e.target.checked)} />压缩包先解压，再复制里面的文件</label> : null}
        <ul style={{ ...S.list, maxHeight: 160, overflow: 'auto', fontSize: 12, color: C.sub }}>
          {d.paths.map((p) => <li key={p}>{p}</li>)}
        </ul>
        <div style={S.sub}>同名同内容的跳过；同名不同内容的改名为"原名(2)"，不覆盖；云同步目录里的文件和快捷方式不复制。</div>
      </div>
    </Modal>
  )
}

/** 选择或新建案件（F-ENT-01、F-CASE-01）。 */
function CasePickDialog({ then, close }: { then?: (c: CaseRef) => void; close: () => void }) {
  const all = useStore(app, (s) => s.cases)
  const hidden = useStore(app, (s) => s.hiddenCases)
  const cases = visibleCases(all, hidden) // 令 2125：已从左栏列表移除的不列
  const [loading, setLoading] = useState(true)
  useEffect(() => { void loadRecent().finally(() => setLoading(false)) }, [])
  const done = (c: CaseRef | undefined) => { if (c) { close(); then?.(c) } }
  return (
    <Modal open onClose={close} title="先选择案件" closeLabel="关闭"
      footer={<>
        <Button variant="outline" onClick={() => void openCase(null, null).then(done)}>打开案件文件夹…</Button>
        {/* 新建先关掉本框：选完文件夹要弹"建哪些子文件夹"，弹框一次只显示队首一个（令 1852 第 17 条） */}
        <Button variant="outline" onClick={() => { close(); void openCase(null, 'civil').then((c) => { if (c) then?.(c) }) }}>新建民商事案件…</Button>
        <Button variant="outline" onClick={() => { close(); void openCase(null, 'criminal').then((c) => { if (c) then?.(c) }) }}>新建刑事案件…</Button>
      </>}>
      <div style={S.sub}>这项业务要在案件里做。选最近的案件，或打开、新建一个案件文件夹。</div>
      {loading ? <Empty>读取中…</Empty> : cases.length === 0 ? <Empty>还没有案件</Empty> : (
        <ul style={{ ...S.list, marginTop: 10 }}>
          {cases.map((c) => (
            <li key={c.case_id}>
              <button type="button" disabled={c.exists === false} onClick={() => void openCase(c.root, null).then(done)}
                style={{ ...S.card, width: '100%', textAlign: 'left', cursor: c.exists === false ? 'not-allowed' : 'pointer', color: C.text, font: 'inherit' }}>
                <div>{c.name}</div>
                <div style={S.sub}>{c.exists === false ? '文件夹已不在原处' : c.root}</div>
              </button>
            </li>
          ))}
        </ul>
      )}
    </Modal>
  )
}

/**
 * 新建案件：要建哪些子文件夹（令 1852 第 17 条）。列出该类型的标准目录（一级，括号里写它带的二级），默认全不勾；
 * "全选 / 全不选"；底部"添加一项"自填一级目录名（非法字符、保留名当场拒）。"工作区""成果"由工作台自己建，不列。
 */
function FoldersDialog({ d }: { d: Extract<Dialog, { kind: 'folders' }> }) {
  const list = CASE_TEMPLATES[d.template]
  const [tops, setTops] = useState<string[]>([])
  const [custom, setCustom] = useState<string[]>([])
  const [draft, setDraft] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const answer = (choice: FolderChoice | null) => { popDialog(d); d.resolve(choice) }
  const toggle = (name: string) => setTops(tops.includes(name) ? tops.filter((x) => x !== name) : list.map((f) => f.name).filter((n) => n === name || tops.includes(n)))
  const all = tops.length === list.length
  const add = () => {
    const name = draft.trim()
    const problem = customFolderProblem(name)
    if (problem) { setErr(problem); return }
    if ([...list.map((f) => f.name), ...custom].some((x) => x.toLowerCase() === name.toLowerCase())) { setErr(`"${name}"已经在列表里了`); return }
    if (custom.length >= MAX_CUSTOM) { setErr(`自己添加的最多 ${MAX_CUSTOM} 项`); return }
    setCustom([...custom, name]); setDraft(''); setErr(null)
  }
  const count = tops.length + custom.length
  return (
    <Modal open onClose={() => answer(null)} title="要建哪些子文件夹" closeLabel="关闭"
      footer={<><Button variant="outline" onClick={() => answer(null)}>取消</Button><Button variant="primary" data-modal-autofocus onClick={() => answer({ tops, custom })}>{count ? `新建案件并建 ${count} 项` : '新建案件（不建子文件夹）'}</Button></>}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        <div>在"{d.caseName}"里按{KIND_WORD[d.template]}案件的常用目录建子文件夹。勾了的才建，已经有的不动；工作台自用的文件夹和"成果"会另外建好，不用勾。</div>
        <div style={S.row}>
          <Button size="sm" variant="ghost" onClick={() => setTops(all ? [] : list.map((f) => f.name))}>{all ? '全不选' : '全选'}</Button>
        </div>
        <ul style={{ ...S.list, maxHeight: 280, overflow: 'auto' }}>
          {list.map((f) => (
            <li key={f.name}>
              <label style={{ ...S.row, alignItems: 'baseline' }}>
                <input type="checkbox" checked={tops.includes(f.name)} onChange={() => toggle(f.name)} />
                <span>{f.name}{f.subs.length ? <span style={S.sub}>（含 {f.subs.join('、')}）</span> : null}</span>
              </label>
            </li>
          ))}
          {custom.map((c) => (
            <li key={c} style={S.row}>
              <input type="checkbox" checked readOnly aria-label={c} />
              <span style={{ flex: 1 }}>{c}</span>
              <Button size="sm" variant="ghost" onClick={() => setCustom(custom.filter((x) => x !== c))}>去掉</Button>
            </li>
          ))}
        </ul>
        <div style={S.row}>
          <input style={{ ...S.input, flex: 1 }} value={draft} placeholder="自己添加一项，例如 09往来函件" aria-label="自己添加的子文件夹名"
            onChange={(e) => { setDraft(e.target.value); setErr(null) }} onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); add() } }} />
          <Button size="sm" variant="outline" disabled={!draft.trim()} onClick={add}>添加一项</Button>
        </div>
        {err ? <div role="alert" style={{ color: C.err, fontSize: 12 }}>{err}</div> : null}
      </div>
    </Modal>
  )
}

/** 首页空白处拖进文件夹（令 1422）：把它建成案件？选类型（民商事 / 刑事 / 日常事务），确定 / 取消。取消什么都不发生。 */
function NewCaseDialog({ d }: { d: Extract<Dialog, { kind: 'newCase' }> }) {
  const [kind, setKind] = useState<DropKind>('civil')
  const answer = (k: DropKind | null) => { popDialog(d); d.resolve(k) }
  return (
    <Modal open onClose={() => answer(null)} title={askTitle(d.name)} closeLabel="关闭"
      footer={<><Button variant="outline" onClick={() => answer(null)}>取消</Button><Button variant="primary" data-modal-autofocus onClick={() => answer(kind)}>{ASK_OK}</Button></>}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        <div style={{ lineHeight: 1.7 }}>{ASK_TEXT}</div>
        <div role="radiogroup" aria-label="案件类型" style={{ ...S.row, flexWrap: 'wrap' }}>
          <span style={S.sub}>类型</span>
          {DROP_KINDS.map((k) => (
            <label key={k.kind} style={S.row}><input type="radio" name="lawbench-new-case-kind" checked={kind === k.kind} onChange={() => setKind(k.kind)} />{k.label}</label>
          ))}
        </div>
      </div>
    </Modal>
  )
}
