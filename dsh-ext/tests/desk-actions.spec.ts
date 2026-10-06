// 令 2043（律师第一批反馈）：Host 打开小工具、打开案件子文件夹、移除材料、在本机建案件文件夹。
import { mkdirSync, mkdtempSync, rmSync, symlinkSync, writeFileSync, existsSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { insideCase, localCaseFolder, localRoot, removableMaterial, safeFolderName, toolExe, type DeskDeps } from '../host/desk-actions.ts'
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
    r.desk = { installDir: 'E:\\law', userProfile: 'C:\\Users\\x', exists: () => true, isDir: () => true, launch: async (f, a) => { calls.push(['launch', [f, a]]) }, openPath: async (d) => { calls.push(['open', d]) }, remove: async (f) => { calls.push(['remove', f]) }, mkdir: async (d) => { calls.push(['mkdir', d]) }, ...desk }
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

  it('openFolder：打开案件根下的子文件夹；出案件根不开', async () => {
    const { r, calls } = remote({})
    expect((await r.openFolder({ root: 'D:\\案件\\甲', rel: '02 案件材料' })).ok).toBe(true)
    expect((await r.openFolder({ root: 'D:\\案件\\甲', rel: '..\\..' })).ok).toBe(false)
    expect(calls).toEqual([['open', join('D:\\案件\\甲', '02 案件材料')]])
  })

  it('materialRemove：核对 case_id 与案件根是服务登记的同一个，删文件后重新扫描；对不上不删', async () => {
    const dir = mkdtempSync(join(tmpdir(), 'lb-desk-'))
    try {
      const root = join(dir, '甲案')
      mkdirSync(join(root, '02 案件材料'), { recursive: true })
      writeFileSync(join(root, '02 案件材料', '起诉书.pdf'), 'x')
      const api = { caseRecent: () => ({ cases: [{ case_id: 'c-1', root, name: '甲案', exists: true }] }), materialsScan: () => ({ added: 0, changed: 0, removed: 1, failed: 0, review_needed: true }) }
      const ok = remote({}, api)
      expect(await ok.r.materialRemove({ case_id: 'c-1', root, rel_path: '02 案件材料\\起诉书.pdf' })).toEqual({ ok: true, value: { added: 0, changed: 0, removed: 1, failed: 0, review_needed: true } })
      expect(ok.calls.map((c) => c[0])).toEqual(['caseRecent', 'remove', 'materialsScan'])
      expect(ok.calls[1]![1]).toBe(join(root, '02 案件材料', '起诉书.pdf'))
      const wrong = remote({}, api)
      expect((await wrong.r.materialRemove({ case_id: 'c-1', root: join(dir, '别的'), rel_path: '02 案件材料\\起诉书.pdf' })).ok).toBe(false)
      expect((await wrong.r.materialRemove({ case_id: 'c-2', root, rel_path: '02 案件材料\\起诉书.pdf' })).ok).toBe(false)
      expect(wrong.calls.map((c) => c[0])).not.toContain('remove')
    } finally { rmSync(dir, { recursive: true, force: true }) }
  })

  it('localCaseFolder：在 <用户目录>\\连越律师工作台 下建好并回位置', async () => {
    const { r, calls } = remote({ exists: () => false })
    expect(await r.localCaseFolder({ name: '张某甲诈骗案' })).toEqual({ ok: true, value: { path: join('C:\\Users\\x', '连越律师工作台', '张某甲诈骗案') } })
    expect(calls).toEqual([['mkdir', join('C:\\Users\\x', '连越律师工作台', '张某甲诈骗案')]])
  })
})

void existsSync
