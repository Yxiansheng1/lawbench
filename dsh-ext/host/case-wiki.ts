// 案件 wiki 合成一张卡（令 1852 第 18 条，第七版待办 18）：Host 读案件 wiki 的六个板块给界面显示。
// 工作台服务没有读 wiki 正文的接口（模型用的 case_read_wiki 是工具，不是 /api），Host 只读这几个文件：
// 工作区\wiki\case.json（案件卡片、生成时间、生成时的材料）、工作区\wiki\案件\{概览,当事人,时间线,材料清单,争议焦点}.md、
// 工作区\材料\index.json（此刻的材料，用来算生成后哪些材料新增、变化、移除）。路径、链接、出案件根的核对同 task-answer.ts。
// 只读不写；内容只回给界面，日志不记。
import { createHash } from 'node:crypto'
import { readInCase } from './task-answer.ts'

export const WIKI_DIR = '工作区/wiki'
/** 卡上的六个板块，顺序同律师说的（案件卡片在前）；rel 为 null 的没有可直接打开的文书文件（案件卡片是 case.json）。 */
export const WIKI_SECTIONS: ReadonlyArray<{ key: string; title: string; rel: string | null }> = [
  { key: 'card', title: '案件卡片', rel: null },
  { key: 'overview', title: '概览', rel: `${WIKI_DIR}/案件/概览.md` },
  { key: 'parties', title: '当事人', rel: `${WIKI_DIR}/案件/当事人.md` },
  { key: 'timeline', title: '时间线', rel: `${WIKI_DIR}/案件/时间线.md` },
  { key: 'inventory', title: '材料清单', rel: `${WIKI_DIR}/案件/材料清单.md` },
  { key: 'issues', title: '争议焦点', rel: `${WIKI_DIR}/案件/争议焦点.md` },
]
export const MAX_SECTION_BYTES = 512 * 1024

export interface WikiFact { text: string; citations: string[]; status: string }
export interface WikiSectionView { key: string; title: string; rel: string | null; text: string | null; truncated: boolean }
export interface CaseWiki {
  /** 有没有 wiki（case.json 和五篇文章都没有为 false）。 */
  exists: boolean
  generated_at: string | null
  sections: WikiSectionView[]
  /** 案件卡片的三组条目（case.json 读不到为 null）。 */
  card: { parties: WikiFact[]; issues: WikiFact[]; key_facts: WikiFact[] } | null
  /** 生成之后材料的变化（按 sha256 比；case.json 读不到或材料索引读不到为 null）。 */
  changes: { added: number; changed: number; removed: number } | null
  /** 这一版 wiki（生成时间）加此刻材料的指纹：律师点"核对完成"时记下它，指纹变了（重新生成或更新、材料变化）就又要复核；律师自己改文章不算。 */
  signature: string
}
type Result = { ok: true; value: CaseWiki } | { ok: false; error: { code: string; message: string } }

const facts = (v: unknown): WikiFact[] => (Array.isArray(v) ? v : [])
  .filter((f) => f && typeof f.text === 'string')
  .map((f) => ({ text: f.text as string, citations: Array.isArray(f.citations) ? f.citations.filter((c: unknown) => typeof c === 'string') : [], status: typeof f.status === 'string' ? f.status : '' }))

const shaMap = (v: unknown): Map<string, string> | null => {
  if (!Array.isArray(v)) return null
  const m = new Map<string, string>()
  // 契约 1.4：律师移除的材料在 index.json 里留着一条（status 为 removed，编号不复用），不算现有的材料
  for (const x of v) if (x && typeof x.material_id === 'string' && typeof x.sha256 === 'string' && x.status !== 'removed') m.set(x.material_id, x.sha256)
  return m
}

/**
 * 读某案件的 wiki。
 * @param root - 案件根（调用方已按服务登记核对过）。
 */
export function readCaseWiki(root: string): Result {
  let card: Record<string, unknown> | null = null
  const cardRaw = readInCase(root, `${WIKI_DIR}/case.json`, 4 * 1024 * 1024)
  if (cardRaw && !cardRaw.truncated) { try { card = JSON.parse(cardRaw.text) } catch { card = null } }
  let index: { materials?: unknown } | null = null
  const indexRaw = readInCase(root, '工作区/材料/index.json', 16 * 1024 * 1024)
  if (indexRaw && !indexRaw.truncated) { try { index = JSON.parse(indexRaw.text) } catch { index = null } }

  const sections: WikiSectionView[] = WIKI_SECTIONS.map((s) => {
    if (!s.rel) return { ...s, text: null, truncated: false }
    const r = readInCase(root, s.rel, MAX_SECTION_BYTES)
    return { ...s, text: r ? r.text : null, truncated: r?.truncated ?? false }
  })
  const generatedAt = typeof card?.generated_at === 'string' ? card.generated_at : null
  const atGen = shaMap(card?.materials_at_generation)
  const now = shaMap(index?.materials)
  let changes: CaseWiki['changes'] = null
  if (atGen && now && generatedAt) {
    let added = 0, changed = 0
    for (const [id, sha] of now) { const old = atGen.get(id); if (old === undefined) added++; else if (old !== sha) changed++ }
    changes = { added, changed, removed: [...atGen.keys()].filter((id) => !now.has(id)).length }
  }
  const h = createHash('sha256')
  h.update(String(generatedAt)).update('\n')
  for (const [id, sha] of [...(now ?? new Map<string, string>())].sort(([a], [b]) => (a < b ? -1 : 1))) h.update(`${id}:${sha}\n`)
  return {
    ok: true,
    value: {
      exists: card !== null || sections.some((s) => s.text !== null),
      generated_at: generatedAt,
      sections,
      card: card ? { parties: facts(card.parties), issues: facts(card.issues), key_facts: facts(card.key_facts) } : null,
      changes,
      signature: h.digest('hex').slice(0, 32),
    },
  }
}
