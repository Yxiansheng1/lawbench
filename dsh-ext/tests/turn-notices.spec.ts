// 上一轮被拦下的原因（INPUT_CHANGED 等）：TurnNotices 本身，和 Host 的接线（T13 INPUT_CHANGED 返修 P3-D）。
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { TurnNotices } from '../shared/turn-notices.ts'
import { apply as applyHost, LawbenchRemote } from '../host/index.ts'
import { LAWBENCH_SERVICE } from '../shared/remote-methods.ts'

describe('TurnNotices', () => {
  it('取一次即删；同一会话只留最新；各会话分开', () => {
    const n = new TurnNotices()
    n.note('S1', 'CASE_NOT_FOUND'); n.note('S1', 'INPUT_CHANGED'); n.note('S2', 'INPUT_CHANGED')
    expect(n.take('S1')).toBe('INPUT_CHANGED')
    expect(n.take('S1')).toBeNull()
    expect(n.take('S2')).toBe('INPUT_CHANGED')
    expect(n.take('S3')).toBeNull()
  })

  it('一轮顺利开始时清掉没被取走的旧记录（之后不误报）', () => {
    const n = new TurnNotices()
    n.note('S1', 'INPUT_CHANGED')
    n.clear('S1')
    expect(n.take('S1')).toBeNull()
  })

  it('超过上限丢最早的', () => {
    const n = new TurnNotices()
    for (let i = 0; i < 201; i++) n.note(`S${i}`, 'INPUT_CHANGED')
    expect(n.take('S0')).toBeNull()
    expect(n.take('S200')).toBe('INPUT_CHANGED')
  })
})

describe('Host 接线：Agent 经 lawbenchCore 记下 / 清掉，界面经远程方法 turnNotice 取走', () => {
  it('noteTurnBlocked 记下的，turnNotice 取得到且只取一次；clearTurnBlocked 清掉的取不到', async () => {
    const appData = mkdtempSync(join(tmpdir(), 'lb-host-notice-'))
    try {
      const provided = new Map<string, unknown>()
      const ctx = {
        provide: (name: string, value: unknown) => { provided.set(name, value); return () => {} },
        effect: () => {},
        get: () => undefined,
        subprocess: { spawn: () => { throw new Error('测试里不启动服务') } },
      }
      applyHost(ctx as never, { command: ['node'], cwd: appData, appData } as never)
      const core = provided.get('lawbenchCore') as { noteTurnBlocked(s: string, c: string, t?: string): void; clearTurnBlocked(s: string): void }
      const remote = provided.get(LAWBENCH_SERVICE) as LawbenchRemote
      expect(remote).toBeInstanceOf(LawbenchRemote)
      core.noteTurnBlocked('S1', 'INPUT_CHANGED')
      expect(await remote.turnNotice({ session_id: 'S1' })).toEqual({ ok: true, value: { code: 'INPUT_CHANGED', task_id: null } })
      expect(await remote.turnNotice({ session_id: 'S1' })).toEqual({ ok: true, value: { code: null, task_id: null } })
      core.noteTurnBlocked('S2', 'INPUT_CHANGED')
      core.clearTurnBlocked('S2')
      expect(await remote.turnNotice({ session_id: 'S2' })).toEqual({ ok: true, value: { code: null, task_id: null } })
      // T14 派修 2：到达用量上限时连同任务编号一起取走
      core.noteTurnBlocked('S3', 'BUDGET_STOPPED', 'T-20261003145955-de5b')
      expect(await remote.turnNotice({ session_id: 'S3' })).toEqual({ ok: true, value: { code: 'BUDGET_STOPPED', task_id: 'T-20261003145955-de5b' } })
    } finally { rmSync(appData, { recursive: true, force: true }) }
  })
})
