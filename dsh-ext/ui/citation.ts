// 草稿正文里的出处（T13 后续项"点出处打开原文"）的纯逻辑：识别、拆出每一处、核对后打开。
// T17 第二步 P-16 起，出处由 DSH 的 Markdown 渲染画成真按钮（ui-chat 的 chatInlineMarks 服务，我方只给正则、每处的范围和打开函数），
// 原来在 document 捕获阶段做命中测试的 citation-click.ts 撤掉。
// 出处写法以契约为准（contracts\common.schema.json 的 citation_text，formats.md 第 3 节），不另写更宽的规则；
// tests\citation.spec.ts 守着下面的 CITATION_PATTERN 与契约逐字一致。
// 出处文字来自模型的回答，当成不可信的输入：只拿去和材料列表比对，不拼进路径、不当成标记渲染。

/** 契约 citation_text 的 pattern 原文（带 ^…$）。 */
export const CITATION_PATTERN =
  '^〔(未找到依据|推断|[^〔〕、 ]+ (第[0-9]+(-[0-9]+)?[页段行]|[^〔〕、!]+![A-Z]{1,3}[0-9]+(:[A-Z]{1,3}[0-9]+)?)(、[^〔〕、 ]+ (第[0-9]+(-[0-9]+)?[页段行]|[^〔〕、!]+![A-Z]{1,3}[0-9]+(:[A-Z]{1,3}[0-9]+)?))*)〕$'

/** 在一段文字里找出处用的正则：契约 pattern 去掉首尾锚点。 */
export const citationScanner = (): RegExp => new RegExp(CITATION_PATTERN.slice(1, -1), 'g')

const FIXED = new Set(['未找到依据', '推断'])

export interface CitationItem {
  /** 这一处的原文，如"借款合同 第2页"。 */
  text: string
  name: string
  /** 位置部分，如"第2页"或"流水!B12"。 */
  loc: string
}

/**
 * 一个出处括号（契约写法的整段匹配，如"〔借款合同 第2页、流水!B12〕"）里每一处的起止（相对这段匹配）。
 * 〔未找到依据〕〔推断〕不是出处，返回空（不成按钮）。
 */
export function citationItemRanges(match: string): Array<[number, number]> {
  const inner = match.slice(1, -1)
  if (FIXED.has(inner)) return []
  const out: Array<[number, number]> = []
  let at = 1
  for (const part of inner.split('、')) {
    out.push([at, at + part.length])
    at += part.length + 1
  }
  return out
}

/** 一处出处的原文（如"借款合同 第2页"）拆成材料名和位置。 */
export function citationItem(text: string): CitationItem {
  const sp = text.indexOf(' ')
  return { text, name: text.slice(0, sp), loc: text.slice(sp + 1) }
}

export interface MaterialLite { material_id: string; name: string; unit: 'page' | 'para' | 'cell' | 'line'; unit_count: number; status: string }

const UNIT_OF: Record<string, MaterialLite['unit']> = { 页: 'page', 段: 'para', 行: 'line' }

/**
 * 按材料列表核对这一处出处。通过返回材料；不通过返回给律师看的中文说明（不打开，也不去猜别的材料）。
 */
