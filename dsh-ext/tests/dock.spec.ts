// @vitest-environment jsdom
// 输入区（ui\dock.tsx）按契约 1.2 的操作顺序测试：在 jsdom 里渲染真实的输入区组件，接一个按 1.2 语义写的内存服务
// （POST /api/task 设置当前选择、新的顶掉旧的；GET /api/task/current 读回；发消息按当前选择复制执行，不消耗）。
// 逐条对应复核员第三轮那张"操作顺序 → 显示与实际"的表（docs\plan\evidence\T13\review-REVIEW-第三轮.md 第一部分第二节），
// 和契约 1.2 复核的 X 系列（review-契约1.2.md）。换会话默认不重挂输入区（只换 sessionId 属性），重挂的另测。
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { ComposerDock, forgetDockSyncs, NO_CASE_TEXT, TURN_ENDED } from '../ui/dock.tsx'
import { toRequest, turnEnds } from '../ui/tasksheet.ts'
import { app, setApi, setIntent, type LawbenchApi, type SkillInfo } from '../ui/state.ts'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const fixture = (name: string) => JSON.parse(readFileSync(join(__dirname, '..', 'ui', 'fixtures', name), 'utf8'))
const CAPSULES = fixture('capsules.json').value
const CASE = fixture('case_recent.json').value.cases[0] as { case_id: string; name: string; root: string; exists: boolean }
const A = { id: 'contract-review', name: '合同审查', skill: 'contract-review' }
const B = { id: 'contract-draft', name: '合同起草', skill: 'contract-draft' }
const skill = (name: string): SkillInfo => ({ name, title: name, description: '', mode: 'agent', kind: 'draft', params: { thinking: '中', window: '64K', max_tokens: 16384 }, inputs: [], questions: [] })
const SKILLS = ['contract-review', 'contract-draft', 'pre-issue-check', 'doc-revise', 'litigation-docs', 'case-wiki-build', 'legal-workflow'].map(skill)

type Sel = { task_id: string; entry: string | null; skill: string | null; inputs: string[]; params: unknown; updated_at: string }

/** 按契约 1.2 语义的内存服务。 */
class Service {
  selections = new Map<string, Sel>()
  failWrite = false
  failRead = false
  /** 服务建了单，但界面收到的是失败（X1、X2：响应超时，或返回不合契约）。 */
  failAfterCreate: { code: string; message: string } | null = null
  /** 写入、读回耗时（毫秒，假时钟）；测"写到一半律师又改了""读回要 2 秒"。 */
  writeDelay = 0
  readDelay = 0
  n = 0
  /** 输入材料变了：发消息时 /core/context 报 INPUT_CHANGED，整轮被拦下（Agent 插件记下，Host 的 turnNotice 取走）。 */
  inputChanged = false
  blocked = new Map<string, string>()
  write(req: { session_id: string; entry: string | null; skill: string | null; inputs: string[]; params: unknown }) {
    if (this.failWrite) return { ok: false as const, error: { code: 'SERVICE_UNAVAILABLE', message: '工作台服务未启动，请稍后重试' } }
    const t = { task_id: `T-20260930120000-${String(++this.n).padStart(4, '0')}`, entry: req.entry, skill: req.skill, inputs: req.inputs, params: req.params, updated_at: '2026-09-30T12:00:00+08:00' }
    this.selections.set(req.session_id, t)
    if (this.failAfterCreate) return { ok: false as const, error: this.failAfterCreate }
    return { ok: true as const, value: { task_id: t.task_id } }
  }
  current(sessionId: string) {
    if (this.failRead) return { ok: false as const, error: { code: 'SERVICE_UNAVAILABLE', message: '工作台服务未启动，请稍后重试' } }
    return { ok: true as const, value: { selection: this.selections.get(sessionId) ?? null } }
  }
  /** 发一条消息：按当前选择新建执行中的任务（复制一份），返回这条按什么跑；当前选择不消耗。 */
  send(sessionId: string): string {
    if (this.inputChanged) { this.blocked.set(sessionId, 'INPUT_CHANGED'); return '被拦下' }
    const s = this.selections.get(sessionId)
    return s && s.entry ? s.entry : '自由对话'
  }
}

