// 左栏"从列表移除案件"后首页和"切换案件"也不再列它（令 2125）：服务的案件登记没有删除接口（候契约 1.4 的 case_forget，候项 17），
// 这一版由 Host 在应用数据目录记一份"已从列表移除的案件"（hidden-cases.json：case_id + 案件根），界面按它过滤。
// 律师再次打开、拖入、从左栏添加同一文件夹（case_open 成功）就去掉记录，重新显示。
// 只是不列出来：服务的登记、案件文件夹、会话都不动。记录读不出来（文件损坏、格式不对）按没有处理。
// case_forget 落地后改调服务并删掉这份记录。日志只记个数，不记路径。
import { readFileSync, writeFileSync } from 'node:fs'

export const HIDDEN_FILE = 'hidden-cases.json'

export interface HiddenCase { case_id: string; root: string }

const norm = (p: string): string => p.replace(/\//g, '\\').replace(/\\+$/, '').toLowerCase()

/** 读记录；没有文件、读不出来、格式不对的一律按空。 */
export function readHidden(file: string): HiddenCase[] {
  try {
    const v = JSON.parse(readFileSync(file, 'utf8')) as { cases?: unknown }
    if (!Array.isArray(v?.cases)) return []
    return v.cases.filter((c): c is HiddenCase => !!c && typeof c.case_id === 'string' && !!c.case_id && typeof c.root === 'string' && !!c.root)
      .map((c) => ({ case_id: c.case_id, root: c.root }))
  } catch { return [] }
}

function write(file: string, cases: HiddenCase[]): void {
  writeFileSync(file, JSON.stringify({ v: 1, cases }), 'utf8')
}

/** 记下一个案件（已记过的不重复记）。@returns 记完后的全部记录。 */
export function addHidden(file: string, c: HiddenCase): HiddenCase[] {
  const now = readHidden(file)
  if (now.some((x) => x.case_id === c.case_id)) return now
  const next = [...now, { case_id: c.case_id, root: c.root }]
  write(file, next)
  return next
}

/**
 * 案件又被打开了：去掉它的记录（按 case_id；同一位置的旧记录一并去掉）。没有记录时不写文件。
 * @returns 去掉了几条。
 */
export function dropHidden(file: string, caseId: string, root: string | undefined): number {
  const now = readHidden(file)
  const next = now.filter((x) => x.case_id !== caseId && !(root && norm(x.root) === norm(root)))
  if (next.length === now.length) return 0
  write(file, next)
  return now.length - next.length
}
