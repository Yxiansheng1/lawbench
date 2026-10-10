// 律师第一批反馈（令 2043）里要 Host 动本机的几件事：打开小工具、打开案件子文件夹、移除一份材料、在本机建案件文件夹。
// 路径判断都在这里（纯函数，tests\desk-actions.spec.ts）；真正启动程序、删文件由调用方注入，便于测。
// 日志只记事件和结果，不记路径、文件名。
import { lstatSync, mkdirSync, readdirSync, realpathSync, statSync } from 'node:fs'
import { basename, extname, isAbsolute, join, normalize, relative, sep } from 'node:path'
import { CASE_TEMPLATES, customFolderProblem, folderRels, isDeviceName, MAX_CUSTOM, safeFolderName, type CaseKind } from '../shared/case-folders.ts'

/** 首页"工具"一栏的两个小工具（打包后在 <安装目录>\tools\<名>\<名>.exe，见 packaging\build.ps1 smalltools 步）。 */
export const TOOLS = { splitter: '长截图切分', convert: '格式互转' } as const
export type ToolName = keyof typeof TOOLS

/** 本机案件的默认上级文件夹（令 2043 第 3 条：不在"文档""桌面"下，Win11 默认会把它们同步到 OneDrive）。 */
export const LOCAL_ROOT_NAME = '连越律师工作台'
export const localRoot = (userProfile: string): string => join(userProfile, LOCAL_ROOT_NAME)

type Fail = { ok: false; error: { code: string; message: string } }
const fail = (code: string, message: string): Fail => ({ ok: false, error: { code, message } })
const BAD_ARG = fail('INVALID_ARGUMENT', '请求参数有误')

/** 小工具的程序位置；开发期（没有安装目录）为 undefined。 */
export function toolExe(installDir: string | undefined, name: unknown): { ok: true; value: string } | Fail {
  if (typeof name !== 'string' || !Object.hasOwn(TOOLS, name)) return BAD_ARG // 复核 P3：不认原型链上的名字（toString 等）
  if (!installDir) return fail('NOT_AVAILABLE', '开发环境里没有打包的小工具')
  return { ok: true, value: join(installDir, 'tools', name, `${name}.exe`) }
}

/** 网络、设备路径、相对路径一律不收（同 archive-plan.ts、path-state.ts）。 */
const plainAbsolute = (p: unknown): p is string => typeof p === 'string' && p !== '' && isAbsolute(p) && !/^[\\/]{2}/.test(p)

/**
 * 案件根下的一个位置（"打开所在文件夹"、"移除此材料"用）：相对路径不能出案件根、不能是绝对路径。
 * @returns 绝对路径。
 */
