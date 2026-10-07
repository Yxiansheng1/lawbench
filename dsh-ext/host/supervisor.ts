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
  /** 进程的标准错误输出（收集到的尾部）；进程结束后读，用来说清楚为什么没起来（令 2048）。 */
  errorText?(): string
}

export interface SupervisorDeps {
  spawn(port: number, token: string): ChildHandle
  /** 探测 /health；成功返回 contract_version，失败返回 undefined。 */
  probe(port: number): Promise<string | undefined>
  pickPort(): Promise<number>
  newToken(): string
  expectedVersion: string
  log(level: 'info' | 'warn' | 'error', event: string, meta?: Record<string, unknown>): void
  /** 把服务标准错误里的路径换掉（安装目录换成"<安装目录>"）；不给就按原样取最后的异常行。 */
  scrubPaths?(text: string): string
  /**
   * 服务的本机转发端口（固定，Spec 15）。退出码 2 是"有一个监听绑不上"：工作台端口每次换新的重试，
   * 重试用完仍是 2，就是这个固定端口被占（令 1556 第 2 条），原因里带上它。
   */
  forwardPort?: number
  now?(): number
  setTimer?(fn: () => void, ms: number): unknown
  clearTimer?(handle: unknown): void
}

export type SupervisorState = 'stopped' | 'starting' | 'running' | 'failed' | 'version_mismatch'

/**
 * 服务没起来的原因（令 2033：干净机上服务不启动、日志里看不出为什么）。类别、退出码；令 2048 起 exited 另带服务标准错误
 * 末条异常行（error，路径已去掉，见 lastErrorLine），不带整段输出。
 * - launch_error：进程没能拉起（找不到程序、被拦截等，detail 是错误类名或 Host 给的代码）；
 * - exited：进程退出（还没就绪或运行中）；
 * - startup_timeout：30 秒内 /health 没通过。
 */
export interface StartFailure { reason: 'launch_error' | 'exited' | 'startup_timeout'; detail?: string; exitCode?: number | null; error?: string; port?: number }

