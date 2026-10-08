// @vitest-environment jsdom
// 令 1321 C：聊天里交代成果——模型保存草稿后在那一轮答复下方插草稿卡片（确认保存、选作下一步输入、自检/没读全折叠），
// 确认保存生成 Word 后同一位置变成成果卡片（打开、打开所在文件夹）。
import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { DRAFT_TOOL, draftsDefinition, draftsForClosing, NO_TASK_TIP, outputOfDraft, parseDraftResult, resetCaseResults, taskOfDraft, TURN_DATA_KEY, TurnResultCards, type SavedDraft } from '../ui/result-cards.tsx'
import { app, setApi, type LawbenchApi } from '../ui/state.ts'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
const T = 'T-20261008120000-ab12'
const PATH = `工作区/任务/${T}/草稿/借款合同-v1.md`
const CASE = { case_id: 'c-1', name: '周某诉青禾贸易借款合同纠纷（虚构）', root: 'D:\\案件\\周某借款', exists: true }
const COV = { total: 3, fully_read: ['甲'], partially_read: [], not_read: ['乙'], unreadable: [{ name: '扫描件丙', reason: '还没识别，读不到文字，请先提交识别' }] }
const CHECK = { passed: false, problems: [{ class: 'B', severity: 'must_fix' as const, excerpt: '借款 50 万', message: '原文是 30 万' }], stats: { citations: 6, must_fix: 1, hints: 0 } }
const resultContent = (o: Record<string, unknown>) => [{ type: 'text', text: JSON.stringify(o) }]

describe('每轮草稿（会话事件）', () => {
  const run = (events: Array<{ type: string; seq: number; surfaceOp?: string; data: Record<string, unknown> }>) => {
    let state: ReturnType<typeof draftsDefinition.start> | undefined
    for (const e of events) {
      const m = draftsDefinition.match(e)
      if (!m) continue
      state = m.role === 'start' ? draftsDefinition.start(undefined, { event: e }) : draftsDefinition.update({ state: state! }, { event: e })
    }
    return draftsDefinition.buildLocationData({ state }, 'turn')
  }

  it('case_save_draft 成功：记成一份草稿（标题取调用参数，路径、版本、自检、覆盖取返回）；别的工具、出错的、返回不合规的不记', () => {
    const data = run([
      { type: 'turn/start', seq: 1, data: { turn: 7 } },
      { type: 'tool/call', seq: 2, data: { turn: 7, callId: 'c1', name: DRAFT_TOOL, arguments: JSON.stringify({ title: '借款合同', content: '……' }) } },
      { type: 'tool/call', seq: 3, data: { turn: 7, callId: 'c2', name: 'case_read', arguments: '{}' } },
      { type: 'tool/call', seq: 4, data: { turn: 7, callId: 'c3', name: DRAFT_TOOL, arguments: JSON.stringify({ title: '出错的', content: '' }) } },
      { type: 'tool/result', seq: 5, surfaceOp: 'append', data: { turn: 7, message: { source: { callId: 'c1' }, content: resultContent({ path: PATH, version: 1, coverage: COV, citation_check: CHECK, not_fully_read: [] }) } } },
      { type: 'tool/result', seq: 6, surfaceOp: 'append', data: { turn: 7, message: { source: { callId: 'c2' }, content: resultContent({ text: '材料' }) } } },
      { type: 'tool/result', seq: 7, surfaceOp: 'append', data: { turn: 7, message: { source: { callId: 'c3' }, isError: true, content: resultContent({ path: 'x', version: 1 }) } } },
    ])
    expect(data).toMatchObject({ kind: 'turn', turn: 7, key: TURN_DATA_KEY })
    // DSH 的约束：每轮数据的 key 必须等于定义的 kind（不然整条会话事件都被拒，聊天区全空）
    expect(draftsDefinition.kind).toBe(TURN_DATA_KEY)
    expect((data as { value: { drafts: SavedDraft[] } }).value.drafts).toEqual([{ seq: 5, title: '借款合同', path: PATH, version: 1, coverage: COV, citation_check: CHECK }])
  })

  it('解析返回：文本块里的 JSON；缺路径或版本为 null', () => {
    expect(parseDraftResult(resultContent({ path: PATH, version: 2 }))).toEqual({ path: PATH, version: 2, coverage: null, citation_check: null })
    expect(parseDraftResult(resultContent({ version: 2 }))).toBeNull()
    expect(parseDraftResult([{ type: 'text', text: 'not json' }])).toBeNull()
  })

  it('收尾显示：不晚于收尾消息的；同名草稿只留最新一版', () => {
    const d = (seq: number, title: string, version: number) => ({ seq, title, path: `${title}-v${version}.md`, version, coverage: null, citation_check: null })
    expect(draftsForClosing([d(3, '甲', 1), d(5, '甲', 2), d(6, '乙', 1), d(20, '丙', 1)], 10).map((x) => x.path)).toEqual(['甲-v2.md', '乙-v1.md'])
    expect(draftsForClosing(undefined)).toEqual([])
  })

  it('对上任务和成果：草稿路径找任务；没有确认记录时，任务里同标题只有这一份草稿、成果里这个任务同标题只有一条才对上（不按版本）', () => {
    const tasks = [{ task_id: T, skill: 'civil-contract-review', status: 'completed', drafts: [{ title: '借款合同', path: PATH, version: 1 }] }]
    const task = taskOfDraft(tasks, PATH)
    expect(task?.task_id).toBe(T)
    expect(taskOfDraft(tasks, 'x')).toBeUndefined()
    // 成果版本按案件同标题最大 +1：这个任务唯一的草稿 v1 生成的可能是成果 v3
    const out = { title: '借款合同', version: 3, files: [{ format: 'docx', path: '成果/借款合同-v3.docx' }], task_id: T, confirmed_at: '2026-10-08T12:00:00+08:00' }
    expect(outputOfDraft([out], task, { title: '借款合同', version: 1, path: PATH })).toBe(out)
    expect(outputOfDraft([out], undefined, { title: '借款合同', version: 1, path: PATH })).toBeUndefined()
    // 别的任务的同名成果不算
    expect(outputOfDraft([{ ...out, task_id: 'T-20261008120000-ffff' }], task, { title: '借款合同', version: 1, path: PATH })).toBeUndefined()
  })

  it('复核 rv-A52 P1：同一任务存了 v1、v2，确认 v2 生成的是成果 v1——没有记录时两张卡都不切换；有确认记录时只切 v2', () => {
    const P1 = `工作区/任务/${T}/草稿/借款合同-v1.md`
    const P2 = `工作区/任务/${T}/草稿/借款合同-v2.md`
    const task = { task_id: T, skill: null, status: 'completed', drafts: [{ title: '借款合同', path: P1, version: 1 }, { title: '借款合同', path: P2, version: 2 }] }
    const out = { title: '借款合同', version: 1, files: [{ format: 'docx', path: '成果/借款合同-v1.docx' }], task_id: T, confirmed_at: '2026-10-08T12:00:00+08:00' }
    // 旧做法（同版本）会把 v1 卡片错标"已保存"、v2 仍可再点
    expect(outputOfDraft([out], task, { title: '借款合同', version: 1, path: P1 })).toBeUndefined()
    expect(outputOfDraft([out], task, { title: '借款合同', version: 2, path: P2 })).toBeUndefined()
    const rec = { [P2]: { version: 1, files: [{ format: 'docx', path: '成果/借款合同-v1.docx' }] } }
    expect(outputOfDraft([out], task, { title: '借款合同', version: 1, path: P1 }, rec)).toBeUndefined()
    expect(outputOfDraft([out], task, { title: '借款合同', version: 2, path: P2 }, rec)?.files).toEqual([{ format: 'docx', path: '成果/借款合同-v1.docx' }])
  })
})

