import { spawn, type ChildProcess } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

export interface Fake { port: number; token: string; appdata: string; stop(): void }

/** 启动本机假服务（dev/fake-service.mjs），等 /health 就绪。 */
export async function startFake(port: number, extra: string[] = []): Promise<Fake> {
  const token = randomBytes(16).toString('hex')
  const appdata = mkdtempSync(join(tmpdir(), 'lb-fake-'))
  const child: ChildProcess = spawn(process.execPath, [join(__dirname, '..', '..', 'dev', 'fake-service.mjs'), '--port', String(port), ...extra], {
    env: { ...process.env, LB_TOKEN: token, LB_APPDATA: appdata }, stdio: 'ignore',
  })
  for (let i = 0; i < 50; i++) {
    try { if ((await fetch(`http://127.0.0.1:${port}/health`)).ok) break } catch { /* 还没起来 */ }
    await new Promise((r) => setTimeout(r, 100))
  }
  // T7 返修 P3-4：停止时删掉自己的临时目录
  return { port, token, appdata, stop: () => { child.kill(); rmSync(appdata, { recursive: true, force: true }) } }
}
