// 纯聊天的默认工作区"日常事务"（执行令 2026-10-04 11:56 第 4 条，用户 N70：不选案件也能聊，记录落默认工作区）。
// 首次配置之后第一次问到时建好并登记：位置是设置"日常办公文件夹"下的 日常事务\；该设置为空时用 文档\连越律师工作台\日常事务\，
// 并把 文档\连越律师工作台 写回设置。登记走现有 /api/case/open（不带标准目录模板：日常事务不分民商事、刑事）。
// 建成后在应用数据目录记 daily-case.json；之后只按记下的位置返回，文件夹被删或搬走时返回 null、不重建
// （照 T17 既有的 CASE_MOVED 提示处理，不特判）。
import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import { mkdir } from 'node:fs/promises'
import { join } from 'node:path'

export const DAILY_NAME = '日常事务'
export const DEFAULT_OFFICE_DIR_NAME = '连越律师工作台'

type ApiError = { code: string; message: string }
export type DailyResult = { ok: true; value: { root: string | null; created: boolean } } | { ok: false; error: ApiError }

export interface DailyDeps {
  /** 记位置的文件（<应用数据>\daily-case.json）。 */
  marker: string
  /** 本机"文档"文件夹。 */
  documents: string
  getSettings(): Promise<{ office: { dir: string | null } } & Record<string, unknown>>
  putSettings(settings: unknown): Promise<unknown>
  caseOpen(request: { path: string; template: null }): Promise<{ ok: true; value: unknown } | { ok: false; error: ApiError }>
}

function readMarker(file: string): string | undefined {
  try {
    const v = JSON.parse(readFileSync(file, 'utf8')) as { root?: unknown }
    return typeof v.root === 'string' && v.root ? v.root : undefined
  } catch { return undefined }
}

/**
 * 取（必要时建）日常事务案件。
 * @returns root 为它的位置；记过但文件夹已不在时为 null。服务不可用、登记被拒（如在云同步目录里）时为错误，下次再试。
 */
export async function ensureDailyCase(d: DailyDeps): Promise<DailyResult> {
  const known = readMarker(d.marker)
  if (known !== undefined) return { ok: true, value: { root: existsSync(known) ? known : null, created: false } }
  try {
    const settings = await d.getSettings()
    let dir = settings.office?.dir ?? null
    if (!dir) {
      dir = join(d.documents, DEFAULT_OFFICE_DIR_NAME)
      await d.putSettings({ ...settings, office: { ...settings.office, dir } })
    }
    const root = join(dir, DAILY_NAME)
    await mkdir(root, { recursive: true })
    const r = await d.caseOpen({ path: root, template: null })
    if (!r.ok) return r
    writeFileSync(d.marker, JSON.stringify({ root }), 'utf8')
    return { ok: true, value: { root, created: true } }
  } catch (e) {
    const message = e instanceof Error && /[一-鿿]/.test(e.message) ? e.message : '工作台服务未启动，请稍后重试'
    return { ok: false, error: { code: 'SERVICE_UNAVAILABLE', message } }
  }
}
