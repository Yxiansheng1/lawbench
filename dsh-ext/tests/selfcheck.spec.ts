// 启动自检（T20 准备，执行令 2301 第 5、6 条）：缺哪项给中文提示、不崩；缓存路径超过约 110 字符且没开长路径时提示。
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { CACHE_PATH_LIMIT, notes, problems, selfCheck, TEXT, type SelfCheckDeps } from '../host/selfcheck.ts'
import { nodeSelfCheckDeps } from '../host/selfcheck-node.ts'
import { LawbenchRemote } from '../host/index.ts'
import type { Supervisor } from '../host/supervisor.ts'

const PY = 'C:\\安装\\runtime\\python\\python.exe'
const SVC = 'C:\\安装\\service'
const SOFFICE = 'C:\\安装\\tools\\libreoffice\\program\\soffice.exe'
const PANDOC = 'C:\\安装\\tools\\pandoc\\pandoc.exe'
const ADMIN = 'C:\\ProgramData\\lawbench\\skills'

function deps(over: Partial<SelfCheckDeps> = {}): SelfCheckDeps {
  const files = new Set([PY, join(SVC, 'lawbench', 'llm', 'tokenizer.json'), SOFFICE, PANDOC])
  return {
    command: [PY, '-I', '-S', 'boot.py'], serviceDir: SVC, appData: 'C:\\Users\\x\\AppData\\Local\\lawbench', adminSkillsDir: ADMIN,
    sofficeCandidates: [SOFFICE], pandocCandidates: [PANDOC],
    isFile: (p) => files.has(p), isDir: (p) => p === ADMIN, which: () => undefined,
    run: async () => '3.12.14\n', canWrite: () => false, longPathsEnabled: async () => false,
    ...over,
  }
}
const level = async (over: Partial<SelfCheckDeps>) => Object.fromEntries((await selfCheck(deps(over))).map((i) => [i.id, i.level]))

describe('启动自检', () => {
  it('全部就位：六项都 ok，没有要提示的', async () => {
    const items = await selfCheck(deps())
    expect(items.map((i) => i.id)).toEqual(['python', 'tokenizer', 'libreoffice', 'pandoc', 'admin_skills', 'cache_path'])
    expect(problems(items)).toEqual([])
  })

  it('内置 Python 不在、版本不是 3.12、跑不起来：error，说重新安装；用 -I -S 隔离着问版本', async () => {
    const seen: string[][] = []
    await selfCheck(deps({ run: async (c) => { seen.push([...c]); return '3.12.14\n' } }))
    expect(seen[0]!.slice(0, 3)).toEqual([PY, '-I', '-S'])
    expect((await level({ isFile: () => false })).python).toBe('error')
    expect((await level({ run: async () => '3.13.1\n' })).python).toBe('error')
    expect((await level({ run: async () => undefined })).python).toBe('error')
    const items = await selfCheck(deps({ run: async () => undefined }))
    expect(items.find((i) => i.id === 'python')!.message).toBe(TEXT.python)
  })

  it('tokenizer、LibreOffice、pandoc 缺了各自 warn；候选位置没有但 PATH 上有也算就位', async () => {
    expect(await level({ isFile: (p) => p === PY })).toMatchObject({ tokenizer: 'warn', libreoffice: 'warn', pandoc: 'warn' })
    expect(await level({ isFile: (p) => p === PY, which: (n) => `C:\\bin\\${n}.exe` })).toMatchObject({ libreoffice: 'ok', pandoc: 'ok' })
  })

  it('管理员 Skill 目录：不存在只作说明 info、不算问题（注记 2053）；普通用户能写 warn（应只读）；只读 ok；没配不查', async () => {
    expect((await level({ isDir: () => false })).admin_skills).toBe('info')
    expect(problems([{ id: 'admin_skills', level: 'info', message: TEXT.adminSkillsMissing }])).toEqual([])
    expect(notes([{ id: 'admin_skills', level: 'info', message: TEXT.adminSkillsMissing }]).map((i) => i.message)).toEqual(['未配置律所统一 Skill 目录'])
    expect((await level({ canWrite: () => true })).admin_skills).toBe('warn')
    expect((await level({})).admin_skills).toBe('ok')
    expect(await level({ adminSkillsDir: undefined })).not.toHaveProperty('admin_skills')
  })

  it(`发票缓存路径：<应用数据>\\ivc 超过 ${CACHE_PATH_LIMIT} 字符且没开长路径时 warn，说出字符数；开了长路径不提示`, async () => {
    const long = 'C:\\' + 'a'.repeat(CACHE_PATH_LIMIT)
    expect((await level({ appData: long })).cache_path).toBe('warn')
    expect((await level({ appData: long, longPathsEnabled: async () => undefined })).cache_path).toBe('warn')
    expect((await level({ appData: long, longPathsEnabled: async () => true })).cache_path).toBe('ok')
    const exact = 'C:\\' + 'b'.repeat(CACHE_PATH_LIMIT - 7) // + '\\ivc' 正好 110
    expect(join(exact, 'ivc').length).toBe(CACHE_PATH_LIMIT)
    expect((await level({ appData: exact })).cache_path).toBe('ok')
    const items = await selfCheck(deps({ appData: long }))
    expect(items.find((i) => i.id === 'cache_path')!.message).toBe(TEXT.cachePath(join(long, 'ivc').length))
  })

  it('Host：只回有问题的项，只跑一次；自检本身出错不影响（回空）', async () => {
    let runs = 0
    const up = { endpoint: () => undefined, state: 'running' } as unknown as Supervisor
    const r = new LawbenchRemote(up, tmpdir(), () => undefined, [], () => {}, undefined, undefined, async () => { runs++; return [{ id: 'pandoc', level: 'warn', message: TEXT.pandoc }, { id: 'python', level: 'ok', message: '' }, { id: 'admin_skills', level: 'info', message: TEXT.adminSkillsMissing }] })
    expect(await r.selfCheck()).toEqual({ ok: true, value: { items: [{ id: 'pandoc', level: 'warn', message: TEXT.pandoc }], notes: [{ id: 'admin_skills', level: 'info', message: TEXT.adminSkillsMissing }] } })
    await r.selfCheck()
    expect(runs).toBe(1)
    const bad = new LawbenchRemote(up, tmpdir(), () => undefined, [], () => {}, undefined, undefined, async () => { throw new Error('x') })
    expect(await bad.selfCheck()).toEqual({ ok: true, value: { items: [], notes: [] } })
  })

  it('真实依赖：能写的临时目录判为能写、不留文件；长路径设置读得到（Windows）', async () => {
    const dir = mkdtempSync(join(tmpdir(), 'lb-selfcheck-'))
    try {
      const d = nodeSelfCheckDeps({ command: [], serviceDir: dir, appData: dir })
      expect(d.canWrite(dir)).toBe(true)
      expect(require('node:fs').readdirSync(dir)).toEqual([])
      expect(d.canWrite(join(dir, '不存在'))).toBe(false)
      if (process.platform === 'win32') expect(typeof (await d.longPathsEnabled())).toBe('boolean')
    } finally { rmSync(dir, { recursive: true, force: true }) }
  })
})
