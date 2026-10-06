// T28 macOS 版的平台分支（令 1424）：Windows 上用参数 / 假 process 模拟 darwin 跑；Windows 原有行为由各自原用例守着。
import { EventEmitter } from 'node:events'
import { readFileSync } from 'node:fs'
import { join, posix } from 'node:path'
import { parse } from 'yaml'
import { defaultAppData } from '../shared/file-log.ts'
import { effectiveConfig, packagedConfig, packagedInstallDir, packagedSkillDirs } from '../host/install-layout.ts'
import { passThroughEnv, scrubPaths } from '../host/index.ts'
import * as keychain from '../credentials/keychain.ts'
import { credentialSource, macStore, macTrusted } from '../credentials/index.ts'
import { isMac, keyStoreName, MAC_NO_INVOICE } from '../ui/platform.ts'
import { converterOptions } from '../ui/settings.tsx'
import type { Config } from '../host/index.ts'

const HOME = '/Users/lawyer'
const APP = '/Applications/连越律师工作台.app'
const EXE = `${APP}/Contents/MacOS/连越律师工作台`
const RES = `${APP}/Contents/Resources`
const DEV: Config = { command: ['node', 'dev/fake-service.mjs'], cwd: '/repo/dsh-ext', appData: `${HOME}/Library/Application Support/lawbench`, forwardPort: 18765 } as Config

describe('应用数据目录', () => {
  it('darwin：~/Library/Application Support/lawbench，不在家目录里建可见文件夹', () => {
    expect(defaultAppData('darwin', {}, HOME)).toBe(join(HOME, 'Library', 'Application Support', 'lawbench'))
  })
  it('win32：照旧 %LOCALAPPDATA%\\lawbench', () => {
    expect(defaultAppData('win32', { LOCALAPPDATA: 'C:\\Users\\x\\AppData\\Local' }, 'C:\\Users\\x')).toBe(join('C:\\Users\\x\\AppData\\Local', 'lawbench'))
  })
})

describe('cordis.patch.yml 的 !!js 表达式', () => {
  const yml = readFileSync(join(__dirname, '..', 'cordis.patch.yml'), 'utf8')
  const exprs = (key: string): string[] => [...yml.matchAll(new RegExp(`^\\s*${key}: !!js (".*")\\s*$`, 'gm'))].map((m) => (parse(`x: ${m[1]}`) as { x: string }).x)
  const darwin = (execPath = EXE, exists: (p: string) => boolean = () => false) => ({
    platform: 'darwin', execPath, env: { LAWBENCH_SKILLS_DIR: '/repo/skills' },
    getBuiltinModule: (m: string) => (m === 'node:path' ? posix : m === 'node:os' ? { homedir: () => HOME } : { existsSync: exists }),
  })
  const run = (expr: string, proc: object): unknown => new Function('process', `return ${expr}`)(proc)

  it('appData（两处）与 documentsDirectory 在 darwin 下都进 Application Support', () => {
    const app = exprs('appData')
    expect(app).toHaveLength(2)
    for (const e of app) expect(run(e, darwin())).toBe(`${HOME}/Library/Application Support/lawbench`)
    expect(run(exprs('documentsDirectory')[0]!, darwin())).toBe(`${HOME}/Library/Application Support/lawbench/dsh-documents`)
  })
  it('customSkillDirs：darwin 装好的认 Contents/Resources/app.asar，开发期用 LAWBENCH_SKILLS_DIR', () => {
    const e = exprs('customSkillDirs')[0]!
    expect(run(e, darwin())).toEqual(['/Library/Application Support/lawbench/skills', '/repo/skills'])
    expect(run(e, darwin(EXE, (p) => p === `${RES}/app.asar`))).toEqual(['/Library/Application Support/lawbench/skills', `${RES}/skills`])
  })
  it('Host 的 skillDirs：darwin 管理员目录', () => {
    expect(run(exprs('skillDirs')[0]!, darwin())).toEqual(['/Library/Application Support/lawbench/skills', '/repo/skills'])
  })
})

