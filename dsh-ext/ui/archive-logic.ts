// 归档面板（T26 第 3 步，U-15）的纯逻辑：方案的类型、律师可改的几项、能否生成、交给 /api/archive/build 的请求、结果的显示文字。
// 契约：tools/case_save_archive_plan 的 $defs/plan（方案）、api/archive_build（请求与返回）。生成全在服务端，这里不碰文件。

/** 办案结果（我方视角），契约的取值；只能由律师点选。 */
export const RESULTS = ['胜诉', '败诉', '部分胜诉', '调解', '撤诉', '其他'] as const
export type CaseResult = (typeof RESULTS)[number]

export interface PlanItem { code: number; name: string; materials: string[] }
export interface ArchivePlan {
  catalog: '民事行政卷' | '刑事卷' | '常法卷' | '其他非诉卷'
  client: string
  opponent: string | null
  cause: string
  lawyer: string | null
  entrust_date: string | null
  close_date: string | null
  jzl_no: string | null
  result: CaseResult | null
  summary: string
  opinion: string
  fee_settled: boolean
  items: PlanItem[]
}

/** /api/archive/build 的返回值。 */
export interface BuildValue {
  folder: string
  files: Array<{ kind: '卷宗' | '立卷申请书' | '结案报告' | '发票' | '归档目录' | '特殊情况说明'; path: string }>
  page_ranges: Array<{ code: number; from: number; to: number }>
  converter: 'word' | 'wps' | 'libreoffice'
  manual: string[]
}

/** 界面上能改的：材料名称、每项里材料的合并顺序、两个日期、承办律师、办案结果。其余照方案原样交回。 */
export type Edit =
  | { kind: 'name'; code: number; name: string }
  | { kind: 'move'; code: number; index: number; by: -1 | 1 }
  | { kind: 'lawyer'; lawyer: string }
  | { kind: 'date'; field: 'entrust_date' | 'close_date'; value: string }
  | { kind: 'result'; result: CaseResult }

export function applyEdit(p: ArchivePlan, e: Edit): ArchivePlan {
  switch (e.kind) {
    case 'name':
      return { ...p, items: p.items.map((it) => (it.code === e.code ? { ...it, name: e.name } : it)) }
    case 'move':
      return {
        ...p,
        items: p.items.map((it) => {
          const j = e.index + e.by
          if (it.code !== e.code || e.index < 0 || e.index >= it.materials.length || j < 0 || j >= it.materials.length) return it
          const m = [...it.materials]
          ;[m[e.index], m[j]] = [m[j], m[e.index]]
          return { ...it, materials: m }
        }),
      }
    case 'lawyer':
      return { ...p, lawyer: e.lawyer }
    case 'date':
      return { ...p, [e.field]: e.value }
    case 'result':
      return { ...p, result: e.result }
  }
}

/** 空或 YYYY-MM-DD 的真实日期。 */
export function dateOk(v: string | null): boolean {
  if (!v) return true
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(v)
  if (!m) return false
  const d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]))
  return d.getUTCFullYear() === +m[1] && d.getUTCMonth() === +m[2] - 1 && d.getUTCDate() === +m[3]
}

/** 还不能生成的原因（第一条）；能生成时为 null。办案结果没点选时按钮不可用。 */
export function blocker(p: ArchivePlan): string | null {
  if (p.result === null) return '请先点选办案结果'
  if (p.items.some((it) => !it.name.trim())) return '材料名称不能为空'
  if (!dateOk(p.entrust_date) || !dateOk(p.close_date)) return '日期格式应为 年-月-日'
  return null
}

/** 交服务端的确认方案：名称去首尾空白；承办律师、日期空着的按契约交 null（律师空着时服务用设置里的律师姓名）。 */
export function confirmedPlan(p: ArchivePlan): ArchivePlan {
  const blank = (v: string | null): string | null => (v && v.trim() ? v.trim() : null)
  return {
    ...p,
    lawyer: blank(p.lawyer),
    entrust_date: blank(p.entrust_date),
    close_date: blank(p.close_date),
    items: p.items.map((it) => ({ ...it, name: it.name.trim() })),
  }
}

export function buildRequest(caseId: string, taskId: string, planPath: string, p: ArchivePlan): {
  case_id: string; task_id: string; plan: string; confirmed: ArchivePlan
} {
  return { case_id: caseId, task_id: taskId, plan: planPath, confirmed: confirmedPlan(p) }
}

/** 页码范围：按编号对上方案里的材料名称；服务端自动加的项（结案报告）方案里没有，只写编号。 */
export function pageLines(v: BuildValue, p: ArchivePlan): string[] {
  const name = new Map(p.items.map((it) => [it.code, it.name]))
  return [...v.page_ranges].sort((a, b) => a.from - b.from).map((r) => {
    const pages = r.from === r.to ? `第 ${r.from} 页` : `第 ${r.from}–${r.to} 页`
    return `${r.code}. ${name.get(r.code) ?? '（程序生成）'}：${pages}`
  })
}

const CONVERTER_WORD: Record<BuildValue['converter'], string> = { word: 'Word', wps: 'WPS', libreoffice: 'LibreOffice' }
/** 结案报告用哪个程序转的（T23 交付说明第 48 行：契约只返回结案报告那一个），提示律师核对是否一页。 */
export function converterHint(v: BuildValue): string {
  return v.converter === 'libreoffice'
    ? '结案报告由 LibreOffice 转成 PDF，版式可能与 Word 略有出入，请在 Word 或 WPS 中打开核对是否为一页。'
    : `结案报告由 ${CONVERTER_WORD[v.converter]} 转成 PDF，请打开核对是否为一页。`
}
