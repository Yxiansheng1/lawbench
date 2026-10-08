// 案件：打开 / 新建（/api/case/open）、最近案件（/api/case/recent）、导入（/api/materials/import）。
// 打开案件后把案件文件夹当 DSH 工作区打开（Spec 1.2"案件 = DSH 的工作区"），会话的工作目录即案件文件夹。
import { app, askFolders, call, caseForRoot, confirm, currentCase, folderName, notice, samePath, pushDialog, rememberCase, type CaseRef } from './state.ts'
import { folderRels, type CaseKind, type FolderChoice } from '../shared/case-folders.ts'
import { getNav } from './kit.tsx'
import { errorText } from './format.ts'

// 令 1321 D.1：右栏不再有"成果"标签（成果在聊天里的卡片和案件概览卡）
export const TABS = { materials: 'lawbench-materials', source: 'lawbench-source' } as const

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
    // 还没做首次配置：配置要等律师填完，不必每 3 秒问一次，按慢节奏等（令 2033）
    const notConfigured = !r.ok && r.error.code === 'NOT_CONFIGURED'
    await wait(i < DAILY_FAST_TRIES && !notConfigured ? DAILY_EVERY_MS : DAILY_SLOW_MS)
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
 * 登记并打开案件：选目录（或用给定路径）→（新建时）问要建哪些子文件夹 → /api/case/open → 按勾选补建子文件夹 → 打开工作区。
 * @param template - 新建案件的类型（民商事 civil / 刑事 criminal），决定子文件夹列表；打开已有案件为 null（不问）。
 * @param navigate - 登记后是否转到该案件的会话（在会话里"作为案件打开"时不转）。
 * @param offerLocal - 在云同步目录里被拒时是否提议"为我在本机建一个文件夹"；打开本机建好的文件夹时为 false（只给一次）。
 * @param picked - 已经选好的子文件夹（换到本机文件夹再开时沿用，不再问）。
 */
export async function openCase(path: string | null, template: CaseKind | null, navigate = true, offerLocal = true, picked?: FolderChoice): Promise<CaseRef | undefined> {
  const nav = getNav()
  const dir = path ?? await nav.pickDirectory()
  if (!dir) return undefined
  // 令 1852 第 17 条：新建时子文件夹由律师勾（默认全不勾），取消即不新建
  const choice = template ? picked ?? await askFolders(folderName(dir) || '新案件', template) : undefined
  if (template && !choice) return undefined
  // 契约 case_open 的 template 只能整套建：一律传 null（服务只建 工作区/、成果/），勾的由 Host 补建（交回件说明，候契约 1.4）
  const r = await call<{ case_id: string; name: string; created: boolean; folders_created: string[] }>('caseOpen', { path: dir, template: null })
  if (!r.ok && r.error.code === 'CASE_IN_SYNC_FOLDER') {
    if (offerLocal) return offerLocalFolder(dir, template, navigate, choice ?? undefined)
    const name = folderName(dir)
    notice(syncWordIn(name) ? SYNC_NAME_TITLE : '没能打开案件', syncWordIn(name) ? syncNameText(name) : errorText(r.error))
    return undefined
  }
  if (!r.ok) { notice('没能打开案件', errorText(r.error)); return undefined }
  const c: CaseRef = { case_id: r.value.case_id, name: folderName(dir) || r.value.name, root: dir, exists: true }
  // 同一案件（case_id 相同）原来登记在别的位置：文件夹改名或搬走后在新位置重新打开（令 1515 第 3 条）。
  // 服务的登记已替换成新位置；界面这边也只留新的一条，打开后把侧栏里旧位置那一项移除
  const prev = app.get().cases.find((x) => x.case_id === c.case_id && !samePath(x.root, dir))
  rememberCase(c)
  if (template && choice) await makeFolders(c, template, choice)
  if (navigate) {
    const opened = await nav.openCaseWorkspace(dir)
    if (prev) await nav.forgetCaseWorkspace?.(prev.root, opened || undefined).catch(() => undefined)
    // 令 1347 第 3 条、令 1321 D.1：开好"原文查看""材料"，停在"材料"，右栏收起（顶部按钮展开）
    nav.seedTabs?.()
  }
  return c
}

