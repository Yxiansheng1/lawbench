// 草稿正文里的出处（T13 后续项"点出处打开原文"，主编排 06:34 注记裁决走 A）的纯逻辑：识别、定位到点中的那一处、核对。
// 出处写法以契约为准（contracts\common.schema.json 的 citation_text，formats.md 第 3 节），不另写更宽的规则；
// tests\citation.spec.ts 守着下面的 CITATION_PATTERN 与契约逐字一致。
// 出处文字来自模型的回答，当成不可信的输入：只拿去和材料列表比对，不拼进路径、不当成标记渲染。

/** DSH 对话区给每个节点标的属性和助手回答节点的取值（ui-chat/src/client/chat/ChatNodeSeat.tsx、register-node-renderers.ts）。 */
export const DSH_FLOW_ATTR = 'data-chat-flow-kind'
export const DSH_ASSISTANT_KIND = 'assistant-step'

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

export type Hit =
  | { kind: 'none' }
  /** 〔未找到依据〕〔推断〕：不是出处，点了不反应。 */
  | { kind: 'fixed' }
  | { kind: 'item'; item: CitationItem; start: number; end: number }

/**
 * 点在 text 的第 offset 个字符上时，点中的是哪一处出处。
 * 一个括号里多处（顿号分隔）时点到哪一处算哪一处；点在括号或顿号上分不清时算第一处。
 */
export function citationAt(text: string, offset: number): Hit {
  for (const m of text.matchAll(citationScanner())) {
    const start = m.index!
    const end = start + m[0].length
    if (offset < start || offset >= end) continue
    const inner = m[0].slice(1, -1)
    if (FIXED.has(inner)) return { kind: 'fixed' }
    const parts = inner.split('、')
    let pos = start + 1
    let chosen = 0
    for (let i = 0; i < parts.length; i++) {
      const pStart = pos
      const pEnd = pos + parts[i]!.length
      if (offset >= pStart && offset < pEnd) { chosen = i; break }
      pos = pEnd + 1
    }
    const part = parts[chosen]!
    const sp = part.indexOf(' ')
    return { kind: 'item', item: { text: part, name: part.slice(0, sp), loc: part.slice(sp + 1) }, start, end }
  }
  return { kind: 'none' }
}

/** 全部出处在 text 里的起止（给下划线用），不含〔未找到依据〕〔推断〕。 */
export function citationRanges(text: string): Array<[number, number]> {
  const out: Array<[number, number]> = []
  for (const m of text.matchAll(citationScanner())) {
    if (!FIXED.has(m[0].slice(1, -1))) out.push([m.index!, m.index! + m[0].length])
  }
  return out
}

/** 多个文字节点拼成的整段里，第 index 个节点的第 offset 个字符在整段中的位置（出处跨加粗等行内元素时用）。 */
export function joinedOffset(segments: readonly string[], index: number, offset: number): number {
  let n = 0
  for (let i = 0; i < index; i++) n += segments[i]!.length
  return n + offset
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

/** 一次点击的情形（从 DOM 取出，交给 shouldHandleClick 判断；返修 B1：判断抽成纯函数以便测试）。 */
export interface ClickFacts {
  button: number
  modifier: boolean
  /** 点击目标在 DSH 的助手回答块（`[data-chat-flow-kind="assistant-step"]`）里。 */
  inAnswer: boolean
  /** 点击目标在链接、按钮、代码、输入框等里（这些各有各的用途）。 */
  inSkipped: boolean
  /** 当前选区是折叠的（没在选文字）。 */
  selectionCollapsed: boolean
  /** 连击次数（MouseEvent.detail）：双击、三击选字时第二下起不接手（返修 B2）。 */
  detail: number
}

/** 这次点击要不要接手去认出处：只看回答块里、不在跳过的元素里、没在选文字、左键、不带修饰键、不是连击的后几下。 */
export function shouldHandleClick(f: ClickFacts): boolean {
  return f.button === 0 && !f.modifier && f.inAnswer && !f.inSkipped && f.selectionCollapsed && f.detail <= 1
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
