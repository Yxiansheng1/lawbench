// 纯聊天的默认工作区"日常事务"（执行令 1156 第 4 条，用户 N70）：首次配置后第一次取时建好并登记，设置"日常办公文件夹"为空时用
// 文档\连越律师工作台 并写回设置；之后只按记下的位置返回、文件夹不在时不重建。界面启动时当前会话不在案件里就打开它。
import { mkdtempSync, rmSync, existsSync, readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { ensureDailyCase, type DailyDeps } from '../host/daily-case.ts'
import { landOnDailyCase } from '../ui/cases.ts'
import { app, setApi, type LawbenchApi } from '../ui/state.ts'

let dir: string
beforeEach(() => { dir = mkdtempSync(join(tmpdir(), 'lb-daily-')) })
afterEach(() => { rmSync(dir, { recursive: true, force: true }); setApi(undefined) })

function deps(office: string | null, open: (p: string) => { ok: true; value: unknown } | { ok: false; error: { code: string; message: string } } = () => ({ ok: true, value: {} })) {
  const calls = { put: [] as unknown[], open: [] as string[] }
  const d: DailyDeps = {
    marker: join(dir, 'appdata-daily-case.json'),
    documents: join(dir, 'Documents'),
    getSettings: async () => ({ v: 1, office: { dir: office, invoice_buyer: null } }),
    putSettings: async (s) => { calls.put.push(s) },
    caseOpen: async (r) => { calls.open.push(r.path); return open(r.path) },
  }
  return { d, calls }
}

describe('Host：日常事务', () => {
  it('日常办公文件夹为空：建 文档\连越律师工作台\日常事务、写回设置、登记；第二次只返回记下的位置', async () => {
    const { d, calls } = deps(null)
    const r = await ensureDailyCase(d)
    const root = join(dir, 'Documents', '连越律师工作台', '日常事务')
    expect(r).toEqual({ ok: true, value: { root, created: true } })
    expect(existsSync(root)).toBe(true)
    expect(calls.open).toEqual([root])
    expect((calls.put[0] as { office: { dir: string } }).office.dir).toBe(join(dir, 'Documents', '连越律师工作台'))
    expect(JSON.parse(readFileSync(d.marker, 'utf8'))).toEqual({ root })
    expect(await ensureDailyCase(d)).toEqual({ ok: true, value: { root, created: false } })
    expect(calls.open.length).toBe(1)
  })

  it('设了日常办公文件夹：建在它下面，不改设置', async () => {
    const office = join(dir, '办公')
    const { d, calls } = deps(office)
    const r = await ensureDailyCase(d)
    expect(r.ok && r.value.root).toBe(join(office, '日常事务'))
    expect(calls.put).toEqual([])
  })

  it('登记被拒（如在云同步文件夹里）：返回错误、不记位置，下次再试', async () => {
    const { d } = deps(null, () => ({ ok: false, error: { code: 'CASE_IN_SYNC_FOLDER', message: '不能选云同步文件夹' } }))
    expect(await ensureDailyCase(d)).toEqual({ ok: false, error: { code: 'CASE_IN_SYNC_FOLDER', message: '不能选云同步文件夹' } })
    expect(existsSync(d.marker)).toBe(false)
  })

  it('记过、但文件夹已被删或搬走：返回 null，不重建（按 T17 的 CASE_MOVED 处理）', async () => {
    const { d, calls } = deps(null)
    const first = await ensureDailyCase(d)
    rmSync((first as { value: { root: string } }).value.root, { recursive: true })
    expect(await ensureDailyCase(d)).toEqual({ ok: true, value: { root: null, created: false } })
    expect(calls.open.length).toBe(1)
  })
})

describe('界面启动：落在日常事务', () => {
  const DAILY = { case_id: 'd-1', name: '日常事务', root: 'D:\文档\连越律师工作台\日常事务', exists: true }
  const REAL = { case_id: 'c-1', name: '张某甲诈骗案', root: 'D:\案件\张某甲诈骗案', exists: true }
  function api(failFirst: number) {
    let n = 0
    setApi({
      dailyCase: async () => (++n <= failFirst ? { ok: false, error: { code: 'SERVICE_UNAVAILABLE', message: '工作台服务未启动，请稍后重试' } } : { ok: true, value: { root: DAILY.root, created: n === failFirst + 1 } }),
      caseRecent: async () => ({ ok: true, value: { cases: [DAILY, REAL] } }),
    } as unknown as LawbenchApi)
  }

  it('服务前两次没就绪：接着取，当前会话不在案件里就打开日常事务（空会话可直接发送）', async () => {
    api(2)
    app.set((s) => ({ ...s, cases: [], currentRoot: null }))
    const opened: string[] = []
    expect(await landOnDailyCase(async (r) => { opened.push(r) }, async () => {})).toBe(true)
    expect(opened).toEqual([DAILY.root])
    expect(app.get().cases.map((c) => c.name)).toContain('日常事务')
  })

  it('律师正在真实案件的会话里：不切走；切到别的案件后再回日常事务由律师在侧栏点', async () => {
    api(0)
    app.set((s) => ({ ...s, cases: [], currentRoot: REAL.root }))
    const opened: string[] = []
    expect(await landOnDailyCase(async (r) => { opened.push(r) }, async () => {})).toBe(false)
    expect(opened).toEqual([])
  })
})
