// 界面插件 legal-ui（T13）的浏览器半边。经 DSH 的 modules 行加载（行名 = 包名 lawbench-dsh，导出 ./client）。
// 不得有读写案件文件的途径、不得有 127.0.0.1 以外的网络访问：一切数据经 ctx.remote.lawbench（Host 转工作台服务）。
// 写法：先 $mount 手写的 lawbench 描述，再 ctx.inject(['remote.lawbench', …]) 取子上下文（T13 执行令 Q1，同 DSH 实验插件 voice-input）。
// 各块分别 inject：某个 DSH 服务不在时只缺那一块，不连累其他块。
import { LAWBENCH_REMOTE } from './remote.ts'
import { DialogHost } from './dialogs.tsx'
import { HomePage } from './home.tsx'
import { MaterialsTab } from './materials.tsx'
import { draftsDefinition, OLD_RESULTS_TAB, OldResultsTab, refreshCaseResults, TurnResultCards } from './result-cards.tsx'
import { SourceTab } from './source.tsx'
import { ComposerDock, TURN_ENDED } from './dock.tsx'
import { turnEnds } from './tasksheet.ts'
import { SettingsSection, loadSettingsIntoState } from './settings.tsx'
import { BrandMark, BrandName, VendorCorner } from './brand.tsx'
import { DailyErrorLine } from './daily-error.tsx'
import { CaseSwitcher } from './case-switcher.tsx'
import { createRightbarSeeder, forgetIfGone, loadSeeded, RIGHTBAR_TABS, saveSeeded, seedTabsCollapsed } from './rightbar.ts'
import { landOnDailyCase, openCase, TABS } from './cases.ts'
import { addCaseFromPicked } from './drop-case.ts'
import { watchRemovedCases } from './hidden-cases.ts'
import { ensureFieldStyle, getNav, setNav, type Nav } from './kit.tsx'
import { app, call, currentCase, notice, samePath, setApi, unwrapRemote, type LawbenchApi } from './state.ts'
import { installPasteTextWatch, makeIntakeHook, type IntakeHook } from './intake.ts'
import { citationMark, type CitationMark } from './citation.ts'
import { citationDeps } from './citation-deps.ts'

export const inject = ['slots', 'remote']

const HOME = 'lawbench-home'
/** 首页入口排在"新会话"上方：DSH 补丁 P-21 把 order <= -1000 的面板画在新会话上面。 */
export const HOME_ORDER = -1000

type Disposer = () => void
type Observable<T> = { getSnapshot(): T; subscribe(fn: () => void): Disposer }
type Ctx = {
  slots: {
    inject(name: string, fn: () => unknown): unknown
    register(options: Record<string, unknown>, component: unknown): Disposer
  }
  remote: { $mount(contribution: unknown): Promise<() => Promise<void>>; lawbench?: LawbenchApi }
  effect(fn: () => unknown, label?: string): void
  inject(deps: string[], apply: (ctx: Ctx) => void): Promise<void> & { dispose(): Promise<void> }
  layout: { selectPanel(id: string | null): void }
  sessions: { list: Observable<{ byId: Record<string, { cwd?: string; running?: boolean } | undefined> }> }
  uiSession: { adapter: { current: Observable<{ key?: string } | undefined> } }
  uiWorkspace: {
    openWorkspace(id: string): Promise<unknown>; openSession(id: string): void; pickDirectory?(): Promise<string | null | undefined>
    /** P-24："添加案件"选完文件夹后交给谁（不设时 DSH 直接把文件夹挂成工作区）。 */
    setDirectoryAdopter?(adopter: ((path: string) => Promise<void>) | undefined): void
  }
  workspaces: {
    create(req: { path: string }): Promise<{ workspaceId: string }>
    delete(workspaceId: string): Promise<void>
    list?: Observable<{ items: Array<{ workspaceId: string; path: string; title?: string }>; state?: string }>
  }
  sidebarRight: { openTab(kind: string, opts?: { params?: Record<string, string> }): unknown; mounted: Observable<string | undefined>; isExpanded?(): boolean; toggleExpanded?(): void }
  /** DSH ui-conversation：按会话事件收每轮数据（成果卡片用，令 1321 C）。 */
  uiConversation: { events: { register(definition: unknown): Disposer } }
  sidebarRightTabs: { register(def: Record<string, unknown>): Disposer }
  /** P-5 源码补丁提供；没打补丁时不存在。 */
  conversationFileIntake: { register(hook: IntakeHook): Disposer }
  /** P-16 源码补丁提供（ui-chat）；没打补丁时不存在，出处就不成按钮。 */
  chatInlineMarks: { register(mark: CitationMark): Disposer }
}

