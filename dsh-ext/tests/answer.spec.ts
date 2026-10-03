// T14 派修 2（执行令 2026-10-03 15:41；用户选"对话区显示草稿"）：到达用量上限那一轮模型没写出回答，
// 输入区上方显示提示和刚存的草稿，出处是可点按钮；成果页"在对话区查看"转到那条会话。
// 另：Host 读草稿（host/task-answer.ts）的路径与链接核对、提示文字、出处拆分、turnNotice 带任务编号。
// @vitest-environment jsdom
import { mkdirSync, mkdtempSync, rmSync, symlinkSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { act } from 'react'
import { readTaskAnswer, MAX_DRAFT_BYTES } from '../host/task-answer.ts'
import { TurnNotices } from '../shared/turn-notices.ts'
import { answerNotice } from '../ui/answer.tsx'
import { citationInlineMarks } from '../ui/citation.ts'
import { BUDGET_STOPPED } from '../ui/dock.tsx'
import { BUDGET_STOPPED as AGENT_BUDGET_STOPPED } from '../agent/index.ts'
import { setNav } from '../ui/kit.tsx'
import { openAnswer } from '../ui/results.tsx'
import { app, setApi } from '../ui/state.ts'
import { api, CASE, flush, h, mount, setup, teardown } from './helpers/dock-lab.ts'

const T = 'T-20261003145955-de5b'
const DRAFT = '# 刑事阅卷笔录\n\n- 骗取吴某保证金 80,000 元〔起诉意见书 第2页〕\n- 张某甲称用于还网贷〔讯问笔录 第2页、转账截图 第1页〕\n'

/** 一个案件根，里面有任务目录：task.json、result.json、草稿。 */
function caseWith(opts: { status?: string; used?: number; draft?: string | null; draftPath?: string } = {}) {
  const root = mkdtempSync(join(tmpdir(), 'lb-answer-'))
  const dir = join(root, '工作区', '任务', T)
  mkdirSync(join(dir, '草稿'), { recursive: true })
  const path = opts.draftPath ?? `工作区/任务/${T}/草稿/刑事阅卷笔录-v1.md`
  if (opts.draft !== null) writeFileSync(join(dir, '草稿', '刑事阅卷笔录-v1.md'), opts.draft ?? DRAFT)
  writeFileSync(join(dir, 'task.json'), JSON.stringify({ task_id: T, session_id: 'S-RUN', budget: { model_calls: 8, tool_calls: 24, minutes: 45 } }))
  writeFileSync(join(dir, 'result.json'), JSON.stringify({ status: opts.status ?? 'budget_stopped', usage: { model_calls: opts.used ?? 8 },
    drafts: opts.draft === null ? [] : [{ title: '刑事阅卷笔录', path, version: 1 }] }))
  return root
}

describe('Host 读任务结果（host/task-answer.ts）', () => {
  const roots: string[] = []
  afterEach(() => { for (const r of roots.splice(0)) rmSync(r, { recursive: true, force: true }) })
  const mk = (o?: Parameters<typeof caseWith>[0]) => { const r = caseWith(o); roots.push(r); return r }

  it('读出状态、会话、用量与上限、最新一版草稿正文', () => {
    const r = readTaskAnswer(mk(), T)
    expect(r).toEqual({ ok: true, value: { status: 'budget_stopped', session_id: 'S-RUN', used: 8, limit: 8,
      draft: { title: '刑事阅卷笔录', version: 1, path: `工作区/任务/${T}/草稿/刑事阅卷笔录-v1.md`, text: DRAFT, truncated: false } } })
  })
  it('没存过草稿：draft 为 null', () => {
    const r = readTaskAnswer(mk({ draft: null }), T)
    expect(r.ok && r.value.draft).toBe(null)
  })
  it('result.json 里的草稿路径不是这个任务自己的 草稿\\ 下一层：不读（那个文件真的在也不读）', () => {
    for (const draftPath of [`工作区/任务/${T}/../../../x.md`, `工作区/任务/T-20261003145955-ffff/草稿/a.md`, `工作区/任务/${T}/草稿/a.txt`, `工作区/任务/${T}/草稿/子/a.md`, `工作区/任务/${T}/task.md`]) {
      const root = mk({ draftPath })
      const target = join(root, ...draftPath.split('/'))
      if (target.startsWith(root)) { mkdirSync(join(target, '..'), { recursive: true }); writeFileSync(target, '不该被读出来的文件') }
      const r = readTaskAnswer(root, T)
      expect(r.ok && r.value.draft, draftPath).toBe(null)
    }
  })
  it('任务编号不合格式、根不是绝对路径：请求参数有误；没有这个任务：TASK_NOT_FOUND', () => {
    const root = mk()
    for (const id of ['T-1', '../x', `${T}/..`, 12]) expect(readTaskAnswer(root, id)).toMatchObject({ ok: false, error: { code: 'INVALID_ARGUMENT' } })
    expect(readTaskAnswer('相对\\路径', T)).toMatchObject({ ok: false, error: { code: 'INVALID_ARGUMENT' } })
    expect(readTaskAnswer(root, 'T-20261003145955-0000')).toMatchObject({ ok: false, error: { code: 'TASK_NOT_FOUND' } })
  })
  it('草稿是链接（可能指到案件外）：不读', () => {
    const root = mk({ draft: null })
    const outside = mkdtempSync(join(tmpdir(), 'lb-answer-out-')); roots.push(outside)
    writeFileSync(join(outside, 'secret.md'), '案件外的文件')
    const dir = join(root, '工作区', '任务', T)
    try { symlinkSync(join(outside, 'secret.md'), join(dir, '草稿', 'x.md'), 'file') } catch { return } // 没有建链接权限的机器上跳过
    writeFileSync(join(dir, 'result.json'), JSON.stringify({ status: 'budget_stopped', drafts: [{ title: 'x', path: `工作区/任务/${T}/草稿/x.md`, version: 1 }] }))
    const r = readTaskAnswer(root, T)
    expect(r.ok && r.value.draft).toBe(null)
  })
  it('草稿过长：截到上限并标 truncated', () => {
    const r = readTaskAnswer(mk({ draft: 'a'.repeat(MAX_DRAFT_BYTES + 10) }), T)
    expect(r.ok && r.value.draft?.truncated).toBe(true)
    expect(r.ok && r.value.draft?.text.length).toBe(MAX_DRAFT_BYTES)
  })
})

describe('提示文字（answerNotice）', () => {
  const d = { title: 'x', version: 1, path: 'p', text: '', truncated: false }
  it('用完模型调用次数、有草稿：执行令原文', () => {
    expect(answerNotice({ status: 'budget_stopped', used: 8, limit: 8, draft: d })).toBe('已用完本次运行的模型调用次数（8/8），结果已保存到成果')
  })
  it('时间到（次数没用完）、没存草稿、上限读不到', () => {
    expect(answerNotice({ status: 'budget_stopped', used: 5, limit: 8, draft: d })).toBe('已到本次运行的时间上限，结果已保存到成果')
    expect(answerNotice({ status: 'budget_stopped', used: 8, limit: 8, draft: null })).toBe('已用完本次运行的模型调用次数（8/8），没有存下草稿；做到哪里请看成果里的"未完成"')
    expect(answerNotice({ status: 'budget_stopped', used: null, limit: null, draft: d })).toBe('已到本次运行的时间上限，结果已保存到成果')
  })
})

describe('出处拆分（citationInlineMarks，给 MarkdownText）', () => {
  const deps = { caseId: () => 'c', materials: async () => [], notice: () => {}, openSource: () => {} }
  it('一处一个按钮，顿号分开的多处各成按钮，括号和顿号留作文字；没有出处返回 undefined', () => {
    const parts = citationInlineMarks(deps).split('甲〔讯问笔录 第2页、转账截图 第1页〕乙')!
    expect(parts.map((p) => (typeof p === 'string' ? p : `[${p.text}]`))).toEqual(['甲〔', '[讯问笔录 第2页]', '、', '[转账截图 第1页]', '〕乙'])
    expect(citationInlineMarks(deps).split('没有出处〔未找到依据〕')).toBe(undefined)
  })
})

describe('turnNotice 带任务编号（shared/turn-notices.ts）', () => {
  it('记 BUDGET_STOPPED 时一并记任务编号，取一次即删；别的码不带任务编号；界面与 Agent 插件用同一个码', () => {
    const n = new TurnNotices()
    n.note('S1', 'BUDGET_STOPPED', T)
    expect(n.takeWithTask('S1')).toEqual({ code: 'BUDGET_STOPPED', task_id: T })
    expect(n.takeWithTask('S1')).toEqual({ code: null, task_id: null })
    n.note('S1', 'BUDGET_STOPPED', T); n.note('S1', 'CASE_MOVED')
    expect(n.takeWithTask('S1')).toEqual({ code: 'CASE_MOVED', task_id: null })
    expect(BUDGET_STOPPED).toBe(AGENT_BUDGET_STOPPED)
  })
})

describe('输入区上方显示草稿（dock）与成果页"在对话区查看"', () => {
  let root = ''
  const opened: Array<[string, Record<string, string> | undefined]> = []
  const sessions: string[] = []
  beforeEach(async () => {
    await setup()
    root = caseWith()
    opened.length = 0; sessions.length = 0
    setNav({ pickDirectory: async () => null, pathFor: () => '', openCaseWorkspace: async () => {}, goHome: () => {}, refreshModels: () => {},
      openTab: (kind, params) => { opened.push([kind, params]) }, openSession: (id) => { sessions.push(id) } })
    app.set((s) => ({ ...s, currentRoot: CASE.root, answers: {} }))
  })
  afterEach(async () => { await teardown(); setNav(undefined); rmSync(root, { recursive: true, force: true }) })
  const withApi = (code: string | null) => setApi({
    ...api(),
    turnNotice: async () => ({ ok: true, value: { code, task_id: code ? T : null } }),
    taskAnswer: async (r: any) => readTaskAnswer(root, r.task_id),
    materialsList: async () => ({ ok: true, value: { materials: [
      { material_id: 'M3', name: '起诉意见书', unit: 'page', unit_count: 5, status: 'parsed' },
      { material_id: 'M2', name: '讯问笔录', unit: 'page', unit_count: 3, status: 'parsed' },
      { material_id: 'M4', name: '转账截图', unit: 'page', unit_count: 1, status: 'parsed' },
    ] } }),
  } as never)

  it('上一轮 BUDGET_STOPPED：显示执行令原文提示和草稿，三处出处是按钮，点了打开原文标签', async () => {
    withApi(BUDGET_STOPPED)
    await mount('S1'); await flush(800)
    const text = h.container.textContent ?? ''
    expect(text).toContain('已用完本次运行的模型调用次数（8/8），结果已保存到成果')
    expect(text).toContain('草稿"刑事阅卷笔录"（第 1 版）')
    const cites = [...h.container.querySelectorAll('button[aria-label^="打开原文："]')].map((b) => b.textContent)
    expect(cites).toEqual(['起诉意见书 第2页', '讯问笔录 第2页', '转账截图 第1页'])
    await act(async () => { (h.container.querySelector('button[aria-label="打开原文：讯问笔录 第2页"]') as HTMLButtonElement).click() })
    await flush(50)
    expect(opened).toEqual([['lawbench-source', { material_id: 'M2', citation: '〔讯问笔录 第2页〕' }]])
  })
  it('别的码（或没有）不显示；"收起"后消失', async () => {
    withApi('CASE_MOVED')
    await mount('S1'); await flush(800)
    expect(h.container.textContent).not.toContain('本次运行的模型调用次数')
    withApi(BUDGET_STOPPED)
    await mount('S2'); await flush(800)
    expect(h.container.textContent).toContain('本次运行的模型调用次数')
    const fold = [...h.container.querySelectorAll('button')].find((b) => b.textContent === '收起')!
    await act(async () => { fold.click() }); await flush()
    expect(h.container.textContent).not.toContain('本次运行的模型调用次数')
  })
  it('成果页"在对话区查看"：转到任务记下的会话并在那里显示；读不到任务时给中文提示、不转', async () => {
    withApi(null)
    await openAnswer({ ...CASE, root }, 'S-NOW', T)
    expect(sessions).toEqual(['S-RUN'])
    expect(app.get().answers).toEqual({ 'S-RUN': T })
    await openAnswer({ ...CASE, root }, 'S-NOW', 'T-20261003145955-0000')
    expect(sessions).toEqual(['S-RUN'])
    expect(app.get().dialogs.at(-1)).toMatchObject({ title: '没能打开这次运行的结果' })
  })
})

vi.setConfig({ testTimeout: 20_000 })
