import { spawn, type ChildProcess } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { mkdtempSync, rmSync } from 'node:fs'
import { createServer } from 'node:net'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

export interface Fake { port: number; token: string; appdata: string; stop(): void }

/** 线 A 的端口段（假服务本身也只接受这一段）。 */
const PORTS = [18801, 18802, 18803, 18804, 18805, 18806, 18807, 18808, 18809]

const portFree = (port: number) => new Promise<boolean>((resolve) => {
  const s = createServer()
  s.once('error', () => resolve(false))
  s.listen(port, '127.0.0.1', () => s.close(() => resolve(true)))
})

/**
 * 启动本机假服务（dev/fake-service.mjs）。
 * 端口：先试给定的，被占就在 18801–18809 里挑一个空闲的；挑不到就报错。
 * 就绪判断用自己的令牌访问要鉴权的接口——端口上若是别人起的服务（如桌面端 Host 的假服务，令牌不同）会回 401，
 * 不会被当成自己的（T7 小项，主编排 2026-09-30 04:41 注记）。
 */
export async function startFake(port: number, extra: string[] = []): Promise<Fake> {
  const token = randomBytes(16).toString('hex')
  const appdata = mkdtempSync(join(tmpdir(), 'lb-fake-'))
  for (const p of [port, ...PORTS.filter((x) => x !== port)]) {
    if (!(await portFree(p))) continue
    const child: ChildProcess = spawn(process.execPath, [join(__dirname, '..', '..', 'dev', 'fake-service.mjs'), '--port', String(p), ...extra], {
      env: { ...process.env, LB_TOKEN: token, LB_APPDATA: appdata }, stdio: 'ignore',
    })
    let exited = false
    child.once('exit', () => { exited = true })
    for (let i = 0; i < 50 && !exited; i++) {
      try {
        const r = await fetch(`http://127.0.0.1:${p}/api/settings`, { headers: { authorization: `Bearer ${token}` } })
        if (r.status === 200) {
          // T7 返修 P3-4：停止时删掉自己的临时目录
          return { port: p, token, appdata, stop: () => { child.kill(); rmSync(appdata, { recursive: true, force: true }) } }
        }
      } catch { /* 还没起来 */ }
      await new Promise((r) => setTimeout(r, 100))
    }
    // 没起来（端口在检查之后被别人抢走，或进程退出）：换下一个端口
    child.kill()
  }
  rmSync(appdata, { recursive: true, force: true })
  throw new Error('假服务起不来：18801–18809 没有可用端口（桌面端开着时它的假服务会占用其中一个），或进程启动失败')
}