describe('打包布局（darwin）', () => {
  const exists = (p: string) => p === `${RES}/app.asar`
  it('装好的判断：Contents/Resources/app.asar；开发期 undefined', () => {
    expect(packagedInstallDir(EXE, exists, 'darwin')).toBe(RES)
    expect(packagedInstallDir('/x/electron/dist/Electron.app/Contents/MacOS/Electron', exists, 'darwin')).toBeUndefined()
  })
  it('命令、工具、PATH 分隔符、Skill 目录', () => {
    const c = packagedConfig(DEV, RES, '', '/usr/bin:/bin', 'darwin')
    expect(c.command).toEqual([`${RES}/python/bin/python3`, '-I', '-B', '-m', 'lawbench'])
    expect(c.cwd).toBe(`${RES}/service`)
    expect(c.env).toEqual({
      LAWBENCH_SOFFICE: `${RES}/tools/LibreOffice.app/Contents/MacOS/soffice`,
      LAWBENCH_PANDOC: `${RES}/tools/pandoc/bin/pandoc`,
      PATH: `${RES}/tools/LibreOffice.app/Contents/MacOS:${RES}/tools/pandoc/bin:/usr/bin:/bin`,
    })
    expect(c.skillDirs).toEqual(packagedSkillDirs(RES, '', 'darwin'))
    expect(c.skillDirs).toEqual(['/Library/Application Support/lawbench/skills', `${RES}/skills`])
  })
  it('effectiveConfig：装好的查内置 python3；开发期 node 不查', () => {
    expect(effectiveConfig(DEV, EXE, exists, '', '', 'darwin')).toMatchObject({ packaged: true, installDir: RES, checkPython: true })
    expect(effectiveConfig(DEV, EXE, () => false, '', '', 'darwin')).toMatchObject({ packaged: false, checkPython: false })
  })
})

describe('Host 传给服务的环境变量（darwin）', () => {
  it('只传 HOME、TMPDIR、PATH、语言等；不传 Windows 那组和别的变量', () => {
    const out = passThroughEnv({ HOME, USER: 'lawyer', TMPDIR: '/var/folders/x/T/', PATH: '/usr/bin', LANG: 'zh_CN.UTF-8', HTTPS_PROXY: 'http://p', APPDATA: 'x', OneDrive: '/x' }, 'darwin')
    expect(out).toEqual({ HOME, USER: 'lawyer', TMPDIR: '/var/folders/x/T/', PATH: '/usr/bin', LANG: 'zh_CN.UTF-8', OneDrive: '/x' })
  })
})

describe('日志去路径（darwin，令 1424 补充第 2 条）', () => {
  it('/Users、/Volumes 下的路径一律换成 <路径>，不留文件名；安装目录内换 <安装目录>', () => {
    const t = scrubPaths(`FileNotFoundError: '/Users/lawyer/案件/张三诉李四/起诉状.docx' at /Volumes/U盘/证据 一/图.png\n  File ${RES}/service/lawbench/app.py`, RES, 'darwin')
    expect(t).not.toMatch(/张三|起诉状|证据|图\.png|lawyer/)
    expect(t).toContain("'<路径>'")
    expect(t).toContain('<安装目录>/service/lawbench/app.py')
  })
  it('不是路径的斜杠不动', () => {
    expect(scrubPaths('exit 1/2 and/or 3', undefined, 'darwin')).toBe('exit 1/2 and/or 3')
  })
})

/** 假的 security：记下参数和标准输入，按脚本给退出码和输出。 */
function fakeSecurity(script: (args: string[], stdin: string) => { code: number; out?: string }) {
  const calls: Array<{ cmd: string; args: string[]; stdin: string }> = []
  const spawner = ((cmd: string, args: string[]) => {
    const child = new EventEmitter() as EventEmitter & Record<string, unknown>
    const stdout = new EventEmitter() as EventEmitter & { setEncoding(): unknown }
    stdout.setEncoding = () => stdout
    const call = { cmd, args, stdin: '' }
    calls.push(call)
    child.stdout = stdout
    child.stderr = new EventEmitter()
    child.kill = () => {}
    child.stdin = { end: (s: string) => {
      call.stdin = s
      setImmediate(() => { const r = script(args, s); if (r.out) stdout.emit('data', r.out); child.emit('close', r.code) })
    } }
    return child
  }) as unknown as keychain.Spawner
  return { calls, spawner }
}

