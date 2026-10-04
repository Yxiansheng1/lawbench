// 设置页"律师工作台"一节（PRD 7.9；settings.json 契约 files/settings.schema.json）：
// 服务器和 Key（T13 执行令 Q7：地址只读；Key 可更换，T14 第二次实跑派修 3）、个人参数预设、Word 模板、本机律师姓名、日常办公文件夹、
// 发票购买方名称、Word 转 PDF 的程序、关于。保存时服务器地址原样带回，不在这里改。
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Button, C, ErrorLine, getNav, S } from './kit.tsx'
import { lawyerMessage } from './format.ts'
import { BrandMark, VendorLine } from './brand.tsx'
import { CapsuleSettings } from './home.tsx'
import { FIRM_NAME, PRODUCT_NAME, PRODUCT_VERSION } from '../shared/product.ts'
import { app, lb, MODE_AGENT, type ConnectionResult, type Params, type SkillInfo } from './state.ts'

interface Settings {
  v: 1
  servers: { llm_base_url: string; prep_base_url: string; llm_alt_base_url: string | null; prep_alt_base_url: string | null }
  defaults: Params
  skill_presets: Record<string, Params>
  templates: { 文书: string | null; 合同: string | null }
  ocr_fallback_llm: boolean
  profile: { lawyer_name: string | null }
  office: { dir: string | null; invoice_buyer: string | null }
  converter: 'auto' | 'word' | 'wps' | 'libreoffice'
}

const CONVERTERS: Array<[Settings['converter'], string]> = [['auto', '自动（依次试 Word、WPS、内置转换程序）'], ['word', 'Microsoft Word'], ['wps', 'WPS'], ['libreoffice', '内置转换程序']]
const THINKING: Params['thinking'][] = ['关闭', '低', '中', '高']
const WINDOWS: Params['window'][] = ['32K', '64K', '128K']

/** 读设置后把默认参数、Skill 预设放进界面状态（输入区参数的初值）。 */
export async function loadSettingsIntoState(): Promise<Settings | undefined> {
  try {
    const s = (await lb().getSettings()) as unknown as Settings
    app.set((st) => ({ ...st, defaults: s.defaults, presets: s.skill_presets }))
    return s
  } catch { return undefined }
}

