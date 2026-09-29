// 任务单（/api/task）的写入与"被取走"判断（T13 返修 P2-1、P2-3，第二次返修 F1、F4）。
// 不变量：输入区显示的选择 = 下一条消息实际会用的任务单。
// 服务的语义（线 B service/lawbench/case/task.py）：每条消息开始时取该会话 created_at 最新的一张待执行任务单（精确到秒），
// 没有就按自由对话新建；其余待执行的留着；/api/tasks 只列出已开始执行的任务（有 result.json 的）。
// 所以界面要保证：它最后写的那张始终等于当前显示的选择，并且是该会话最新的一张待执行任务单。做法：
// - 选择一变就写一张（同一选择不重复写）；
// - "不知道服务那边有没有待执行的"（刚建立：软件重启、插件重载之后；或我们最后写的那张刚被取走）时选"自由对话"，也写一张
//   entry、skill 为空的，把服务那边可能残留的旧任务单压在下面（F1）；
// - 两次写入至少隔 1.1 秒，避免同一秒两张、服务取哪张不确定；
// - 怎么知道被取走：我们写的某张的 task_id 出现在 /api/tasks 里。取走的是最后写的那张，就回到"不知道"；
//   取走的是更早的那张（同一秒打平、或查询途中律师已改选），最后写的那张还是最新的，显示不变（F4）。
// 写入和查询排成一队，互不交错。

export interface SheetRequest { entry: string | null; skill: string | null; inputs: string[]; params: unknown }
export type WriteResult = { ok: true; value: { task_id: string } } | { ok: false; error: { code: string; message: string } }

export interface SheetDeps {
  write(req: SheetRequest): Promise<WriteResult>
  /** 已开始执行的任务编号；读不到时 undefined（下次再查）。 */
  started(): Promise<string[] | undefined>
  /** 当前毫秒数、等待（测试里替换）。 */
  now?: () => number
  wait?: (ms: number) => Promise<void>
}

export type SheetStatus =
  | { kind: 'none' }
  | { kind: 'ready'; label: string }
  | { kind: 'error'; error: { code: string; message: string } }

export interface Selection { capsuleId: string | null; skill: string | null; inputs: string[]; params: unknown; label: string }

/** label 为 null 表示"自由对话"单。 */
export interface Written { taskId: string; label: string | null; key: string }

export interface Consumed {
  /** 被一条消息用掉的那张（有多张时取最后写的）。 */
  used: Written
  /** 用掉的是不是我们最后写的那张（是：界面该回到自由对话；否：最后写的那张仍是下一条要用的）。 */
  latestConsumed: boolean
}

export const MIN_WRITE_GAP_MS = 1100

export const selectionKey = (sel: Pick<Selection, 'capsuleId' | 'skill' | 'inputs' | 'params'>): string =>
  JSON.stringify([sel.capsuleId, sel.skill, sel.params, sel.inputs])

export class TaskSheet {
  /** 本次运行里写过、还没见到被取走的（按写入先后）。 */
  private written: Written[] = []
  /** 最后写的那张；null 且 known 为 false 时表示"不知道服务那边有什么"。 */
  private latest: Written | null = null
  private known = false
  private lastWriteAt: number
  private queue: Promise<unknown> = Promise.resolve()
  private readonly now: () => number
  private readonly wait: (ms: number) => Promise<void>

  constructor(private readonly deps: SheetDeps) {
    this.now = deps.now ?? Date.now
    this.wait = deps.wait ?? ((ms) => new Promise((r) => setTimeout(r, ms)))
    // 上一次运行（重启、重载之前）可能刚写过一张：把"刚建立"当作刚写过，第一次写也隔开 1.1 秒，免得和它同一秒
    this.lastWriteAt = this.now()
  }

  /** 下一条消息会用的、我们写的那张（没有或不知道时 null）。 */
  get pending(): Written | null { return this.latest }

