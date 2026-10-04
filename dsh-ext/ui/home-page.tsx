// 首页（令 1426，用户："首页需要入口……首页做大气点，这样看着好小气"）：就是原来侧栏"案件"点开的那一页，升级为首页。
// 顶部：律所 logo、产品名，右侧"律师姓名 · 今天日期"，下面一行分流提示；三个主按钮（打开案件、新建民商事案件、新建刑事案件）；
// 最近案件大卡片（"日常事务（非办案）"单独一张排第一，其余按上次打开倒序、最多 12 个），每张：案件名、路径、材料 / 待识别 / 成果份数、
// 上次打开时间，整卡可点进入，可把文件拖到卡片导入；没有案件时居中一段欢迎语和三个按钮；底部"技术支持"一行。
// 数据走现有的 caseRecent、materialsList、outputsList、getCapsules，不加接口。
import { useEffect, useState, type DragEvent, type ReactNode } from 'react'
import type { Capsules } from './capsules.ts'
import { loadRecent, openCase, startImport } from './cases.ts'
import { Badge, Button, C, CONNECTING_TEXT, Empty, ErrorLine, getNav, useLoad, useRetryLoad } from './kit.tsx'
import { app, call, isDaily, type CaseRef } from './state.ts'
import { useStore } from './store.ts'
import { BrandMark } from './brand.tsx'
import { PRODUCT_NAME } from '../shared/product.ts'
import { materialCounts, shortTime } from './overview.tsx'
import { loadSettingsIntoState } from './settings.tsx'

/** 首页最多列这么多个案件（日常事务另算）；其余在"打开案件…"里。 */
export const HOME_MAX_CASES = 12
export const WELCOME_TEXT = '欢迎使用连越律师工作台。打开已有的案件文件夹，或新建一个案件开始。'
const WEEK = ['日', '一', '二', '三', '四', '五', '六']

/** 今天日期：2026年10月4日 星期日。 */
export const todayText = (d: Date = new Date()): string => `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日 星期${WEEK[d.getDay()]}`

/** 首页卡片的顺序：日常事务排第一，其余按上次打开倒序，最多 HOME_MAX_CASES 个。 */
export function homeCases(cases: CaseRef[], dailyRoot: string | null): { daily: CaseRef | undefined; others: CaseRef[] } {
  const daily = cases.find((c) => isDaily({ dailyRoot }, c))
  const others = cases.filter((c) => c !== daily)
    .sort((a, b) => (Date.parse(b.last_opened ?? '') || 0) - (Date.parse(a.last_opened ?? '') || 0))
    .slice(0, HOME_MAX_CASES)
  return { daily, others }
}

const PAGE = { boxSizing: 'border-box' as const, width: '100%', maxWidth: 1180, margin: '0 auto', padding: '40px 32px 24px', display: 'flex', flexDirection: 'column' as const, gap: 28, color: C.text }
const SHADOW = '0 1px 2px rgba(0,0,0,0.04), 0 4px 16px rgba(0,0,0,0.06)'

export function HomeLanding({ banner }: { banner?: ReactNode }) {
  const [recent, reload] = useRetryLoad(async () => {
    const r = await loadRecent()
    return Array.isArray(r) ? { ok: true as const, value: r } : { ok: false as const, error: r }
  }, [])
  const [caps, reloadCaps] = useLoad(() => call<Capsules>('getCapsules'), [])
  // 启动时服务往往还没就绪，分流提示和律师姓名第一次读不到：案件列表读到了（服务已就绪）再读一次（真机核过）
  const ready = recent.state === 'ok'
  useEffect(() => { if (ready) { void reloadCaps(); void loadSettingsIntoState() } }, [ready]) // eslint-disable-line react-hooks/exhaustive-deps
  const cases = useStore(app, (s) => s.cases)
  const dailyRoot = useStore(app, (s) => s.dailyRoot)
  const lawyer = useStore(app, (s) => s.lawyerName)
  const { daily, others } = homeCases(cases, dailyRoot)
  return (
    <div style={{ height: '100%', overflowY: 'auto' }}>
      <div style={PAGE}>
        <header style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
              <BrandMark size={46} />
              <h1 style={{ margin: 0, fontSize: 28, fontWeight: 600, letterSpacing: 1 }}>{PRODUCT_NAME}</h1>
            </div>
            <div style={{ fontSize: 14, color: C.sub }}>{lawyer ? `${lawyer} · ` : ''}{todayText()}</div>
          </div>
          {caps.state === 'ok' ? <div style={{ fontSize: 14, color: C.sub, lineHeight: 1.7 }}>{caps.value.hint}</div> : null}
        </header>
        {banner}
        {recent.state === 'loading' ? <Empty>读取中…</Empty> : null}
        {recent.state === 'connecting' ? <Empty>{CONNECTING_TEXT}</Empty> : null}
        {recent.state === 'fail' ? (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}><ErrorLine error={recent.error} /><Button size="sm" variant="outline" onClick={() => void reload()}>重试</Button></div>
        ) : null}
        {recent.state === 'ok' && others.length === 0 ? (
          <section aria-label="欢迎" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 18, padding: '36px 16px', border: `1px dashed ${C.border}`, borderRadius: 16 }}>
            <div style={{ fontSize: 17, color: C.text, textAlign: 'center' }}>{WELCOME_TEXT}</div>
            <MainButtons />
          </section>
        ) : null}
        {recent.state === 'ok' && (others.length > 0 || daily) ? (
          <section aria-label="最近案件" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
              <h2 style={{ margin: 0, fontSize: 20, fontWeight: 600 }}>最近案件</h2>
              {others.length > 0 ? <MainButtons /> : null}
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 16 }}>
              {daily ? <CaseCard c={daily} daily /> : null}
              {others.map((c) => <CaseCard key={c.case_id} c={c} />)}
            </div>
          </section>
        ) : null}
      </div>
    </div>
  )
}

