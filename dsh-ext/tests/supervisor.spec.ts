import { spawn } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { join } from 'node:path'
import { Supervisor, type ChildHandle } from '../host/supervisor.ts'

const FAKE = join(__dirname, '..', 'dev', 'fake-service.mjs')

function realDeps(ports: number[], extra: { version?: string } = {}) {
  const events: Array<{ event: string; meta?: Record<string, unknown> }> = []
  const children: ChildHandle[] = []
  let i = 0
  const deps = {
    spawn(port: number, token: string): ChildHandle {
      const c = spawn(process.execPath, [FAKE, '--port', String(port)], { env: { ...process.env, LB_TOKEN: token }, stdio: 'ignore' })
      const h: ChildHandle = { pid: c.pid, exited: new Promise((r) => c.on('exit', (code) => r(code))), kill: () => { c.kill() } }
      children.push(h)
      return h
    },
    async probe(port: number) {
      try {
        const r = await fetch(`http://127.0.0.1:${port}/health`, { signal: AbortSignal.timeout(1000) })
        return r.ok ? ((await r.json()) as { contract_version: string }).contract_version : undefined
      } catch { return undefined }
    },
    pickPort: async () => ports[i++ % ports.length],
    newToken: () => randomBytes(16).toString('hex'),
    expectedVersion: extra.version ?? '1.1',
    log: (_l: string, event: string, meta?: Record<string, unknown>) => { events.push({ event, meta }) },
  }
  return { deps, events, children }
}

const waitFor = async (cond: () => boolean, ms = 20000) => {
  const end = Date.now() + ms
  while (!cond()) { if (Date.now() > end) throw new Error('等待超时'); await new Promise((r) => setTimeout(r, 100)) }
}

describe('看护：真实进程（假服务）', () => {
  it('启动后 running；杀掉进程后 15 秒内自动重启回到 running', async () => {
    const { deps, events, children } = realDeps([18803, 18804])
    const s = new Supervisor(deps)
    await s.start()
    expect(s.state).toBe('running')
    const firstPid = children[0].pid
    const t0 = Date.now()
    children[0].kill()
    await waitFor(() => s.state === 'running' && children.length === 2, 15000)
    expect(Date.now() - t0).toBeLessThan(15000)
    expect(children[1].pid).not.toBe(firstPid)
    expect(events.some((e) => e.event === 'service.restart')).toBe(true)
    s.stop()
    expect(s.state).toBe('stopped')
  })

  it('版本不一致：停在 version_mismatch，不继续、不重启', async () => {
    const { deps, children } = realDeps([18805], { version: '9.9' })
    const s = new Supervisor(deps)
    await s.start()
    expect(s.state).toBe('version_mismatch')
    await new Promise((r) => setTimeout(r, 1500))
    expect(children).toHaveLength(1)
    expect(s.endpoint()).toBeUndefined()
  })

  it('主动 stop 后进程结束且不重启', async () => {
    const { deps, children } = realDeps([18806])
    const s = new Supervisor(deps)
    await s.start()
    s.stop()
    await children[0].exited
    await new Promise((r) => setTimeout(r, 1000))
    expect(children).toHaveLength(1)
  })
})

describe('看护：策略（模拟进程）', () => {
  function simDeps(exitCodes: Array<number | null>, probeOk = true) {
    const spawned: number[] = []
    const events: string[] = []
    let n = 0
    const deps = {
      spawn(port: number): ChildHandle {
        spawned.push(port)
        const code = exitCodes[n++]
        let kill!: () => void
        const exited = new Promise<number | null>((r) => { kill = () => r(null); if (code !== undefined) setTimeout(() => r(code), 30) })
        return { pid: 1000 + n, exited, kill }
      },
      probe: async () => (probeOk ? '1.1' : undefined),
      pickPort: async () => 18000 + spawned.length,
      newToken: () => 't'.repeat(32),
      expectedVersion: '1.1',
      log: (_l: string, e: string) => { events.push(e) },
    }
    return { deps, spawned, events }
  }

  it('1 分钟内重启超过 3 次就停止，状态 failed', async () => {
    const { deps, spawned } = simDeps([1, 1, 1, 1, 1, 1])
    const s = new Supervisor(deps)
    await s.start()
    await waitFor(() => s.state === 'failed', 5000)
    expect(spawned).toHaveLength(4) // 首次 + 3 次重启
  })

  it('退出码 2（端口被占）换端口重试，不计入重启次数', async () => {
    const { deps, spawned } = simDeps([2, 2, undefined as unknown as number])
    const s = new Supervisor(deps)
    await s.start()
    await waitFor(() => s.state === 'running' && spawned.length === 3, 5000)
    expect(new Set(spawned).size).toBe(3)
    s.stop()
  })

  it('连续 3 次探测没响应就结束进程并重启', async () => {
    let ok = true
    const timers: Array<() => void> = []
    const spawned: number[] = []
    const kills: number[] = []
    const deps = {
      spawn(port: number): ChildHandle {
        spawned.push(port)
        let resolve!: (c: number | null) => void
        const exited = new Promise<number | null>((r) => { resolve = r })
        return { pid: port, exited, kill: () => { kills.push(port); resolve(null) } }
      },
      probe: async () => (ok ? '1.1' : undefined),
      pickPort: async () => 18100 + spawned.length,
      newToken: () => 't'.repeat(32),
      expectedVersion: '1.1',
      log: () => {},
      setTimer: (fn: () => void) => { timers.push(fn); return timers.length },
      clearTimer: () => {},
    }
    const s = new Supervisor(deps)
    await s.start()
    expect(s.state).toBe('running')
    ok = false
    for (let i = 0; i < 3; i++) { timers.shift()!(); await new Promise((r) => setTimeout(r, 10)) }
    expect(kills).toEqual([18100])
    ok = true
    await waitFor(() => spawned.length === 2 && s.state === 'running', 2000)
    s.stop()
  })
})
