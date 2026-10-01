// 发票整理页（U-13，Spec 13.3）的纯逻辑：表单 → /api/invoice/run 请求（契约 api/invoice_run 1.3）、结果怎么标、哪些动作要先预览再确认。
// 页面在 invoice.tsx。参数由服务端拼成引擎命令，界面只给契约里的字段。
import { createStore } from './store.ts'

export type InvoiceAction =
  | 'env_check' | 'history' | 'plan' | 'run' | 'analyze' | 'import' | 'prepare' | 'reprint'
  | 'cancel' | 'reimburse' | 'review' | 'exclude' | 'report' | 'check_schema'

/** 按钮上的字（Spec 13.3 白名单动作表"界面按钮"一列）。 */
export const ACTION_LABEL: Record<InvoiceAction, string> = {
  env_check: '环境检查',
  history: '查看历史未报',
  plan: '开始本期',
  run: '导入并生成贴票包',
  analyze: '分析对账',
  import: '入账',
  prepare: '生成贴票包',
  reprint: '重印',
  cancel: '取消批次',
  reimburse: '确认已报销',
  review: '人工核验',
  exclude: '人工排除一项',
  report: '报表',
  check_schema: '台账体检',
}

export interface InvoiceForm {
  period: string
  channel: 'local' | 'eml'
  history: 'exclude' | 'selected'
  historyNumbers: string
  start: string
  end: string
  batch: string
  src: string
  replace: boolean
  item: string
  reason: string
  reviewer: string
  sha256: string
}

export const PERIOD_RE = /^[0-9]{4}-(0[1-9]|1[0-2])$/
export const BATCH_RE = /^[A-Za-z0-9_一-鿿-]{1,40}$/
export const NUMBER_RE = /^[0-9]{18,20}$/
export const DATE_RE = /^[0-9]{4}-[0-9]{2}-[0-9]{2}$/
export const ITEM_RE = /^[0-9a-f]{64}$/
export const SHA_RE = /^[0-9a-f]{64}$/

