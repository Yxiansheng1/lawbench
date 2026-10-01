// 启动自检的真实依赖（文件、PATH、子进程、注册表）。逻辑在 selfcheck.ts。
import { execFile } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { statSync, unlinkSync, writeFileSync } from 'node:fs'
import { delimiter, join } from 'node:path'
import type { SelfCheckDeps } from './selfcheck.ts'

const isFile = (p: string): boolean => { try { return statSync(p).isFile() } catch { return false } }
const isDir = (p: string): boolean => { try { return statSync(p).isDirectory() } catch { return false } }

function run(command: readonly string[], timeoutMs: number): Promise<string | undefined> {
  return new Promise((resolve) => {
    execFile(command[0]!, command.slice(1), { timeout: timeoutMs, windowsHide: true, encoding: 'utf8' }, (error, stdout) => resolve(error ? undefined : stdout))
  })
}

function which(name: string): string | undefined {
  const exts = process.platform === 'win32' ? (process.env.PATHEXT ?? '.EXE;.CMD;.BAT').split(';').filter(Boolean) : ['']
  for (const dir of (process.env.PATH ?? '').split(delimiter).filter(Boolean)) {
    for (const ext of exts) { const p = join(dir, name + ext.toLowerCase()); if (isFile(p)) return p }
  }
  return undefined
}

function canWrite(dir: string): boolean {
  const probe = join(dir, `.lawbench-write-check-${randomBytes(4).toString('hex')}`)
  try { writeFileSync(probe, '', { flag: 'wx' }) } catch { return false }
  try { unlinkSync(probe) } catch { /* 删不掉也说明能写 */ }
  return true
}

async function longPathsEnabled(): Promise<boolean | undefined> {
  if (process.platform !== 'win32') return true
  const out = await run(['reg', 'query', 'HKLM\\SYSTEM\\CurrentControlSet\\Control\\FileSystem', '/v', 'LongPathsEnabled'], 5_000)
  const m = out ? /LongPathsEnabled\s+REG_DWORD\s+0x([0-9a-f]+)/i.exec(out) : null
  return m ? parseInt(m[1]!, 16) === 1 : undefined
}

export function nodeSelfCheckDeps(base: Pick<SelfCheckDeps, 'command' | 'serviceDir' | 'appData' | 'adminSkillsDir' | 'sofficeCandidates' | 'pandocCandidates'>): SelfCheckDeps {
  return { ...base, isFile, isDir, which, run, canWrite, longPathsEnabled }
}
