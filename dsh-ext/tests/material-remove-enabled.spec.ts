// 注记 0934 ④（复核 rv-A48）：materialRemove 开关打开时的正向用例。开关在 shared/feature-flags.ts 里关着（服务能从检索里去掉之前不开），
// 这里单独一个文件把它模拟成开，验证打开后的流程：核对 case_id 与案件根是服务登记的同一个，删文件后重新扫描；对不上不删。
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { LawbenchRemote } from '../host/index.ts'
import type { DeskDeps } from '../host/desk-actions.ts'
import type { Supervisor } from '../host/supervisor.ts'

vi.mock('../shared/feature-flags.ts', async (importOriginal: () => Promise<Record<string, unknown>>) => ({ ...(await importOriginal()), MATERIAL_REMOVE_ENABLED: true }))

const up = { endpoint: () => ({ port: 1, token: 't' }), state: 'running' } as unknown as Supervisor
function remote(api: Record<string, (body: unknown) => unknown>) {
  const r = new LawbenchRemote(up, tmpdir(), () => undefined)
  const calls: Array<[string, unknown]> = []
  r.desk = { installDir: 'E:\\law', userProfile: 'C:\\Users\\x', exists: () => true, isDir: () => true, openable: () => ({ ok: true, value: '' }), launch: async () => undefined, openPath: async () => undefined, remove: async (f) => { calls.push(['remove', f]) }, mkdir: async () => undefined } as DeskDeps
  ;(r as unknown as { callApi: (route: { method: string }, body: unknown) => Promise<unknown> }).callApi = async (route, body) => {
    calls.push([route.method, body])
    return api[route.method] ? { ok: true, value: api[route.method]!(body) } : { ok: false, error: { code: 'X', message: 'x' } }
  }
  return { r, calls }
}

it('开关打开时：核对 case_id 与案件根是服务登记的同一个，删文件后重新扫描；对不上不删', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'lb-desk-'))
  try {
    const root = join(dir, '甲案')
    mkdirSync(join(root, '02 案件材料'), { recursive: true })
    writeFileSync(join(root, '02 案件材料', '起诉书.pdf'), 'x')
    const api = { caseRecent: () => ({ cases: [{ case_id: 'c-1', root, name: '甲案', exists: true }] }), materialsScan: () => ({ added: 0, changed: 0, removed: 1, failed: 0, review_needed: true }) }
    const ok = remote(api)
    expect(await ok.r.materialRemove({ case_id: 'c-1', root, rel_path: '02 案件材料\\起诉书.pdf' })).toEqual({ ok: true, value: { added: 0, changed: 0, removed: 1, failed: 0, review_needed: true } })
    expect(ok.calls.map((c) => c[0])).toEqual(['caseRecent', 'remove', 'materialsScan'])
    expect(ok.calls[1]![1]).toBe(join(root, '02 案件材料', '起诉书.pdf'))
    const wrong = remote(api)
    expect((await wrong.r.materialRemove({ case_id: 'c-1', root: join(dir, '别的'), rel_path: '02 案件材料\\起诉书.pdf' })).ok).toBe(false)
    expect((await wrong.r.materialRemove({ case_id: 'c-2', root, rel_path: '02 案件材料\\起诉书.pdf' })).ok).toBe(false)
    expect((await wrong.r.materialRemove({ case_id: 'c-1', root, rel_path: '..\\外面.pdf' })).ok).toBe(false)
    expect(wrong.calls.map((c) => c[0])).not.toContain('remove')
  } finally { rmSync(dir, { recursive: true, force: true }) }
})
