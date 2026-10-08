// 令 2043（律师第一批反馈）：Host 打开小工具、打开案件子文件夹、移除材料、在本机建案件文件夹。
import { mkdirSync, mkdtempSync, realpathSync, rmSync, symlinkSync, writeFileSync, existsSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { insideCase, localCaseFolder, localRoot, openableFolder, removableMaterial, safeFolderName, sameFolder, toolExe, type DeskDeps } from '../host/desk-actions.ts'
import { MATERIAL_REMOVE_ENABLED } from '../shared/feature-flags.ts'
import { LawbenchRemote } from '../host/index.ts'
import type { Supervisor } from '../host/supervisor.ts'

describe('路径判断', () => {
  it('小工具只认两个名字，位置按安装目录；开发期没有', () => {
    expect(toolExe('E:\\law', 'splitter')).toEqual({ ok: true, value: join('E:\\law', 'tools', 'splitter', 'splitter.exe') })
    expect(toolExe('E:\\law', 'convert')).toEqual({ ok: true, value: join('E:\\law', 'tools', 'convert', 'convert.exe') })
    expect(toolExe('E:\\law', '..\\..\\Windows\\notepad').ok).toBe(false)
    expect(toolExe(undefined, 'splitter')).toMatchObject({ ok: false, error: { code: 'NOT_AVAILABLE' } })
  })

  it('案件根下的位置：不出案件根、不收绝对路径和网络路径', () => {
    expect(insideCase('D:\\案件\\甲', '02 案件材料\\起诉书.pdf')).toEqual({ ok: true, value: join('D:\\案件\\甲', '02 案件材料', '起诉书.pdf') })
    expect(insideCase('D:\\案件\\甲', '..\\乙\\x.pdf').ok).toBe(false)
    expect(insideCase('D:\\案件\\甲', 'a\\..\\..\\x').ok).toBe(false)
    expect(insideCase('D:\\案件\\甲', 'C:\\Windows\\x').ok).toBe(false)
    expect(insideCase('\\\\fs\\share\\甲', 'x.pdf').ok).toBe(false)
    expect(insideCase('案件\\甲', 'x.pdf').ok).toBe(false)
  })

  it('本机案件文件夹：<用户目录>\\连越律师工作台\\<案件名>，非法字符换掉，同名加 (2)', () => {
    expect(localRoot('C:\\Users\\x')).toBe(join('C:\\Users\\x', '连越律师工作台'))
    expect(safeFolderName('张某甲: 诈骗案?')).toBe('张某甲_ 诈骗案_')
    expect(safeFolderName('  ..  ')).toBe('新案件')
    expect(safeFolderName('CON')).toBe('新案件')
    expect(safeFolderName('con.txt')).toBe('新案件') // 复核 P3：保留名带扩展名
    // 注记 0934 ②：与服务 gate.py 的 DEVICE_NAMES 同一套
    for (const n of ['com0', 'LPT0', 'com¹', 'lpt³', 'conin$', 'CONOUT$', 'CON .txt', 'nul.tar.gz', 'aux ']) expect(safeFolderName(n), n).toBe('新案件')
    for (const n of ['com10', 'console', 'con甲', 'lpt']) expect(safeFolderName(n), n).toBe(n)
    expect(safeFolderName('甲'.repeat(79) + ' 乙')).toBe('甲'.repeat(79)) // 先截 80 再去末尾空格
    expect(safeFolderName(String.raw`a\b`)).toBe('a_b')
    expect(toolExe('E:\\law', 'toString').ok).toBe(false) // 复核 P3：不认原型链上的名字
    const taken = new Set([join('C:\\Users\\x', '连越律师工作台', '甲案')])
    expect(localCaseFolder('C:\\Users\\x', '甲案', (p) => taken.has(p))).toBe(join('C:\\Users\\x', '连越律师工作台', '甲案') + '(2)')
  })
})

describe('移除材料（真文件系统）', () => {
  let dir: string
  beforeEach(() => { dir = mkdtempSync(join(tmpdir(), 'lb-desk-')) })
  afterEach(() => rmSync(dir, { recursive: true, force: true }))

  it('只收案件根里的普通文件；文件夹、不存在的、链到外面的都不收', () => {
    const root = join(dir, '甲案')
    mkdirSync(join(root, '02 案件材料'), { recursive: true })
    writeFileSync(join(root, '02 案件材料', '起诉书.pdf'), 'x')
    writeFileSync(join(dir, '外面.pdf'), 'x')
    expect(removableMaterial(root, '02 案件材料\\起诉书.pdf')).toEqual({ ok: true, value: join(root, '02 案件材料', '起诉书.pdf') })
    expect(removableMaterial(root, '02 案件材料').ok).toBe(false)
    expect(removableMaterial(root, '02 案件材料\\没有.pdf')).toMatchObject({ ok: false, error: { code: 'NOT_FOUND' } })
    let linked = false
    try { symlinkSync(join(dir, '外面.pdf'), join(root, '02 案件材料', '链接.pdf')); linked = true } catch { /* 没有建链接的权限就跳过这一项 */ }
    if (linked) expect(removableMaterial(root, '02 案件材料\\链接.pdf').ok).toBe(false)
  })
})

describe('Host 方法', () => {
  const up = { endpoint: () => ({ port: 1, token: 't' }), state: 'running' } as unknown as Supervisor
  function remote(desk: Partial<DeskDeps>, api: Record<string, (body: unknown) => unknown> = {}) {
    const r = new LawbenchRemote(up, tmpdir(), () => undefined)
    const calls: Array<[string, unknown]> = []
    r.desk = { installDir: 'E:\\law', userProfile: 'C:\\Users\\x', exists: () => true, isDir: () => true, openable: (root, rel) => ({ ok: true, value: rel ? join(root, String(rel)) : root }), launch: async (f, a) => { calls.push(['launch', [f, a]]) }, openPath: async (d) => { calls.push(['open', d]) }, remove: async (f) => { calls.push(['remove', f]) }, mkdir: async (d) => { calls.push(['mkdir', d]) }, ...desk }
    ;(r as unknown as { callApi: (route: { method: string }, body: unknown) => Promise<unknown> }).callApi = async (route, body) => {
      calls.push([route.method, body])
      return api[route.method] ? { ok: true, value: api[route.method]!(body) } : { ok: false, error: { code: 'X', message: 'x' } }
    }
    return { r, calls }
  }

  it('openTool：启动安装目录里的程序；名字不对、程序不在都不启动', async () => {
    const { r, calls } = remote({})
    expect(await r.openTool({ name: 'splitter' })).toEqual({ ok: true, value: { opened: true } })
    expect(calls).toEqual([['launch', [join('E:\\law', 'tools', 'splitter', 'splitter.exe'), []]]])
    expect((await r.openTool({ name: 'cmd' })).ok).toBe(false)
    const missing = remote({ exists: () => false })
    expect(await missing.r.openTool({ name: 'convert' })).toMatchObject({ ok: false, error: { code: 'NOT_FOUND' } })
    expect(missing.calls).toEqual([])
  })

  it('openFolder（真文件系统）：只开服务登记的案件根下的文件夹；未登记的根、网络根、联接指到案件外、出案件根都不开（复核 P2-2）', async () => {
    const dir = mkdtempSync(join(tmpdir(), 'lb-desk-'))
    try {
      const root = join(dir, '甲案')
      mkdirSync(join(root, '成果'), { recursive: true })
      mkdirSync(join(dir, '外面'), { recursive: true })
      let junction = false
      try { symlinkSync(join(dir, '外面'), join(root, '联接'), 'junction'); junction = true } catch { /* 建不了联接就跳过那一项 */ }
      const api = { caseRecent: () => ({ cases: [{ case_id: 'c-1', root, name: '甲案', exists: true }, { case_id: 'c-unc', root: String.raw`\\fs01\案卷\乙案`, name: '乙案', exists: true }] }) }
      const { r, calls } = remote({ openable: (root2, rel) => openableFolder(root2, rel) }, api)
      expect((await r.openFolder({ case_id: 'c-1', root, rel: '成果' })).ok).toBe(true)
      expect((await r.openFolder({ case_id: 'c-1', root, rel: '' })).ok).toBe(true)
      expect(await r.openFolder({ case_id: 'c-1', root: join(dir, '外面'), rel: '' })).toMatchObject({ ok: false, error: { code: 'INVALID_ARGUMENT' } })
      expect(await r.openFolder({ case_id: 'c-9', root, rel: '' })).toMatchObject({ ok: false, error: { code: 'INVALID_ARGUMENT' } })
      expect(await r.openFolder({ case_id: 'c-unc', root: String.raw`\\fs01\案卷\乙案`, rel: '' })).toMatchObject({ ok: false, error: { code: 'INVALID_ARGUMENT' } })
      expect((await r.openFolder({ case_id: 'c-1', root, rel: String.raw`..\外面` })).ok).toBe(false)
      if (junction) expect((await r.openFolder({ case_id: 'c-1', root, rel: '联接' })).ok).toBe(false)
      expect(calls.filter((c) => c[0] === 'open').map((c) => c[1])).toEqual([join(root, '成果'), root].map((p) => realpathSync.native(p)))
    } finally { rmSync(dir, { recursive: true, force: true }) }
  })

  it('openFolder：界面经联接（或 subst、映射盘）给的案件根与登记的是同一文件夹时照开，开的是登记的那个（注记 0934 ①）', async () => {
    const dir = mkdtempSync(join(tmpdir(), 'lb-desk-'))
    try {
      const root = join(dir, '甲案')
      mkdirSync(join(root, '成果'), { recursive: true })
      const alias = join(dir, '甲案别名')
      try { symlinkSync(root, alias, 'junction') } catch { return } // 建不了联接的环境跳过
      const api = { caseRecent: () => ({ cases: [{ case_id: 'c-1', root, name: '甲案', exists: true }] }) }
      const { r, calls } = remote({ openable: (root2, rel) => openableFolder(root2, rel) }, api)
      expect((await r.openFolder({ case_id: 'c-1', root: alias, rel: '成果' })).ok).toBe(true)
      expect(calls.filter((c) => c[0] === 'open').map((c) => c[1])).toEqual([realpathSync.native(join(root, '成果'))])
    } finally { rmSync(dir, { recursive: true, force: true }) }
  })

  it('openFile（真文件系统，令 1321 C.2）：只开登记案件根里的文书类普通文件；程序、出案件根、文件夹、未登记的根都不开', async () => {
    const dir = mkdtempSync(join(tmpdir(), 'lb-desk-'))
    try {
      const root = join(dir, '甲案')
      mkdirSync(join(root, '成果'), { recursive: true })
      writeFileSync(join(root, '成果', '借款合同-v1.docx'), 'x')
      writeFileSync(join(root, '成果', '工具.exe'), 'x')
      writeFileSync(join(dir, '外面.docx'), 'x')
      const api = { caseRecent: () => ({ cases: [{ case_id: 'c-1', root, name: '甲案', exists: true }] }) }
      const { r, calls } = remote({}, api)
      expect(await r.openFile({ case_id: 'c-1', root, rel: '成果/借款合同-v1.docx' })).toEqual({ ok: true, value: { opened: true } })
      expect(await r.openFile({ case_id: 'c-1', root, rel: '成果/工具.exe' })).toMatchObject({ ok: false, error: { code: 'INVALID_ARGUMENT' } })
      expect((await r.openFile({ case_id: 'c-1', root, rel: '..\\外面.docx' })).ok).toBe(false)
      expect((await r.openFile({ case_id: 'c-1', root, rel: '成果' })).ok).toBe(false)
      expect(await r.openFile({ case_id: 'c-1', root, rel: '成果/没有.docx' })).toMatchObject({ ok: false, error: { code: 'NOT_FOUND' } })
      expect((await r.openFile({ case_id: 'c-9', root, rel: '成果/借款合同-v1.docx' })).ok).toBe(false)
      expect(calls.filter((c) => c[0] === 'open').map((c) => c[1])).toEqual([join(root, '成果', '借款合同-v1.docx')])
    } finally { rmSync(dir, { recursive: true, force: true }) }
  })

  it('sameFolder：字面相同（大小写、斜杠、末尾斜杠）直接认；不同再比实际位置；解析不了按不同', () => {
    expect(sameFolder('D:\\案件\\甲\\', 'd:/案件/甲', () => { throw new Error('不该解析') })).toBe(true)
    const subst = (p: string) => p.replace(/^X:/i, 'D:\\案件')
    expect(sameFolder('D:\\案件\\甲', 'X:\\甲', subst)).toBe(true)
    expect(sameFolder('D:\\案件\\甲', 'X:\\乙', subst)).toBe(false)
    expect(sameFolder('D:\\案件\\甲', 'Y:\\甲', () => { throw new Error('ENOENT') })).toBe(false)
  })

  it('materialRemove：开关关着时 Host 直接拒绝（NOT_AVAILABLE），不问服务、不删文件（复核 P2-3）', async () => {
    expect(MATERIAL_REMOVE_ENABLED).toBe(false)
    const api = { caseRecent: () => ({ cases: [{ case_id: 'c-1', root: 'D:\\案件\\甲', name: '甲', exists: true }] }) }
    const { r, calls } = remote({}, api)
    expect(await r.materialRemove({ case_id: 'c-1', root: 'D:\\案件\\甲', rel_path: '02 案件材料\\起诉书.pdf' })).toMatchObject({ ok: false, error: { code: 'NOT_AVAILABLE' } })
    expect(calls).toEqual([])
  })

  it('localCaseFolder：在 <用户目录>\\连越律师工作台 下建好并回位置', async () => {
    const { r, calls } = remote({ exists: () => false })
    expect(await r.localCaseFolder({ name: '张某甲诈骗案' })).toEqual({ ok: true, value: { path: join('C:\\Users\\x', '连越律师工作台', '张某甲诈骗案') } })
    expect(calls).toEqual([['mkdir', join('C:\\Users\\x', '连越律师工作台', '张某甲诈骗案')]])
  })
})

void existsSync
