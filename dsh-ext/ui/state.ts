// 界面插件的共享状态：已登记的案件、会话 → 案件的对应、每个会话当前选的胶囊 / Skill / 参数 / 前序成果、
// 首页和成果区留给案件的"待带入意向"、弹框队列。
// 案件 = DSH 的工作区（Spec 1.2）：会话的工作目录就是案件文件夹。界面不接受、也不保存案件文件内容。
import type { ApiResult } from '../host/index.ts'
import { createStore } from './store.ts'
import { lawyerMessage } from './format.ts'

export interface CaseRef { case_id: string; name: string; root: string; exists?: boolean }

export interface Params { thinking: '关闭' | '低' | '中' | '高'; window: '32K' | '64K' | '128K'; max_tokens: number; temperature?: number }

/**
 * 会话输入区上方的选择（契约 1.2：服务管"当前选择"，界面显示前读、改动时写）。capsuleId 为 null 表示自由对话。
 * saved：这份选择是否已经和服务一致（刚从服务读回，或写成功之后没再改）；律师改动后为 false，直到写成功。
 */
export interface Selection { capsuleId: string | null; skill: string | null; params: Params | null; inputs: string[]; saved: boolean }

export type Dialog =
  | { kind: 'confirm'; title: string; text: string; ok: string; resolve: (yes: boolean) => void }
  | { kind: 'notice'; title: string; text: string; lines?: string[] }
  | { kind: 'import'; caseRef: CaseRef; paths: string[]; from: string }
  | { kind: 'casePick'; then?: (c: CaseRef) => void }
  | { kind: 'placeholder'; title: string; text: string }

export interface AppState {
  cases: CaseRef[]
  /** 按会话 id（契约 1.2：服务的"当前选择"按会话存，界面同口径，T13 返修 P2-2）。 */
  selections: Record<string, Selection>
  /** 按案件 id：首页点胶囊、成果区"选用"留下的改动，由该案件当前会话的输入区读回服务的选择后取走一次。 */
  intents: Record<string, Intent>
  dialogs: Dialog[]
  /** 设置里的默认参数（settings.json 的 defaults、skill_presets）；未读到时为 null。 */
  defaults: Params | null
  presets: Record<string, Params>
  /** DSH 当前显示的会话的工作目录（apply 里按 uiSession、sessions 更新）；没有会话为 null。 */
  currentRoot: string | null
}

export const app = createStore<AppState>({ cases: [], selections: {}, intents: {}, dialogs: [], defaults: null, presets: {}, currentRoot: null })

/** 当前会话对应的已登记案件。 */
export const currentCase = (s: AppState): CaseRef | undefined =>
  s.currentRoot ? s.cases.find((c) => samePath(c.root, s.currentRoot!)) : undefined