type DesktopWindow = Window & {
  __DSH_DIRECTORY_PICKER__?: { pick(): Promise<string | null> }
  __DSH_HOST_PATHS__?: { pathFor(file: File): string }
}
const win = window as DesktopWindow

/** 打开案件后会话名单没刷新到这个案件时的提示（第五轮复核 F2）。 */
export const ROOTS_NOT_REFRESHED = ['会话名单没刷新', '案件已打开，但会话名单没刷新，请稍后再打开一次。'] as const

/** 导航能力：各块 inject 成功后各自填入。 */
const navImpl: Partial<Nav> & { pending?: { kind: string; params?: Record<string, string> } } = {
  pathFor: (f) => { try { return win.__DSH_HOST_PATHS__?.pathFor(f) ?? '' } catch { return '' } },
  refreshModels: () => {},
}
const nav: Nav = {
  pickDirectory: () => navImpl.pickDirectory?.() ?? Promise.resolve(null),
  pathFor: (f) => navImpl.pathFor!(f),
  openCaseWorkspace: (root) => navImpl.openCaseWorkspace?.(root) ?? Promise.resolve(),
  openTab: (kind, params) => { if (navImpl.openTab) navImpl.openTab(kind, params); else navImpl.pending = { kind, params } },
  seedTabs: () => navImpl.seedTabs?.(),
  goHome: () => navImpl.goHome?.(),
  refreshModels: () => navImpl.refreshModels!(),
  openSession: (id) => navImpl.openSession?.(id),
  forgetCaseWorkspace: (root, except) => navImpl.forgetCaseWorkspace?.(root, except) ?? Promise.resolve(),
}

/** 输入框上权限模式开关的空占位（令 1347 第 4 条）。 */
const NoPermissionPicker = (): null => null

/** 侧栏"首页"的图标。 */
function HomeIcon({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" aria-hidden="true" stroke="currentColor" strokeWidth={1.3}>
      <path d="M2.5 7.2 8 2.8l5.5 4.4V13a.7.7 0 0 1-.7.7H10V10H6v3.7H3.2a.7.7 0 0 1-.7-.7V7.2Z" strokeLinejoin="round" />
    </svg>
  )
}