export function SettingsSection() {
  const [loaded, setLoaded] = useState<Settings | null>(null)
  const [draft, setDraft] = useState<Settings | null>(null)
  const [hasKey, setHasKey] = useState<boolean | null>(null)
  const [skills, setSkills] = useState<SkillInfo[]>([])
  const [err, setErr] = useState<{ code: string; message: string } | null>(null)
  const [saved, setSaved] = useState(false)
  const templateInput = useRef<HTMLInputElement>(null)
  const [templateFor, setTemplateFor] = useState<'文书' | '合同'>('文书')
  useEffect(() => {
    void loadSettingsIntoState().then((s) => { if (s) { setLoaded(s); setDraft(structuredClone(s)) } else setErr({ code: 'SERVICE_UNAVAILABLE', message: '没能读取设置，请稍后重试' }) })
    void lb().setupState().then((s) => setHasKey(s.hasKey)).catch(() => setHasKey(null))
    void lb().listSkills().then((r) => setSkills(r.value.skills.filter((x) => x.mode === MODE_AGENT))).catch(() => undefined)
  }, [])
  if (!draft || !loaded) return <div style={{ padding: 16 }}><h2 style={S.h2}>律师工作台</h2><ErrorLine error={err} />{err ? null : <div style={S.sub}>读取中…</div>}</div>

  const up = (f: (d: Settings) => void) => { const d = structuredClone(draft); f(d); setDraft(d); setSaved(false) }
  const dirty = JSON.stringify(draft) !== JSON.stringify(loaded)
  const save = async () => {
    try {
      await lb().putSettings({ ...draft, servers: loaded.servers, ocr_fallback_llm: loaded.ocr_fallback_llm })
      setLoaded(structuredClone(draft)); setErr(null); setSaved(true)
      app.set((st) => ({ ...st, defaults: draft.defaults, presets: draft.skill_presets }))
    } catch (e) { setErr({ code: 'INVALID_ARGUMENT', message: lawyerMessage((e as Error).message) }) }
  }
  const skillTitle = (n: string) => skills.find((s) => s.name === n)?.title ?? n
  const unset = skills.filter((s) => !draft.skill_presets[s.name])

  return (
    <div style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 18, color: C.text, fontSize: 13 }}>
      <div style={S.between}>
        <h2 style={S.h2}>律师工作台</h2>
        <div style={S.row}>{saved ? <span style={{ color: C.ok, fontSize: 12 }}>已保存</span> : null}<Button variant="primary" size="sm" disabled={!dirty} onClick={() => void save()}>保存</Button></div>
      </div>
      <ErrorLine error={err} />

      <Block title="服务器和 Key" note="服务器地址本版只显示；Key 可以更换。">
        <Field label="律所模型服务器"><Ro>{loaded.servers.llm_base_url}</Ro><Ro>所外：{loaded.servers.llm_alt_base_url ?? '未设置'}</Ro></Field>
        <Field label="律所识别服务器"><Ro>{loaded.servers.prep_base_url}</Ro><Ro>所外：{loaded.servers.prep_alt_base_url ?? '未设置'}</Ro></Field>
        <Field label="个人 Key"><Ro>{hasKey === null ? '读取中' : hasKey ? '已设置（保存在 Windows 凭据管理器）' : '未设置'}</Ro><ChangeKey onChanged={() => setHasKey(true)} /></Field>
      </Block>

      <Block title="胶囊" note="输入框上方的两层胶囊：排序、改名、隐藏、新增。只影响这台电脑。">
        <CapsuleSettings />
      </Block>

      <Block title="个人参数预设" note="新任务的默认参数；也可以给某个 Skill 单独设一套。">
        <ParamsRow label="默认" p={draft.defaults} onChange={(p) => up((d) => { d.defaults = p })} />
        {Object.entries(draft.skill_presets).map(([name, p]) => (
          <ParamsRow key={name} label={skillTitle(name)} p={p} onChange={(np) => up((d) => { d.skill_presets[name] = np })}
            extra={<Button size="sm" variant="ghost" onClick={() => up((d) => { delete d.skill_presets[name] })}>去掉</Button>} />
        ))}
        {unset.length ? (
          <label style={S.row}>给 Skill 单独设
            <select style={S.input} value="" onChange={(e) => { const n = e.target.value; if (n) up((d) => { d.skill_presets[n] = { ...(skills.find((s) => s.name === n)?.params ?? d.defaults) } }) }}>
              <option value="">选择 Skill…</option>
              {unset.map((s) => <option key={s.name} value={s.name}>{s.title}</option>)}
            </select>
          </label>
        ) : null}
      </Block>

      <Block title="Word 模板" note="导出 Word 时套用；不设就用内置模板。">
        {(['文书', '合同'] as const).map((k) => (
          <Field key={k} label={`${k}模板`}>
            <Ro>{draft.templates[k] ?? '内置模板'}</Ro>
            <Button size="sm" variant="outline" onClick={() => { setTemplateFor(k); templateInput.current?.click() }}>选择文件…</Button>
            {draft.templates[k] ? <Button size="sm" variant="ghost" onClick={() => up((d) => { d.templates[k] = null })}>用内置</Button> : null}
          </Field>
        ))}
        <input ref={templateInput} type="file" accept=".docx" hidden onChange={(e) => {
          const f = e.target.files?.[0]; e.target.value = ''
          const path = f ? getNav().pathFor(f) : ''
          if (path) up((d) => { d.templates[templateFor] = path })
        }} />
      </Block>

      <Block title="本机律师">
        <Field label="律师姓名"><input style={{ ...S.input, width: 200 }} value={draft.profile.lawyer_name ?? ''} placeholder="结案报告、立卷申请书默认的承办律师"
          onChange={(e) => up((d) => { d.profile.lawyer_name = e.target.value.trim() ? e.target.value : null })} /></Field>
      </Block>

      <Block title="日常办公" note="发票台账等放在这里；不要选云同步文件夹。">
        <Field label="日常办公文件夹">
          <Ro>{draft.office.dir ?? '未设置'}</Ro>
          <Button size="sm" variant="outline" onClick={() => void getNav().pickDirectory().then((p) => { if (p) up((d) => { d.office.dir = p }) })}>选择文件夹…</Button>
        </Field>
        <Field label="发票购买方名称"><input style={{ ...S.input, width: 280 }} value={draft.office.invoice_buyer ?? ''} placeholder="律所全称，用于核对发票抬头"
          onChange={(e) => up((d) => { d.office.invoice_buyer = e.target.value.trim() ? e.target.value : null })} /></Field>
      </Block>

      <Block title="Word 转 PDF">
        <Field label="使用的程序">
          <select style={S.input} value={draft.converter} onChange={(e) => up((d) => { d.converter = e.target.value as Settings['converter'] })}>
            {CONVERTERS.map(([v, t]) => <option key={v} value={v}>{t}</option>)}
          </select>
        </Field>
      </Block>

      <Block title="关于">
        <div style={{ ...S.row, gap: 12 }}><BrandMark size={32} /><span style={{ fontWeight: 600 }}>{PRODUCT_NAME} {PRODUCT_VERSION}</span></div>
        <div style={S.sub}>{FIRM_NAME} · 本机运行，案件材料只在这台电脑和律所服务器之间处理。</div>
        <VendorLine />
      </Block>
    </div>
  )
}

