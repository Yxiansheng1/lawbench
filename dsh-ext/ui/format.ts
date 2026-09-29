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
}

export function errorText(e: { code: string; message: string }): string {
  const hint = ERROR_HINT[e.code]
  return hint ? `${e.message} ${hint}` : e.message
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