/** 设置页一节、弹框：只要 slots 和 remote.lawbench。 */
function registerCore(ctx: Ctx): void {
  setApi(unwrapRemote(ctx.remote.lawbench as unknown as Record<string, (...a: unknown[]) => Promise<unknown>>))
  ctx.effect(() => () => setApi(undefined), '律师工作台界面：接口')
  void loadSettingsIntoState()
  // 令 1609：深色下原生下拉框的选项看得清（关窗口不拦，见 settings-draft.ts 开头）
  ensureFieldStyle()
  ctx.slots.inject('settings.section', () => ctx.slots.register({ name: 'settings.section', id: 'lawbench', order: -20, label: () => '律师工作台' }, SettingsSection))
  // 侧栏品牌位：我方产品名和版本（T14 派修 3；原版位置显示"DSH 本地构建 0.1.7-rc.2-…"）
  ctx.slots.inject('sidebar.brand.name', () => ctx.slots.register({ name: 'sidebar.brand.name' }, BrandName))
  // 律所 logo 常驻品牌位、技术公司一行常驻侧栏底部（执行令 2026-10-04 11:56 第 1、2 条）
  ctx.slots.inject('sidebar.brand.mark', () => ctx.slots.register({ name: 'sidebar.brand.mark' }, BrandMark))
  ctx.slots.inject('conversation.hero.brand.mark', () => ctx.slots.register({ name: 'conversation.hero.brand.mark' }, BrandMark))
  ctx.slots.inject('sidebar.footer.action', () => ctx.slots.register({ name: 'sidebar.footer.action', id: 'lawbench.daily-error', order: 900 }, DailyErrorLine))
  ctx.slots.inject('shell.overlay', () => ctx.slots.register({ name: 'shell.overlay', id: 'lawbench.dialogs' }, DialogHost))
  // 令 1515 第 1 条：技术支持信息只留主窗口右下角一处
  ctx.slots.inject('shell.overlay', () => ctx.slots.register({ name: 'shell.overlay', id: 'lawbench.vendor' }, VendorCorner))
  // 令 1347 第 4 条：DSH 输入框上的权限模式开关（"工作区内修改"等，编码工具的权限档）律师用不到——
  // 在同一位置登记一个排得更前的空占位，DSH 的那个就不画了（单一位置按 priority 从小到大取第一个）
  ctx.slots.inject('conversation.input.permission', () => ctx.slots.register({ name: 'conversation.input.permission', priority: -10 }, NoPermissionPicker))
  ctx.slots.inject('conversation.input.dock', () => ctx.slots.register({ name: 'conversation.input.dock', id: 'lawbench', order: -10 }, ComposerDock))
  navImpl.pickDirectory = async () => (win.__DSH_DIRECTORY_PICKER__ ? await win.__DSH_DIRECTORY_PICKER__.pick() : null)
}

/** 首页（令 1426）：侧栏最顶部的入口、启动落首页；对话区顶部的当前案件与切换（令 1515）。 */
function registerHome(ctx: Ctx): void {
  // 令 1426：侧栏最顶部（新会话上方）常显"首页"，启动默认落首页。令 1515：侧栏"案件：xxx"一块删掉（与首页重复），
  // 当前案件改在对话区顶部（CaseSwitcher）；侧栏只留首页、新会话、会话列表
  let shown = false
  ctx.slots.inject('main', () => {
    const dispose = ctx.slots.register({ name: 'main', key: HOME }, HomePage)
    if (!shown) { shown = true; setTimeout(() => { try { ctx.layout.selectPanel(HOME) } catch { /* 页面还没登记好 */ } }, 0) }
    return dispose
  })
  ctx.slots.inject('sidebar.panellist', () => ctx.slots.register({ name: 'sidebar.panellist', id: HOME, order: HOME_ORDER, label: () => '首页' }, HomeIcon))
  ctx.slots.inject('conversation.session.header.actions', () => ctx.slots.register({ name: 'conversation.session.header.actions', id: 'lawbench.case', order: -100 }, CaseSwitcher))
  navImpl.goHome = () => ctx.layout.selectPanel(HOME)
  ctx.effect(() => () => { navImpl.goHome = undefined }, '律师工作台界面：首页导航')
}

/**
 * 打开案件 = 把案件文件夹当工作区打开（Spec 1.2）。建好（或取到已有的）工作区后，请 Host 把 cwd 就是这个案件根、
 * 又不在任何工作区里的会话挂回来（T17 第三轮复核 B-F2：案件搬家、复制后旧会话不再落进"未分组"）；挂回失败不影响打开。
 */
/** 最近一次打开的工作区（读列表时发现换了位置也不撤它）。 */
let lastOpenedWorkspace: string | undefined

