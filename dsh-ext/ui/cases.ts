// 案件：打开 / 新建（/api/case/open）、最近案件（/api/case/recent）、导入（/api/materials/import）。
// 打开案件后把案件文件夹当 DSH 工作区打开（Spec 1.2"案件 = DSH 的工作区"），会话的工作目录即案件文件夹。
import { app, call, caseForRoot, currentCase, folderName, notice, samePath, pushDialog, rememberCase, type CaseRef } from './state.ts'
import { getNav } from './kit.tsx'
import { errorText } from './format.ts'

export const TABS = { materials: 'lawbench-materials', results: 'lawbench-results', source: 'lawbench-source' } as const

/** 默认导入位置（U-12、F-MAT-02a）。 */
export const DEFAULT_TARGET = '02案件材料'

/**
 * 启动时取"日常事务"：服务就绪前、首次配置做完前都取不到（主窗口在首次配置页之后才显示，但界面插件那时已经在跑）。
 * 前 30 秒每 2 秒一次，之后每 10 秒一次，取到为止。
 */
export const DAILY_FAST_TRIES = 15
export const DAILY_EVERY_MS = 2000
export const DAILY_SLOW_MS = 10_000
/** 会自己好的错误（服务还没就绪、首次配置没做完、超时）：接着取；别的（如在云同步文件夹里）停下并在侧栏说明（令 1347 P3-1）。 */
export const DAILY_RETRY_CODES: ReadonlySet<string> = new Set(['SERVICE_UNAVAILABLE', 'NOT_CONFIGURED', 'TIMEOUT', 'INTERNAL'])

/**
 * 纯聊天的默认工作区（执行令 1156 第 4 条，N70）：启动时向 Host 取"日常事务"（首次配置后第一次取时建好并登记），
 * 当前会话不在任何已登记案件里时打开它，空会话就落在这里；律师正在某个案件的会话里时不动。
 * @returns 打开了"日常事务"为 true。
 */
export async function landOnDailyCase(open: (root: string) => Promise<void>, wait = (ms: number) => new Promise<void>((res) => setTimeout(res, ms))): Promise<boolean> {
  for (let i = 0; ; i++) {
    const r = await call<{ root: string | null; created: boolean }>('dailyCase')
    if (!r.ok && !DAILY_RETRY_CODES.has(r.error.code)) {
      app.set((s) => ({ ...s, dailyError: r.error }))
      return false
    }
    if (r.ok) {
      if (!r.value.root) return false
      const root = r.value.root
      app.set((s) => ({ ...s, dailyRoot: root, dailyError: null }))
      // 记过位置时 Host 不问服务就返回；服务还没就绪时读不到案件列表，打开也会失败——读到了再往下（真机核过）
      const recent = await loadRecent()
      if (Array.isArray(recent)) {
        if (currentCase(app.get())) return false
        await open(r.value.root)
        return true
      }
    }
    await wait(i < DAILY_FAST_TRIES ? DAILY_EVERY_MS : DAILY_SLOW_MS)
  }
}

export async function loadRecent(): Promise<CaseRef[] | { code: string; message: string }> {
  const r = await call<{ cases: Array<{ case_id: string; name: string; root: string; exists: boolean; last_opened?: string }> }>('caseRecent', {})
  if (!r.ok) return r.error
  const cases = r.value.cases.map((c) => ({ case_id: c.case_id, name: folderName(c.root) || c.name, root: c.root, exists: c.exists, last_opened: c.last_opened }))
  // 同一案件换了位置（改名或搬走后在新位置重新打开，服务已替换登记）：侧栏里旧位置那一项一并移除（令 1515 第 3 条）
  const moved = cases.flatMap((c) => {
    const old = app.get().cases.find((x) => x.case_id === c.case_id)
    return old && !samePath(old.root, c.root) ? [old.root] : []
  })
  app.set((s) => {
    const known = new Map(s.cases.map((c) => [c.case_id, c]))
    for (const c of cases) known.set(c.case_id, c)
    return { ...s, cases: [...known.values()] }
  })
  for (const root of moved) { try { void getNav().forgetCaseWorkspace?.(root).catch(() => undefined) } catch { /* 界面还没准备好：下次再移除 */ } }
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
  const c: CaseRef = { case_id: r.value.case_id, name: folderName(dir) || r.value.name, root: dir, exists: true }
  // 同一案件（case_id 相同）原来登记在别的位置：文件夹改名或搬走后在新位置重新打开（令 1515 第 3 条）。
  // 服务的登记已替换成新位置；界面这边也只留新的一条，打开后把侧栏里旧位置那一项移除
  const prev = app.get().cases.find((x) => x.case_id === c.case_id && !samePath(x.root, dir))
  rememberCase(c)
  if (r.value.folders_created.length) notice('已建好标准目录', `在"${c.name}"里新建了 ${r.value.folders_created.length} 个子文件夹。`, r.value.folders_created)
  if (navigate) {
    const opened = await nav.openCaseWorkspace(dir)
    if (prev) await nav.forgetCaseWorkspace?.(prev.root, opened || undefined).catch(() => undefined)
    // 令 1347 第 3 条：右侧栏三个标签常显，停在"材料"（最后开的为当前）
    for (const kind of [TABS.results, TABS.source, TABS.materials]) nav.openTab(kind) // 同 rightbar.ts 的 RIGHTBAR_TABS
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
