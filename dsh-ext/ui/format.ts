// 界面上的中文说法和确认框文字（纯函数，便于测试）。
// 词表检查（scripts\check_ui_words.py）扫这里的字符串：不出现 token、context 这类词。

export type Unit = 'page' | 'para' | 'cell' | 'line'
export type MaterialStatus = 'parsed' | 'needs_ocr' | 'ocr_running' | 'partial' | 'failed' | 'source_deleted'

export interface Material {
  material_id: string
  name: string
  rel_path: string
  type: string
  status: MaterialStatus
  unit: Unit
  unit_count: number
  is_ocr: unknown
  stale_ocr: boolean
  error: string | null
  pages_need_ocr: number[]
  pages_mixed: number[]
}

/**
 * 单位的说法（T13 执行令 Q10："没有页的材料按它的单位写（段、行、工作表）"）。
 * Excel 的位置单位是单元格，但数量按工作表说——契约没写明 cell 时 unit_count 数的是什么，已记入交付说明。
 */
export const UNIT_WORD: Record<Unit, string> = { page: '页', para: '段', cell: '个工作表', line: '行' }

export const STATUS_WORD: Record<MaterialStatus, string> = {
  parsed: '已解析',
  needs_ocr: '有页待识别',
  ocr_running: '识别中',
  partial: '部分页未识别',
  failed: '无法处理',
  source_deleted: '原件已删除',
}

export const TYPE_WORD: Record<string, string> = {
  pdf: 'PDF', docx: 'Word', doc: 'Word', wps: 'WPS', xlsx: 'Excel', xls: 'Excel', csv: '表格', md: '文本', txt: '文本', image: '图片',
}

/** 服务器的说法：6000D 和 395 对律师都叫"律所服务器"，括号里区分用途。 */
export const SERVER_WORD = { llm: '律所模型服务器（6000D）', prep: '律所识别服务器（395）' } as const

/** 把各材料的数量按单位合计成"共 12 页、42 段"。 */
export function sumUnits(items: ReadonlyArray<{ unit: Unit; count: number }>): string {
  const order: Unit[] = ['page', 'para', 'cell', 'line']
  const total = new Map<Unit, number>()
  for (const { unit, count } of items) total.set(unit, (total.get(unit) ?? 0) + count)
  const parts = order.filter((u) => total.has(u)).map((u) => `${total.get(u)} ${UNIT_WORD[u]}`)
  return parts.length ? parts.join('、') : '0 页'
}

/** 提交识别的确认文字（工单第 3 步、Q10）：发往哪台服务器、几份材料、共多少页。不提去水印（第 5a 步）。 */
export function ocrConfirmText(picks: ReadonlyArray<{ name: string; pages: number[] }>): string {
  const pages = picks.reduce((n, p) => n + p.pages.length, 0)
  return `将把 ${picks.length} 份材料、共 ${pages} 页的页面图片发往${SERVER_WORD.prep}识别。识别在后台进行，完成后会通知你。`
}

/** 生成 / 更新 wiki 的确认文字：6000D，勾选 395 抽取时另写 395；材料数与合计量取自材料列表。 */
export function wikiConfirmText(materials: readonly Material[], usePrep: boolean, update: boolean): string {
  const readable = materials.filter((m) => m.status !== 'failed')
  const amount = sumUnits(readable.map((m) => ({ unit: m.unit, count: m.unit_count })))
  const action = update ? '更新案件 wiki' : '生成案件 wiki'
  const servers = usePrep ? `${SERVER_WORD.llm}，其中字段抽取和材料分类发往${SERVER_WORD.prep}` : SERVER_WORD.llm
  return `${action}：将把 ${readable.length} 份材料（共 ${amount}）的文字发往${servers}。`
}

/** 页码列表压成"3-6、9"。 */
export function pageRanges(pages: readonly number[]): string {
  const s = [...new Set(pages)].sort((a, b) => a - b)
  const out: string[] = []
  for (let i = 0; i < s.length; i++) {
    let j = i
    while (j + 1 < s.length && s[j + 1] === s[j]! + 1) j++
    out.push(i === j ? `${s[i]}` : `${s[i]}-${s[j]}`)
    i = j
  }
  return out.join('、')
}

/** 解析律师输入的页码范围"1-3, 5、7"；超出 1..max 或写法不对返回 undefined。 */
export function parsePageRanges(text: string, max: number): number[] | undefined {
  const pages = new Set<number>()
  for (const part of text.split(/[,，、\s]+/).filter(Boolean)) {
    const m = /^(\d+)(?:\s*[-–~至]\s*(\d+))?$/.exec(part)
    if (!m) return undefined
    const a = Number(m[1]); const b = m[2] === undefined ? a : Number(m[2])
    if (a < 1 || b < a || b > max) return undefined
    for (let p = a; p <= b; p++) pages.add(p)
  }
  return pages.size ? [...pages].sort((x, y) => x - y) : undefined
}

/** 契约的错误码 → 律师看的补充说明（主提示用服务给的中文 message，这里只补"下一步怎么办"）。 */
export const ERROR_HINT: Record<string, string> = {
  CASE_ROOT_IS_LINK: '请选择真实的文件夹，不要选快捷方式或链接。',
  CASE_IN_SYNC_FOLDER: '请把案件放在本机不同步的文件夹里。',
  CASE_NOT_FOUND: '请回到首页重新打开案件。',
  SERVER_UNREACHABLE: '请检查网络；在所外时确认已连上律所网络。',
  PREP_UNAVAILABLE: '识别服务器暂时不可用，稍后再试。',
  KEY_INVALID: '请到设置里检查个人 Key。',
  SERVICE_UNAVAILABLE: '工作台服务正在启动或已停止，稍后再试。',
  OFFICE_DIR_NOT_SET: '请到设置的"律师工作台"里指定日常办公文件夹。',
  ENGINE_BUSY: '发票整理正在进行中，请等它结束后再操作。',
  ENGINE_FAILED: '请稍后再试；多次出现请联系技术支持。',
}

