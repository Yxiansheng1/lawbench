// 令 0329 P0（用户真机 2026-10-11）：思考 → 加载技能 → 上下文已压缩 → 同一句思考 → 又加载技能……一圈一次模型调用，16/16 用完、没有草稿。
// 根因在 DSH 压缩的默认值（这里用 DSH 自己的源码算，不抄公式）：
//   1. 触发点 = min(窗口 × thresholdRatio, 窗口 − 请求的 maxTokens − headroomTokens)，headroomTokens 默认 65536：
//      我方按 Skill 的 max_tokens（16384 / 32768 / 49152）发请求，触发点只有 49152 / 32768 / 16384——上下文不到一半就每一步都压缩，
//      前面的案件卡片、任务输入、已加载的技能被换成摘要，模型从头再想、再加载；
//   2. 压缩一触发先剪工具结果，超过 8192 字的只留头 4096、尾 1024：一次读满 8000 字的材料转成 JSON 后会被剪掉中间。
// 改法：组合包（cordis.patch.yml）把触发点放回窗口的五成六到八成、剪枝门槛放到一次读回的材料之上；Agent 插件加防循环兜底。
import { readFileSync, readdirSync, existsSync } from 'node:fs'
import { join } from 'node:path'
import { resolveCompactSpec, resolveConfig, resolveTargetPolicy } from '../../dsh/packages/compaction/compaction-basic/src/config.ts'
import { DEFAULTS as PRUNER_DEFAULTS, resolveConfig as resolvePruner } from '../../dsh/packages/compaction/compaction-tool-result-pruner/src/config.ts'
import { ToolResultPruner } from '../../dsh/packages/compaction/compaction-tool-result-pruner/src/index.ts'
import { BUDGET_STOPPED, DENY_SKILL_RELOAD, LegalAgent } from '../agent/index.ts'
import { MAX_COMPACTIONS, MAX_SKILL_LOADS, TaskState, UNFINISHED_TITLE } from '../agent/task-state.ts'
import type { CoreClient } from '../shared/core-client.ts'

