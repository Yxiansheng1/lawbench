// 首页空白处拖入文件夹 = 建案件（令 1422，第七版待办 20；用户 2026-10-10 定：用落点区分，建案件只有这一个拖入入口）。
// 拖到案件卡片、材料面板、对话框仍是"加进该案的材料"，不在这里。
// 建案件 = 拖进来的文件夹原地成为案件根：不复制、不挪动；case_open 一律 template=null，不弹子文件夹勾选框（律师的文件夹已有自己的结构）。
// 文件夹在云同步目录里（服务拒 CASE_IN_SYNC_FOLDER）：只给"复制到本机建案件"——在 <用户目录>\连越律师工作台\<文件夹名> 建案件，
// 再把原文件夹顶层各项经 /api/materials/import 复制到案件根（保持原来的结构）。
import { app, askNewCase, call, confirm, folderName, notice, samePath, type CaseRef } from './state.ts'
import { openCase, reportImport, SYNC_NAME_TITLE, syncNameText, syncWordIn, type ImportResult } from './cases.ts'
import { errorText } from './format.ts'
import { isDeviceName, RESERVED_TOPS } from '../shared/case-folders.ts'

/** Host dropInfo 回的一项（host\desk-actions.ts 的 DroppedItem）。 */
export interface DroppedItem { path: string; name: string; kind: 'dir' | 'file' | 'other'; has_case: boolean; children: string[] | null }

/** 确认框里选的类型。 */
export type DropKind = 'civil' | 'criminal' | 'daily'
export const DROP_KINDS: ReadonlyArray<{ kind: DropKind; label: string }> = [
  { kind: 'civil', label: '民商事' }, { kind: 'criminal', label: '刑事' }, { kind: 'daily', label: '日常事务' },
]

export const BLANK_HINT = '松开：建新案件'
export const cardHint = (caseName: string): string => `松开：加入 ${caseName} 的材料`
export const BLANK_IDLE = '把整理好的案子文件夹拖到空白处，可以直接建成案件。'
export const askTitle = (name: string): string => `把『${name}』建成案件？`
export const ASK_TEXT = '这个文件夹会原地成为案件：里面的文件不复制、不挪动，直接作为案件材料；工作台只在里面加"成果"等自用的文件夹。'
export const ASK_OK = '建成案件'
export const FILE_TITLE = '文件不能建成案件'
export const FILE_TEXT = '一个文件不能成为案件：请拖到某个案件卡片上，或先新建案件。'
export const NO_PATH_TEXT = '拖进来的内容没有本机路径，请从资源管理器里拖文件夹进来。'
export const OTHER_TITLE = '这一项不能建成案件'
export const OTHER_TEXT = '快捷方式、链接和网络位置上的文件夹不能建成案件，请拖本机上的文件夹本身。'
export const NAME_TITLE = '这个文件夹名不能当案件名'
export const ROOT_TEXT = '不能把整个盘当成案件。请拖盘里的某个文件夹进来。'
/** 盘根（D:\\）：不问，直接说明（否则先问"把『D:』建成案件？"再被服务拒，复核 rv-A55 顺手项）。 */
export const isDriveRoot = (path: string): boolean => /^[A-Za-z]:[\\/]*$/.test(path)
export const nameText = (name: string): string => `"${name}"是工作台或 Windows 自己要用的名字。请给文件夹换个名字，再拖进来。`
export const SYNC_DROP_TITLE = '这个文件夹在云同步目录里，不能直接当案件'
export const syncDropText = (name: string): string =>
  `案件材料不能放在 OneDrive、坚果云等会自动上传的文件夹里。可以在这台电脑上新建案件"连越律师工作台\\${name}"（在你的用户文件夹下），并把这个文件夹里的内容复制过去；原来的文件夹不动。`
export const SYNC_DROP_OK = '复制到本机建案件'

/** 文件夹名能不能当案件名：工作台自用的名字、Windows 设备名不行（同 safeFolderName 的口径）。 */
export const badCaseName = (name: string): boolean => name === '' || isDeviceName(name) || RESERVED_TOPS.some((r) => r.toLowerCase() === name.toLowerCase())

