// 工作台服务的启动和看护（Spec 1.3；T7 执行令 Q4 与"T4 转来的事项"第 4 条）。
// 纯逻辑，进程启动、探测、计时都由调用方注入，便于测试。
// - 每 5 秒探测 /health；进程退出或连续 3 次没有响应就重启；
// - 1 分钟内重启超过 3 次就停止重启，状态记为 failed（界面提示"工作台服务异常"，由 T13 显示）；
// - 启动后比对 contract_version，不一致记为 version_mismatch，不继续（"组件版本不一致，请重新安装"）；
// - 端口由 Host 自己挑（服务不支持 --port 0）；退出码 2 = 端口绑定失败，换端口重启且不计入重启次数；
// - 退出码 3 = 被信号停止。是否重启看是谁停的，不看退出码：Host 自己发起的停止（stop()）不重启；
//   不是 Host 发起的（包括退出码 3）照常重启，并计入 1 分钟内的重启次数（T7 返修令第 4 节）。

export interface ChildHandle {
  readonly pid: number | undefined
  /** 进程结束时 resolve 退出码（被信号结束时可能是 null）。 */
  readonly exited: Promise<number | null>
  kill(): void
}

export interface SupervisorDeps {
  spawn(port: number, token: string): ChildHandle
  /** 探测 /health；成功返回 contract_version，失败返回 undefined。 */
  probe(port: number): Promise<string | undefined>
  pickPort(): Promise<number>
  newToken(): string
  expectedVersion: string
  log(level: 'info' | 'warn' | 'error', event: string, meta?: Record<string, unknown>): void
  now?(): number
  setTimer?(fn: () => void, ms: number): unknown
  clearTimer?(handle: unknown): void
}

export type SupervisorState = 'stopped' | 'starting' | 'running' | 'failed' | 'version_mismatch'

export const PROBE_INTERVAL_MS = 5_000
export const MAX_MISSED_PROBES = 3
export const RESTART_WINDOW_MS = 60_000
export const MAX_RESTARTS_IN_WINDOW = 3
export const EXIT_PORT_IN_USE = 2
export const EXIT_SIGNALLED = 3
const MAX_PORT_RETRIES = 5
const STARTUP_TIMEOUT_MS = 30_000

export class Supervisor {
  state: SupervisorState = 'stopped'
  port: number | undefined
  token: string | undefined
  private child: ChildHandle | undefined
  private timer: unknown
  private missed = 0
  private restarts: number[] = []
  private stopping = false
  private generation = 0
  private readonly listeners = new Set<(s: SupervisorState) => void>()

  constructor(private readonly deps: SupervisorDeps) {}

  private now(): number { return this.deps.now?.() ?? Date.now() }
  private setTimer(fn: () => void, ms: number): unknown { return (this.deps.setTimer ?? setTimeout)(fn, ms) }
  private clearTimer(h: unknown): void { if (h !== undefined) (this.deps.clearTimer ?? ((x: unknown) => clearTimeout(x as ReturnType<typeof setTimeout>)))(h) }

  onState(fn: (s: SupervisorState) => void): () => void { this.listeners.add(fn); return () => this.listeners.delete(fn) }
  private setState(s: SupervisorState): void {
    if (this.state === s) return
    this.state = s
    this.deps.log(s === 'failed' || s === 'version_mismatch' ? 'error' : 'info', 'service.state', { state: s })
    for (const fn of this.listeners) fn(s)
  }

  /** 当前可用的端点；服务没在正常运行时返回 undefined。 */
  endpoint(): { port: number; token: string } | undefined {
    return this.state === 'running' && this.port !== undefined && this.token !== undefined ? { port: this.port, token: this.token } : undefined
  }

  async start(): Promise<void> {
    this.stopping = false
    this.restarts = []
    // 首次启动挑端口就失败时也设为 failed，不停在 starting（T7 第二次返修 F3；异常在 launch 内按代次处理）
    await this.launch(0)
  }