function registerWorkspace(ctx: Ctx): void {
  navImpl.openCaseWorkspace = async (root) => {
    const ws = await ctx.workspaces.create({ path: root })
    const r = await call<{ listed?: boolean }>('attachCaseSessions', { root }).catch(() => undefined)
    // 打开后会话名单没刷新到这个案件（服务没答、挂住）：旧会话可能还没归到这里，提示稍后再打开一次（第五轮复核 F2）
    if (r?.ok && r.value.listed === false) notice(ROOTS_NOT_REFRESHED[0], ROOTS_NOT_REFRESHED[1])
    await ctx.uiWorkspace.openWorkspace(ws.workspaceId)
    lastOpenedWorkspace = ws.workspaceId
    return ws.workspaceId
  }
  navImpl.openSession = (id) => { try { ctx.uiWorkspace.openSession(id) } catch { /* 会话已不在：不转 */ } }
  // 1612 复核 P1：不撤刚打开的那一项；移除前问 Host 旧位置是不是确实不在了（在就不撤：多半是同一位置换了写法）
  navImpl.forgetCaseWorkspace = async (root, except) => {
    const items = ctx.workspaces.list?.getSnapshot().items ?? []
    await forgetIfGone(items, root, except ?? lastOpenedWorkspace, samePath, (path) => call<{ exists: boolean }>('pathState', { path }), (id) => { ownRemoved.add(id); return ctx.workspaces.delete(id) })
  }
  // 令 2125：律师在左栏"从列表移除案件"后，首页和"切换案件"也不再列它（程序自己撤掉的旧位置那一项不算）
  const ownRemoved = new Set<string>()
  if (ctx.workspaces.list) { const list = ctx.workspaces.list; ctx.effect(() => watchRemovedCases(list, ownRemoved), '律师工作台界面：从列表移除案件') }
  const fallbackPick = ctx.uiWorkspace.pickDirectory
  if (!win.__DSH_DIRECTORY_PICKER__ && fallbackPick) navImpl.pickDirectory = async () => (await fallbackPick.call(ctx.uiWorkspace)) ?? null
  ctx.effect(() => () => { navImpl.openCaseWorkspace = undefined; navImpl.openSession = undefined; navImpl.forgetCaseWorkspace = undefined }, '律师工作台界面：打开案件')
  // 令 1851：左栏"添加案件"、菜单"添加案件…"选完文件夹走建案件流程（同首页拖文件夹），不再直接挂成没登记的工作区
  registerAddCaseAdopter(ctx.uiWorkspace, (fn, label) => ctx.effect(fn, label))
  // 纯聊天的默认工作区"日常事务"（执行令 1156 第 4 条）：当前会话不在案件里时打开它。走"进入"同一条路（再登记一次、
  // 记进界面状态、打开工作区）：只打开工作区时，DSH 新建的空会话在输入区认不出案件（真机核过）
  // 令 1426：启动落首页——日常事务照样打开（空会话要落在一个案件里），打开后再回首页
  void landOnDailyCase((root) => openCase(root, null).then(() => { navImpl.goHome?.() })).catch(() => undefined)
  // 1612 复核 P3：去掉"重启后不在登记里的一律撤"（服务的登记丢了会把全部案件撤掉）；重启前的旧位置那一项留着，律师可在侧栏菜单"从列表移除案件"
}

/**
 * 把"添加案件"选完文件夹之后的事接过来（DSH 的 P-24 给的口子）；界面插件卸下时还回去。
 * DSH 没有这个口子（补丁没打上）时什么也不做。
 */
export function registerAddCaseAdopter(uiWorkspace: Ctx['uiWorkspace'], effect: (fn: () => () => void, label: string) => void): void {
  if (!uiWorkspace.setDirectoryAdopter) return
  effect(() => {
    uiWorkspace.setDirectoryAdopter!(addCaseFromPicked)
    return () => { uiWorkspace.setDirectoryAdopter!(undefined) }
  }, '律师工作台界面：添加案件走建案件流程')
}