/** 路径比较：不分大小写、正反斜杠一样、去掉末尾斜杠（Windows）。 */
export const samePath = (a: string, b: string): boolean => norm(a) === norm(b)
const norm = (p: string) => p.replace(/\//g, '\\').replace(/\\+$/, '').toLowerCase()

export const caseForRoot = (root: string | undefined): CaseRef | undefined =>
  root ? app.get().cases.find((c) => samePath(c.root, root)) : undefined

export function rememberCase(c: CaseRef): void {
  app.set((s) => ({ ...s, cases: [c, ...s.cases.filter((x) => x.case_id !== c.case_id && !samePath(x.root, c.root))] }))
}

const EMPTY_SELECTION: Selection = { capsuleId: null, skill: null, params: null, inputs: [], saved: false }

/** 待带入意向：对选择的一次改动（字段同 Selection，没给的不改）。 */
export type Intent = Partial<Omit<Selection, 'saved'>>

/** 律师在输入区改动某会话的选择：记为未保存，输入区随后写给服务。 */
export function setSelection(sessionId: string, patch: Intent): void {
  app.set((s) => {
    const cur = s.selections[sessionId] ?? EMPTY_SELECTION
    return { ...s, selections: { ...s.selections, [sessionId]: { ...cur, ...patch, saved: false } } }
  })
}

/** 从服务读回的当前选择：原样显示，记为已保存。 */
export function applyServerSelection(sessionId: string, sel: Omit<Selection, 'saved'>): void {
  app.set((s) => ({ ...s, selections: { ...s.selections, [sessionId]: { ...sel, saved: true } } }))
}

/** 写成功：只有写的就是此刻显示的那份（写的途中没再改）才记为已保存。 */
export function markSelectionSaved(sessionId: string, isSame: (cur: Selection) => boolean): void {
  app.set((s) => {
    const cur = s.selections[sessionId]
    if (!cur || cur.saved || !isSame(cur)) return s
    return { ...s, selections: { ...s.selections, [sessionId]: { ...cur, saved: true } } }
  })
}

/** 首页点胶囊、成果区"选用"：给案件留一份待带入的改动（还没取走的与之合并，后给的字段覆盖先给的）。 */
export function setIntent(caseId: string, patch: Intent): void {
  app.set((s) => ({ ...s, intents: { ...s.intents, [caseId]: { ...s.intents[caseId], ...patch } } }))
}

/** 输入区取走案件的待带入意向（只取一次）；没有返回 undefined。 */
export function takeIntent(caseId: string): Intent | undefined {
  const it = app.get().intents[caseId]
  if (!it) return undefined
  app.set((s) => { const { [caseId]: _taken, ...rest } = s.intents; return { ...s, intents: rest } })
  return it
}

export function pushDialog(d: Dialog): void { app.set((s) => ({ ...s, dialogs: [...s.dialogs, d] })) }
export function popDialog(d: Dialog): void { app.set((s) => ({ ...s, dialogs: s.dialogs.filter((x) => x !== d) })) }

/** 弹确认框，律师点确定返回 true。所有发往服务器的操作都先经这里（工单第 3 步）。 */
export function confirm(title: string, text: string, ok = '确定'): Promise<boolean> {
  return new Promise((resolve) => pushDialog({ kind: 'confirm', title, text, ok, resolve }))
}

export function notice(title: string, text: string, lines?: string[]): void { pushDialog({ kind: 'notice', title, text, lines }) }

/** 界面调用 Host 的方法表（ctx.remote.lawbench），在 apply 里填入。 */
export type LawbenchApi = Record<string, (arg?: unknown) => Promise<ApiResult>> & {
  setupState(): Promise<{ configured: boolean; hasSettings: boolean; hasKey: boolean; service: string }>
  getSettings(): Promise<Record<string, unknown>>
  putSettings(settings: unknown): Promise<unknown>
  listSkills(): Promise<{ ok: true; value: { skills: SkillInfo[] } }>
}

/** Skill 头部 mode 为对话型的取值（contracts\skillrontmatter.schema.json）。 */
export const MODE_AGENT = 'agent' as const // ui-words: 标识符（契约取值，不显示）

export interface SkillInfo {
  name: string; title: string; description: string; mode: 'agent' | 'pipeline'; kind: string // ui-words: 标识符（SKILL.md 头部 mode 的取值）
  params: Params; inputs: string[]; questions: { key: string; question: string; fromMaterials: boolean }[]
}

let api: LawbenchApi | undefined

/**
 * DSH 网关的客户端把每次远程调用的返回再包一层 { ok, value }（失败为 { ok: false, error }，
 * packages/api/gateway/src/client/index.ts 的 invoke）。这里剥掉这一层：成功返回 Host 方法的原返回值，失败抛出。
 */
export function unwrapRemote(remote: Record<string, (...a: unknown[]) => Promise<unknown>>): LawbenchApi {
  return new Proxy({}, {
    get: (_t, method: string) => async (...args: unknown[]) => {
      const fn = remote[method]
      if (typeof fn !== 'function') throw new Error('工作台服务还没接上，请稍后重试')
      const r = (await fn.apply(remote, args)) as { ok: boolean; value?: unknown; error?: { message?: string } }
      if (!r || r.ok !== true) throw new Error(lawyerMessage(r?.error?.message))
      return r.value
    },
  }) as LawbenchApi
}

export const setApi = (a: LawbenchApi | undefined): void => { api = a }
export function lb(): LawbenchApi {
  if (!api) throw new Error('工作台服务还没接上，请稍后重试')
  return api
}

/** 调 /api 方法；失败返回 { ok: false }，界面按错误码显示（Q6）。Host 不可达也折成同样的形状。 */
export async function call<T = unknown>(method: string, request?: unknown): Promise<{ ok: true; value: T } | { ok: false; error: { code: string; message: string } }> {
  try {
    return (await lb()[method]!(request)) as { ok: true; value: T }
  } catch (e) {
    return { ok: false, error: { code: 'SERVICE_UNAVAILABLE', message: lawyerMessage((e as Error)?.message) } }
  }
}