const YML = readFileSync(join(__dirname, '..', 'cordis.patch.yml'), 'utf8')
/** 组合包里某一行插件的 config 块里的数字项（按缩进取紧跟着的 config）。 */
function configOf(id: string): Record<string, number> {
  const at = YML.indexOf(`- id: ${id}\n`)
  if (at < 0) throw new Error(`组合包里没有 ${id}`)
  const rest = YML.slice(at).split('\n').slice(1)
  const out: Record<string, number> = {}
  let inConfig = false
  for (const line of rest) {
    if (/^\s*- id:/.test(line)) break
    if (/^\s*#/.test(line)) continue
    if (/^\s*config:\s*$/.test(line)) { inConfig = true; continue }
    const m = /^\s+(\w+):\s*([\d.]+)\s*$/.exec(line)
    if (inConfig && m) out[m[1]!] = Number(m[2])
  }
  return out
}
const WINDOW = Number(/contextWindow:\s*(\d+)/.exec(YML)![1])
const TARGET = { provider: 'lawfirm', model: 'qwen38-27b' }
/** 我方各 Skill 的 max_tokens（请求按它预留输出）。 */
const SKILLS_DIR = join(__dirname, '..', '..', 'skills')
const skills = readdirSync(SKILLS_DIR).filter((d) => existsSync(join(SKILLS_DIR, d, 'SKILL.md'))).map((d) => {
  const text = readFileSync(join(SKILLS_DIR, d, 'SKILL.md'), 'utf8')
  return { name: d, text, maxTokens: Number(/max_tokens:\s*(\d+)/.exec(text)?.[1] ?? 0) }
})
const threshold = (cfg: Parameters<typeof resolveConfig>[0], maxTokens: number): number =>
  resolveCompactSpec(resolveTargetPolicy(resolveConfig(cfg), TARGET), WINDOW, maxTokens).thresholdTokens

describe('压缩触发点（用 DSH 的 compaction-basic 源码算）', () => {
  it('根因：DSH 默认值下，按我方 Skill 的 max_tokens 请求，触发点只有窗口的四成、四分之一、八分之一', () => {
    expect(WINDOW).toBe(131072)
    expect([16384, 32768, 49152].map((m) => threshold({}, m))).toEqual([49152, 32768, 16384])
    // 真机右下角显示 ~52K/131K 时一直在压缩：自由对话和刑期计算（max_tokens 16384）的触发点正是 49152
    expect(skills.find((s) => s.name === 'sentence-calc')!.maxTokens).toBe(16384)
    expect(52_000).toBeGreaterThan(threshold({}, 16384))
    for (const s of skills) expect(threshold({}, Math.max(s.maxTokens, 16384)) / WINDOW, s.name).toBeLessThan(0.4)
  })

  it('改后：组合包的配置下，每个 Skill 的触发点都过窗口的一半；max_tokens 不超过 16384 的在八成', () => {
    const cfg = configOf('compaction-basic')
    expect(cfg).toEqual({ thresholdRatio: 0.8, headroomTokens: 8192, maxTokens: 8192 })
    expect(skills.length).toBeGreaterThanOrEqual(18)
    for (const s of skills) {
      expect(s.maxTokens, s.name).toBeGreaterThan(0)
      const t = threshold(cfg, s.maxTokens)
      expect(t / WINDOW, `${s.name} max_tokens=${s.maxTokens}`).toBeGreaterThan(0.55)
      expect(t, s.name).toBeGreaterThanOrEqual(threshold({}, s.maxTokens) * 1.5)
      if (s.maxTokens <= 16384) expect(t, s.name).toBe(Math.floor(WINDOW * 0.8))
    }
    expect([16384, 32768, 49152].map((m) => threshold(cfg, m))).toEqual([104857, 90112, 73728])
    // 真机那一幕（52K）离新的触发点还有一倍
    expect(52_000).toBeLessThan(threshold(cfg, 16384) / 2 + 1)
  })
})

describe('剪工具结果（用 DSH 的 tool-result-pruner 源码剪）', () => {
  const prune = (cfg: Parameters<typeof resolvePruner>[0], text: string) => {
    const self = { config: resolvePruner(cfg), measureContent: ToolResultPruner.prototype.measureContent }
    return ToolResultPruner.prototype.pruneContent.call(self as never, [{ type: 'text', text }])
  }
  /** 一次读材料读满 8000 字时工具结果的样子（Agent 插件把返回值转成 JSON 文本）。 */
  const read8000 = JSON.stringify({ name: '讯问笔录', text: '【第1页】\n' + '嫌疑人供述"借款"经过。\n'.repeat(700).slice(0, 8000), has_more: true, next_start: 9, unit: 'page' })

  it('根因：DSH 默认门槛（8192 字）下，一次读满 8000 字的材料会被剪掉中间（技能全文不到 6000 字，本来不剪）', () => {
    expect(PRUNER_DEFAULTS).toMatchObject({ thresholdChars: 8192, headChars: 4096, tailChars: 1024 })
    expect(read8000.length).toBeGreaterThan(8192)
    const cut = prune({}, read8000)
    expect(cut).not.toBeNull()
    expect((cut![0] as { text: string }).text.length).toBeLessThan(5200)
    for (const s of skills) expect(prune({}, s.text), s.name).toBeNull()
  })

  it('改后：组合包的门槛下，一次读满的材料、技能全文都不剪；真正异常大的结果仍然剪', () => {
    const cfg = configOf('tool-result-pruner')
    expect(cfg).toEqual({ thresholdChars: 48000, headChars: 32000, tailChars: 8000 })
    expect(prune(cfg, read8000)).toBeNull()
    expect(prune(cfg, read8000.repeat(3))).toBeNull() // 余量：读回的再长两倍也不剪
    for (const s of skills) expect(prune(cfg, s.text), s.name).toBeNull()
    expect(prune(cfg, 'x'.repeat(cfg.thresholdChars! + 1))).not.toBeNull()
  })
})

// —— Agent 插件的防循环兜底：假的技能加载和假的压缩器 ——
const T = 'T-20261011032900-ab12'
function fakeCore(modelCalls = 16) {
  const calls: Array<{ cmd: string; body: Record<string, unknown> }> = []
  const saved = JSON.parse(readFileSync(join(__dirname, '..', '..', 'contracts', 'examples', 'tool_save_draft.result.json'), 'utf8')) as unknown
  const core = {
    call: async (cmd: string, body: Record<string, unknown>) => {
      calls.push({ cmd, body })
      if (cmd === 'task/begin') return { ok: true, value: { task_id: T, params: { thinking: '低', window: '64K', max_tokens: 16384 }, budget: { model_calls: modelCalls, tool_calls: 24, minutes: 45 } } }
      if (cmd === 'context') return { ok: true, value: { l0: { text: '案件卡片' }, l1: { text: '任务输入', truncated: false, toc: [] } } }
      if (cmd === 'tool') return { ok: true, value: saved }
      return { ok: true, value: {} }
    },
  } as unknown as CoreClient
  return { core, calls }
}
const agentObj = (id: string) => ({ id, session: { header: { cwd: 'D:\\案件\\张某甲诈骗案' } } })
const enter = () => ({ kind: 'enter' as const, messages: [] })

describe('防循环兜底（Agent 插件）', () => {
  it('同一个技能在一个任务里最多加载 3 次，第 4 次拒绝并告诉模型不要再加载；别的技能、别的任务各算各的', async () => {
    expect(MAX_SKILL_LOADS).toBe(3)
    const s = new TaskState(T, { model_calls: 16, tool_calls: 24, minutes: 45 }, { thinking: '低', window: '64K', max_tokens: 16384 })
    expect([1, 2, 3, 4, 5].map(() => s.beforeSkillLoad('sentence-calc').allow)).toEqual([true, true, true, false, false])
    expect(s.beforeSkillLoad('criminal-reading-notes').allow).toBe(true)

    const logs: Array<[string, string]> = []
    const f = fakeCore()
    const a = new LegalAgent(f.core, ((level: string, event: string) => { logs.push([level, event]) }) as never)
    await a.preStep(agentObj('s'), 1, enter())
    for (let i = 0; i < 3; i++) expect(a.preTool('s', 'skill', { name: 'sentence-calc' })).toEqual({ kind: 'allow' })
    expect(a.preTool('s', 'skill', { name: 'sentence-calc' })).toEqual({ kind: 'deny', reason: DENY_SKILL_RELOAD })
    expect(DENY_SKILL_RELOAD).toContain('不要再加载')
    expect(logs.filter((l) => l[1] === 'agent.skill_reload_loop')).toEqual([['warn', 'agent.skill_reload_loop']])
    expect(a.preTool('s', 'skill', { name: 'doc-revise' })).toEqual({ kind: 'allow' })
    // 新的一轮（新任务）重新计
    await a.onSessionEvent('s', { type: 'turn/end', data: { reason: { kind: 'completed' } } })
    await a.preStep(agentObj('s'), 1, enter())
    expect(a.preTool('s', 'skill', { name: 'sentence-calc' })).toEqual({ kind: 'allow' })
    // 没有任务时（界面别处调）不拦
    expect(a.preTool('nobody', 'skill', { name: 'sentence-calc' })).toEqual({ kind: 'allow' })
  })

  it('重放真机上的循环（每圈：模型调用 → 加载技能 → 压缩）：不会转到 16 次用完——第 4 次加载被拒，压缩第 4 次后存稿收尾', async () => {
    expect(MAX_COMPACTIONS).toBe(3)
    const logs: Array<[string, string, Record<string, unknown> | undefined]> = []
    const noted: Array<[string, string, string | undefined]> = []
    const f = fakeCore(16)
    const a = new LegalAgent(f.core, ((level: string, event: string, meta?: Record<string, unknown>) => { logs.push([level, event, meta]) }) as never,
      (id, code, taskId) => { noted.push([id, code, taskId]) })
    let rounds = 0
    const loads: string[] = []
    for (let step = 1; step <= 16; step++) {
      const d = await a.preStep(agentObj('s'), step, enter())
      if (d.kind === 'reject') break
      rounds++
      // 模型：想了同一句话，然后去加载技能
      await a.onSessionEvent('s', { type: 'assistant/message', data: { message: { content: [{ type: 'text', text: '用户问量刑问题，根据案件卡片诈骗金额 126,500 元。' }] } } })
      loads.push(a.preTool('s', 'skill', { name: 'sentence-calc' }).kind)
      // DSH：上下文已压缩
      await a.onSessionEvent('s', { type: 'compaction/summary' })
    }
    expect(loads).toEqual(['allow', 'allow', 'allow', 'deny'])
    expect(rounds).toBe(4) // 原来是 16 圈
    expect(noted).toEqual([['s', BUDGET_STOPPED, T]])
    // 收尾时把最后一条回复代存为未完成草稿（令 0321），律师不至于一无所有
    const saves = f.calls.filter((c) => c.cmd === 'tool')
    expect(saves.map((c) => (c.body.args as { title: string }).title)).toEqual([UNFINISHED_TITLE])
    const loop = logs.filter((l) => l[1] === 'agent.compaction_loop')
    expect(loop.length).toBe(2) // 超过上限时一条，收尾时一条
    expect(loop.at(-1)![2]).toMatchObject({ compactions: 4, stopped: true })
    expect(a.tasks.get('s')!.endReason('completed')).toBe('budget')
    // 日志只有次数
    expect(JSON.stringify(logs)).not.toMatch(/126,500|量刑|sentence-calc/)
  })

  it('正常的任务（压缩不超过 3 次、技能加载不超过 3 次）不受影响', async () => {
    const f = fakeCore(16)
    const a = new LegalAgent(f.core, (() => {}) as never)
    for (let step = 1; step <= 16; step++) {
      expect((await a.preStep(agentObj('s'), step, enter())).kind).toBe('enter')
      if (step === 1) expect(a.preTool('s', 'skill', { name: 'contract-review' }).kind).toBe('allow')
      if (step === 5 || step === 9 || step === 13) await a.onSessionEvent('s', { type: 'compaction/summary' })
    }
    expect(a.tasks.get('s')!.compactions).toBe(3)
    expect(a.tasks.get('s')!.compactionLoop).toBe(false)
  })
})

describe('压缩之后发新消息：模型该答新消息（注记 0342）', () => {
  it('每一轮我方注入的案件卡片、任务输入排在律师消息之前：模型收到的最后一条用户消息是律师刚发的那句', async () => {
    const f = fakeCore()
    const a = new LegalAgent(f.core, (() => {}) as never)
    const hello = { id: 'u-1', role: 'user' as const, content: [{ type: 'text' as const, text: '你好' }], source: { kind: 'user' } }
    const d = await a.preStep(agentObj('s'), 1, { kind: 'enter', messages: [hello] } as never)
    const msgs = (d as { messages: Array<{ content: Array<{ text: string }>; source: { kind?: string; form?: string } }> }).messages
    expect(msgs.map((m) => m.source.form ?? m.source.kind)).toEqual(['snapshot', 'user'])
    expect(msgs.at(-1)!.content[0]!.text).toBe('你好')
    expect(msgs[0]!.content[0]!.text).toContain('案件卡片（L0）')
  })

  it('"立即收尾"这类提醒仍排在最后（它就是要模型马上照做的）', async () => {
    const f = fakeCore(2)
    const a = new LegalAgent(f.core, (() => {}) as never)
    const hello = { id: 'u-1', role: 'user' as const, content: [{ type: 'text' as const, text: '你好' }], source: { kind: 'user' } }
    const d = await a.preStep(agentObj('s'), 1, { kind: 'enter', messages: [hello] } as never)
    const msgs = (d as { messages: Array<{ content: Array<{ text: string }>; source: { kind?: string; form?: string } }> }).messages
    expect(msgs.map((m) => m.source.form ?? m.source.kind)).toEqual(['snapshot', 'user', 'notice'])
    expect(msgs.at(-1)!.content[0]!.text).toContain('立即收尾')
  })

  it('DSH 补丁 P-25：压缩摘要插回对话时写明"检查点是历史，当前请求是之后最新的那条用户消息"；写摘要时待办只列最近一条消息要求的事', () => {
    const src = readFileSync(join(__dirname, '..', '..', 'dsh', 'packages', 'compaction', 'compaction-basic', 'src', 'summarizer.ts'), 'utf8')
    const preamble = src.slice(src.indexOf('const CHECKPOINT_PREAMBLE ='), src.indexOf('export interface SummarizationInput'))
    expect(preamble).toContain('Everything inside this checkpoint is history from earlier turns')
    expect(preamble).toContain('The current request is the latest user message after this checkpoint')
    expect(preamble).toContain('do not resume an earlier request from the checkpoint unless that message asks for it')
    expect(src).toContain('list only work the MOST RECENT user message asks for')
    // 补丁文件登记在案
    const ledger = readFileSync(join(__dirname, '..', '..', 'dsh-patches', 'PATCHES.md'), 'utf8')
    expect(ledger).toContain('P-25-checkpoint-is-history.patch')
  })
})