let svc: Service
let root: Root | undefined
let container: HTMLDivElement

function api(): LawbenchApi {
  const fns: Record<string, (arg?: unknown) => Promise<unknown>> = {
    taskCreate: async (r) => {
      if (svc.writeDelay) await new Promise((res) => setTimeout(res, svc.writeDelay))
      return svc.write(r as Parameters<Service['write']>[0])
    },
    taskCurrent: async (r) => {
      if (svc.readDelay) await new Promise((res) => setTimeout(res, svc.readDelay))
      return svc.current((r as { session_id: string }).session_id)
    },
    turnNotice: async (r) => {
      const id = (r as { session_id: string }).session_id
      const code = svc.blocked.get(id) ?? null
      svc.blocked.delete(id)
      return { ok: true, value: { code } }
    },
    getCapsules: async () => ({ ok: true, value: CAPSULES }),
    caseRecent: async () => ({ ok: true, value: { cases: [CASE] } }),
    listSkills: async () => ({ ok: true, value: { skills: SKILLS } }),
  }
  return fns as unknown as LawbenchApi
}

async function flush(ms = 0): Promise<void> {
  await act(async () => { await vi.advanceTimersByTimeAsync(ms) })
  await act(async () => { await Promise.resolve() })
}

/** 显示某个会话的输入区。默认不重挂（同一个组件只换 sessionId）；remount 为真时按会话重挂。 */
async function mount(sessionId: string, remount = false): Promise<void> {
  if (!root) root = createRoot(container)
  const useSessions = <T,>(select: (s: { byId: Record<string, { cwd?: string }> }) => T): T => select({ byId: { [sessionId]: { cwd: CASE.root } } })
  await act(async () => { root!.render(createElement(ComposerDock, { key: remount ? sessionId : 'dock', sessionId, useSessions })) })
  await flush()
}

/** 模拟软件重启、插件重载：界面状态全清（服务那边不变）。 */
async function restart(sessionId: string): Promise<void> {
  await act(async () => { root?.unmount() })
  root = undefined
  app.set((s) => ({ ...s, selections: {}, intents: {}, inputChanged: {}, staleServer: {} }))
  await mount(sessionId)
}

const capsuleSelect = () => container.querySelector('select[aria-label="胶囊"]') as HTMLSelectElement
const skillSelect = () => container.querySelector('select[aria-label="Skill"]') as HTMLSelectElement | null
const status = () => container.querySelector('[role=status]')?.textContent ?? ''
const shown = () => capsuleSelect().value || '自由对话'

async function pick(id: string, el: HTMLSelectElement = capsuleSelect()): Promise<void> {
  const set = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value')!.set!
  await act(async () => { set.call(el, id); el.dispatchEvent(new Event('change', { bubbles: true })) })
}

async function turnEnded(sessionId: string): Promise<void> {
  await act(async () => { window.dispatchEvent(new CustomEvent(TURN_ENDED, { detail: sessionId })) })
  await flush()
}

/** 发一条消息并结束这一轮：返回这条实际按什么跑。 */
async function send(sessionId: string): Promise<string> {
  const ran = svc.send(sessionId)
  await turnEnded(sessionId)
  return ran
}

const READY = (name: string) => `下一条消息按「${name}」运行（直到你改掉）`

beforeEach(async () => {
  vi.useFakeTimers()
  forgetDockSyncs()
  svc = new Service()
  setApi(api())
  app.set((s) => ({ ...s, cases: [CASE], selections: {}, intents: {}, inputChanged: {}, staleServer: {} }))
  container = document.createElement('div')
  document.body.appendChild(container)
  await mount('S1')
})