export const SYNC_TITLE = '这个文件夹会被云盘同步'
export const syncText = (name: string): string =>
  `案件材料不能放在 OneDrive 等会自动上传的文件夹里（Windows 11 默认会同步"文档"和"桌面"）。可以在这台电脑上为你建一个不同步的文件夹"连越律师工作台\\${name}"（在你的用户文件夹下），以后就在那里办这个案件。原来文件夹里的材料不会自动搬过去，需要的话打开后点"导入文件夹"。`
export const SYNC_OK = '为我在本机建一个文件夹'

/**
 * 案件文件夹在云同步目录里被拒（SEC-14 不变）时（令 2043 第 3 条）：说明原因，问要不要在 <用户目录>\连越律师工作台\<案件名> 建一个本机文件夹，
 * 要就建好并以它继续（同样的新建 / 打开方式）。
 */
async function offerLocalFolder(dir: string, template: CaseKind | null, navigate: boolean, picked: FolderChoice | undefined): Promise<CaseRef | undefined> {
  const name = folderName(dir) || '新案件'
  // 复核 AMEND P2-4：名字里就含同步软件的名字时，本机新建的同名文件夹照样被拒（SEC-14 按子串匹配），不给"为我建"，直接说清楚
  if (syncWordIn(name)) { notice(SYNC_NAME_TITLE, syncNameText(name)); return undefined }
  if (!await confirm(SYNC_TITLE, syncText(name), SYNC_OK)) return undefined
  const made = await call<{ path: string }>('localCaseFolder', { name })
  if (!made.ok) { notice('没能建好本机文件夹', errorText(made.error)); return undefined }
  // 只给一次：本机文件夹仍被拒时只说明、不再提议（否则每确认一次多一个空的"(n)"文件夹）
  // 注记 0934 ③：不再用模块级开关，按参数传（并发打开两个案件时互不影响）
  return openCase(made.value.path, template, navigate, false, picked)
}

/** 按律师勾的建子文件夹（经 Host，只补缺）；一个没勾就不问 Host。建了的列出来，建不成的说明。 */
async function makeFolders(c: CaseRef, template: CaseKind, choice: FolderChoice): Promise<void> {
  if (folderRels(template, choice).length === 0) return
  const r = await call<{ folders_created: string[] }>('caseFolders', { case_id: c.case_id, root: c.root, kind: template, tops: choice.tops, custom: choice.custom })
  if (!r.ok) { notice('子文件夹没能建好', `案件已经建好，子文件夹没有建（${errorText(r.error)}）。可以在资源管理器里自己建。`); return }
  if (r.value.folders_created.length) notice('已建好子文件夹', `在"${c.name}"里新建了 ${r.value.folders_created.length} 个子文件夹。`, r.value.folders_created)
}

/** SEC-14 按名字子串拒绝的同步软件名（Spec 4.2 的列表，服务端以配置为准；这里只用来选说法）。 */
export const SYNC_NAME_WORDS = ['OneDrive', '坚果云', 'Nutstore', 'BaiduNetdisk', '百度网盘', 'Dropbox', 'Google Drive', 'iCloudDrive', 'WPS云盘']
export const syncWordIn = (name: string): string | undefined => SYNC_NAME_WORDS.find((w) => name.toLowerCase().includes(w.toLowerCase()))
export const SYNC_NAME_TITLE = '文件夹名字里有同步软件的名字'
export const syncNameText = (name: string): string =>
  `"${name}"里含有"${syncWordIn(name) ?? '同步软件的名字'}"，程序会把它当成云盘文件夹拒绝（不管它实际在哪）。请给文件夹换个不含这些字的名字，再打开或新建。`

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
