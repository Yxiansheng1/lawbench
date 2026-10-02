// 委托材料（U-14，Spec 13.5）：首页点"文件生成"胶囊 → 启动本机证件识别驱动 → 经 P-11 打开独立窗口；
// 窗口关闭后停驱动，提示把新生成的文件导入到 01委托手续（导入只新增、同名改名，不覆盖）。
// 窗口、分区、白名单、下载位置都在桌面端主进程（DSH 补丁 P-11），这里只经预加载暴露的 __LAWBENCH_RETAINER__ 调用。
import { call, confirm, notice, type CaseRef } from './state.ts'
import { errorText } from './format.ts'
import { runImport } from './cases.ts'

export const RETAINER_TARGET = '01委托手续'

/** 主进程交回的结果（P-11 的 RetainerResult）。 */
export type RetainerResult =
  | { kind: 'closed'; dir: string; inCase: boolean; files: string[]; failed: number }
  | { kind: 'already-open' }

export interface RetainerBridge { open(request: { caseRoot: string | null; caseName: string | null }): Promise<RetainerResult> }

type DriverValue = { running: boolean; port: number; message: string }

export const TEXT = {
  noDesktop: ['委托材料窗口打不开', '委托材料只能在律师工作台桌面端使用。'],
  openFailed: '委托材料窗口打不开',
  driverDown: '证件识别没有启动',
  driverDownTail: '仍可在委托材料窗口里手工填写。',
  // ENGINE_FAILED 在这条接口上只表示驱动的模型文件缺失或损坏（T25：启动前核 sha256），服务的通用说明会提到发票整理，换成自己的话（复核 P3-3）
  engineBroken: '本机识别引擎文件缺失或损坏，请联系技术支持。',
  stopTitle: '证件识别',
  importTitle: '导入新生成的文件到 01委托手续',
  noCaseTitle: '请先打开案件再导入',
} as const

/** 关窗后要不要解压：有 ZIP（"保存案件目录"回退为下载整个案件 ZIP）就解压。 */
export const hasZip = (files: readonly string[]): boolean => files.some((f) => /\.zip$/i.test(f))

const bridge = (): RetainerBridge | undefined => (window as Window & { __LAWBENCH_RETAINER__?: RetainerBridge }).__LAWBENCH_RETAINER__

/**
 * 打开委托材料窗口，等它关闭后收尾。
 * @param current - 此刻打开的案件（下载落它的 工作区\临时\委托材料；关窗后导入到它）；没有为 undefined。
 */
export async function openRetainer(current: CaseRef | undefined, b: RetainerBridge | undefined = bridge()): Promise<void> {
  if (!b) { notice(TEXT.noDesktop[0], TEXT.noDesktop[1]); return }
  const started = await call<DriverValue>('retainerDriver', { action: 'start' })
  if (!started.ok) notice(TEXT.driverDown, `${started.error.code === 'ENGINE_FAILED' ? TEXT.engineBroken : errorText(started.error)} ${TEXT.driverDownTail}`)
  else if (!started.value.running) notice(TEXT.driverDown, `${started.value.message} ${TEXT.driverDownTail}`)

  let result: RetainerResult
  try {
    result = await b.open({ caseRoot: current?.root ?? null, caseName: current?.name ?? null })
  } catch (e) {
    const m = (e as Error)?.message ?? ''
    notice(TEXT.openFailed, /[一-鿿]/.test(m) ? m.replace(/^Error invoking remote method '[^']*': (Error: )?/, '') : '请稍后再试；多次出现请联系技术支持。')
    if (started.ok && started.value.running) await stopDriver()
    return
  }
  if (result.kind === 'already-open') return
  await stopDriver()
  await afterClose(result, current)
}

/** 关窗：停驱动；停不下来（running 仍为 true）如实显示服务的话（如"关闭未完成，请稍后再试"）。 */
async function stopDriver(): Promise<void> {
  const r = await call<DriverValue>('retainerDriver', { action: 'stop' })
  if (!r.ok) notice(TEXT.stopTitle, errorText(r.error))
  else if (r.value.running) notice(TEXT.stopTitle, r.value.message)
}

/** 窗口关了：有新文件就提示导入到 01委托手续；没有案件时说明文件在哪、先打开案件再导入。 */
export async function afterClose(r: Extract<RetainerResult, { kind: 'closed' }>, current: CaseRef | undefined): Promise<void> {
  const lost = r.failed ? `另有 ${r.failed} 个文件没有保存成功，请在委托材料窗口里重新生成。` : ''
  if (!r.files.length) { if (lost) notice('委托材料', lost); return }
  if (!r.inCase || !current) {
    notice(TEXT.noCaseTitle, `新生成的 ${r.files.length} 个文件在 ${r.dir}。打开案件后，可在"材料"标签里把它们导入到 ${RETAINER_TARGET}。${lost}`, r.files)
    return
  }
  const zip = hasZip(r.files)
  const yes = await confirm(TEXT.importTitle,
    `委托材料窗口新生成了 ${r.files.length} 个文件，在案件"${current.name}"的 工作区\\临时\\委托材料 里。现在导入到 ${RETAINER_TARGET} 吗？`
      + `${zip ? '压缩包会先解压。' : ''}同名文件改名，不覆盖。${lost}`, '导入')
  if (yes) await runImport(current, r.files, RETAINER_TARGET, zip)
}