/** 给律师看的提示：没有中文的（如 DSH 网关的英文技术信息）一律换成通用中文提示（返修 P3-2，Spec U-1）。 */
export const GENERIC_ERROR = '工作台服务暂时连不上，请稍后重试；多次出现请联系技术支持'
export function lawyerMessage(message: string | undefined | null): string {
  return message && /[一-鿿]/.test(message) ? message : GENERIC_ERROR
}

/** Host 说出了服务没起来的原因（"本机服务未能启动：…"）：原因已含做法，不再接"正在启动或已停止，稍后再试"。 */
export const START_FAILED = /^本机服务未能启动：/

export function errorText(e: { code: string; message: string }): string {
  const hint = ERROR_HINT[e.code]
  const msg = lawyerMessage(e.message)
  return hint && !START_FAILED.test(msg) ? `${msg} ${hint}` : msg
}

/**
 * 输入区状态行用的错误文字：说明和原文说的是同一件事时只留一句（T13 返修小项③，原来显示成
 * "工作台服务未启动，请稍后重试 工作台服务正在启动或已停止，稍后再试。"）。原文是通用提示时用说明；
 * 原文和说明都只是叫人稍后再试时用原文；说明另有做法（如"请回到首页重新打开案件"）时照旧接在后面。
 */
export function statusErrorText(e: { code: string; message: string }): string {
  const msg = lawyerMessage(e.message)
  const hint = ERROR_HINT[e.code]
  if (!hint || START_FAILED.test(msg)) return msg
  if (msg === GENERIC_ERROR) return hint
  if (/稍后/.test(msg) && /稍后/.test(hint)) return msg
  return `${msg} ${hint}`
}

/**
 * 出处文本（契约 citation_text：〔材料名 位置、材料名 位置〕）拆成可点的几处，材料名按材料列表换成编号。
 * 〔未找到依据〕〔推断〕和列表里找不到的材料不给编号（界面只显示文字，不可点）。
 */
export function citationTargets(citation: string, materials: ReadonlyArray<{ material_id: string; name: string }>): Array<{ text: string; material_id?: string; citation: string }> {
  const inner = /^〔(.*)〕$/.exec(citation.trim())?.[1]
  if (!inner || inner === '未找到依据' || inner === '推断') return [{ text: citation, citation }]
  return inner.split('、').map((part) => {
    const name = part.slice(0, part.indexOf(' '))
    const m = materials.find((x) => x.name === name)
    return { text: part, material_id: m?.material_id, citation: `〔${part}〕` }
  })
}

/** wiki 整理结束时是否发"整理任务已完成"：只在被观察的那个任务状态为 completed 时（被停止、失败、读不到都不发）。 */
export function shouldNotifyWikiDone(watchedId: string | null, tasks: ReadonlyArray<{ task_id: string; status: string }> | undefined): boolean {
  if (!watchedId || !tasks) return false
  return tasks.find((t) => t.task_id === watchedId)?.status === 'completed'
}

/** 覆盖清单（契约 1.2 tasks_list.coverage；按实际读取记录算，不采信模型自报）。 */
export interface Coverage {
  total: number
  fully_read: string[]
  partially_read: Array<{ name: string; read_units: number; total_units: number }>
  not_read: string[]
  unreadable: Array<{ name: string; reason: string }>
}

/** "没读全的材料"一行：没读全的三类都要让律师看见（执行令 1134 第 1 条）。null 为服务还没算（尚未统计）。 */
export function coverageLines(c: Coverage | null): { ok: boolean; summary: string; lines: string[] } {
  if (!c) return { ok: false, summary: '尚未统计', lines: [] }
  const lines = [
    ...c.partially_read.map((x) => `${x.name}：只读了 ${x.read_units} / ${x.total_units}`),
    ...c.not_read.map((x) => `${x}：没有读`),
    ...c.unreadable.map((x) => `${x.name}：读不了（${x.reason}）`),
  ]
  if (!lines.length && c.total === 0) return { ok: false, summary: '本任务没有列入材料', lines }
  if (!lines.length) return { ok: true, summary: `本任务范围内 ${c.total} 份材料都读全了`, lines }
  return { ok: false, summary: `本任务范围内 ${c.total} 份材料，${lines.length} 份没读全`, lines }
}

/** 出处核对结果（契约 1.2 tasks_list.citation_check；界面叫"数值与出处位置核对"）。 */
export interface CitationCheck {
  passed: boolean
  problems: Array<{ class: string; severity: 'must_fix' | 'hint'; excerpt: string; citation?: string | null; message: string }>
  stats: { citations: number; must_fix: number; hints: number }
}

/** "自检结果"一行：null 时显示"尚未核对"（T10 接入前），不显示"通过"。 */
export function citationSummary(c: CitationCheck | null): { tone: 'ok' | 'err' | 'faint'; summary: string; lines: string[] } {
  if (!c) return { tone: 'faint', summary: '尚未核对', lines: [] }
  const lines = c.problems.map((p) => `${p.severity === 'must_fix' ? '必须修改' : '提示'}：${p.excerpt}——${p.message}`)
  const hints = c.stats.hints ? `，另有 ${c.stats.hints} 条提示` : ''
  if (c.passed) return { tone: 'ok', summary: `没有必须修改的问题（核对了 ${c.stats.citations} 处出处${hints}）`, lines }
  return { tone: 'err', summary: `有 ${c.stats.must_fix} 处必须修改（核对了 ${c.stats.citations} 处出处${hints}）`, lines }
}
