// 处理前估算（令 2043 第 4 条，律师第一批反馈"没读全要提前知道"）：选定一项 Skill（写任务单）之前，按案件材料的篇幅估一次能读全多少份；
// 超过一次能读全的量就先问"材料较长……"，可以"仍然开始"。不改"没读全的材料"事后提示。
// 契约里材料只有页数类字段（materials_list 的 unit / unit_count），没有字数，所以按"折合页数"估。
import { call, confirm, type CaseRef } from './state.ts'
import type { Material } from './format.ts'

/**
 * 一次能读全的量：**100 页或 11 份，先到者触发**（注记 2156、令 2203 第 5 条；线 B evidence\T18\read-capacity.md：
 * 16 次预算 ≈ 11 次读取 × 7000 字 ≈ 7.7 万字、最多 11 份；按页估误差大）。契约 1.4 加 chars 后改按字数。
 * 改这一处即可；ESTIMATE_OFF 为 true 时整项不问。
 */
export const READ_BUDGET_PAGES = 100
export const READ_BUDGET_FILES = 11
export const ESTIMATE_OFF = false

/** 不同单位折合成页（占位比例，随阈值一起由线 B 的实测校准）：段 10 段一页，行 40 行一页，工作表一张算 2 页。 */
export const PAGE_EQUIV: Record<string, number> = { page: 1, para: 0.1, line: 0.025, cell: 2 }

export interface Estimate { total: number; fit: number; pages: number; over: boolean }

/** 估一次能读全几份：从小到大装，页数超额度或份数到上限即停（能读全的份数取最乐观的估计，且不超过份数上限）。 */
export function estimateCoverage(materials: ReadonlyArray<Pick<Material, 'unit' | 'unit_count'>>, budget = READ_BUDGET_PAGES, maxFiles = READ_BUDGET_FILES): Estimate {
  const sizes = materials.map((m) => Math.max(0, m.unit_count) * (PAGE_EQUIV[m.unit] ?? 1)).sort((a, b) => a - b)
  const pages = sizes.reduce((a, b) => a + b, 0)
  let used = 0
  let fit = 0
  for (const s of sizes) { if (fit >= maxFiles || used + s > budget) break; used += s; fit++ }
  return { total: sizes.length, fit, pages: Math.round(pages), over: pages > budget || sizes.length > maxFiles }
}

export const ESTIMATE_TITLE = '材料较长'
export const estimateText = (e: Estimate): string =>
  `按案件全部材料估：共 ${e.total} 份、约 ${e.pages} 页，一次读不全，预计能读全约 ${e.fit} 份 / 共 ${e.total} 份。建议拆分、分批，或缩小范围（只导入这次要用的材料）。没读全的会在成果里列出。`
export const ESTIMATE_OK = '仍然开始'

/**
 * 选 Skill 之前问一次（超过额度才问）。读不到材料列表时不拦。
 * @returns 继续为 true，律师选了取消为 false。
 */
export async function confirmScope(c: CaseRef | undefined): Promise<boolean> {
  if (ESTIMATE_OFF || !c) return true
  const r = await call<{ materials: Material[] }>('materialsList', { case_id: c.case_id })
  if (!r.ok) return true
  const e = estimateCoverage(r.value.materials)
  if (!e.over) return true
  return confirm(ESTIMATE_TITLE, estimateText(e), ESTIMATE_OK)
}
