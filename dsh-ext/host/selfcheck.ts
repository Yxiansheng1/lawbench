// 启动自检（T20 准备，执行令 2301 第 5、6 条）：Host 启动时查一遍外部件是否就位，缺哪项给律师一句中文说明，不崩、不拦启动。
// 查：内置 Python 版本、tokenizer.json、LibreOffice、pandoc、管理员 Skill 目录普通用户只读、发票引擎缓存路径长度。
// 纯逻辑，文件、子进程、注册表都由调用方注入（tests\selfcheck.spec.ts）。日志只记各项 id 和结果，不记路径。
import { join } from 'node:path'

export type CheckId = 'python' | 'tokenizer' | 'libreoffice' | 'pandoc' | 'admin_skills' | 'cache_path'

export interface CheckItem {
  id: CheckId
  /** ok：就位；warn：能用但有隐患或某项功能受影响；error：对应功能用不了。 */
  level: 'ok' | 'warn' | 'error'
  /** 给律师看的一句话（ok 时为空）。 */
  message: string
}

export interface SelfCheckDeps {
  /** 服务启动命令（Host 配置的 command），第一项是内置 Python。 */
  command: readonly string[]
  /** 服务源码目录（Host 配置的 cwd）。 */
  serviceDir: string
  /** 应用数据目录（Host 配置的 appData）。 */
  appData: string
  /** 管理员 Skill 目录（Host 配置的 skillDirs 第一项）；没配不查。 */
  adminSkillsDir?: string
  /** LibreOffice、pandoc 的候选位置（打包后在安装目录里，T20 步骤 3 定）；PATH 上的也算。 */
  sofficeCandidates?: readonly string[]
  pandocCandidates?: readonly string[]
  isFile(path: string): boolean
  isDir(path: string): boolean
  /** PATH 上找可执行文件。 */
  which(name: string): string | undefined
  /** 跑一个命令拿标准输出（失败、超时返回 undefined）。 */
  run(command: readonly string[], timeoutMs: number): Promise<string | undefined>
  /** 当前用户能否在该目录里新建文件（试建后删掉）。 */
  canWrite(dir: string): boolean
  /** 系统是否开了长路径支持（LongPathsEnabled=1）；读不到为 undefined。 */
  longPathsEnabled(): Promise<boolean | undefined>
}

/** 发票引擎缓存目录 <应用数据>\ivc 的长度上限：引擎缓存里最长的文件约 104 字符，合计不能超过 259（T25 交付说明"给 T20 的配合"）。 */
export const CACHE_PATH_LIMIT = 110
export const INVOICE_CACHE_DIR = 'ivc'

export const TEXT = {
  python: '内置的 Python 不在或版本不对，工作台服务起不来。请重新安装律师工作台。',
  tokenizer: '缺少分词文件（tokenizer.json），字数按估算计，长材料可能被截断得不准。请重新安装律师工作台。',
  libreoffice: '没找到 LibreOffice，旧版 Word、WPS 文件和表格公式的转换用不了。请重新安装律师工作台。',
  pandoc: '没找到 pandoc，导出 Word 用不了。请重新安装律师工作台。',
  adminSkillsMissing: '管理员 Skill 目录不存在，律所统一下发的 Skill 不会加载。请联系技术支持检查安装。',
  adminSkillsWritable: '管理员 Skill 目录普通用户也能改，统一下发的 Skill 可能被改动。请联系技术支持设置为只读。',
  cachePath: (n: number) => `应用数据目录的路径太长（发票整理的缓存目录 ${n} 个字符，超过 ${CACHE_PATH_LIMIT}），发票整理可能失败。请联系技术支持开启系统长路径支持，或把应用数据放到较短的位置。`,
} as const

const ok = (id: CheckId): CheckItem => ({ id, level: 'ok', message: '' })

/** 跑一遍自检，按固定顺序返回每一项。 */
export async function selfCheck(d: SelfCheckDeps): Promise<CheckItem[]> {
  const out: CheckItem[] = []

  // 内置 Python：只认 3.12.x（服务 requires-python >=3.12,<3.13）；-I -S 与正式启动同样隔离
  const python = d.command[0]
  const version = python && d.isFile(python) ? await d.run([python, '-I', '-S', '-c', 'import sys;print("%d.%d.%d" % sys.version_info[:3])'], 10_000) : undefined
  out.push(/^3\.12\.\d+\s*$/.test(version ?? '') ? ok('python') : { id: 'python', level: 'error', message: TEXT.python })

  out.push(d.isFile(join(d.serviceDir, 'lawbench', 'llm', 'tokenizer.json')) ? ok('tokenizer') : { id: 'tokenizer', level: 'warn', message: TEXT.tokenizer })

  const found = (name: string, candidates: readonly string[] = []) => candidates.some((c) => d.isFile(c)) || d.which(name) !== undefined
  out.push(found('soffice', d.sofficeCandidates) ? ok('libreoffice') : { id: 'libreoffice', level: 'warn', message: TEXT.libreoffice })
  out.push(found('pandoc', d.pandocCandidates) ? ok('pandoc') : { id: 'pandoc', level: 'warn', message: TEXT.pandoc })

  if (d.adminSkillsDir !== undefined) {
    if (!d.isDir(d.adminSkillsDir)) out.push({ id: 'admin_skills', level: 'warn', message: TEXT.adminSkillsMissing })
    else out.push(d.canWrite(d.adminSkillsDir) ? { id: 'admin_skills', level: 'warn', message: TEXT.adminSkillsWritable } : ok('admin_skills'))
  }

  // 发票引擎缓存：系统开了长路径支持就不限；没开（或读不到）按 110 字符查
  const cache = join(d.appData, INVOICE_CACHE_DIR)
  const long = await d.longPathsEnabled()
  out.push(long === true || cache.length <= CACHE_PATH_LIMIT ? ok('cache_path') : { id: 'cache_path', level: 'warn', message: TEXT.cachePath(cache.length) })
  return out
}

/** 只留有问题的项（界面据此提示）。 */
export const problems = (items: readonly CheckItem[]): CheckItem[] => items.filter((i) => i.level !== 'ok')
