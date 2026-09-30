// 输入区选择与服务端"当前选择"的同步（契约 1.2，N37 用户定；执行令 2026-09-30 10:54）。
// 服务的语义：POST /api/task 设置该会话当前的选择（新的顶掉旧的），执行时不消耗，之后每条消息都按它运行，直到下一次设置或清除；
// GET /api/task/current 读回。界面不再自己记"写过哪张""被取走没有"：显示之前从服务读，律师改动时写，写成功之前显示"正在保存"。
// 本文件只放不碰界面的逻辑（dock.tsx 用），便于按操作顺序测试。

export interface SheetRequest { entry: string | null; skill: string | null; inputs: string[]; params: unknown }
export type ApiError = { code: string; message: string }
export type WriteResult = { ok: true; value: { task_id: string } } | { ok: false; error: ApiError }
export interface ServerSelection { task_id: string; entry: string | null; skill: string | null; inputs: string[]; params: unknown; updated_at: string }
export type CurrentResult = { ok: true; value: { selection: ServerSelection | null } } | { ok: false; error: ApiError }

export interface SheetDeps {
  write(req: SheetRequest): Promise<WriteResult>
  current(): Promise<CurrentResult>
}

/** 输入区里的一份选择（胶囊为 null 且没有选用成果即自由对话）。 */
export interface UiSelection { capsuleId: string | null; skill: string | null; inputs: string[]; params: unknown }

export const isFree = (s: Pick<UiSelection, 'capsuleId' | 'inputs'>): boolean => s.capsuleId === null && s.inputs.length === 0

/** 比较用的键：自由对话不看 Skill，但看参数（1.2 起选择一直生效，自由对话里改"思考""窗口"也要写，复核 A6）。 */
export const selectionKey = (s: UiSelection): string =>
  isFree(s) ? JSON.stringify(['free', s.params]) : JSON.stringify([s.capsuleId, s.skill, s.params, s.inputs])

/** 界面选择 → 写给服务的请求（自由对话：entry、skill 都为 null）。 */
export function toRequest(s: UiSelection): SheetRequest {
  const free = isFree(s)
  return { entry: s.capsuleId, skill: free ? null : s.skill, inputs: s.inputs, params: s.params }
}

/** 服务返回的当前选择 → 界面选择（null：自由对话或还没设置过）。 */
export function fromServer(sel: ServerSelection | null): UiSelection {
  if (!sel) return { capsuleId: null, skill: null, inputs: [], params: null }
  return { capsuleId: sel.entry, skill: sel.skill, inputs: sel.inputs, params: sel.params }
}

export type SheetStatus =
  | { kind: 'loading' }
  | { kind: 'saving' }
  | { kind: 'error'; error: ApiError }
  | { kind: 'free' }
  | { kind: 'ready'; label: string }
  | { kind: 'notice'; text: string }

/**
 * 状态行显示什么。
 * @param saved - 当前显示的选择是否已经和服务一致（刚读回，或写成功且之后没再改）。
 * @param error - 最近一次写入或读取失败的错误，且失败的就是当前显示的这份选择。
 */
export function statusOf(sel: UiSelection | undefined, saved: boolean, error: ApiError | null, label: string): SheetStatus {
  if (error) return { kind: 'error', error }
  if (!sel) return { kind: 'loading' }
  if (!saved) return { kind: 'saving' }
  return isFree(sel) ? { kind: 'free' } : { kind: 'ready', label }
}

export function statusText(st: SheetStatus): string {
  switch (st.kind) {
    case 'loading': return '正在读取当前选择…'
    case 'saving': return '正在保存选择…'
    case 'error': return st.error.message
    case 'free': return '自由对话'
    case 'ready': return `下一条消息按「${st.label}」运行（直到你改掉）`
    case 'notice': return st.text
  }
}

/**
 * 会话列表变化时找出"一轮刚结束"的会话，并更新记录（index.tsx 用）：
 * running 由真变假；或者一直没看到在跑、但会话的 updatedAt 变了（一轮很短、被拦下时 running 的翻转可能被合并掉，
 * ORCH 注记 2026-09-30 13:18 的 INPUT_CHANGED 就是这样）。多报一次只是多读一次服务，无害。
 * @param running - 上一次看到的各会话 running（原地更新）。
 * @param updated - 上一次看到的各会话 updatedAt（原地更新）。
 */
export function turnEnds(running: Map<string, boolean>, byId: Record<string, { running?: boolean; updatedAt?: number } | undefined>, updated: Map<string, number> = new Map()): string[] {
  const ended: string[] = []
  for (const [id, s] of Object.entries(byId)) {
    const now = s?.running === true
    const was = running.get(id) === true
    const at = s?.updatedAt
    const touched = at !== undefined && updated.has(id) && updated.get(id) !== at
    if ((was && !now) || (!was && !now && touched)) ended.push(id)
    running.set(id, now)
    if (at !== undefined) updated.set(id, at)
  }
  return ended
}

/** 读和写排成一队，互不交错：读总是看到在它之前排队的写的结果。 */
export class SelectionSync {
  private queue: Promise<unknown> = Promise.resolve()
  constructor(private readonly deps: SheetDeps) {}
  private enqueue<T>(fn: () => Promise<T>): Promise<T> {
    const run = this.queue.then(fn, fn)
    this.queue = run.catch(() => undefined)
    return run
  }
  save(s: UiSelection): Promise<WriteResult> { return this.enqueue(() => this.deps.write(toRequest(s))) }
  current(): Promise<CurrentResult> { return this.enqueue(() => this.deps.current()) }
}
