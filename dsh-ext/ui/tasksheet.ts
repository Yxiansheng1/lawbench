// 任务单（/api/task）的写入与"被取走"判断（T13 返修 P2-1、P2-3）。
// 一张任务单管一条消息（Spec 9.2：插件在每条消息开始时取该会话最新的待执行任务单，没有就按自由对话新建）。
// - 选了胶囊（或选了前序成果）：写一张；
// - 切回"自由对话"时，若本会话有我们写的、还没被取走的任务单，再写一张 entry、skill 为空的（P2-1），
//   否则下一条消息会拿到旧的那张、按旧 Skill 跑；没有待执行的就不写（插件本来就按自由对话新建）；
// - 怎么知道"被取走"：/api/tasks 只列出已开始执行的任务（有 result.json 的，线 B 的 TaskStore.list），
//   我们写的那张的 task_id 出现在列表里，就说明已被一条消息用掉（P2-3，不改契约、不改 DSH 源码）。

export interface SheetRequest { entry: string | null; skill: string | null; inputs: string[]; params: unknown }
export type WriteResult = { ok: true; value: { task_id: string } } | { ok: false; error: { code: string; message: string } }

export interface SheetDeps {
  write(req: SheetRequest): Promise<WriteResult>
  /** 已开始执行的任务编号；读不到时 undefined（下次再查）。 */
  started(): Promise<string[] | undefined>
}

export type SheetStatus =
  | { kind: 'none' }
  | { kind: 'ready'; label: string }
  | { kind: 'error'; error: { code: string; message: string } }

export interface Selection { capsuleId: string | null; skill: string | null; inputs: string[]; params: unknown; label: string }

/** label 为 null 表示待执行的那张是"自由对话"单。 */
export interface Pending { taskId: string; label: string | null }

export class TaskSheet {
  pending: Pending | null = null
  private queue: Promise<unknown> = Promise.resolve()
  constructor(private readonly deps: SheetDeps) {}

  /** 按当前选择写（或不写）任务单。串行执行，后一次等前一次写完。 */
  apply(sel: Selection): Promise<SheetStatus> {
    const run = this.queue.then(() => this.applyOnce(sel), () => this.applyOnce(sel))
    this.queue = run.catch(() => undefined)
    return run
  }

  private async applyOnce(sel: Selection): Promise<SheetStatus> {
    const free = sel.capsuleId === null && sel.inputs.length === 0
    // 自由对话：没有待执行的，或待执行的本来就是自由对话单——不用写
    if (free && (this.pending === null || this.pending.label === null)) return { kind: 'none' }
    const r = await this.deps.write({ entry: sel.capsuleId, skill: free ? null : sel.skill, inputs: sel.inputs, params: sel.params })
    if (!r.ok) return { kind: 'error', error: r.error }
    this.pending = { taskId: r.value.task_id, label: free ? null : sel.label }
    return free ? { kind: 'none' } : { kind: 'ready', label: sel.label }
  }

  /** 查一次待执行的那张是否已被取走；取走了返回它（并清掉 pending），否则 null。 */
  async poll(): Promise<Pending | null> {
    const p = this.pending
    if (!p) return null
    const ids = await this.deps.started()
    if (!ids || !ids.includes(p.taskId) || this.pending !== p) return null
    this.pending = null
    return p
  }
}

/** 按会话各一份（会话之间互不影响）。 */
const sheets = new Map<string, TaskSheet>()
export function sheetFor(sessionId: string, deps: SheetDeps): TaskSheet {
  let s = sheets.get(sessionId)
  if (!s) { s = new TaskSheet(deps); sheets.set(sessionId, s) }
  return s
}
