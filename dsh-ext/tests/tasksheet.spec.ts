// T13 返修 P2-1、P2-3，第二次返修 F1、F4：任务单一张管一条消息；输入区显示的 = 下一条消息实际用的。
// 模拟服务照线 B 的语义（service/lawbench/case/task.py）：
// - begin 取该会话 created_at 最新的一张 pending，created_at 精确到秒；同一秒打平时取哪张不确定——这里故意取**更早写的**（最坏情况）；
// - 没有 pending 就按自由对话新建；其余 pending 一直留着（线 B 还没做"新建时作废旧单"）；
// - /api/tasks 只列出已开始执行的任务。服务重启不丢任务单（在磁盘上）。
// Harness 照 dock.tsx 的做法：选择一变就 apply；定时 poll，按 afterConsumed 的结果复位、补写自由对话单。
import { afterConsumed, FREE_KEY, selectionKey, TaskSheet, type SheetRequest, type Selection } from '../ui/tasksheet.ts'

class FakeService {
  clock = 1_000_000 // 毫秒
  private seq = 0
  sheets: Array<{ id: string; session: string; req: SheetRequest; createdSec: number; order: number; state: 'pending' | 'started' }> = []
  failWrite = false
  depsFor(session: string) {
    return {
      write: async (req: SheetRequest) => {
        if (this.failWrite) return { ok: false as const, error: { code: 'SERVICE_UNAVAILABLE', message: '工作台服务未启动，请稍后重试' } }
        const order = ++this.seq
        const id = `T-${Math.floor(this.clock / 1000)}-${order.toString(16).padStart(4, '0')}`
        this.sheets.push({ id, session, req, createdSec: Math.floor(this.clock / 1000), order, state: 'pending' })
        return { ok: true as const, value: { task_id: id } }
      },
      started: async () => this.sheets.filter((s) => s.state === 'started').map((s) => s.id),
      now: () => this.clock,
      wait: async (ms: number) => { this.clock += ms },
    }
  }
  /** 一条消息开始：取最新一张 pending（同秒取更早写的）；返回实际跑的 entry。 */
  message(session: string): string | null {
    const pending = this.sheets.filter((s) => s.session === session && s.state === 'pending')
    if (pending.length === 0) return null
    const maxSec = Math.max(...pending.map((s) => s.createdSec))
    const pick = pending.filter((s) => s.createdSec === maxSec).sort((a, b) => a.order - b.order)[0]!
    pick.state = 'started'
    return pick.req.entry
  }
}

const P = { thinking: '中', window: '128K', max_tokens: 16384 }
const FREE: Selection = { capsuleId: null, skill: null, inputs: [], params: P, label: '自由对话' }
const cap = (id: string, label = id): Selection => ({ capsuleId: id, skill: `skill-${id}`, inputs: [], params: P, label })
const keyOf = (s: Selection) => (s.capsuleId === null && s.inputs.length === 0 ? FREE_KEY : selectionKey(s))

/** 一个输入区（照 dock.tsx）。 */
class Dock {
  sel: Selection = FREE
  text: string | null = null
  sheet: TaskSheet
  constructor(private svc: FakeService, private session: string, sheet?: TaskSheet) {
    this.sheet = sheet ?? new TaskSheet(svc.depsFor(session))
  }
  /** 挂上时按当前选择走一遍（dock 的 effect 首次运行）。 */
  async mount() { await this.sheet.apply(this.sel) }
  async select(s: Selection) { this.sel = s; await this.sheet.apply(s) }
  async tick() {
    this.svc.clock += 3000
    const c = await this.sheet.poll()
    if (!c) return
    const d = afterConsumed(c, keyOf(this.sel), this.sel.label)
    if (d.resetToFree) this.sel = FREE
    if (d.writeFree) await this.sheet.apply({ ...FREE, params: this.sel.params })
    if (d.text) this.text = d.text
  }
  /** 发一条消息：先断言"显示的 = 实际跑的"。 */
  send(): string | null {
    this.svc.clock += 1500
    const shown = this.sel.capsuleId
    const ran = this.svc.message(this.session)
    expect(ran, `显示「${this.sel.label}」`).toBe(shown)
    return ran
  }
}

