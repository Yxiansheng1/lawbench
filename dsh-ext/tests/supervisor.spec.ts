import { spawn } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { join } from 'node:path'
import { Supervisor, type ChildHandle } from '../host/supervisor.ts'
import { CONTRACT_VERSION } from '../shared/contracts.ts'

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
    expectedVersion: extra.version ?? CONTRACT_VERSION, // 跟契约走（1.2 起），不写死
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

  it('退出码 2（端口被占）换端口重试，不计入重启次数：连续 4 次退出码 2 后仍是 running', async () => {
    // 4 次超过"1 分钟内 3 次"的上限：若退出码 2 被计入重启次数，这里会变成 failed（T7 返修 P3-1）
    const { deps, spawned } = simDeps([2, 2, 2, 2, undefined as unknown as number])
    const s = new Supervisor(deps)
    await s.start()
    await waitFor(() => spawned.length === 5, 5000)
    await new Promise((r) => setTimeout(r, 100))
    expect(s.state).toBe('running')
    expect(new Set(spawned).size).toBe(5)
    s.stop()
  })

  it('重启时挑端口抛错：记日志、状态 failed，不留未处理的拒绝（T7 返修 P3-2）', async () => {
    const events: string[] = []
    let calls = 0
    const deps = {
      spawn(): ChildHandle { let r!: (c: number | null) => void; const exited = new Promise<number | null>((res) => { r = res }); setTimeout(() => r(1), 20); return { pid: 1, exited, kill: () => r(null) } },
      probe: async () => '1.1',
      pickPort: async () => { calls++; if (calls > 1) throw new Error('服务端口范围内没有空闲端口'); return 18200 },
      newToken: () => 't'.repeat(32),
      expectedVersion: '1.1',
      log: (_l: string, e: string) => { events.push(e) },
    }
    const s = new Supervisor(deps)
    await s.start()
    await waitFor(() => s.state === 'failed', 3000)
    expect(events).toContain('service.launch_failed')
  })

  it('首次启动挑端口就失败：状态 failed，不停在 starting（T7 第二次返修 F3）', async () => {
    const events: string[] = []
    const deps = {
      spawn(): ChildHandle { throw new Error('不应被调用') },
      probe: async () => '1.1',
      pickPort: async () => { throw new Error('服务端口范围内没有空闲端口') },
      newToken: () => 't'.repeat(32),
      expectedVersion: '1.1',
      log: (_l: string, e: string) => { events.push(e) },
    }
    const s = new Supervisor(deps)
    await s.start()
    expect(s.state).toBe('failed')
    expect(events).toContain('service.launch_failed')
  })

  it('重启失败时已在停止中：状态保持 stopped，不改成 failed（T7 第二次返修 F4）', async () => {
    let calls = 0
    let releaseSecond!: () => void
    let exit!: (c: number | null) => void
    const deps = {
      spawn(): ChildHandle { return { pid: 1, exited: new Promise<number | null>((r) => { exit = r }), kill: () => {} } },
      probe: async () => '1.1',
      // 第二次挑端口（重启时）先挂起，放行后抛错
      pickPort: async () => { calls++; if (calls === 1) return 18400; await new Promise<void>((r) => { releaseSecond = r }); throw new Error('端口挑选失败') },
      newToken: () => 't'.repeat(32),
      expectedVersion: '1.1',
      log: () => {},
    }
    const s = new Supervisor(deps)
    await s.start()
    expect(s.state).toBe('running')
    exit(1)                       // 进程退出 → 触发重启，重启卡在挑端口
    await waitFor(() => calls === 2, 2000)
    s.stop()                      // 重启途中主动停止
    releaseSecond()               // 重启失败
    await new Promise((r) => setTimeout(r, 50))
    expect(s.state).toBe('stopped')
  })

  it('旧代次的启动失败不覆盖新一代的状态（T7 第三轮 P3-2）', async () => {
    let calls = 0
    let failFirst!: () => void
    const deps = {
      spawn(): ChildHandle { return { pid: 1, exited: new Promise<number | null>(() => {}), kill: () => {} } },
      probe: async () => '1.1',
      // 第一次挑端口挂起，放行后抛错；第二次立即成功
      pickPort: async () => { calls++; if (calls === 1) { await new Promise<void>((r) => { failFirst = r }); throw new Error('旧的一次挑端口失败') } return 18500 },
      newToken: () => 't'.repeat(32),
      expectedVersion: '1.1',
      log: () => {},
    }
    const s = new Supervisor(deps)
    const first = s.start()
    await new Promise((r) => setTimeout(r, 10))
    await s.start()               // 第二代启动成功
    expect(s.state).toBe('running')
    failFirst()                   // 第一代此时才失败
    await first
    expect(s.state).toBe('running')
    s.stop()
  })

  it('挑端口期间 stop()：不再拉起进程（T7 返修 P3-2）', async () => {
    const spawned: number[] = []
    let release!: (p: number) => void
    const deps = {
      spawn(port: number): ChildHandle { spawned.push(port); return { pid: 1, exited: new Promise(() => {}), kill: () => {} } },
      probe: async () => '1.1',
      pickPort: () => new Promise<number>((r) => { release = r }),
      newToken: () => 't'.repeat(32),
      expectedVersion: '1.1',
      log: () => {},
    }
    const s = new Supervisor(deps)
    const starting = s.start()
    await new Promise((r) => setTimeout(r, 10))
    s.stop()
    release(18300)
    await starting
    expect(spawned).toEqual([])
    expect(s.state).toBe('stopped')
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