/** 当前会话 → 工作目录，首页据此知道"当前案件"。 */
function registerSessionTracking(ctx: Ctx): void {
  const update = () => {
    const id = ctx.uiSession.adapter.current.getSnapshot()?.key
    const cwd = id ? ctx.sessions.list.getSnapshot().byId[id]?.cwd ?? null : null
    if (app.get().currentRoot !== cwd) app.set((s) => ({ ...s, currentRoot: cwd }))
  }
  // 一轮结束（会话的 running 由真变假）：通知输入区重新读服务的当前选择（契约 1.2，界面不在本地记）
  const running = new Map<string, boolean>()
  const watchTurns = () => {
    for (const id of turnEnds(running, ctx.sessions.list.getSnapshot().byId)) window.dispatchEvent(new CustomEvent(TURN_ENDED, { detail: id }))
  }
  update()
  watchTurns()
  ctx.effect(() => ctx.uiSession.adapter.current.subscribe(update), '律师工作台界面：当前会话')
  ctx.effect(() => ctx.sessions.list.subscribe(() => { update(); watchTurns() }), '律师工作台界面：会话列表')
}

/** P-5：拖入、粘贴、选择到对话框的文件导入案件文件夹（要 DSH 源码补丁提供的 conversationFileIntake）。 */
function registerIntake(ctx: Ctx): void {
  ctx.effect(() => installPasteTextWatch(), '律师工作台界面：粘贴是否带文字')
  ctx.effect(() => ctx.conversationFileIntake.register(makeIntakeHook((id) => ctx.sessions.list.getSnapshot().byId[id]?.cwd)), '律师工作台界面：对话框导入')
}

/** P-16：草稿正文里的出处由 DSH 画成真按钮（键盘、读屏可用）；点了核对后打开原文。 */
function registerCitationMarks(ctx: Ctx): void {
  ctx.effect(() => ctx.chatInlineMarks.register(citationMark(citationDeps)), '律师工作台界面：出处按钮')
}

/** 右侧栏两个标签：材料、原文查看（令 1321 D.1：成果挪进聊天里的卡片和案件概览卡，右栏不再有"成果"）。 */
function registerTabs(ctx: Ctx): void {
  const tabs: Array<[string, string, string, number, unknown]> = [
    [TABS.materials, '材料', '案件材料、导入、识别和案件 wiki', 10, MaterialsTab],
    [TABS.source, '原文查看', '按出处查看原文，检索本案材料', 30, SourceTab],
  ]
  for (const [id, title, description, order, Body] of tabs) {
    ctx.effect(() => ctx.sidebarRightTabs.register({
      id, kind: id, priority: 'extension', title: () => title,
      guide: [{ id, order, title: () => title, description: () => description }],
    }), `律师工作台界面：标签 ${id}`)
    ctx.slots.inject('sidebar.right.pane.tab', () => ctx.slots.register({ name: 'sidebar.right.pane.tab', key: id }, Body))
  }
  // 复核 rv-A52 P3-4：旧会话里 DSH 记住了以前开过的"成果"标签——种类留着登记（不进"添加标签"的列表），里面一句话指路，不空白、不报错
  ctx.effect(() => ctx.sidebarRightTabs.register({ id: OLD_RESULTS_TAB, kind: OLD_RESULTS_TAB, priority: 'extension', title: () => '成果', guide: [] }), '律师工作台界面：旧"成果"标签')
  ctx.slots.inject('sidebar.right.pane.tab', () => ctx.slots.register({ name: 'sidebar.right.pane.tab', key: OLD_RESULTS_TAB }, OldResultsTab))
  // 刚打开工作区时会话界面还没挂上：等挂上再做（最多 10 秒）
  const whenMounted = (go: () => void) => {
    if (ctx.sidebarRight.mounted.getSnapshot() !== undefined) { go(); return }
    let off: Disposer | undefined = ctx.sidebarRight.mounted.subscribe(() => {
      if (ctx.sidebarRight.mounted.getSnapshot() === undefined) return
      off?.(); off = undefined; go()
    })
    setTimeout(() => { off?.(); off = undefined }, 10_000)
  }
  // 点出处等：开标签（DSH 的 openTab 会顺带展开右栏）
  const open = (kind: string, params?: Record<string, string>) => {
    whenMounted(() => { try { ctx.sidebarRight.openTab(kind, params ? { params } : undefined) } catch { /* 没有会话界面时不开 */ } })
  }
  // 令 1321 D.1：开好"原文查看""材料"两个标签但右栏保持收起（默认收起，顶部按钮展开）——openTab 会自动展开，
  // 原来是收起的就再收回去（DSH 只有 toggleExpanded，没有单独的收起）
  const seedTabs = () => { whenMounted(() => seedTabsCollapsed(ctx.sidebarRight, RIGHTBAR_TABS)) }
  navImpl.openTab = open
  navImpl.seedTabs = seedTabs
  // 令 1347 第 3 条、令 1321 D.1：打开案件（含日常事务）的会话第一次显示时开好"原文查看""材料"两个标签、停在"材料"，右栏收起；
  // 每个会话只做一次（记在本机），之后展开、折叠、关掉都由 DSH 按会话记住
  const seeder = createRightbarSeeder(loadSeeded(), saveSeeded, seedTabs)
  const seed = () => { seeder(ctx.sidebarRight.mounted.getSnapshot(), !!currentCase(app.get())) }
  ctx.effect(() => ctx.sidebarRight.mounted.subscribe(seed), '律师工作台界面：右侧栏默认展开')
  ctx.effect(() => app.subscribe(seed), '律师工作台界面：右侧栏默认展开（案件列表）')
  if (navImpl.pending) { const p = navImpl.pending; navImpl.pending = undefined; open(p.kind, p.params) }
  ctx.effect(() => () => { navImpl.openTab = undefined; navImpl.seedTabs = undefined }, '律师工作台界面：标签导航')
}

