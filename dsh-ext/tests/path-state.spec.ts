// Host 方法 pathState（令 1726 复核 AMEND）：网络 / 设备路径不收；异步 stat 带超时，掉线网络盘不卡 Host；问不到回"不知道"。
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathState } from '../host/path-state.ts'

describe('pathState', () => {
  it('在的回 exists:true，不在的回 exists:false', async () => {
    const dir = mkdtempSync(join(tmpdir(), 'lb-ps-'))
    try {
      expect(await pathState({ path: dir })).toEqual({ ok: true, value: { exists: true } })
      expect(await pathState({ path: join(dir, '没有这个') })).toEqual({ ok: true, value: { exists: false } })
    } finally { rmSync(dir, { recursive: true, force: true }) }
  })

  it('网络路径、设备路径、相对路径、空的一律不收', async () => {
    for (const path of [String.raw`\\host\share\案件`, '//host/share', String.raw`\\?\D:\案件`, String.raw`\\.\D:\案件`, String.raw`案件\甲`, '', undefined]) {
      const r = await pathState({ path })
      expect(r.ok, String(path)).toBe(false)
    }
  })

  it('stat 卡住时按超时回"不知道"（不是"不在"）；别的错误也一样', async () => {
    const hang = () => new Promise<never>(() => {})
    expect(await pathState({ path: String.raw`D:\案件\甲` }, { statFn: hang, timeoutMs: 20 })).toMatchObject({ ok: false, error: { code: 'TIMEOUT' } })
    const denied = () => Promise.reject(Object.assign(new Error('x'), { code: 'EACCES' }))
    expect(await pathState({ path: String.raw`D:\案件\甲` }, { statFn: denied })).toMatchObject({ ok: false, error: { code: 'UNKNOWN' } })
  })
})