describe('卡片', () => {
  let root: Root | undefined
  let box: HTMLDivElement
  let outputs: unknown[]
  let calls: Array<[string, unknown]>
  beforeEach(() => {
    box = document.createElement('div'); document.body.appendChild(box)
    outputs = []
    calls = []
    resetCaseResults()
    localStorage.clear()
    app.set((s) => ({ ...s, cases: [CASE], intents: {}, selections: {} }))
    setApi({
      tasksList: async () => ({ ok: true, value: { tasks: [{ task_id: T, skill: 'civil-contract-review', status: 'completed', drafts: [{ title: '借款合同', path: PATH, version: 1 }], finished_at: null, coverage: null, citation_check: null }] } }),
      outputsList: async () => ({ ok: true, value: { outputs } }),
      outputsConfirm: async (req: unknown) => {
        calls.push(['outputsConfirm', req])
        // 真服务口径：成果版本按案件同标题最大 +1（这里已有 v1、v2，生成 v3）
        outputs = [{ title: '借款合同', version: 3, files: [{ format: 'docx', path: '成果/借款合同-v3.docx' }], task_id: T, confirmed_at: '2026-10-08T12:00:00+08:00' }]
        return { ok: true, value: { outputs: [{ format: 'docx', path: '成果/借款合同-v3.docx', version: 3 }] } }
      },
      openFile: async (req: unknown) => { calls.push(['openFile', req]); return { ok: true, value: { opened: true } } },
      openFolder: async (req: unknown) => { calls.push(['openFolder', req]); return { ok: true, value: { opened: true } } },
    } as unknown as LawbenchApi)
  })
  afterEach(async () => { await act(async () => { root?.unmount() }); root = undefined; box.remove(); setApi(undefined); document.body.innerHTML = '' })

  const draft: SavedDraft = { seq: 5, title: '借款合同', path: PATH, version: 1, coverage: COV, citation_check: CHECK }
  const props = (drafts: SavedDraft[], seq = 10) => ({
    turn: { data: new Map([[TURN_DATA_KEY, { drafts }]]) }, seq, sessionId: 's-1',
    useSessions: <R>(sel: (s: { byId: Record<string, { cwd?: string }> }) => R) => sel({ byId: { 's-1': { cwd: CASE.root } } }),
  })
  const flush = async () => { await act(async () => { for (let i = 0; i < 5; i++) await Promise.resolve() }) }
  const render = async (p: ReturnType<typeof props>) => { root = createRoot(box); await act(async () => { root!.render(createElement(TurnResultCards, p as never)) }); await flush() }
  const button = (text: string) => [...document.querySelectorAll('button')].find((b) => b.textContent === text)

  it('这一轮没存草稿、不是案件会话：不出卡片', async () => {
    await render(props([]))
    expect(box.innerHTML).toBe('')
  })

  it('草稿卡片：标题、版本、"确认保存…""选作下一步输入"；自检结果、没读全（含待识别）折叠在卡片里', async () => {
    await render(props([draft]))
    const card = box.querySelector('[data-result-state="draft"]')!
    expect(card.textContent).toContain('借款合同')
    expect(card.textContent).toContain('草稿 · 第 1 版')
    expect(button('确认保存…')?.disabled).toBe(false)
    expect(card.textContent).toContain('自检结果：有 1 处必须修改')
    expect(card.textContent).toContain('本任务范围内 3 份材料，1 份待识别、1 份没读全')
    expect(card.querySelectorAll('details').length).toBe(2)
  })

  it('选作下一步输入：记进本案的待带入意向，再点取消', async () => {
    await render(props([draft]))
    await act(async () => { button('选作下一步输入')!.click() })
    expect(app.get().intents['c-1']?.inputs).toEqual([PATH])
    expect(button('已选作下一步输入')).toBeTruthy()
    await act(async () => { button('已选作下一步输入')!.click() })
    expect(app.get().intents['c-1']?.inputs).toEqual([])
  })

  it('确认保存后同一位置变成成果卡片：文件名、"打开"（默认程序，经 Host）、"打开所在文件夹"', async () => {
    await render(props([draft]))
    await act(async () => { button('确认保存…')!.click() })
    await act(async () => { button('保存到成果')!.click() })
    await flush()
    expect(calls[0]).toEqual(['outputsConfirm', { case_id: 'c-1', task_id: T, draft: PATH, formats: ['docx'], template: '文书' }])
    const card = box.querySelector('[data-result-state="output"]')!
    expect(card).toBeTruthy()
    expect(box.querySelector('[data-result-state="draft"]')).toBeNull()
    expect(card.textContent).toContain('成果/借款合同-v3.docx')
    // 记在本机：重开（缓存清掉）后仍是成果卡片
    expect(JSON.parse(localStorage.getItem('lawbench.confirmed.c-1')!)).toEqual({ [PATH]: { version: 3, files: [{ format: 'docx', path: '成果/借款合同-v3.docx' }] } })
    await act(async () => { button('打开')!.click() })
    await act(async () => { button('打开所在文件夹')!.click() })
    expect(calls.slice(1)).toEqual([
      ['openFile', { case_id: 'c-1', root: CASE.root, rel: '成果/借款合同-v3.docx' }],
      ['openFolder', { case_id: 'c-1', root: CASE.root, rel: '成果' }],
    ])
  })

  it('任务列表里没有这份草稿的任务：确认保存不可点，提示找不到运行记录（不一直说"正在读取"）', async () => {
    setApi({ tasksList: async () => ({ ok: true, value: { tasks: [] } }), outputsList: async () => ({ ok: true, value: { outputs: [] } }) } as unknown as LawbenchApi)
    await render(props([draft]))
    expect(button('确认保存…')?.disabled).toBe(true)
    expect(button('确认保存…')?.title).toBe(NO_TASK_TIP)
  })

  it('归档 Skill 的草稿：卡片上另有"核对归档方案并生成归档文件…"', async () => {
    setApi({
      tasksList: async () => ({ ok: true, value: { tasks: [{ task_id: T, skill: 'case-archiving', status: 'completed', drafts: [{ title: '借款合同', path: PATH, version: 1 }] }] } }),
      outputsList: async () => ({ ok: true, value: { outputs: [] } }),
    } as unknown as LawbenchApi)
    await render(props([draft]))
    expect(button('核对归档方案并生成归档文件…')).toBeTruthy()
  })
})
