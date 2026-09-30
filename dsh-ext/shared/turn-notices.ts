// 一轮被拦下的原因（ORCH 注记 2026-09-30 13:18：1.2 语义下 INPUT_CHANGED 要在输入区提示）。
// Agent 插件在 /core/task/begin 或 /core/context 失败、拒绝整轮时记下错误码；DSH 的 reject 不能带消息，
// 界面经 Host 远程方法 turnNotice 取走（取一次即删）。只记错误码，不记内容（Spec 4.5）。

const MAX = 200

export class TurnNotices {
  private readonly codes = new Map<string, string>()

  /** 记下某会话这一轮被拦下的错误码（同一会话只留最新的；超过上限丢最早的）。 */
  note(sessionId: string, code: string): void {
    this.codes.delete(sessionId)
    this.codes.set(sessionId, code)
    if (this.codes.size > MAX) this.codes.delete(this.codes.keys().next().value!)
  }

  /** 取走某会话记下的错误码；没有返回 null。 */
  take(sessionId: string): string | null {
    const code = this.codes.get(sessionId) ?? null
    this.codes.delete(sessionId)
    return code
  }
}