/** 报销年月默认本月。 */
export function defaultPeriod(now = new Date()): string {
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`
}

export function emptyForm(now = new Date(), reviewer = ''): InvoiceForm {
  const period = defaultPeriod(now)
  return { period, channel: 'local', history: 'exclude', historyNumbers: '', start: '', end: '', batch: period, src: '', replace: false, item: '', reason: '', reviewer, sha256: '' }
}

/** 律师贴进来的发票号码：按空白、逗号、顿号分开；格式不对的另列出来。 */
export function parseNumbers(text: string): { numbers: string[]; bad: string[] } {
  const parts = text.split(/[\s,，、;；]+/).filter(Boolean)
  const numbers = [...new Set(parts.filter((p) => NUMBER_RE.test(p)))]
  return { numbers, bad: parts.filter((p) => !NUMBER_RE.test(p)) }
}

export type Built = { ok: true; request: Record<string, unknown> } | { ok: false; problem: string }

const need = (cond: boolean, problem: string): string | undefined => (cond ? undefined : problem)
const PERIOD = '请填报销年月，例如 2026-09。'
const BATCH = '请填批次名：1 到 40 个字，只用汉字、字母、数字、下划线和短横线。'

/**
 * 表单 → 契约请求。
 * @param opts.apply - reimburse 是否真的执行（false 只预览）。cancel 一律 apply:true：引擎不支持 cancel 预览，服务对 cancel 也一律带 --apply
 *   （契约 1.3 说明），界面只在律师看过报表、点了确认之后才构造它（两步路径）。
 * review、exclude 一律 confirm:true：引擎对不带 --confirm 的 review 直接报 [BLOCKED]（workflow.py:155），没有预览；
 *   界面先弹确认框再发一次。
 */
export function buildInvoiceRequest(action: InvoiceAction, f: InvoiceForm, opts: { apply?: boolean; confirm?: boolean } = {}): Built {
  const period = f.period.trim()
  const batch = f.batch.trim()
  const problem = (...checks: Array<string | undefined>): Built | undefined => {
    const p = checks.find(Boolean)
    return p ? { ok: false, problem: p } : undefined
  }
  switch (action) {
    case 'env_check':
    case 'report':
    case 'check_schema':
      return { ok: true, request: { action } }
    case 'history':
    case 'analyze':
    case 'import':
      return problem(need(PERIOD_RE.test(period), PERIOD)) ?? { ok: true, request: { action, period } }
    case 'plan': {
      const { numbers, bad } = parseNumbers(f.historyNumbers)
      const eml = f.channel === 'eml'
      const p = problem(
        need(PERIOD_RE.test(period), PERIOD),
        need(f.history === 'exclude' || bad.length === 0, `这些不是发票号码（应为 18 到 20 位数字）：${bad.slice(0, 3).join('、')}`),
        need(f.history === 'exclude' || numbers.length > 0, '选了纳入历史未报票，请填要纳入的发票号码（18 到 20 位数字）。'),
        need(!eml || (DATE_RE.test(f.start) && DATE_RE.test(f.end)), '导入 EML 文件时请填邮件的起止日期。'),
        need(!eml || f.start <= f.end, '起始日期不能晚于截止日期。'),
      )
      if (p) return p
      return {
        ok: true,
        request: {
          action, period, channel: f.channel, history: f.history,
          history_numbers: f.history === 'selected' ? numbers : [],
          ...(eml ? { start: f.start, end: f.end } : {}),
        },
      }
    }
    case 'run':
      return problem(need(PERIOD_RE.test(period), PERIOD), need(BATCH_RE.test(batch), BATCH), need(/^([A-Za-z]:[\\/]|\\\\)/.test(f.src.trim()) || f.src.trim().startsWith('/'), '请先选择要导入的发票文件夹。'))
        ?? { ok: true, request: { action, period, batch, src: f.src.trim(), channel: f.channel } }
    case 'prepare':
      return problem(need(PERIOD_RE.test(period), PERIOD), need(BATCH_RE.test(batch), BATCH))
        ?? { ok: true, request: { action, period, batch, replace: f.replace } }
    case 'reprint':
      return problem(need(BATCH_RE.test(batch), BATCH)) ?? { ok: true, request: { action, batch } }
    case 'cancel':
      return problem(need(BATCH_RE.test(batch), BATCH)) ?? { ok: true, request: { action, batch, apply: true } }
    case 'reimburse':
      return problem(need(BATCH_RE.test(batch), BATCH)) ?? { ok: true, request: { action, batch, apply: opts.apply === true } }
    case 'review':
      return problem(need(SHA_RE.test(f.sha256.trim()), '请填要核验的发票文件指纹（64 位小写字母和数字，见引擎输出）。'), need(f.reviewer.trim().length > 0, '请填核验人。'))
        ?? { ok: true, request: { action, sha256: f.sha256.trim(), reviewer: f.reviewer.trim(), confirm: true } }
    case 'exclude':
      return problem(
        need(PERIOD_RE.test(period), PERIOD),
        need(ITEM_RE.test(f.item.trim()), '请填要排除的记录编号（64 位小写字母和数字，见对账表）。'),
        need(f.reason.trim().length > 0 && f.reason.trim().length <= 200, '请写明排除理由（200 字以内）。'),
        need(f.reviewer.trim().length > 0 && f.reviewer.trim().length <= 40, '请填核验人（40 字以内）。'),
      ) ?? { ok: true, request: { action, period, item: f.item.trim(), reason: f.reason.trim(), reviewer: f.reviewer.trim(), confirm: true } }
  }
}

export interface InvoiceValue { exit_code: number; attention: boolean; failed: boolean; output: string; files: string[] }

/** 结果怎么标：failed 红、attention（退出码 2）黄、其余绿。 */
export function resultTone(v: InvoiceValue): 'err' | 'warn' | 'ok' {
  if (v.failed) return 'err'
  if (v.attention || v.exit_code === 2) return 'warn'
  return 'ok'
}

export const TONE_TEXT = {
  err: '引擎报告没有完成，原因见下方输出。',
  warn: '有重复、冲突、待核或部分失败，请看下方明细。',
  ok: '完成。',
} as const

/** 生成、重印贴票包时服务可能不列文件（files 为空），打印包位置在输出里。 */
export const PRINT_FROM_OUTPUT = '打印包的位置见下方输出。'

/** 先预览、再确认的动作（Spec 13.3：--apply 类先预览；cancel 引擎不支持预览，先显示台账报表再确认；review 没有预览，见 REVIEW_CONFIRM）。 */
export const TWO_STEP: Partial<Record<InvoiceAction, { preview: 'self' | 'report'; title: string; text: (batch: string) => string; ok: string }>> = {
  reimburse: { preview: 'self', title: '确认已报销', text: (b) => `上面是批次"${b}"确认报销的预览。确认后批次标为已报销，不能撤回。`, ok: '确认已报销' },
  cancel: { preview: 'report', title: '取消批次', text: (b) => `将取消批次"${b}"并写入台账，取消后不能撤回。上面的报表是整个台账的统计；请先确认这个批次尚未报销。`, ok: '取消这个批次' },
}

/** 人工核验：引擎没有预览，逐张核对原票后确认，确认后写入台账（只发一次 confirm:true）。 */
export const REVIEW_CONFIRM = {
  title: '人工核验',
  text: (reviewer: string) => `请先逐张核对原票。确认后以核验人"${reviewer}"写入台账。`,
  ok: '确认写入',
}

export const EXCLUDE_CONFIRM = {
  title: '人工排除一项',
  text: '排除后本期不再计入该票。只改本期任务目录里的收集表和对账表，不碰台账，不联网，不能撤回。',
  ok: '排除',
}

export const REPLACE_CONFIRM = {
  title: '替换贴票包',
  text: '这个批次已有的贴票包会被新生成的替换。',
  ok: '替换',
}

/** 服务在动作进行中收到新的动作：等锁 2 秒没等到返回 ENGINE_BUSY（契约 1.3）。 */
export const BUSY_CODE = 'ENGINE_BUSY'
export const BUSY_TEXT = '发票整理正在进行中，请等它结束后再操作。'
/** ENGINE_BUSY 之后按钮停用多久（另一个动作可能还在跑；之后律师可以再试）。 */
export const BUSY_HOLD_MS = 15_000

/** 首页工具胶囊点"发票整理"后，首页换成发票页；点"返回首页"换回。 */
export const homeView = createStore<'home' | 'invoice'>('home')