const KIND_KEY = (caseId: string) => `lawbench.caseKind.${caseId}`
/** 律师选的类型按案件记在本机（契约里没有存它的地方；目前只记下，候主编排定用处）。 */
export function recordKind(caseId: string, kind: DropKind): void {
  try { localStorage.setItem(KIND_KEY(caseId), kind) } catch { /* 记不下不影响建案件 */ }
}
export function readKind(caseId: string): DropKind | null {
  try { const v = localStorage.getItem(KIND_KEY(caseId)); return DROP_KINDS.some((k) => k.kind === v) ? v as DropKind : null } catch { return null }
}

/**
 * 首页空白处松手：文件夹逐个问、各建一案；文件不建，说明一次。
 * @param paths - 拖进来各项的本机路径（没有路径的已被调用方去掉）。
 * @returns 建成或打开的案件。
 */
export async function dropOnBlank(paths: string[]): Promise<CaseRef[]> {
  const clean = [...new Set(paths.filter(Boolean))]
  if (!clean.length) { notice(FILE_TITLE, NO_PATH_TEXT); return [] }
  const info = await call<{ items: DroppedItem[] }>('dropInfo', { paths: clean })
  if (!info.ok) { notice('没能建案件', errorText(info.error)); return [] }
  const dirs = info.value.items.filter((x) => x.kind === 'dir')
  // 第 4 条：文件不建案件（文件夹和文件混拖只处理文件夹），说明一次
  if (info.value.items.some((x) => x.kind === 'file')) notice(FILE_TITLE, FILE_TEXT)
  if (info.value.items.some((x) => x.kind === 'other')) notice(OTHER_TITLE, OTHER_TEXT)
  const made: CaseRef[] = []
  for (const [i, d] of dirs.entries()) {
    // 只有最后一个转到案件里；前面的建好留在首页列表
    // 一个出错不耽误后面的
    const c = await caseFromFolder(d, i === dirs.length - 1).catch(() => { notice('没能建案件', `"${d.name}"没有建成，请重试。`); return undefined })
    if (c) made.push(c)
  }
  return made
}

/** 一个文件夹建成案件（或已是案件就直接打开）。取消、被拒返回 undefined。 */
export async function caseFromFolder(d: DroppedItem, navigate: boolean): Promise<CaseRef | undefined> {
  // 第 6 条：已登记的、以前当过案件的直接打开，不问
  const known = app.get().cases.find((c) => samePath(c.root, d.path))
  if (known || d.has_case) return openCase(d.path, null, navigate, false)
  if (isDriveRoot(d.path)) { notice(OTHER_TITLE, ROOT_TEXT); return undefined }
  const name = d.name || folderName(d.path)
  if (badCaseName(name)) { notice(NAME_TITLE, nameText(name)); return undefined }
  const kind = await askNewCase(name)
  if (!kind) return undefined
  // 类型在登记成功时就记下（不等转到案件里）
  return openCase(d.path, null, navigate, false, undefined, { onSync: () => copyToLocal(d, name, navigate, kind), onOpened: (c) => recordKind(c.case_id, kind) })
}

/** 第 2 条：云同步目录里的文件夹，只给"复制到本机建案件"。 */
async function copyToLocal(d: DroppedItem, name: string, navigate: boolean, kind: DropKind): Promise<CaseRef | undefined> {
  // 名字里就含同步软件的名字时，本机新建的同名文件夹照样被拒（SEC-14 按子串匹配）：直接说清楚
  if (syncWordIn(name)) { notice(SYNC_NAME_TITLE, syncNameText(name)); return undefined }
  if (!await confirm(SYNC_DROP_TITLE, syncDropText(name), SYNC_DROP_OK)) return undefined
  const made = await call<{ path: string }>('localCaseFolder', { name })
  if (!made.ok) { notice('没能建好本机文件夹', errorText(made.error)); return undefined }
  const c = await openCase(made.value.path, null, navigate, false, undefined, { onOpened: (x) => recordKind(x.case_id, kind) })
  if (!c) return undefined
  // 顶层各项逐项复制到案件根（target 为 null：服务放案件根），保持原来的结构；项数太多时整个文件夹复制（多一层同名文件夹）
  const paths = d.children ?? [d.path]
  if (!paths.length) { notice('已建好案件', `"${c.name}"已在本机建好。原来的文件夹是空的，没有内容可复制。`); return c }
  const r = await call<ImportResult>('materialsImport', { case_id: c.case_id, paths, target: null, unzip: false })
  if (!r.ok) { notice('案件已建好，内容没有复制完', `${errorText(r.error)} 可以进入案件后把文件夹再拖进去。`); return c }
  reportImport(c, r.value, '复制结果')
  return c
}