/**
 * 聊天里交代成果（令 1321 C）：按会话事件收每轮存下的草稿，答复下方插草稿卡片 / 成果卡片（conversation.chat.turnTail，
 * 同 DSH 的 ui-deliverables）。一轮结束时重读任务和成果（卡片上"确认保存"要任务号）。
 */
function registerResultCards(ctx: Ctx): void {
  ctx.effect(() => ctx.uiConversation.events.register(draftsDefinition), '律师工作台界面：每轮草稿')
  ctx.slots.inject('conversation.chat.turnTail', () => ctx.slots.register({ name: 'conversation.chat.turnTail', id: 'lawbench.results', order: 50 }, TurnResultCards))
  const onTurnEnd = () => { const c = currentCase(app.get()); if (c) void refreshCaseResults(c.case_id) }
  window.addEventListener(TURN_ENDED, onTurnEnd)
  ctx.effect(() => () => window.removeEventListener(TURN_ENDED, onTurnEnd), '律师工作台界面：成果卡片刷新')
}

export async function apply(ctx: Ctx): Promise<() => Promise<void>> {
  setNav(nav)
  const disposeRemote = await ctx.remote.$mount(LAWBENCH_REMOTE)
  const core = ctx.inject(['remote.lawbench', 'slots'], registerCore)
  try { await core } catch (error) { await core.dispose(); await disposeRemote(); throw error }
  // 以下各块不等待：所需服务不在时只是那一块不出现
  const others = [
    ctx.inject(['slots', 'layout'], registerHome),
    ctx.inject(['workspaces', 'uiWorkspace'], registerWorkspace), // ui-words: 标识符（DSH 服务名）
    ctx.inject(['sessions', 'uiSession'], registerSessionTracking), // ui-words: 标识符（DSH 服务名）
    ctx.inject(['slots', 'sidebarRight', 'sidebarRightTabs'], registerTabs),
    ctx.inject(['conversationFileIntake', 'sessions'], registerIntake), // ui-words: 标识符（DSH 服务名）
    ctx.inject(['chatInlineMarks'], registerCitationMarks), // ui-words: 标识符（DSH 服务名）
    ctx.inject(['slots', 'uiConversation'], registerResultCards), // ui-words: 标识符（DSH 服务名）
  ]
  return async () => {
    for (const o of others) await o.dispose()
    await core.dispose()
    await disposeRemote()
    setNav(undefined)
  }
}
