// T13 返修 P2-1、P2-3：任务单写入与"被取走"判断。
// 用一个模拟服务照线 B 的语义（service/lawbench/case/task.py）：begin 取该会话最新的一张 pending，没有就按自由对话新建；
// /api/tasks 只列出已开始执行的任务。
import { TaskSheet, type SheetRequest, type Selection } from '../ui/tasksheet.ts'

class FakeService {
  private seq = 0
  sheets: Array<{ id: string; req: SheetRequest; state: 'pending' | 'running' }> = []
  begun: Array<{ id: string; entry: string | null; skill: string | null }> = []
  failWrite = false
  deps = {
    write: async (req: SheetRequest) => {
      if (this.failWrite) return { ok: false as const, error: { code: 'SERVICE_UNAVAILABLE', message: '工作台服务未启动，请稍后重试' } }
      const id = `T-20260930120000-${(++this.seq).toString(16).padStart(4, '0')}`
      this.sheets.push({ id, req, state: 'pending' })
      return { ok: true as const, value: { task_id: id } }
    },
    started: async () => this.begun.map((b) => b.id),
  }
  /** 一条消息：取最新的 pending（线 B 的 _pending_for），没有就按自由对话新建。 */
  message(): { entry: string | null; skill: string | null } {
    const pending = this.sheets.filter((s) => s.state === 'pending')
    const latest = pending[pending.length - 1]
    if (latest) {
      latest.state = 'running'
      this.begun.push({ id: latest.id, entry: latest.req.entry, skill: latest.req.skill })
      return { entry: latest.req.entry, skill: latest.req.skill }
    }
    const id = `T-20260930120000-f${(++this.seq).toString(16).padStart(3, '0')}`
    this.begun.push({ id, entry: null, skill: null })
    return { entry: null, skill: null }
  }
}

const P = { thinking: '中', window: '128K', max_tokens: 16384 }
const capsule = (id: string, skill: string, label: string): Selection => ({ capsuleId: id, skill, inputs: [], params: P, label })
const free: Selection = { capsuleId: null, skill: null, inputs: [], params: P, label: '自由对话' }

describe('任务单：一张管一条消息', () => {
  it('P2-1 选了胶囊又切回自由对话：再写一张自由对话单，下一条消息按自由对话跑', async () => {
    const svc = new FakeService()
    const sheet = new TaskSheet(svc.deps)
    expect((await sheet.apply(capsule('contract-review', 'contract-review', '合同审查'))).kind).toBe('ready')
    expect((await sheet.apply(free)).kind).toBe('none')
    expect(svc.sheets.at(-1)!.req).toMatchObject({ entry: null, skill: null, inputs: [] })
    expect(svc.message()).toEqual({ entry: null, skill: null })
  })

  it('没有待执行的任务单时选自由对话：不写', async () => {
    const svc = new FakeService()
    const sheet = new TaskSheet(svc.deps)
    await sheet.apply(free)
    expect(svc.sheets).toHaveLength(0)
    expect(svc.message()).toEqual({ entry: null, skill: null })
  })

  it('P2-3 消息取走任务单后：poll 报出按哪个胶囊跑的，之后自由对话不再写，下一条确实是自由对话', async () => {
    const svc = new FakeService()
    const sheet = new TaskSheet(svc.deps)
    await sheet.apply(capsule('case-analysis', 'criminal-reading-notes', '案卷分析'))
    expect(await sheet.poll()).toBeNull() // 还没发消息
    expect(svc.message()).toEqual({ entry: 'case-analysis', skill: 'criminal-reading-notes' })
    expect(await sheet.poll()).toMatchObject({ label: '案卷分析' })
    expect(sheet.pending).toBeNull()
    // 界面随即复位成自由对话：不再写单子；下一条消息按自由对话新建
    await sheet.apply(free)
    expect(svc.sheets).toHaveLength(1)
    expect(svc.message()).toEqual({ entry: null, skill: null })
  })

  it('连续换胶囊：以最后一次为准；换来换去再回到自由对话也写自由对话单', async () => {
    const svc = new FakeService()
    const sheet = new TaskSheet(svc.deps)
    await sheet.apply(capsule('a', 'sa', '甲'))
    await sheet.apply(capsule('b', 'sb', '乙'))
    expect(svc.message()).toEqual({ entry: 'b', skill: 'sb' })
    await sheet.poll()
    await sheet.apply(capsule('a', 'sa', '甲'))
    await sheet.apply(free)
    expect(svc.message()).toEqual({ entry: null, skill: null })
  })

  it('只选了前序成果、没选胶囊：也写（entry、skill 为空，带 inputs）', async () => {
    const svc = new FakeService()
    const sheet = new TaskSheet(svc.deps)
    const r = await sheet.apply({ ...free, inputs: ['工作区/任务/T-1/草稿/起诉状.md'], label: '自由对话（带选用的成果）' })
    expect(r.kind).toBe('ready')
    expect(svc.sheets[0]!.req).toMatchObject({ entry: null, skill: null, inputs: ['工作区/任务/T-1/草稿/起诉状.md'] })
  })

  it('写入失败：带回错误，不记为待执行', async () => {
    const svc = new FakeService()
    svc.failWrite = true
    const sheet = new TaskSheet(svc.deps)
    const r = await sheet.apply(capsule('a', 'sa', '甲'))
    expect(r).toMatchObject({ kind: 'error', error: { code: 'SERVICE_UNAVAILABLE' } })
    expect(sheet.pending).toBeNull()
  })

  it('两次选择几乎同时到达：串行写，最后留下的是后一次', async () => {
    const svc = new FakeService()
    const sheet = new TaskSheet(svc.deps)
    await Promise.all([sheet.apply(capsule('a', 'sa', '甲')), sheet.apply(capsule('b', 'sb', '乙'))])
    expect(sheet.pending!.label).toBe('乙')
    expect(svc.message()).toEqual({ entry: 'b', skill: 'sb' })
  })
})