export const PROBE_INTERVAL_MS = 5_000
export const MAX_MISSED_PROBES = 3
export const RESTART_WINDOW_MS = 60_000
export const MAX_RESTARTS_IN_WINDOW = 3
export const EXIT_PORT_IN_USE = 2
export const EXIT_SIGNALLED = 3
const MAX_PORT_RETRIES = 5
const STARTUP_TIMEOUT_MS = 30_000
/** 连续几次 30 秒没就绪就不再重启、记为 failed（复核 P2-1：每轮 ≥30 秒，"1 分钟内超过 3 次"的限额永远攒不满）。 */
export const MAX_STARTUP_TIMEOUTS = 2

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
  /** 最近一次没起来的原因；起来了就清掉。 */
  lastFailure: StartFailure | undefined
  /** 哪一代是因为 30 秒没就绪被 Host 杀掉的（它退出时原因仍记"没就绪"，不记成"退出"）。 */
  private timedOutGen = -1
  /** 连续没就绪的次数；起来了就清零。 */
  private startupTimeouts = 0
  private exitingChild: ChildHandle | undefined

  constructor(private readonly deps: SupervisorDeps) {}

  private now(): number { return this.deps.now?.() ?? Date.now() }
  private setTimer(fn: () => void, ms: number): unknown { return (this.deps.setTimer ?? setTimeout)(fn, ms) }
  private clearTimer(h: unknown): void { if (h !== undefined) (this.deps.clearTimer ?? ((x: unknown) => clearTimeout(x as ReturnType<typeof setTimeout>)))(h) }

  onState(fn: (s: SupervisorState) => void): () => void { this.listeners.add(fn); return () => this.listeners.delete(fn) }
  private setState(s: SupervisorState): void {
    if (this.state === s) return
    this.state = s
    this.deps.log(s === 'failed' || s === 'version_mismatch' ? 'error' : 'info', 'service.state', { state: s })
    if (s === 'running') { this.lastFailure = undefined; this.startupTimeouts = 0 }
    // 重启也救不回来：留一条带原因的记录（令 2033）
    if (s === 'failed') this.deps.log('error', 'service.start_failed', { ...(this.lastFailure ?? { reason: 'unknown' }) })
    for (const fn of this.listeners) fn(s)
  }

  /** 当前可用的端点；服务没在正常运行时返回 undefined。 */
  endpoint(): { port: number; token: string } | undefined {
    return this.state === 'running' && this.port !== undefined && this.token !== undefined ? { port: this.port, token: this.token } : undefined
  }

  async start(): Promise<void> {
    this.stopping = false
    this.restarts = []
    this.startupTimeouts = 0
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
      this.lastFailure = { reason: 'launch_error', detail: launchErrorKind(e) }
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
    void child.exited.then((code) => this.onExit(gen, code, portRetries, child))

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
      this.lastFailure = { reason: 'startup_timeout' }
      this.timedOutGen = gen
      this.startupTimeouts += 1
      if (this.startupTimeouts >= MAX_STARTUP_TIMEOUTS) {
        // 不再重启：先换代，进程退出时 onExit 不再接手重启
        this.generation++
        child.kill()
        this.child = undefined
        this.setState('failed')
        return
      }
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

  private onExit(gen: number, code: number | null, portRetries: number, child?: ChildHandle): void {
    if (gen !== this.generation) return
    this.exitingChild = child
    this.clearTimer(this.timer)
    this.timer = undefined
    this.child = undefined
    this.deps.log(code === 0 || this.stopping ? 'info' : 'warn', 'service.exit', { code })
    if (this.stopping || this.state === 'version_mismatch') return
    if (this.timedOutGen !== gen) {
      const error = lastErrorLine(this.exitingChild?.errorText?.() ?? '', this.deps.scrubPaths)
      const port = code === EXIT_PORT_IN_USE && this.deps.forwardPort !== undefined ? { port: this.deps.forwardPort } : {}
      this.lastFailure = { reason: 'exited', exitCode: code, ...(error ? { error } : {}), ...port }
    }
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

/** 拉起失败的类别：Host 自己给的代码（如 PYTHON_MISSING）优先，其次系统错误码（ENOENT、EACCES、EPERM…），再次错误类名。 */
export function launchErrorKind(e: unknown): string {
  const err = e as { code?: unknown; name?: unknown } | null
  if (err && typeof err.code === 'string' && /^[A-Z_]{2,40}$/.test(err.code)) return err.code
  return err && typeof err.name === 'string' && /^[A-Za-z]{1,40}$/.test(err.name) ? err.name : 'Error'
}

/** 给律师看的原因（首次配置页"测试连接"、首页）。 */
export function startFailureText(f: StartFailure | undefined): string {
  if (!f) return '原因不明'
  if (f.reason === 'startup_timeout') return '30 秒内没有就绪'
  // 服务把 uvicorn 的出错日志关了（不记全文），绑定失败时标准错误里没有"address already in use"，只有退出码 2
  if (f.reason === 'exited' && f.exitCode === EXIT_PORT_IN_USE && f.port !== undefined) return `本机 ${f.port} 端口被其他程序占用，请关闭占用程序后重试`
  if (f.reason === 'exited') return f.error ?? `服务启动后退出（代码 ${f.exitCode ?? '无'}）`
  if (f.detail === 'PYTHON_MISSING') return '找不到内置的 Python'
  if (f.detail === 'EACCES' || f.detail === 'EPERM') return '程序被拒绝运行（可能被安全软件拦截）'
  if (f.detail === 'ENOENT') return '找不到要运行的程序'
  return `程序没能运行（${f.detail ?? '未知错误'}）`
}

/**
 * 服务标准错误最后 20 行里最后一条"异常类名: 消息"（Python 回溯的末行，如
 * "ImportError: DLL load failed while importing _sqlite3: 应用程序控制策略已阻止此文件。"）。
 * 只要这一行，不要整段回溯；路径交 scrub 换掉，最长 300 字。找不到异常行返回 undefined。
 */
export function lastErrorLine(text: string, scrub: (t: string) => string = (t) => t): string | undefined {
  const lines = text.split(/\r?\n/).map((l) => l.trim()).filter(Boolean).slice(-20)
  for (let i = lines.length - 1; i >= 0; i--) {
    const m = /^([A-Za-z_][\w.]*(?:Error|Exception|Exit|Interrupt)):\s*(.*)$/.exec(lines[i]!)
    if (m) return scrub(`${m[1]}: ${m[2]}`).slice(0, 300)
  }
  return undefined
}
