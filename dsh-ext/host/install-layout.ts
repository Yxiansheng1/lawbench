// 打包后的固定布局（T20 步骤 3，执行令 0127 第 5 条；PATCHES.md 待办 T20 两行）：
// 开发期 legal-host 的启动命令、服务目录、Skill 目录由环境变量给（LAWBENCH_SERVICE_CMD、LAWBENCH_SERVICE_CWD、LAWBENCH_SKILLS_DIR 等，
// 见 cordis.patch.yml）；装好的客户端一律按安装目录写死、忽略这些环境变量——否则改个环境变量就能让 Host 去跑别的程序、加载别处的 Skill。
// 判断"装好的"：Host 以 Electron 当 Node 跑（ELECTRON_RUN_AS_NODE），process.execPath 是应用自己的 exe；安装目录里它旁边有 resources\app.asar
// （开发期是 Electron 自带的 default_app.asar，没有 app.asar）。
// macOS（T28）：execPath 是 <名>.app/Contents/MacOS/<名>，app.asar 和我方载荷都在 <名>.app/Contents/Resources/；
// 下面的"安装目录"在 macOS 上指这个 Resources 目录，其余写法与 Windows 共用。macOS 分支用 posix 路径拼接。
import { dirname, join, posix } from 'node:path'
import type { Config } from './index.ts'

/** 管理员 Skill 目录名（%ProgramData%\<名>\skills）。产品正式名定了一起改（候 owner N58）。 */
export const ADMIN_DIR_NAME = 'lawbench'
/** macOS 的管理员目录所在（/Library/Application Support/<名>/skills，第一阶段由管理员手工建）。 */
export const MAC_ADMIN_BASE = '/Library/Application Support'

/** 装好的客户端返回安装目录（macOS：Contents/Resources）；开发期返回 undefined。 */
export function packagedInstallDir(execPath: string, exists: (p: string) => boolean, platform: string = process.platform): string | undefined {
  if (platform === 'darwin') {
    const res = posix.join(posix.dirname(execPath), '..', 'Resources')
    return exists(posix.join(res, 'app.asar')) ? res : undefined
  }
  const dir = dirname(execPath)
  return exists(join(dir, 'resources', 'app.asar')) ? dir : undefined
}

/** 管理员目录在前（同名时覆盖内置），内置目录在后（Spec 10.1）。 */
export function packagedSkillDirs(installDir: string, programData: string, platform: string = process.platform): string[] {
  if (platform === 'darwin') return [posix.join(MAC_ADMIN_BASE, ADMIN_DIR_NAME, 'skills'), posix.join(installDir, 'skills')]
  return [join(programData, ADMIN_DIR_NAME, 'skills'), join(installDir, 'skills')]
}

/** macOS 装好的客户端：内置 Python（python-build-standalone 布局）、LibreOffice.app、pandoc 都在 Resources 下。 */
function macPackagedConfig(config: Config, installDir: string, basePath: string): Config {
  const soffice = posix.join(installDir, 'tools', 'LibreOffice.app', 'Contents', 'MacOS', 'soffice')
  const pandoc = posix.join(installDir, 'tools', 'pandoc', 'bin', 'pandoc')
  const toolDirs = [posix.dirname(soffice), posix.dirname(pandoc)].join(':')
  return {
    // -B: the signed .app must not get __pycache__ written into it at run time (T28 review P3-1)
    command: [posix.join(installDir, 'python', 'bin', 'python3'), '-I', '-B', '-m', 'lawbench'],
    cwd: posix.join(installDir, 'service'),
    appData: config.appData,
    forwardPort: config.forwardPort,
    env: { LAWBENCH_SOFFICE: soffice, LAWBENCH_PANDOC: pandoc, PATH: basePath ? `${toolDirs}:${basePath}` : toolDirs },
    skillDirs: packagedSkillDirs(installDir, '', 'darwin'),
    sofficeCandidates: [soffice],
    pandocCandidates: [pandoc],
  }
}

/**
 * 装好的客户端的 Host 配置：命令、目录全部按安装目录，环境变量给的一概不用。
 * 应用数据目录、转发端口照原配置（它们本来就不取自开发期环境变量）。
 * 随包的 LibreOffice、pandoc 在 <安装目录>\tools\ 下：给服务进程传 LAWBENCH_SOFFICE、LAWBENCH_PANDOC，PATH 前置这两个目录
 * （主编排定，T20 第二轮复核 P2-C；服务侧优先读这两个变量归线 C）。
 * @param basePath - Host 自己的 PATH（服务进程原本继承的那份）。
 */
export function packagedConfig(config: Config, installDir: string, programData: string, basePath = '', platform: string = process.platform): Config {
  if (platform === 'darwin') return macPackagedConfig(config, installDir, basePath)
  const soffice = join(installDir, 'tools', 'libreoffice', 'program', 'soffice.exe')
  const pandoc = join(installDir, 'tools', 'pandoc', 'pandoc.exe')
  const toolDirs = [dirname(soffice), dirname(pandoc)].join(';')
  return {
    command: [join(installDir, 'python', 'python.exe'), '-I', '-m', 'lawbench'],
    cwd: join(installDir, 'service'),
    appData: config.appData,
    forwardPort: config.forwardPort,
    env: { LAWBENCH_SOFFICE: soffice, LAWBENCH_PANDOC: pandoc, PATH: basePath ? `${toolDirs};${basePath}` : toolDirs },
    skillDirs: packagedSkillDirs(installDir, programData),
    sofficeCandidates: [soffice],
    pandocCandidates: [pandoc],
  }
}

/**
 * Host 实际用的配置和要不要查内置 Python：装好的客户端按安装目录写死；开发期照配置（环境变量给的）。
 * 启动命令不是 Python（开发期用 node 起假服务）时自检不查内置 Python。apply 里用，单独拿出来便于测。
 */
export function effectiveConfig(given: Config, execPath: string, exists: (p: string) => boolean, programData: string, basePath: string, platform: string = process.platform): { config: Config; packaged: boolean; installDir: string | undefined; checkPython: boolean } {
  const installDir = packagedInstallDir(execPath, exists, platform)
  const config = installDir ? packagedConfig(given, installDir, programData, basePath, platform) : given
  const cmd = config.command[0] ?? ''
  return { config, packaged: installDir !== undefined, installDir, checkPython: /python(w)?(\.exe)?$/i.test(cmd) || (platform === 'darwin' && /python3$/.test(cmd)) }
}