afterEach(async () => {
  await act(async () => { root?.unmount() })
  root = undefined
  container.remove()
  vi.useRealTimers()
})

describe('输入区任务单：契约 1.2（管到律师改掉为止）', () => {
  it('刚挂上：从服务读当前选择；没设置过显示自由对话', async () => {
    expect(shown()).toBe('自由对话')
    expect(status()).toBe('自由对话')
  })

  it('选 A 发两条（R1、原 W1）：两条都按 A 跑，状态行一直说按 A（不再有"只管这一条"和轮询空窗）', async () => {
    await pick(A.id)
    expect(status()).toBe('正在保存选择…')
    await flush(600)
    expect(status()).toBe(READY(A.name))
    expect(await send('S1')).toBe(A.id)
    expect([shown(), status()]).toEqual([A.id, READY(A.name)])
    expect(await send('S1')).toBe(A.id)
    expect([shown(), status()]).toEqual([A.id, READY(A.name)])
  })

  it('选 A 改选 B 发两条（R2、原 W3）：都按 B 跑', async () => {
    await pick(A.id); await flush(600)
    await pick(B.id); await flush(600)
    expect(status()).toBe(READY(B.name))
    expect([await send('S1'), await send('S1')]).toEqual([B.id, B.id])
  })

  it('一秒内连改三次后立刻发（R3、R3b）：写成功之前状态行说"正在保存"，不说已就绪；写完后按最后一次跑', async () => {
    await pick(A.id); await flush(600)
    await pick(B.id); await flush(200)
    await pick(A.id); await flush(200)
    await pick(B.id); await flush(100)
    expect(status()).toBe('正在保存选择…') // 此刻发出去按服务的当前选择（A）跑：界面没有声称"已就绪 B"
    expect(await send('S1')).toBe(A.id)
    expect(status()).toBe('正在保存选择…') // 一轮结束的重读不覆盖律师还没写成功的改动
    await flush(600)
    expect(status()).toBe(READY(B.name))
    expect(await send('S1')).toBe(B.id)
  })

  it('选 A 切回自由对话发两条（R4、原 W2）：都按自由对话跑，状态行说自由对话', async () => {
    await pick(A.id); await flush(600)
    await pick(''); await flush(600)
    expect(status()).toBe('自由对话')
    expect([await send('S1'), await send('S1')]).toEqual(['自由对话', '自由对话'])
    expect(svc.selections.get('S1')).toMatchObject({ entry: null, skill: null })
  })

  it('选 A 不发，重启、重载后马上发（R5、原 1.6 秒窗口）：界面读回 A 并显示 A，发出去按 A 跑', async () => {
    await pick(A.id); await flush(600)
    await restart('S1')
    expect([shown(), status()]).toEqual([A.id, READY(A.name)])
    expect(await send('S1')).toBe(A.id)
  })

  it('重启后先改选 B 再发（R6）：按 B 跑', async () => {
    await pick(A.id); await flush(600)
    await restart('S1')
    await pick(B.id); await flush(600)
    expect(await send('S1')).toBe(B.id)
  })

  it('重启后连发三条（R7、原 W4）：界面显示服务的选择，三条都按它跑', async () => {
    await pick(A.id); await flush(600)
    await restart('S1')
    expect([await send('S1'), await send('S1'), await send('S1')]).toEqual([A.id, A.id, A.id])
    expect(shown()).toBe(A.id)
  })

  it('写失败（R8、R12：服务不可用）：显示错误、保留下拉框的值，不显示已就绪；一轮结束的重读不盖掉错误；恢复后点重试写成', async () => {
    await pick(A.id); await flush(600)
    svc.failWrite = true
    await pick(B.id); await flush(600)
    expect(shown()).toBe(B.id)
    expect(status()).toContain('工作台服务未启动')
    expect(await send('S1')).toBe(A.id) // 实际按服务的 A 跑；界面此刻显示的是红字错误，没有声称按 B
    expect(shown()).toBe(B.id)
    expect(status()).toContain('工作台服务未启动')
    svc.failWrite = false
    const retry = [...container.querySelectorAll('button')].find((b) => b.textContent === '重试')!
    await act(async () => { retry.click() })
    await flush(600)
    expect(status()).toBe(READY(B.name))
    expect(await send('S1')).toBe(B.id)
  })

  it('读失败（服务未启动时挂上）：显示错误不显示已就绪；恢复后点重试读回服务的选择，不把界面默认值写过去', async () => {
    await pick(A.id); await flush(600)
    svc.failRead = true
    await restart('S1')
    expect(status()).toContain('工作台服务未启动')
    svc.failRead = false
    const retry = [...container.querySelectorAll('button')].find((b) => b.textContent === '重试')!
    await act(async () => { retry.click() })
    await flush()
    expect([shown(), status()]).toEqual([A.id, READY(A.name)])
    expect(svc.selections.get('S1')).toMatchObject({ entry: A.id })
  })

  for (const remount of [false, true]) {
    it(`选 A 不发，切到别的会话再切回（R9）；同一案件两个会话交替（R10）：各按各的当前选择（${remount ? '重挂' : '不重挂'}）`, async () => {
      await pick(A.id); await flush(600)
      await mount('S2', remount)
      expect(shown()).toBe('自由对话')
      await pick(B.id); await flush(600)
      await mount('S1', remount)
      expect([shown(), status()]).toEqual([A.id, READY(A.name)])
      expect(await send('S1')).toBe(A.id)
      await mount('S2', remount)
      expect([shown(), status()]).toEqual([B.id, READY(B.name)])
      expect(await send('S2')).toBe(B.id)
    })
  }

  it('发消息的同时改选择（R11）：写成功之前说"正在保存"，那条按原来的跑；之后按新的', async () => {
    await pick(A.id); await flush(600)
    await pick(B.id); await flush(200)
    expect(status()).toBe('正在保存选择…')
    expect(await send('S1')).toBe(A.id)
    await flush(600)
    expect(await send('S1')).toBe(B.id)
  })

  it('首页点胶囊再进案件（选择先于输入区挂上）：挂上后不被服务的旧值盖掉，写成后按它跑', async () => {
    await act(async () => { root?.unmount() })
    root = undefined
    setIntent(CASE.case_id, { capsuleId: A.id, skill: A.skill, params: null, inputs: [] })
    await mount('S3')
    expect(shown()).toBe(A.id)
    await flush(600)
    expect(status()).toBe(READY(A.name))
    expect(await send('S3')).toBe(A.id)
    expect(app.get().intents[CASE.case_id]).toBeUndefined() // 取走一次
  })

  it('首页点胶囊、成果区选用是按案件的待带入意向：只由当前会话取走一次，换到同案别的会话不再带入（P2-2）', async () => {
    await pick(A.id); await flush(600)
    await act(async () => { setIntent(CASE.case_id, { capsuleId: B.id, skill: B.skill, params: null, inputs: [] }) })
    await flush(600)
    expect(svc.selections.get('S1')).toMatchObject({ entry: B.id })
    await mount('S2'); await flush(600)
    expect([shown(), status()]).toEqual(['自由对话', '自由对话'])
    expect(svc.selections.get('S2')).toBeUndefined()
  })

  it('一轮结束后重读：服务那边的选择变了（别处改的）就跟着显示', async () => {
    await pick(A.id); await flush(600)
    svc.write({ session_id: 'S1', entry: B.id, skill: B.skill, inputs: [], params: null })
    await turnEnded('S1')
    expect([shown(), status()]).toEqual([B.id, READY(B.name)])
  })

  it('写到一半律师又改了：那次写成功不把新的选择记为已保存，状态行仍说"正在保存"，直到新的写成', async () => {
    svc.writeDelay = 1000
    await pick(A.id); await flush(600) // 开始写 A，要 1 秒
    await pick(B.id); await flush(1000) // A 在 1.5 秒写成，此刻（1.6 秒）界面已是 B，B 排在 A 后面还在写
    expect(svc.selections.get('S1')).toMatchObject({ entry: A.id })
    expect(status()).toBe('正在保存选择…')
    expect(await send('S1')).toBe(A.id)
    await flush(2000)
    expect(status()).toBe(READY(B.name))
    expect(await send('S1')).toBe(B.id)
  })

  it('胶囊和 Skill 分开读写：选胶囊 A 里另一个 Skill，重启后两个下拉框都按服务的值显示', async () => {
    await pick(A.id); await flush(600)
    await pick('pre-issue-check', skillSelect()!); await flush(600)
    expect(svc.selections.get('S1')).toMatchObject({ entry: A.id, skill: 'pre-issue-check' })
    await restart('S1')
    expect([shown(), skillSelect()?.value]).toEqual([A.id, 'pre-issue-check'])
  })

  it('自由对话写给服务时 entry、skill 都为 null（即使界面残留了 Skill）', () => {
    expect(toRequest({ capsuleId: null, skill: 'contract-review', inputs: [], params: null })).toMatchObject({ entry: null, skill: null })
    expect(toRequest({ capsuleId: null, skill: 'contract-review', inputs: ['03成果/x.docx'], params: null })).toMatchObject({ entry: null, skill: 'contract-review' })
  })

  it('一轮结束的判断：会话 running 由真变假才算；新出现的、一直空闲的不算', () => {
    const running = new Map<string, boolean>()
    expect(turnEnds(running, { S1: { running: true }, S2: {} })).toEqual([])
    expect(turnEnds(running, { S1: { running: true }, S2: { running: false } })).toEqual([])
    expect(turnEnds(running, { S1: { running: false }, S2: { running: false } })).toEqual(['S1'])
    expect(turnEnds(running, { S1: { running: false } })).toEqual([])
  })

  it('INPUT_CHANGED（ORCH 注记 13:18）：上一轮因输入材料变化被拦下，状态行提示重新选择并重读；律师改选后提示消失，写成后就绪', async () => {
    await pick(A.id); await flush(600)
    svc.inputChanged = true
    const n = svc.n
    expect(await send('S1')).toBe('被拦下')
    expect(status()).toBe('输入材料已变化，请重新选择')
    expect(shown()).toBe(A.id) // 重读回服务的选择（仍是 A），不自动改写
    expect(svc.n).toBe(n) // 不自动重写
    await turnEnded('S1') // 再一轮结束（这次没被拦下）不消掉提示：律师还没重新选
    expect(status()).toBe('输入材料已变化，请重新选择')
    svc.inputChanged = false
    await pick(B.id)
    expect(status()).toBe('正在保存选择…')
    await flush(600)
    expect(status()).toBe(READY(B.name))
    expect(await send('S1')).toBe(B.id)
  })

  it('INPUT_CHANGED 的提示只在被拦下的那个会话显示', async () => {
    await pick(A.id); await flush(600)
    svc.inputChanged = true
    await send('S1')
    svc.inputChanged = false
    await mount('S2')
    expect(status()).toBe('自由对话')
    await mount('S1')
    expect(status()).toBe('输入材料已变化，请重新选择')
  })

  it('自由对话下改参数也写（复核 A6）：1.2 起选择一直生效，参数要到服务那边', async () => {
    const think = () => [...container.querySelectorAll('select')].find((s) => [...s.options].some((o) => o.value === '高'))!
    await act(async () => { ([...container.querySelectorAll('button')].find((b) => b.textContent === '参数')!).click() })
    await pick('高', think()); await flush(600)
    expect(svc.selections.get('S1')).toMatchObject({ entry: null, skill: null, params: { thinking: '高' } })
    expect(status()).toBe('自由对话')
  })

  it('N46 ②：会话不在已登记案件里时，输入区上方提示先打开或新建案件，有"回首页"', async () => {
    await act(async () => { root?.unmount() })
    root = createRoot(container)
    const useSessions = <T,>(select: (s: { byId: Record<string, { cwd?: string }> }) => T): T => select({ byId: { S9: { cwd: 'D:\\别处' } } })
    await act(async () => { root!.render(createElement(ComposerDock, { sessionId: 'S9', useSessions })) })
    await flush()
    expect(status()).toBe(NO_CASE_TEXT)
    expect([...container.querySelectorAll('button')].some((b) => b.textContent === '回首页')).toBe(true)
    expect(container.querySelector('select[aria-label="胶囊"]')).toBeNull()
  })

  it('同一选择连选两次：只写一次', async () => {
    await pick(A.id); await flush(600)
    const n = svc.n
    await pick(A.id); await flush(600)
    expect(svc.n).toBe(n)
  })

  describe('契约 1.2 复核 X 系列（T13 返修）', () => {
    for (const [name, error] of [['X1b 响应超时', { code: 'TIMEOUT', message: '工作台服务响应超时，请稍后重试' }], ['X2 返回不合契约', { code: 'BAD_RESPONSE', message: '工作台服务返回的内容不对，请联系技术支持' }]] as const) {
      it(`${name}但服务已建单 B，律师改回 A：重新写一次，状态行和实际一致（P2-1）`, async () => {
        await pick(A.id); await flush(600)
        svc.failAfterCreate = error
        await pick(B.id); await flush(600)
        expect(svc.selections.get('S1')).toMatchObject({ entry: B.id }) // 服务那边其实已经是 B
        expect(status()).toBe(error.message)
        svc.failAfterCreate = null
        const n = svc.n
        await pick(A.id)
        expect(status()).toBe('正在保存选择…') // 修前：直接绿字"按合同审查运行"，实际按 B 跑
        await flush(600)
        expect(svc.n).toBe(n + 1)
        expect(status()).toBe(READY(A.name))
        expect(await send('S1')).toBe(A.id)
      })
    }

    it('X1 写入超时但已建 B，律师不改直接发：红字报错，不声称按 A 或 B 就绪', async () => {
      await pick(A.id); await flush(600)
      svc.failAfterCreate = { code: 'TIMEOUT', message: '工作台服务响应超时，请稍后重试' }
      await pick(B.id); await flush(600)
      expect([shown(), status()]).toEqual([B.id, '工作台服务响应超时，请稍后重试'])
      expect(await send('S1')).toBe(B.id)
    })

    it('X3 改过选择、别处改成 B，一轮结束时读失败：显示读错误，不再显示绿字 A（P3-1）', async () => {
      await pick(A.id); await flush(600)
      svc.write({ session_id: 'S1', entry: B.id, skill: B.skill, inputs: [], params: null })
      svc.failRead = true
      expect(await send('S1')).toBe(B.id)
      expect(status()).toContain('工作台服务未启动')
      expect(status()).not.toBe(READY(A.name))
      svc.failRead = false
      await turnEnded('S1')
      expect([shown(), status()]).toEqual([B.id, READY(B.name)])
    })

    for (const remount of [false, true]) {
      it(`X4 切到 S2、读回要 2 秒、读回前发：不显示 S1 的选择，状态行说正在读取（P2-2，${remount ? '重挂' : '不重挂'}）`, async () => {
        await pick(A.id); await flush(600)
        svc.readDelay = 2000
        await mount('S2', remount)
        expect(shown()).toBe('自由对话')
        expect(status()).toBe('正在读取当前选择…')
        expect(await send('S2')).toBe('自由对话')
        await flush(2000)
        expect([shown(), status()]).toEqual(['自由对话', '自由对话'])
      })

      it(`X4 变体：S2 以前看过（选的 B），再切过去读回前：显示 S2 上次的 B，状态行说正在读取，不说就绪（${remount ? '重挂' : '不重挂'}）`, async () => {
        await mount('S2', remount); await pick(B.id); await flush(600)
        await mount('S1', remount); await pick(A.id); await flush(600)
        svc.readDelay = 2000
        await mount('S2', remount)
        expect([shown(), status()]).toEqual([B.id, '正在读取当前选择…'])
        await flush(2000)
        expect([shown(), status()]).toEqual([B.id, READY(B.name)])
      })

      it(`X5 S1 改 B 没到防抖就切到 S2：B 不写进 S2；切回 S1 时 B 还在、写进 S1（P2-2，${remount ? '重挂' : '不重挂'}）`, async () => {
        await pick(A.id); await flush(600)
        await pick(B.id); await flush(200)
        await mount('S2', remount); await flush(1000)
        expect(svc.selections.get('S2')).toBeUndefined()
        expect([shown(), status()]).toEqual(['自由对话', '自由对话'])
        expect(await send('S2')).toBe('自由对话')
        await mount('S1', remount)
        expect([shown(), status()]).toEqual([B.id, '正在保存选择…'])
        await flush(600)
        expect(svc.selections.get('S1')).toMatchObject({ entry: B.id })
        expect(status()).toBe(READY(B.name))
      })

      it(`X6 S1 写 B 失败后切到 S2：B 不写进 S2，S2 不显示 S1 的错误（P2-2，${remount ? '重挂' : '不重挂'}）`, async () => {
        await pick(A.id); await flush(600)
        svc.failWrite = true
        await pick(B.id); await flush(600)
        expect(status()).toContain('工作台服务未启动')
        await mount('S2', remount)
        svc.failWrite = false
        await flush(1000)
        expect(svc.selections.get('S2')).toBeUndefined()
        expect([shown(), status()]).toEqual(['自由对话', '自由对话'])
        expect(svc.selections.get('S1')).toMatchObject({ entry: A.id })
      })
    }

    it('写 B 在途时切到 S2、写完才回来：结果记到 S1，不动 S2 的显示', async () => {
      await pick(A.id); await flush(600)
      svc.writeDelay = 1000
      await pick(B.id); await flush(600) // 开始写 B
      await mount('S2'); await flush(1500)
      expect(svc.selections.get('S1')).toMatchObject({ entry: B.id })
      expect([shown(), status()]).toEqual(['自由对话', '自由对话'])
      await mount('S1')
      expect([shown(), status()]).toEqual([B.id, READY(B.name)])
    })

    it('S1 的 B 在 S2 显示时才写成，律师随后在 S2 也选 B：照样写进 S2（S1 的结果不当成 S2 服务那边的值）', async () => {
      await pick(A.id); await flush(600)
      svc.writeDelay = 1000
      await pick(B.id); await flush(600)
      await mount('S2'); await flush(1500) // S2 先读回（自由对话），S1 的 B 随后写成
      svc.writeDelay = 0
      await pick(B.id); await flush(600)
      expect(svc.selections.get('S2')).toMatchObject({ entry: B.id })
      expect(status()).toBe(READY(B.name))
      expect(await send('S2')).toBe(B.id)
    })

    it('切到 S2、读回前就选了和 S1 一样的 A：照样写进 S2，不拿 S1 服务那边的值当 S2 的', async () => {
      await pick(A.id); await flush(600)
      svc.readDelay = 2000
      await mount('S2')
      await pick(A.id); await flush(600)
      expect(status()).toBe('正在保存选择…')
      await flush(2500)
      expect(svc.selections.get('S2')).toMatchObject({ entry: A.id })
      expect([shown(), status()]).toEqual([A.id, READY(A.name)])
      expect(await send('S2')).toBe(A.id)
    })

    it('X8 改 B 未到防抖就重载：读回 A、按 A 跑（B 没写成，和显示一致）', async () => {
      await pick(A.id); await flush(600)
      await pick(B.id); await flush(200)
      await restart('S1')
      expect([shown(), status()]).toEqual([A.id, READY(A.name)])
      expect(await send('S1')).toBe(A.id)
    })
  })
})