describe('输入区显示的 = 下一条消息实际用的（按操作顺序）', () => {
  it('S1 选 A → 发 → 轮询复位 → 再发', async () => {
    const svc = new FakeService(); const d = new Dock(svc, 's1'); await d.mount()
    await d.select(cap('A', '合同审查'))
    d.send(); await d.tick()
    expect(d.sel.capsuleId).toBeNull()
    expect(d.text).toBe('上一条已按「合同审查」运行；下一条按自由对话，要继续用请重新选择')
    d.send()
  })

  it('S2 选 A → 改选 B → 发 → 复位 → 再发（旧的 A 不会被第二条取到）', async () => {
    const svc = new FakeService(); const d = new Dock(svc, 's2'); await d.mount()
    await d.select(cap('A')); await d.select(cap('B'))
    d.send(); await d.tick(); d.send(); await d.tick(); d.send()
  })

  it('S2b A、B 很快连选（同一秒）：写入间隔保证 B 更新，发出的就是 B', async () => {
    const svc = new FakeService(); const d = new Dock(svc, 's2b'); await d.mount()
    await Promise.all([d.sheet.apply(cap('A')), (d.sel = cap('B'), d.sheet.apply(cap('B')))])
    d.send(); await d.tick(); d.send()
  })

  it('S3 选 A → 切回自由对话 → 发（P2-1）', async () => {
    const svc = new FakeService(); const d = new Dock(svc, 's3'); await d.mount()
    await d.select(cap('A')); await d.select(FREE)
    d.send()
  })

  it('S4 选 A 不发 → 软件重启（界面记录清空，服务那张还在）→ 回到该会话发（F1）', async () => {
    const svc = new FakeService()
    const before = new Dock(svc, 's4'); await before.mount(); await before.select(cap('A'))
    const after = new Dock(svc, 's4'); await after.mount() // 新的 TaskSheet：不知道服务那边有什么
    after.send(); await after.tick(); after.send()
  })

  it('S4b 重启后第一条自由对话被取走，再下一条仍是自由对话（残留的旧单一直压在下面）', async () => {
    const svc = new FakeService()
    const before = new Dock(svc, 's4b'); await before.mount(); await before.select(cap('A'))
    const after = new Dock(svc, 's4b'); await after.mount()
    after.send(); await after.tick(); after.send(); await after.tick(); after.send()
  })

  it('S4c 插件重载时正选着 A（选择也清空）：同 S4', async () => {
    const svc = new FakeService()
    const d1 = new Dock(svc, 's4c'); await d1.mount(); await d1.select(cap('A')); d1.send(); await d1.tick(); await d1.select(cap('B'))
    const d2 = new Dock(svc, 's4c'); await d2.mount()
    d2.send(); await d2.tick(); d2.send()
  })

  it('S5 选 A 不发 → 切走再切回（同一份记录、输入区重新挂载）→ 发 → 再发：不重复写', async () => {
    const svc = new FakeService(); const d = new Dock(svc, 's5'); await d.mount()
    await d.select(cap('A'))
    const remounted = new Dock(svc, 's5', d.sheet); remounted.sel = d.sel; await remounted.mount()
    expect(svc.sheets.filter((s) => s.req.entry === 'A')).toHaveLength(1)
    remounted.send(); await remounted.tick(); remounted.send()
  })

  it('S6 / F4 查询途中律师改选 B：待执行的仍是 B，显示 B，下一条跑 B', async () => {
    const svc = new FakeService()
    let release!: () => void
    const gate = new Promise<void>((r) => { release = r })
    const deps = svc.depsFor('s6')
    const sheet = new TaskSheet({ ...deps, started: async () => { await gate; return deps.started() } })
    const d = new Dock(svc, 's6', sheet); await d.mount()
    await d.select(cap('A'))
    d.send() // A 被取走
    const polling = d.tick() // 查询挂起
    d.sel = cap('B'); const writingB = sheet.apply(cap('B')) // 改选 B（排在查询之后）
    release(); await polling; await writingB
    expect(sheet.pending?.label).toBe('B')
    expect(d.sel.capsuleId).toBe('B')
    d.send()
  })

  it('S6b 先改选 B（已写）再轮询到 A 被取走：A 是更早的那张，B 仍是下一条要用的', async () => {
    const svc = new FakeService(); const d = new Dock(svc, 's6b'); await d.mount()
    await d.select(cap('A'))
    d.send()
    await d.select(cap('B'))
    await d.tick()
    expect(d.sel.capsuleId).toBe('B')
    expect(d.text).toBe('上一条已按「A」运行；下一条按「B」')
    d.send()
  })

  it('服务重启（任务单在磁盘上，界面记录还在）：照常一致', async () => {
    const svc = new FakeService(); const d = new Dock(svc, 'sr'); await d.mount()
    await d.select(cap('A'))
    d.send(); await d.tick(); d.send()
  })

  it('同一案件两个会话：选择按案件共用，任务单按会话各写各的，各自一致', async () => {
    const svc = new FakeService()
    const a = new Dock(svc, 'x1'); const b = new Dock(svc, 'x2')
    await a.mount(); await b.mount()
    await a.select(cap('A')); b.sel = a.sel; await b.mount()
    a.send(); b.send()
    await a.tick(); await b.tick()
    a.send(); b.send()
  })

  it('自由对话单被取走后，同样补写一张自由对话单（不留空档）', async () => {
    const svc = new FakeService()
    const before = new Dock(svc, 'sf'); await before.mount(); await before.select(cap('A'))
    const d = new Dock(svc, 'sf'); await d.mount()
    d.send(); await d.tick()
    expect(svc.sheets.filter((s) => s.session === 'sf' && s.state === 'pending' && s.req.entry === null).length).toBeGreaterThan(0)
    d.send()
  })

  it('只选了前序成果、没选胶囊：也写（entry、skill 为空，带 inputs）', async () => {
    const svc = new FakeService(); const sheet = new TaskSheet(svc.depsFor('si'))
    const r = await sheet.apply({ ...FREE, inputs: ['工作区/任务/T-1/草稿/起诉状.md'], label: '自由对话（带选用的成果）' })
    expect(r.kind).toBe('ready')
    expect(svc.sheets[0]!.req).toMatchObject({ entry: null, skill: null, inputs: ['工作区/任务/T-1/草稿/起诉状.md'] })
  })

  it('写入失败：带回错误，不记为待执行（状态行显示错误）', async () => {
    const svc = new FakeService(); const sheet = new TaskSheet(svc.depsFor('se'))
    svc.failWrite = true
    const r = await sheet.apply(cap('A'))
    expect(r).toMatchObject({ kind: 'error', error: { code: 'SERVICE_UNAVAILABLE' } })
    expect(sheet.pending).toBeNull()
  })

  it('同一选择再 apply 不重复写；两次写入至少隔 1.1 秒', async () => {
    const svc = new FakeService(); const sheet = new TaskSheet(svc.depsFor('sd'))
    await sheet.apply(cap('A')); await sheet.apply(cap('A'))
    expect(svc.sheets).toHaveLength(1)
    await sheet.apply(cap('B'))
    expect(svc.sheets[1]!.createdSec).toBeGreaterThan(svc.sheets[0]!.createdSec)
  })
})
