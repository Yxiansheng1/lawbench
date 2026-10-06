// 律师第一批反馈（令 2043）里要 Host 动本机的几件事：打开小工具、打开案件子文件夹、移除一份材料、在本机建案件文件夹。
// 路径判断都在这里（纯函数，tests\desk-actions.spec.ts）；真正启动程序、删文件由调用方注入，便于测。
// 日志只记事件和结果，不记路径、文件名。
import { lstatSync, realpathSync } from 'node:fs'
import { isAbsolute, join, normalize, relative, sep } from 'node:path'

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
  if (typeof name !== 'string' || !(name in TOOLS)) return BAD_ARG
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

/** 文件夹名里 Windows 不许的字符换成"_"，去掉首尾空格和点；空了用"新案件"。 */
export function safeFolderName(name: unknown): string {
  const s = typeof name === 'string' ? name : ''
  const t = s.replace(/[<>:"/\\|?*\u0000-\u001f]/g, '_').replace(/^[\s.]+|[\s.]+$/g, '').slice(0, 80)
  return /^(con|prn|aux|nul|com\d|lpt\d)$/i.test(t) || t === '' ? '新案件' : t
}

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
  /** 启动一个程序，不等它结束。 */
  launch(file: string, args: string[]): Promise<void>
  /** 在资源管理器（Mac 为访达）里打开文件夹。 */
  openPath(dir: string): Promise<void>
  remove(file: string): Promise<void>
  mkdir(dir: string): Promise<void>
}
