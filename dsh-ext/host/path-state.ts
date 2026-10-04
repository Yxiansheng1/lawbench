// Host 方法 pathState（1612 复核 P1）：界面撤侧栏旧位置一项前问"这个位置还在不在"。只回在不在，不读内容，日志不记路径。
// 令 1726：网络路径、设备路径（\\host\share、//host、\\?\、\\.\）一律不收（同 archive-plan.ts）；
// 用带超时的异步 stat，掉线的网络盘不卡 Host——超时、出错（除"不存在"外）都回"不知道"，界面那边不撤。
import { stat } from 'node:fs/promises'
import { isAbsolute } from 'node:path'

export const PATH_STATE_TIMEOUT_MS = 3000

export type PathStateResult = { ok: true; value: { exists: boolean } } | { ok: false; error: { code: string; message: string } }

const MISSING = new Set(['ENOENT', 'ENOTDIR'])

export async function pathState(request: unknown, opts: { timeoutMs?: number; statFn?: (p: string) => Promise<unknown> } = {}): Promise<PathStateResult> {
  const p = (request as { path?: unknown } | null)?.path
  if (typeof p !== 'string' || !p || !isAbsolute(p) || /^[\\/]{2}/.test(p)) return { ok: false, error: { code: 'INVALID_ARGUMENT', message: '请求参数有误' } }
  const statFn = opts.statFn ?? stat
  let timer: ReturnType<typeof setTimeout> | undefined
  const timeout = new Promise<'timeout'>((r) => { timer = setTimeout(() => r('timeout'), opts.timeoutMs ?? PATH_STATE_TIMEOUT_MS) })
  try {
    const r = await Promise.race([statFn(p).then(() => 'found' as const, (e: NodeJS.ErrnoException) => (MISSING.has(e?.code ?? '') ? 'missing' as const : 'unknown' as const)), timeout])
    if (r === 'found') return { ok: true, value: { exists: true } }
    if (r === 'missing') return { ok: true, value: { exists: false } }
    return { ok: false, error: { code: r === 'timeout' ? 'TIMEOUT' : 'UNKNOWN', message: '查不到这个位置' } }
  } finally {
    clearTimeout(timer)
  }
}