  stop(): void {
    this.stopping = true
    this.clearTimer(this.timer)
    this.timer = undefined
    this.child?.kill()
    this.child = undefined
    this.setState('stopped')
  }

  /**
   * 拉起一次服务。launch 自己接住异常（T7 第三轮 P3-2：带上代次比对）：
   * 只有仍是当前代次、且不在停止中时才把状态设为 failed，旧代次的失败只记日志，不覆盖新一代的状态。
   */
  private async launch(portRetries: number): Promise<void> {
    if (this.stopping) return
    const gen = ++this.generation
    try {
      await this.launchInner(gen, portRetries)
    } catch (e) {
      this.deps.log('error', 'service.launch_failed', { error: String((e as Error)?.message ?? e) })
      if (!this.stopping && gen === this.generation) this.setState('failed')
    }
  }

  private async launchInner(gen: number, portRetries: number): Promise<void> {
    this.setState('starting')
    const port = await this.deps.pickPort()
    // T7 返修 P3-2：挑端口期间可能已 stop() 或已换代，此时不再拉起进程
    if (this.stopping || gen !== this.generation) return
    this.port = port
    this.token = this.deps.newToken()
    this.missed = 0
    const child = this.deps.spawn(this.port, this.token)
    this.child = child
    this.deps.log('info', 'service.spawn', { pid: child.pid, port: this.port })
    void child.exited.then((code) => this.onExit(gen, code, portRetries))

    // 等首次 /health 通过再比对版本
    const deadline = this.now() + STARTUP_TIMEOUT_MS
    while (gen === this.generation && !this.stopping && this.now() < deadline) {
      const v = await this.deps.probe(this.port)
      if (gen !== this.generation || this.stopping) return
      if (v !== undefined) {
        if (v !== this.deps.expectedVersion) {
          this.deps.log('error', 'service.version_mismatch', { expected: this.deps.expectedVersion, actual: v })
          this.generation++
          child.kill()
          this.child = undefined
          this.setState('version_mismatch')
          return
        }
        this.setState('running')
        this.schedulePing(gen)
        return
      }
      await new Promise((r) => setTimeout(r, 500))
    }
    if (gen === this.generation && !this.stopping) {
      this.deps.log('warn', 'service.startup_timeout', {})
      child.kill()
    }
  }

  private schedulePing(gen: number): void {
    this.timer = this.setTimer(() => { void this.ping(gen) }, PROBE_INTERVAL_MS)
  }

  private async ping(gen: number): Promise<void> {
    if (gen !== this.generation || this.stopping || this.port === undefined) return
    const v = await this.deps.probe(this.port)
    if (gen !== this.generation || this.stopping) return
    if (v === undefined) {
      this.missed += 1
      this.deps.log('warn', 'service.probe_missed', { missed: this.missed })
      if (this.missed >= MAX_MISSED_PROBES) {
        this.child?.kill() // 由 onExit 负责重启
        return
      }
    } else {
      this.missed = 0
    }
    this.schedulePing(gen)
  }

  private onExit(gen: number, code: number | null, portRetries: number): void {
    if (gen !== this.generation) return
    this.clearTimer(this.timer)
    this.timer = undefined
    this.child = undefined
    this.deps.log(code === 0 || this.stopping ? 'info' : 'warn', 'service.exit', { code })
    if (this.stopping || this.state === 'version_mismatch') return
    if (code === EXIT_PORT_IN_USE && portRetries < MAX_PORT_RETRIES) {
      this.relaunch(portRetries + 1)
      return
    }
    const t = this.now()
    this.restarts = this.restarts.filter((x) => t - x < RESTART_WINDOW_MS)
    if (this.restarts.length >= MAX_RESTARTS_IN_WINDOW) {
      this.setState('failed')
      return
    }
    this.restarts.push(t)
    this.deps.log('info', 'service.restart', { attempt: this.restarts.length })
    this.relaunch(0)
  }

  /** 重启：launch 自己按代次处理异常（见 launch）。 */
  private relaunch(portRetries: number): void {
    void this.launch(portRetries)
  }
}
