// 打包后的固定布局（T20 步骤 3，执行令 0127 第 5 条）：装好的客户端按安装目录写死 Host 的启动命令和各目录，
// 不读开发期环境变量（LAWBENCH_SERVICE_CMD、LAWBENCH_SERVICE_CWD、LAWBENCH_SKILLS_DIR、LAWBENCH_SERVICE_ENV）。
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { parse } from 'yaml'
import { ADMIN_DIR_NAME, effectiveConfig, packagedConfig, packagedInstallDir } from '../host/install-layout.ts'
import type { Config } from '../host/index.ts'

let dir: string
beforeEach(() => { dir = mkdtempSync(join(tmpdir(), 'lb-layout-')) })
afterEach(() => rmSync(dir, { recursive: true, force: true }))

/** 一个"装好的"目录：exe 旁边有 resources\app.asar。 */
function installed(): { inst: string; exe: string } {
  const inst = join(dir, '连越律师工作台')
  mkdirSync(join(inst, 'resources'), { recursive: true })
  writeFileSync(join(inst, 'resources', 'app.asar'), '')
  return { inst, exe: join(inst, '连越律师工作台.exe') }
}
/** 开发期：Electron 自带的 default_app.asar，没有 app.asar。 */
function development(): string {
  const d = join(dir, 'electron', 'dist')
  mkdirSync(join(d, 'resources'), { recursive: true })
  writeFileSync(join(d, 'resources', 'default_app.asar'), '')
  return join(d, 'electron.exe')
}
const exists = (p: string) => { try { readFileSync(p); return true } catch { return false } }

const DEV: Config = {
  command: ['C:\\evil\\run.exe'], cwd: 'C:\\evil', appData: 'C:\\Users\\x\\AppData\\Local\\lawbench', forwardPort: 18765,
  portRange: [18801, 18809], env: { LB_EXTRA: '1' }, skillDirs: ['C:\\ProgramData\\lawbench\\skills', 'C:\\evil\\skills'],
}

describe('打包后的固定布局', () => {
  it('exe 旁有 resources\\app.asar 才算装好的客户端；开发期的 Electron 不算', () => {
    const { inst, exe } = installed()
    expect(packagedInstallDir(exe, exists)).toBe(inst)
    expect(packagedInstallDir(development(), exists)).toBeUndefined()
  })

  it('装好的客户端：命令、服务目录、Skill 目录、工具位置都按安装目录；环境变量给的命令、目录、额外环境变量一概不用', () => {
    const { inst } = installed()
    const c = packagedConfig(DEV, inst, 'C:\\ProgramData', 'C:\\Windows\\system32')
    expect(c.command).toEqual([join(inst, 'python', 'python.exe'), '-I', '-m', 'lawbench'])
    expect(c.cwd).toBe(join(inst, 'service'))
    expect(c.skillDirs).toEqual([join('C:\\ProgramData', ADMIN_DIR_NAME, 'skills'), join(inst, 'skills')])
    // 随包工具：服务进程拿到 LAWBENCH_SOFFICE、LAWBENCH_PANDOC，PATH 前置两个工具目录（第二轮复核 P2-C）；开发期给的 LB_EXTRA 不带
    expect(c.env).toEqual({
      LAWBENCH_SOFFICE: join(inst, 'tools', 'libreoffice', 'program', 'soffice.exe'),
      LAWBENCH_PANDOC: join(inst, 'tools', 'pandoc', 'pandoc.exe'),
      PATH: `${join(inst, 'tools', 'libreoffice', 'program')};${join(inst, 'tools', 'pandoc')};C:\\Windows\\system32`,
    })
    expect(c.portRange).toBeUndefined()
    expect(c.sofficeCandidates).toEqual([join(inst, 'tools', 'libreoffice', 'program', 'soffice.exe')])
    expect(c.pandocCandidates).toEqual([join(inst, 'tools', 'pandoc', 'pandoc.exe')])
    expect(c.appData).toBe(DEV.appData)
    expect(c.forwardPort).toBe(18765)
    expect(JSON.stringify(c)).not.toContain('evil')
  })

  it('cordis.patch.yml 里 Skill 加载器的目录：开发期用 LAWBENCH_SKILLS_DIR；装好的客户端用安装目录、忽略它', () => {
    // 取那一行的 YAML 双引号串，交给 yaml 去掉转义，得到运行时 !!js 求值的那段表达式
    const line = /^\s*customSkillDirs: !!js (".*")\s*$/m.exec(readFileSync(join(__dirname, '..', 'cordis.patch.yml'), 'utf8'))
    const expr = line ? (parse(`x: ${line[1]}`) as { x: string }).x : undefined
    expect(expr).toBeTruthy()
    const run = (execPath: string) => new Function('process', `return ${expr}`)({
      execPath, env: { ProgramData: 'C:\\ProgramData', LAWBENCH_SKILLS_DIR: 'C:\\evil\\skills' }, getBuiltinModule: (m: string) => require(m),
    }) as string[]
    expect(run(development())).toEqual([join('C:\\ProgramData', 'lawbench', 'skills'), 'C:\\evil\\skills'])
    const { inst, exe } = installed()
    expect(run(exe)).toEqual([join('C:\\ProgramData', 'lawbench', 'skills'), join(inst, 'skills')])
  })

  it('apply 用的分支（复核 NOTE）：装好的客户端按安装目录、查内置 Python；开发期照配置，命令是 node 时不查、是 python 时查', () => {
    const { inst, exe } = installed()
    const BASE = 'C:\\Windows\\system32;C:\\Windows'
    const p = effectiveConfig(DEV, exe, exists, 'C:\\ProgramData', BASE)
    expect(p.packaged).toBe(true)
    expect(p.config.command[0]).toBe(join(inst, 'python', 'python.exe'))
    expect(p.checkPython).toBe(true)
    // 装好的客户端：工具目录在前、交进来的原 PATH 整个接在后面（T20 第三轮复核 P3-c：原 PATH 丢了，服务进程就没有 System32）
    const path = (p.config.env as Record<string, string>).PATH
    expect(path.startsWith(join(inst, 'tools', 'libreoffice', 'program'))).toBe(true)
    expect(path.endsWith(`;${BASE}`)).toBe(true)
    const devCfg: Config = { ...DEV, command: ['D:\\node\\node.exe', 'fake-service.mjs'] }
    const node = effectiveConfig(devCfg, development(), exists, 'C:\\ProgramData', BASE)
    expect(node).toMatchObject({ packaged: false, checkPython: false })
    // 开发期：配置原样交回（同一个对象），环境变量里没有 LAWBENCH_* 工具变量、PATH 也不动
    expect(node.config).toBe(devCfg)
    expect(Object.keys(node.config.env ?? {}).filter((k) => k.startsWith('LAWBENCH_') || k === 'PATH')).toEqual([])
    const py = effectiveConfig({ ...DEV, command: ['C:\\Py\\python.exe', '-m', 'lawbench'] }, development(), exists, 'C:\\ProgramData', BASE)
    expect(py).toMatchObject({ packaged: false, checkPython: true })
  })
})