/** 三个主按钮。 */
function MainButtons() {
  return (
    <div role="group" aria-label="案件操作" style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
      <Button variant="primary" onClick={() => void openCase(null, null)}>打开案件…</Button>
      <Button variant="outline" onClick={() => void openCase(null, 'civil')}>新建民商事案件…</Button>
      <Button variant="outline" onClick={() => void openCase(null, 'criminal')}>新建刑事案件…</Button>
    </div>
  )
}

/** 一张案件卡片：整卡可点进入；接受拖入文件和文件夹导入（U-12）。 */
export function CaseCard({ c, daily = false }: { c: CaseRef; daily?: boolean }) {
  const [over, setOver] = useState(false)
  const [mats] = useLoad(() => call<{ materials: Array<{ pages_need_ocr?: unknown[] }> }>('materialsList', { case_id: c.case_id }), [c.case_id])
  const [outs] = useLoad(() => call<{ outputs: unknown[] }>('outputsList', { case_id: c.case_id }), [c.case_id])
  const counts = mats.state === 'ok' ? materialCounts(mats.value.materials) : null
  const missing = c.exists === false
  const enter = () => { if (!missing) void openCase(c.root, null) }
  const drop = (e: DragEvent) => {
    e.preventDefault(); e.stopPropagation(); setOver(false) // 不冒泡到 DSH 的 document 拖入监听（否则会被当成聊天附件）
    if (missing) return // 文件夹不在原处：拦下默认行为（Electron 里可能跳到 file://），不导入
    startImport(c, [...e.dataTransfer.files].map((f) => getNav().pathFor(f)), '案件卡片')
  }
  const stats = [
    counts ? `材料 ${counts.total} 份` : mats.state === 'fail' ? '材料读不到' : '材料 …',
    counts ? `待识别 ${counts.pending} 份` : null,
    outs.state === 'ok' ? `成果 ${outs.value.outputs.length} 份` : null,
  ].filter(Boolean).join(' · ')
  return (
    <div role="button" tabIndex={missing ? -1 : 0} aria-label={`进入${c.name}`} data-case-card={daily ? 'daily' : 'case'} data-lawbench-drop=''
      onClick={enter} onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); enter() } }}
      onDragEnter={(e) => e.stopPropagation()} onDragOver={(e) => { e.stopPropagation(); e.preventDefault(); if (missing) e.dataTransfer.dropEffect = 'none'; else setOver(true) }}
      onDragLeave={(e) => { e.stopPropagation(); setOver(false) }} onDrop={drop}
      style={{
        border: `1px solid ${over ? C.brand : C.border}`, borderRadius: 14, padding: '18px 18px 14px', minHeight: 150, boxShadow: SHADOW,
        background: daily ? 'rgba(47,107,255,0.05)' : 'transparent', cursor: missing ? 'not-allowed' : 'pointer', opacity: missing ? 0.7 : 1,
        display: 'flex', flexDirection: 'column', gap: 8, outline: 'none',
      }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
        <span style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
          {daily ? <DailyIcon /> : <FolderIcon />}
          <span style={{ fontSize: 18, fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{daily ? `${c.name}（非办案）` : c.name}</span>
        </span>
        {missing ? <Badge tone="warn">文件夹不在原处</Badge> : null}
      </div>
      <div style={{ fontSize: 12, color: C.faint, wordBreak: 'break-all' }}>{c.root}</div>
      <div style={{ fontSize: 14, color: C.text }}>{stats}</div>
      <div style={{ marginTop: 'auto', display: 'flex', justifyContent: 'space-between', fontSize: 12, color: C.faint }}>
        <span>{over ? '松开即导入到这个案件' : '可把文件拖到这里导入'}</span>
        <span>{c.last_opened ? `上次打开 ${shortTime(c.last_opened)}` : ''}</span>
      </div>
    </div>
  )
}

const FolderIcon = () => (
  <svg width={20} height={20} viewBox="0 0 16 16" fill="none" aria-hidden="true" stroke={C.brand} strokeWidth={1.3} style={{ flex: 'none' }}>
    <path d="M2 4.2c0-.4.3-.7.7-.7h3.4l1.4 1.5h5.8c.4 0 .7.3.7.7v6.9c0 .4-.3.7-.7.7H2.7a.7.7 0 0 1-.7-.7V4.2Z" strokeLinejoin="round" />
  </svg>
)
/** 日常事务：对话气泡（与案件的文件夹区分）。 */
const DailyIcon = () => (
  <svg width={20} height={20} viewBox="0 0 16 16" fill="none" aria-hidden="true" stroke={C.sub} strokeWidth={1.3} style={{ flex: 'none' }}>
    <path d="M2.5 3.5h11v7.2h-6.3L4.5 13v-2.3h-2V3.5Z" strokeLinejoin="round" />
  </svg>
)