describe('钥匙串（keychain.ts，令 1424 补充第 3 条）', () => {
  const KEY = 'sk-TEST"quote\'and$dollar'
  it('写入：Key 只在标准输入里（十六进制），命令行参数里没有；-T 列出可信程序；写后读回核对', async () => {
    let stored: string | undefined
    const { calls, spawner } = fakeSecurity((args, stdin) => {
      if (args[0] === '-i') { stored = Buffer.from(/-X ([0-9a-f]+)/.exec(stdin)![1]!, 'hex').toString('utf8'); return { code: 0 } }
      return stored === undefined ? { code: 44 } : { code: 0, out: stored + '\n' }
    })
    await keychain.writeKey(KEY, [EXE, `${RES}/python/bin/python3`], undefined, undefined, spawner)
    expect(calls.map((c) => c.cmd)).toEqual(['/usr/bin/security', '/usr/bin/security'])
    for (const c of calls) expect(c.args.join(' ')).not.toContain(KEY)
    expect(calls[0]!.args).toEqual(['-i'])
    expect(calls[0]!.stdin).not.toContain(KEY)
    expect(calls[0]!.stdin.startsWith('delete-generic-password -s "lawbench/LAWFIRM_KEY" -a "lawbench"\n')).toBe(true)   // 先删后加：访问名单换成本版程序
    expect(calls[0]!.stdin).toContain('add-generic-password -U -s "lawbench/LAWFIRM_KEY" -a "lawbench"')
    expect(calls[0]!.stdin).toContain(`-T "/usr/bin/security" -T "${EXE}" -T "${RES}/python/bin/python3"`)
    expect(stored).toBe(KEY)
    expect(calls[1]!.args).toEqual(['find-generic-password', '-s', 'lawbench/LAWFIRM_KEY', '-a', 'lawbench', '-w'])
  })
  it('写入后读回不一致：报错', async () => {
    const { spawner } = fakeSecurity((args) => (args[0] === '-i' ? { code: 0 } : { code: 44 }))
    await expect(keychain.writeKey('abc', [], undefined, undefined, spawner)).rejects.toThrow('核对不一致')
  })
  it('非可见 ASCII 的 Key 拒绝，不起进程', async () => {
    const { calls, spawner } = fakeSecurity(() => ({ code: 0 }))
    await expect(keychain.writeKey('有中文', [], undefined, undefined, spawner)).rejects.toThrow()
    expect(calls).toHaveLength(0)
  })
  it('读取：没有条目（44）→ undefined；其他失败只带退出码', async () => {
    expect(await keychain.readKey(undefined, undefined, fakeSecurity(() => ({ code: 44 })).spawner)).toBeUndefined()
    expect(await keychain.readKey(undefined, undefined, fakeSecurity(() => ({ code: 0, out: 'k1\n' })).spawner)).toBe('k1')
    await expect(keychain.readKey(undefined, undefined, fakeSecurity(() => ({ code: 51, out: 'secret diag' })).spawner)).rejects.toThrow('退出码 51')
  })
  it('删除：不存在返回 false', async () => {
    expect(await keychain.deleteKey(undefined, undefined, fakeSecurity(() => ({ code: 44 })).spawner)).toBe(false)
    expect(await keychain.deleteKey(undefined, undefined, fakeSecurity(() => ({ code: 0 })).spawner)).toBe(true)
  })
  it('可免弹窗读取的程序（-T）：装好的含 Host 与内置 python3；开发期只有 Host（复核 P3-3）', () => {
    expect(macTrusted(EXE, (p) => p === `${RES}/app.asar`)).toEqual([EXE, `${RES}/python/bin/python3`])
    expect(macTrusted('/x/Electron', () => false)).toEqual(['/x/Electron'])
  })
  it('Key 来源标记：darwin 是钥匙串，不是 Windows 凭据管理器（复核 P3-3）', () => {
    expect(credentialSource('darwin')).toBe('macos-keychain')
    expect(credentialSource('win32')).toBe('windows-credential-manager')
  })
  it('macStore 可构造（装好的 / 开发期）', () => {
    expect(typeof macStore(EXE, (p) => p === `${RES}/app.asar`).write).toBe('function')
    expect(typeof macStore('/x/Electron', () => false).read).toBe('function')
  })
})

describe('界面的平台说法', () => {
  it('isMac 看 navigator', () => {
    expect(isMac({ platform: 'MacIntel' })).toBe(true)
    expect(isMac({ platform: 'Win32', userAgent: 'Mozilla/5.0 (Windows NT 10.0)' })).toBe(false)
    expect(isMac({ userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)' })).toBe(true)
  })
  it('Key 存放处与发票整理说法', () => {
    expect(keyStoreName(true)).toBe('钥匙串')
    expect(keyStoreName(false)).toBe('Windows 凭据管理器')
    expect(MAC_NO_INVOICE).toBe('Mac 版暂不支持发票整理')
  })
  it('转换程序选项（令 1424 第 2 条）：Mac 不列 Word/WPS；旧值照样显示并注明不可用；Windows 不变', () => {
    expect(converterOptions('auto', true).map(([v]) => v)).toEqual(['auto', 'libreoffice'])
    expect(converterOptions('word', true).at(-1)).toEqual(['word', 'Microsoft Word（Mac 版不可用）'])
    expect(converterOptions('auto', false).map(([v]) => v)).toEqual(['auto', 'word', 'wps', 'libreoffice'])
  })
})