/** 一台服务器测试结果的一句话（服务给的 message 已是中文说明）。 */
export function connectionLine(label: string, r: ConnectionResult | null): string {
  if (!r) return `${label}：没有测成`
  return `${label}：${r.message}`
}

/**
 * 更换 Key（执行令 1751 必修 3）：输入新 Key → Host 写进凭据管理器（覆盖旧 Key）→ 自动测一次连接 → 显示结果。
 * 输入框是密码框；提交后立即清空，界面任何地方都不显示 Key。
 */
export function ChangeKey({ onChanged }: { onChanged: () => void }) {
  const [open, setOpen] = useState(false)
  const [key, setKey] = useState('')
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<{ ok: boolean; lines: string[] } | null>(null)
  const submit = async () => {
    const k = key.trim()
    setKey('')
    if (!/^[!-~]{8,512}$/.test(k)) { setResult({ ok: false, lines: ['Key 格式不对：应为 8 个字符以上、不含空格和中文'] }); return }
    setBusy(true); setResult(null)
    try {
      const r = await lb().changeKey(k)
      onChanged()
      setOpen(false)
      const ok = !r.error && r.llm?.reachable === true && r.llm.key_valid !== false && r.prep?.reachable === true
      setResult({ ok, lines: ['已换成新 Key', ...(r.error ? [`测试连接没有做成：${r.error}`] : [connectionLine('律所模型服务器', r.llm), connectionLine('律所识别服务器', r.prep)])] })
    } catch (e) {
      setResult({ ok: false, lines: [`没有换成：${lawyerMessage((e as Error).message)}`] })
    } finally { setBusy(false) }
  }
  return (
    <>
      {open ? (
        <span style={S.row}>
          <input type="password" autoComplete="off" aria-label="新 Key" style={{ ...S.input, width: 240 }} value={key} placeholder="粘贴新 Key"
            onChange={(e) => setKey(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter' && key) void submit() }} />
          <Button size="sm" variant="primary" disabled={!key || busy} onClick={() => void submit()}>保存并测试</Button>
          <Button size="sm" variant="ghost" disabled={busy} onClick={() => { setKey(''); setOpen(false) }}>取消</Button>
        </span>
      ) : <Button size="sm" variant="outline" disabled={busy} onClick={() => { setResult(null); setOpen(true) }}>{busy ? '正在测试…' : '更换 Key'}</Button>}
      {result ? (
        <div role="status" style={{ width: '100%', paddingLeft: 118, fontSize: 12, color: result.ok ? C.ok : C.err }}>
          {result.lines.map((l) => <div key={l}>{l}</div>)}
        </div>
      ) : null}
    </>
  )
}

function Block({ title, note, children }: { title: string; note?: string; children: ReactNode }) {
  return (
    <section style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div><h3 style={S.h3}>{title}</h3>{note ? <div style={S.sub}>{note}</div> : null}</div>
      {children}
    </section>
  )
}
const Field = ({ label, children }: { label: string; children: ReactNode }) => (
  <div style={{ ...S.row, flexWrap: 'wrap' }}><span style={{ width: 110, color: C.sub }}>{label}</span>{children}</div>
)
const Ro = ({ children }: { children: ReactNode }) => <span style={{ ...S.input, border: 'none', padding: '5px 0', wordBreak: 'break-all' }}>{children}</span>

function ParamsRow({ label, p, onChange, extra }: { label: string; p: Params; onChange: (p: Params) => void; extra?: ReactNode }) {
  return (
    <div style={{ ...S.row, flexWrap: 'wrap' }}>
      <span style={{ width: 110, color: C.sub }}>{label}</span>
      <label style={S.row}>思考<select style={S.input} value={p.thinking} onChange={(e) => onChange({ ...p, thinking: e.target.value as Params['thinking'] })}>{THINKING.map((x) => <option key={x}>{x}</option>)}</select></label>
      <label style={S.row}>窗口<select style={S.input} value={p.window} onChange={(e) => onChange({ ...p, window: e.target.value as Params['window'] })}>{WINDOWS.map((x) => <option key={x}>{x}</option>)}</select></label>
      <label style={S.row}>最长输出<input type="number" min={256} max={262144} step={1024} style={{ ...S.input, width: 100 }} value={p.max_tokens}
        onChange={(e) => { const n = Number(e.target.value); if (n >= 256 && n <= 262144) onChange({ ...p, max_tokens: n }) }} /></label>
      {extra}
    </div>
  )
}