export function insideCase(root: unknown, rel: unknown): { ok: true; value: string } | Fail {
  if (!plainAbsolute(root) || typeof rel !== 'string' || isAbsolute(rel) || /^[\\/]/.test(rel)) return BAD_ARG
  // 复核 rv-A52 P3-1：与服务 gate.py 的 _BAD_CHARS 一致——":"（盘符、备用数据流 x.docx:evil）、控制字符、Windows 保留字符都拒
  if (/[\u0000-\u001f<>:"|?*]/.test(rel)) return BAD_ARG
  const full = normalize(join(root, rel))
  const back = relative(normalize(root), full)
  if (back === '' && rel !== '') return BAD_ARG
  if (back.startsWith('..') || isAbsolute(back)) return BAD_ARG
  return { ok: true, value: full }
}

/**
 * 要移除的材料文件：须在案件根里、是普通文件（不是链接、不是文件夹），且实际位置（解析链接后）仍在案件根里。
 * @param statFn、realFn 测试替身；默认用真文件系统。
 */
export function removableMaterial(root: unknown, rel: unknown,
  statFn: (p: string) => { isFile(): boolean; isSymbolicLink(): boolean } = lstatSync,
  realFn: (p: string) => string = realpathSync.native): { ok: true; value: string } | Fail {
  const at = insideCase(root, rel)
  if (!at.ok) return at
  let st
  try { st = statFn(at.value) } catch { return fail('NOT_FOUND', '这份材料的文件已经不在了，点"重新扫描"更新列表') }
  if (st.isSymbolicLink() || !st.isFile()) return fail('INVALID_ARGUMENT', '只能移除普通文件')
  let realRoot: string, realFile: string
  try { realRoot = realFn(root as string); realFile = realFn(at.value) } catch { return fail('NOT_FOUND', '这份材料的文件已经不在了，点"重新扫描"更新列表') }
  const back = relative(realRoot, realFile)
  if (back === '' || back.startsWith('..') || isAbsolute(back)) return BAD_ARG
  return { ok: true, value: at.value }
}

/** 成果卡片"打开"能开的文件类型（令 1321 C.2）：只开文书类，不开程序、脚本、快捷方式（案件文件夹里可能有任何东西）。 */
export const OPENABLE_FILE_EXT: ReadonlySet<string> = new Set(['.docx', '.doc', '.wps', '.md', '.pdf', '.xlsx', '.xls', '.txt'])

/**
 * 成果卡片"打开"的文件：须在案件根里、是文书类的普通文件（不是链接、不是文件夹），且实际位置（解析链接后）仍在案件根里。
 * @param statFn、realFn 测试替身；默认用真文件系统。
 */
export function openableFile(root: unknown, rel: unknown,
  statFn: (p: string) => { isFile(): boolean; isSymbolicLink(): boolean } = lstatSync,
  realFn: (p: string) => string = realpathSync.native): { ok: true; value: string } | Fail {
  const at = insideCase(root, rel)
  if (!at.ok) return at
  if (!OPENABLE_FILE_EXT.has(extname(at.value).toLowerCase())) return fail('INVALID_ARGUMENT', '这类文件不在这里打开，请到"打开所在文件夹"里找')
  let st
  try { st = statFn(at.value) } catch { return fail('NOT_FOUND', '这份成果的文件已经不在了') }
  if (st.isSymbolicLink() || !st.isFile()) return fail('INVALID_ARGUMENT', '只能打开普通文件')
  let realRoot: string, realFile: string
  try { realRoot = realFn(root as string); realFile = realFn(at.value) } catch { return fail('NOT_FOUND', '这份成果的文件已经不在了') }
  const back = relative(realRoot, realFile)
  if (back === '' || back.startsWith('..') || isAbsolute(back)) return BAD_ARG
  return { ok: true, value: at.value }
}

// safeFolderName、isDeviceName 移到 shared\case-folders.ts（界面检查自填的子文件夹名也用，令 1852 第 17 条）
export { isDeviceName, safeFolderName }

/** "为我在本机建一个文件夹"的位置：<用户目录>\连越律师工作台\<案件名>；同名已在时加"(2)"…… */
export function localCaseFolder(userProfile: string, name: unknown, exists: (p: string) => boolean): string {
  const base = join(localRoot(userProfile), safeFolderName(name))
  if (!exists(base)) return base
  for (let i = 2; i < 1000; i++) { const p = `${base}(${i})`; if (!exists(p)) return p }
  return `${base}(${Date.now()})`
}

/** 给日志用：只记是哪一类子文件夹，不记路径。 */
export const folderKind = (rel: string): string => (rel.split(/[\\/]/)[0] || 'root').slice(0, 20)
export const SEP = sep

/** Host 动本机的实际做法（index.ts 的 LawbenchRemote.desk；测试换成替身）。 */
export interface DeskDeps {
  /** 安装目录；开发期为 undefined（小工具不可用）。 */
  readonly installDir: string | undefined
  /** 用户目录（%USERPROFILE%）。 */
  readonly userProfile: string
  exists(p: string): boolean
  isDir(p: string): boolean
  /** 能打开的案件文件夹（openableFolder，真文件系统）。 */
  openable(root: string, rel: unknown): { ok: true; value: string } | Fail
  /** 解析联接、subst、映射盘后的实际位置（sameFolder 用；不给时用 realpathSync.native）。 */
  realpath?(p: string): string
  /** 启动一个程序，不等它结束。 */
  launch(file: string, args: string[]): Promise<void>
  /** 在资源管理器（Mac 为访达）里打开文件夹。 */
  openPath(dir: string): Promise<void>
  remove(file: string): Promise<void>
  mkdir(dir: string): Promise<void>
  /** 新建案件补建子文件夹（mkdirInCase）用的文件系统操作；不给时用真文件系统。 */
  mkdirFs?: MkdirFs
  /** 看首页拖进来的东西（droppedItems）用的文件系统操作；不给时用真文件系统。 */
  dropFs?: DropFs
}

/**
 * 界面给的案件根与服务登记的是不是同一个文件夹（注记 0934 ①，复核 rv-A48）：先按字面比（不分大小写、斜杠方向、末尾斜杠），
 * 不同再各自解析联接、subst、映射盘后比实际位置——同一文件夹经两条路径到达时不误拒。解析不了（不存在等）按不同算。
 */
export function sameFolder(a: string, b: string, realFn: (p: string) => string = realpathSync.native): boolean {
  const norm = (p: string) => p.toLowerCase().replace(/\//g, '\\').replace(/\\+$/, '')
  if (norm(a) === norm(b)) return true
  // 复核 rv-A52 P3-2：界面给的不是普通绝对路径（网络路径等）就不去解析（UNC 解析会先连 SMB）
  if (!plainAbsolute(b)) return false
  try { return norm(realFn(a)) === norm(realFn(b)) } catch { return false }
}

/**
 * 能打开的案件文件夹（复核 AMEND P2-2）：案件根须是普通绝对路径（不收网络路径：UNC 根会先连 SMB）；rel 为空即案件根，
 * 否则不出案件根；解析联接、链接后实际位置仍须在案件根里（子目录是联接时可能指到案件外）；须是文件夹。
 */
export function openableFolder(root: unknown, rel: unknown,
  realFn: (p: string) => string = realpathSync.native, isDir: (p: string) => boolean = (p) => { try { return statSync(p).isDirectory() } catch { return false } }): { ok: true; value: string } | Fail {
  if (!plainAbsolute(root)) return BAD_ARG
  const at = rel === '' ? { ok: true as const, value: normalize(root) } : insideCase(root, rel)
  if (!at.ok) return at
  let realRoot: string, real: string
  try { realRoot = realFn(root); real = realFn(at.value) } catch { return fail('NOT_FOUND', '这个文件夹还没有内容（还没建出来）') }
  const back = relative(realRoot, real)
  if (back.startsWith('..') || isAbsolute(back)) return BAD_ARG
  if (!isDir(real)) return fail('NOT_FOUND', '这个文件夹还没有内容（还没建出来）')
  return { ok: true, value: real }
}

/**
 * 新建案件时律师勾的子文件夹（令 1852 第 17 条）：界面给的名单再核一遍——种类只认 civil / criminal，一级目录须在该类标准目录里，
 * 自填的须是合法的一级目录名（同 customFolderProblem）。
 * @returns 要建的相对路径（正斜杠，一级后紧跟它的二级）。
 */
export function chosenFolders(kind: unknown, tops: unknown, custom: unknown): { ok: true; value: string[] } | Fail {
  if (kind !== 'civil' && kind !== 'criminal') return BAD_ARG
  const strings = (v: unknown): v is string[] => Array.isArray(v) && v.every((x) => typeof x === 'string')
  if (!strings(tops) || !strings(custom) || custom.length > MAX_CUSTOM) return BAD_ARG
  const known = new Set(CASE_TEMPLATES[kind as CaseKind].map((f) => f.name))
  if (tops.some((t) => !known.has(t)) || custom.some((c) => customFolderProblem(c) !== null)) return BAD_ARG
  return { ok: true, value: folderRels(kind as CaseKind, { tops, custom }) }
}

/** 建子文件夹用到的文件系统操作（测试换成替身，默认真文件系统）。 */
export interface MkdirFs {
  lstat(p: string): { isDirectory(): boolean; isSymbolicLink(): boolean } | undefined
  realpath(p: string): string
  mkdir(p: string): void
}
export const nodeMkdirFs: MkdirFs = {
  lstat: (p) => { try { return lstatSync(p) } catch { return undefined } },
  realpath: (p) => realpathSync.native(p),
  mkdir: (p) => { mkdirSync(p) },
}

/**
 * 在案件根里补建一个空文件夹，规则同服务 gate.py 的 mkdir_original：只补缺、不改已有的；
 * 路上哪一级已是链接（含联接）或同名文件就整条跳过、不往里建；逐级建，每建一级前核它的上级实际位置仍在案件根里。
 * @returns 新建了为 true；已有或跳过为 false。
 */
export function mkdirInCase(root: string, rel: string, fs: MkdirFs = nodeMkdirFs): boolean {
  const at = insideCase(root, rel)
  if (!at.ok) return false
  const parts = rel.split('/')
  let realRoot: string
  try { realRoot = fs.realpath(root) } catch { return false }
  let cur = root
  let made = false
  for (const p of parts) {
    const parent = cur
    cur = join(cur, p)
    const st = fs.lstat(cur)
    if (st) {
      if (st.isSymbolicLink() || !st.isDirectory()) return false
      continue
    }
    let realParent: string
    try { realParent = fs.realpath(parent) } catch { return false }
    const back = relative(realRoot, realParent)
    if (back.startsWith('..') || isAbsolute(back)) return false
    try { fs.mkdir(cur) } catch { return false }
    made = true
  }
  return made
}

/** 首页空白处拖进来的一项（令 1422，第七版待办 20）：是不是文件夹、是不是已经当过案件、顶层有哪些东西。 */
export interface DroppedItem {
  path: string
  /** 文件夹名（或文件名）。 */
  name: string
  /** dir：普通文件夹；file：文件；other：链接、联接、不存在、网络路径或相对路径（都不能建案件）。 */
  kind: 'dir' | 'file' | 'other'
  /** 文件夹里已有 工作区\（以前当过案件）。 */
  has_case: boolean
  /** 顶层各项的绝对路径（不含以 . 开头的和 工作区、成果）；"复制到本机建案件"时逐项交给 /api/materials/import。超过上限为 null。 */
  children: string[] | null
}
/** 顶层最多列这么多项（多了不列，界面改为整个文件夹复制）。 */
export const MAX_DROP_CHILDREN = 2000
/** 一次最多看这么多项。 */
export const MAX_DROP_ITEMS = 50

/** 看拖进来的东西用到的文件系统操作（测试换成替身，默认真文件系统）。 */
export interface DropFs {
  lstat(p: string): { isDirectory(): boolean; isFile(): boolean; isSymbolicLink(): boolean } | undefined
  readdir(p: string): string[]
}
export const nodeDropFs: DropFs = {
  lstat: (p) => { try { return lstatSync(p) } catch { return undefined } },
  readdir: (p) => readdirSync(p),
}

/**
 * 看首页空白处拖进来的各项：只收普通绝对路径（同 knownCase / openFolder 的口径，网络路径、相对路径算 other，不去碰）；
 * 链接、联接算 other（案件根不能是链接，服务也拒）。只看是不是文件夹和顶层名字，不读文件内容。
 */
export function droppedItems(paths: unknown, fs: DropFs = nodeDropFs): { ok: true; value: DroppedItem[] } | Fail {
  if (!Array.isArray(paths) || paths.length === 0 || paths.length > MAX_DROP_ITEMS || paths.some((p) => typeof p !== 'string')) return BAD_ARG
  const reserved = new Set(['工作区', '成果'])
  const out = (paths as string[]).map((path): DroppedItem => {
    const item: DroppedItem = { path, name: basename(path.replace(/[\\/]+$/, '')), kind: 'other', has_case: false, children: [] }
    if (!plainAbsolute(path)) return item
    const st = fs.lstat(path)
    if (!st || st.isSymbolicLink()) return item
    if (st.isFile()) return { ...item, kind: 'file' }
    if (!st.isDirectory()) return item
    let names: string[]
    try { names = fs.readdir(path) } catch { return item }
    const work = fs.lstat(join(path, '工作区'))
    const kept = names.filter((n) => !n.startsWith('.') && !reserved.has(n)).sort()
    return { ...item, kind: 'dir', has_case: !!work && work.isDirectory() && !work.isSymbolicLink(), children: kept.length > MAX_DROP_CHILDREN ? null : kept.map((n) => join(path, n)) }
  })
  return { ok: true, value: out }
}
