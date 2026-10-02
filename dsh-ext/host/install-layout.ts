// 打包后的固定布局（T20 步骤 3，执行令 0127 第 5 条；PATCHES.md 待办 T20 两行）：
// 开发期 legal-host 的启动命令、服务目录、Skill 目录由环境变量给（LAWBENCH_SERVICE_CMD、LAWBENCH_SERVICE_CWD、LAWBENCH_SKILLS_DIR 等，
// 见 cordis.patch.yml）；装好的客户端一律按安装目录写死、忽略这些环境变量——否则改个环境变量就能让 Host 去跑别的程序、加载别处的 Skill。
// 判断"装好的"：Host 以 Electron 当 Node 跑（ELECTRON_RUN_AS_NODE），process.execPath 是应用自己的 exe；安装目录里它旁边有 resources\app.asar
// （开发期是 Electron 自带的 default_app.asar，没有 app.asar）。
import { dirname, join } from 'node:path'
import type { Config } from './index.ts'

/** 管理员 Skill 目录名（%ProgramData%\<名>\skills）。产品正式名定了一起改（候 owner N58）。 */
export const ADMIN_DIR_NAME = 'lawbench'

/** 装好的客户端返回安装目录；开发期返回 undefined。 */
export function packagedInstallDir(execPath: string, exists: (p: string) => boolean): string | undefined {
  const dir = dirname(execPath)
  return exists(join(dir, 'resources', 'app.asar')) ? dir : undefined
}

/** 管理员目录在前（同名时覆盖内置），内置目录在后（Spec 10.1）。 */
export function packagedSkillDirs(installDir: string, programData: string): string[] {
  return [join(programData, ADMIN_DIR_NAME, 'skills'), join(installDir, 'skills')]
}

/**
 * 装好的客户端的 Host 配置：命令、目录全部按安装目录，环境变量给的一概不用。
 * 应用数据目录、转发端口照原配置（它们本来就不取自开发期环境变量）。
 * 随包的 LibreOffice、pandoc 在 <安装目录>\tools\ 下：给服务进程传 LAWBENCH_SOFFICE、LAWBENCH_PANDOC，PATH 前置这两个目录
 * （主编排定，T20 第二轮复核 P2-C；服务侧优先读这两个变量归线 C）。
 * @param basePath - Host 自己的 PATH（服务进程原本继承的那份）。
 */
export function packagedConfig(config: Config, installDir: string, programData: string, basePath = ''): Config {
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
export function effectiveConfig(given: Config, execPath: string, exists: (p: string) => boolean, programData: string, basePath: string): { config: Config; packaged: boolean; checkPython: boolean } {
  const installDir = packagedInstallDir(execPath, exists)
  const config = installDir ? packagedConfig(given, installDir, programData, basePath) : given
  return { config, packaged: installDir !== undefined, checkPython: /python(w)?(\.exe)?$/i.test(config.command[0] ?? '') }
}
