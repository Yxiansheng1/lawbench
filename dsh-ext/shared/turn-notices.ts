// 一轮被拦下的原因（ORCH 注记 2026-09-30 13:18：1.2 语义下 INPUT_CHANGED 要在输入区提示）。
// Agent 插件在 /core/task/begin 或 /core/context 失败、拒绝整轮时记下错误码；DSH 的 reject 不能带消息，
// 界面经 Host 远程方法 turnNotice 取走（取一次即删）。只记错误码，不记内容（Spec 4.5）。

const MAX = 200

export class TurnNotices {
  private readonly codes = new Map<string, string>()
  /** 到达用量上限（BUDGET_STOPPED）时一并记下任务编号，界面据此取草稿显示在对话区（T14 派修 2）。 */
  private readonly tasks = new Map<string, string>()
  /** 到顶提示后面还排着一条 TASK_END_FAILED 的会话。 */
  private readonly after = new Set<string>()

  /** 记下某会话这一轮被拦下的错误码（同一会话只留最新的；超过上限丢最早的）。 */
  note(sessionId: string, code: string, taskId?: string): void {
    // 到顶提示还没被取走时又来了"结束状态没登记上"（复核 rv-A62 P3-1）：不盖掉到顶提示（界面靠它显示草稿），排在它后面，下一次取到
    if (code === 'TASK_END_FAILED' && this.codes.get(sessionId) === 'BUDGET_STOPPED') { this.after.add(sessionId); return }
    this.after.delete(sessionId)
    this.codes.delete(sessionId)
    this.codes.set(sessionId, code)
    this.tasks.delete(sessionId)
    if (taskId !== undefined) this.tasks.set(sessionId, taskId)
    if (this.codes.size > MAX) {
      const oldest = this.codes.keys().next().value!
      this.codes.delete(oldest)
      this.tasks.delete(oldest)
    }
  }

  /** 某会话这一轮顺利开始（取任务、取上下文都成功）：清掉之前没被取走的记录，免得之后误报。 */
  clear(sessionId: string): void {
    this.after.delete(sessionId)
    this.codes.delete(sessionId)
    this.tasks.delete(sessionId)
  }

  /** 取走某会话记下的错误码；没有返回 null。 */
  take(sessionId: string): string | null {
    return this.takeWithTask(sessionId).code
  }

  /**
   * 任务单没写成的会话（T14 第二次实跑派修 2，执行令 1751）：输入区写 POST /api/task 明确失败时记上、之后写成时去掉；
   * 记着的会话 Agent 插件整轮拒绝（TASK_SHEET_FAILED），不拿服务上一张任务单发。
   */
  private readonly holds = new Set<string>()

  hold(sessionId: string, on: boolean): void {
    this.holds.delete(sessionId)
    if (on) this.holds.add(sessionId)
    if (this.holds.size > MAX) this.holds.delete(this.holds.values().next().value!)
  }

  held(sessionId: string): boolean { return this.holds.has(sessionId) }

  /** 取走错误码和随它记下的任务编号。 */
  takeWithTask(sessionId: string): { code: string | null; task_id: string | null } {
    const code = this.codes.get(sessionId) ?? null
    const taskId = this.tasks.get(sessionId) ?? null
    this.codes.delete(sessionId)
    this.tasks.delete(sessionId)
    if (this.after.delete(sessionId)) this.codes.set(sessionId, 'TASK_END_FAILED')
    return { code, task_id: taskId }
  }
}
