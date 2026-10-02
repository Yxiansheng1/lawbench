// 案件：打开 / 新建（/api/case/open）、最近案件（/api/case/recent）、导入（/api/materials/import）。
// 打开案件后把案件文件夹当 DSH 工作区打开（Spec 1.2"案件 = DSH 的工作区"），会话的工作目录即案件文件夹。
import { app, call, caseForRoot, notice, pushDialog, rememberCase, type CaseRef } from './state.ts'
import { getNav } from './kit.tsx'
import { errorText } from './format.ts'

export const TABS = { materials: 'lawbench-materials', results: 'lawbench-results', source: 'lawbench-source' } as const

/** 默认导入位置（U-12、F-MAT-02a）。 */
export const DEFAULT_TARGET = '02案件材料'

export async function loadRecent(): Promise<CaseRef[] | { code: string; message: string }> {
  const r = await call<{ cases: Array<{ case_id: string; name: string; root: string; exists: boolean }> }>('caseRecent', {})
  if (!r.ok) return r.error
  const cases = r.value.cases.map((c) => ({ case_id: c.case_id, name: c.name, root: c.root, exists: c.exists }))
  app.set((s) => {
    const known = new Map(s.cases.map((c) => [c.case_id, c]))
    for (const c of cases) known.set(c.case_id, c)
    return { ...s, cases: [...known.values()] }
  })
  return cases
}

/**
 * 登记并打开案件：选目录（或用给定路径）→ /api/case/open → 打开工作区。
 * @param template - 新建案件时的标准目录（民商事 civil / 刑事 criminal）；打开已有案件为 null。
 * @param navigate - 登记后是否转到该案件的会话（在会话里"作为案件打开"时不转）。
 */
export async function openCase(path: string | null, template: 'civil' | 'criminal' | null, navigate = true): Promise<CaseRef | undefined> {
  const nav = getNav()
  const dir = path ?? await nav.pickDirectory()
  if (!dir) return undefined
  const r = await call<{ case_id: string; name: string; created: boolean; folders_created: string[] }>('caseOpen', { path: dir, template })
  if (!r.ok) { notice('没能打开案件', errorText(r.error)); return undefined }
  const c: CaseRef = { case_id: r.value.case_id, name: r.value.name, root: dir, exists: true }
  rememberCase(c)
  if (r.value.folders_created.length) notice('已建好标准目录', `在"${c.name}"里新建了 ${r.value.folders_created.length} 个子文件夹。`, r.value.folders_created)
  if (navigate) {
    await nav.openCaseWorkspace(dir)
    nav.openTab(TABS.materials)
  }
  return c
}

/** 有打开的案件就用它，否则先让律师选择或新建（F-ENT-01）。 */
export function withCase(current: CaseRef | undefined, then: (c: CaseRef) => void): void {
  if (current) then(current)
  else pushDialog({ kind: 'casePick', then })
}

/** 拖入、选择的文件交给导入确认框（U-12）；没有本机路径的（粘贴的内容）由调用方另走粘贴导入。 */
export function startImport(caseRef: CaseRef, paths: string[], from: string): void {
  const clean = [...new Set(paths.filter(Boolean))]
  if (!clean.length) { notice('没有可导入的文件', '拖入或选择的内容没有本机路径。粘贴的截图请直接粘贴到对话框。'); return }
  pushDialog({ kind: 'import', caseRef, paths: clean, from })
}

export interface ImportResult {
  copied: Array<{ from: string; to: string }>
  skipped: Array<{ path: string; reason: string }>
  scan: { added: number; changed: number; removed: number; failed: number; review_needed: boolean }
}

export async function runImport(caseRef: CaseRef, paths: string[], target: string, unzip: boolean): Promise<void> {
  const r = await call<ImportResult>('materialsImport', { case_id: caseRef.case_id, paths, target, unzip })
  if (!r.ok) { notice('导入没有完成', errorText(r.error)); return }
  const v = r.value
  const lines = [
    ...v.copied.map((c) => `已复制：${c.to}`),
    ...v.skipped.map((s) => `已跳过：${s.path}（${s.reason}）`),
  ]
  const summary = `复制 ${v.copied.length} 个，跳过 ${v.skipped.length} 个；解析：新增 ${v.scan.added}、变化 ${v.scan.changed}、移除 ${v.scan.removed}、失败 ${v.scan.failed}。`
    + (v.scan.review_needed ? '材料有变化，案件 wiki 和已有成果需要复核。' : '')
  notice('导入结果', summary, lines)
  window.dispatchEvent(new CustomEvent('lawbench:materials-changed', { detail: caseRef.case_id }))
}

export { caseForRoot }