export function resolveCitation(item: CitationItem, materials: readonly MaterialLite[]): { ok: true; material: MaterialLite } | { ok: false; message: string } {
  const same = materials.filter((m) => m.name === item.name)
  if (same.length === 0) return { ok: false, message: `本案材料里没有"${item.name}"，没法打开这处出处（可能材料改了名或出处写错了）。` }
  if (same.length > 1) return { ok: false, message: `本案有 ${same.length} 份材料都叫"${item.name}"，分不清是哪一份，没有打开。` }
  const m = same[0]!
  if (m.unit_count === 0) return { ok: false, message: `"${item.name}"没有可读的内容（可能解析失败），没法打开这处出处。` }
  const range = /^第([0-9]+)(?:-([0-9]+))?([页段行])$/.exec(item.loc)
  if (range) {
    const unit = UNIT_OF[range[3]!]!
    const from = Number(range[1]); const to = range[2] === undefined ? from : Number(range[2])
    if (unit !== m.unit) return { ok: false, message: `"${item.name}"按${{ page: '页', para: '段', line: '行', cell: '单元格' }[m.unit]}定位，出处写的是"${item.loc}"，对不上，没有打开。` }
    if (from < 1 || to < from || to > m.unit_count) return { ok: false, message: `"${item.name}"只有 ${m.unit_count} ${range[3]}，出处写的是"${item.loc}"，超出范围，没有打开。` }
  } else if (m.unit !== 'cell') {
    return { ok: false, message: `"${item.name}"不是表格，出处写的是"${item.loc}"，对不上，没有打开。` }
  }
  if (m.status === 'source_deleted') return { ok: false, message: `"${item.name}"的原件已经删除，没法打开原文。` }
  return { ok: true, material: m }
}

export interface OpenDeps {
  caseId(): string | undefined
  materials(caseId: string): Promise<MaterialLite[] | undefined>
  notice(title: string, text: string): void
  openSource(materialId: string, citation: string): void
}

/** 核对后打开原文；任何不通过都给中文提示，不静默、不打开（返修 B1：抽出来以便测试）。 */
export async function openCitation(item: CitationItem, deps: OpenDeps): Promise<void> {
  const caseId = deps.caseId()
  if (!caseId) { deps.notice('没有打开原文', '这个会话不在已打开的案件里。请从首页打开案件后再点出处。'); return }
  const ms = await deps.materials(caseId)
  if (!ms) { deps.notice('没有打开原文', '读不到本案材料列表，请稍后重试。'); return }
  if (deps.caseId() !== caseId) return // 读列表期间换了案件：这份列表和出处都属于原来的案件，不打开
  const v = resolveCitation(item, ms)
  if (!v.ok) { deps.notice('没有打开原文', v.message); return }
  deps.openSource(v.material.material_id, `〔${item.text}〕`)
}

/** 登记给 DSH 的出处标记（ui-chat 的 chatInlineMarks，P-16）：只给正则、每处的范围、读屏标签和打开函数，不给 HTML。 */
export interface CitationMark {
  pattern: RegExp
  ranges(match: string): Array<[number, number]>
  label(text: string): string
  open(text: string): void
}

/** 出处标记：点按钮（或 Tab 到后按 Enter）核对后打开原文，核对不过给中文提示。 */
export function citationMark(deps: OpenDeps): CitationMark {
  return {
    pattern: citationScanner(),
    ranges: citationItemRanges,
    label: (text) => `打开原文：${text}`,
    open: (text) => { void openCitation(citationItem(text), deps) },
  }
}

/** MarkdownText 的 inlineMarks 一段文字拆出的片段：原文或可点的出处。 */
export type InlinePart = string | { text: string; label: string; open: () => void }

/**
 * 我方自己用 DSH 的 MarkdownText 画文字时（对话区的草稿，T14 派修 2）给它的出处拆分：
 * 与 ui-chat 的 buildInlineMarks 同一算法，只一种标记（出处）。
 */
export function citationInlineMarks(deps: OpenDeps): { split(value: string): InlinePart[] | undefined } {
  const mark = citationMark(deps)
  return {
    split(value) {
      const spans: Array<{ start: number; end: number }> = []
      for (const m of value.matchAll(citationScanner())) {
        for (const [from, to] of mark.ranges(m[0])) spans.push({ start: m.index + from, end: m.index + to })
      }
      if (spans.length === 0) return undefined
      const out: InlinePart[] = []
      let at = 0
      for (const s of spans) {
        if (s.start > at) out.push(value.slice(at, s.start))
        const text = value.slice(s.start, s.end)
        out.push({ text, label: mark.label(text), open: () => mark.open(text) })
        at = s.end
      }
      if (at < value.length) out.push(value.slice(at))
      return out
    },
  }
}