  private enqueue<T>(fn: () => Promise<T>): Promise<T> {
    const run = this.queue.then(fn, fn)
    this.queue = run.catch(() => undefined)
    return run
  }

  /** 按当前选择写（或不写）任务单。 */
  apply(sel: Selection): Promise<SheetStatus> { return this.enqueue(() => this.applyOnce(sel)) }

  private async applyOnce(sel: Selection): Promise<SheetStatus> {
    const free = sel.capsuleId === null && sel.inputs.length === 0
    const key = free ? FREE_KEY : selectionKey(sel)
    if (this.latest && this.latest.key === key) return free ? { kind: 'none' } : { kind: 'ready', label: sel.label }
    // 自由对话：确知服务那边没有我们的待执行单（刚被取走后又写过自由对话单的情形已由上面的去重处理）才不写
    if (free && this.known && this.latest === null) return { kind: 'none' }
    const gap = this.now() - this.lastWriteAt
    if (gap < MIN_WRITE_GAP_MS) await this.wait(MIN_WRITE_GAP_MS - gap)
    const r = await this.deps.write({ entry: sel.capsuleId, skill: free ? null : sel.skill, inputs: sel.inputs, params: sel.params })
    this.lastWriteAt = this.now()
    if (!r.ok) return { kind: 'error', error: r.error }
    const w: Written = { taskId: r.value.task_id, label: free ? null : sel.label, key }
    this.written.push(w)
    this.latest = w
    this.known = true
    return free ? { kind: 'none' } : { kind: 'ready', label: sel.label }
  }

  /** 查一次有没有我们写的任务单被取走。 */
  poll(): Promise<Consumed | null> { return this.enqueue(() => this.pollOnce()) }

  private async pollOnce(): Promise<Consumed | null> {
    if (this.written.length === 0) return null
    const ids = await this.deps.started()
    if (!ids) return null
    const gone = this.written.filter((w) => ids.includes(w.taskId))
    if (gone.length === 0) return null
    this.written = this.written.filter((w) => !ids.includes(w.taskId))
    const used = gone[gone.length - 1]!
    const latestConsumed = this.latest !== null && gone.includes(this.latest)
    if (latestConsumed) {
      this.latest = null
      this.known = false // 服务那边可能还有更早的待执行单（本次或上次运行留下的），下次选自由对话要再写一张压住
    }
    return { used, latestConsumed }
  }
}

/** 按会话各一份（会话之间互不影响）。 */
const sheets = new Map<string, TaskSheet>()
export function sheetFor(sessionId: string, deps: SheetDeps): TaskSheet {
  let s = sheets.get(sessionId)
  if (!s) { s = new TaskSheet(deps); sheets.set(sessionId, s) }
  return s
}

/**
 * 任务单被取走后界面怎么办（输入区用；抽出来便于按操作顺序测试）。
 * @param currentKey - 此刻输入区显示的选择的 key（selectionKey，自由对话用规整后的 key）。
 * @param currentLabel - 此刻显示的选择的名称。
 */
export function afterConsumed(c: Consumed, currentKey: string, currentLabel: string): { resetToFree: boolean; writeFree: boolean; text: string | null } {
  const ran = c.used.label ?? '自由对话'
  if (!c.latestConsumed) return { resetToFree: false, writeFree: false, text: `上一条已按「${ran}」运行；下一条按「${currentLabel}」` }
  if (c.used.key !== currentKey) return { resetToFree: false, writeFree: false, text: `上一条已按「${ran}」运行` }
  if (c.used.label === null) return { resetToFree: false, writeFree: true, text: null }
  return { resetToFree: true, writeFree: true, text: `上一条已按「${ran}」运行；下一条按自由对话，要继续用请重新选择` }
}

/** 自由对话选择的 key（规整：自由对话不看参数）。 */
export const FREE_KEY = selectionKey({ capsuleId: null, skill: null, inputs: [], params: null })
