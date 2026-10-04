// 弹框（注册在 DSH 的 shell.overlay）：确认、提示、导入确认、选择案件。一次显示队首一个。
import { useEffect, useState } from 'react'
import { Modal } from '@deepseek-ai/dsh-client-ui-primitives'
import { app, popDialog, type CaseRef, type Dialog } from './state.ts'
import { useStore } from './store.ts'
import { Button, C, Empty, S } from './kit.tsx'
import { DEFAULT_TARGET, loadRecent, openCase, runImport } from './cases.ts'
import { KEEP_LABEL } from './settings-draft.ts'

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
  const cases = useStore(app, (s) => s.cases)
  const [loading, setLoading] = useState(true)
  useEffect(() => { void loadRecent().finally(() => setLoading(false)) }, [])
  const done = (c: CaseRef | undefined) => { if (c) { close(); then?.(c) } }
  return (
    <Modal open onClose={close} title="先选择案件" closeLabel="关闭"
      footer={<>
        <Button variant="outline" onClick={() => void openCase(null, null).then(done)}>打开案件文件夹…</Button>
        <Button variant="outline" onClick={() => void openCase(null, 'civil').then(done)}>新建（民商事目录）…</Button>
        <Button variant="outline" onClick={() => void openCase(null, 'criminal').then(done)}>新建（刑事目录）…</Button>
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
