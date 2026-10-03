// @vitest-environment jsdom
// 首页启动时服务还没就绪（T14 第二次实跑派修 1，执行令 1751）：读失败每 2 秒自动重读、最多 30 秒，期间显示"正在连接本机服务…"；
// 服务就绪后自动显示胶囊和最近案件；30 秒仍不行给"重试"按钮。假服务延迟起。
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { HomePage } from '../ui/home.tsx'
import { app, setApi, type LawbenchApi } from '../ui/state.ts'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
const fixture = (name: string) => JSON.parse(readFileSync(join(__dirname, '..', 'ui', 'fixtures', name), 'utf8'))
const DOWN = { ok: false, error: { code: 'SERVICE_UNAVAILABLE', message: '工作台服务未启动，请稍后重试' } }
let root: Root | undefined
let box: HTMLDivElement
let up: boolean
let calls: number

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
  up = false; calls = 0
  app.set((s) => ({ ...s, cases: [] }))
  setApi({
    getCapsules: async () => { calls++; return up ? fixture('capsules.json') : DOWN },
    caseRecent: async () => (up ? fixture('case_recent.json') : DOWN),
    listSkills: async () => ({ ok: true, value: { skills: [] } }),
    selfCheck: async () => ({ ok: true, value: { items: [] } }),
  } as unknown as LawbenchApi)
  box = document.createElement('div'); document.body.appendChild(box)
})
afterEach(async () => { await act(async () => { root?.unmount() }); root = undefined; box.remove(); setApi(undefined); vi.useRealTimers() })

const render = async () => { root = createRoot(box); await act(async () => { root!.render(createElement(HomePage)) }) }
const wait = async (ms: number) => { await act(async () => { await vi.advanceTimersByTimeAsync(ms) }) }

describe('首页启动时服务未就绪', () => {
  it('先显示"正在连接本机服务…"，服务 5 秒后起来：自动显示胶囊和最近案件，不用点', async () => {
    await render()
    expect(box.textContent).toContain('正在连接本机服务…')
    expect(box.textContent).not.toContain('工作台服务未启动')
    await wait(5000)
    up = true
    await wait(2000)
    expect(box.textContent).not.toContain('正在连接本机服务…')
    expect(box.textContent).toContain('管理胶囊')
    expect(box.textContent).toContain('周某诉青禾贸易借款合同纠纷（虚构）')
  })

  it('30 秒仍连不上：停止自动重读，显示错误和"重试"；服务起来后点重试即显示', async () => {
    await render()
    await wait(30_000)
    expect(box.textContent).toContain('工作台服务未启动')
    const n = calls
    expect(n).toBe(16) // 首次 + 每 2 秒一次共 15 次
    await wait(10_000)
    expect(calls).toBe(n)
    up = true
    const retry = [...box.querySelectorAll('button')].find((b) => b.textContent === '重试')!
    await act(async () => { retry.click() })
    await wait(0)
    expect(box.textContent).toContain('管理胶囊')
    expect(box.textContent).not.toContain('工作台服务未启动')
  })
})
