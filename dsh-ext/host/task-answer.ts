// 预算到顶时对话区显示草稿（T14 联调派修 2，执行令 2026-10-03 15:41；用户原话件 OWNER-T14预算到顶对话区显示草稿-20261003-1549）。
// 那一轮最后一次模型调用是"存草稿"，模型没有写出文字回答；输入区上方改为显示"已用完本次运行的模型调用次数（8/8），结果已保存到成果"
// 和刚存的草稿正文（出处是可点按钮）。工作台服务没有读草稿正文的接口，Host 只读这个任务目录下的
// task.json（预算、会话）、result.json（状态、用量、草稿列表）和最新一版草稿；路径规则、链接与出案件根的核对同 archive-plan.ts。
import { lstatSync, readFileSync, realpathSync } from 'node:fs'
import { join, relative, isAbsolute } from 'node:path'

const TASK_ID = /^[TP]-\d{14}-[0-9a-f]{4}$/
/** 草稿相对路径：只认这个任务自己的 草稿\ 下一层的 .md（同服务 result.json 的写法，正斜杠）。 */
const draftPathOf = (taskId: string): RegExp => new RegExp(`^工作区/任务/${taskId}/草稿/[^/\\\\:*?"<>|]+\\.md$`)
/** 草稿正文最多读这么多字节（多出的截掉并说明；正常草稿几十 KB）。 */
export const MAX_DRAFT_BYTES = 512 * 1024
export const NO_TASK = '没有找到这个任务的结果，请到"成果"里查看。'

export interface TaskAnswer {
  status: string
  session_id: string | null
  /** 本次用掉的模型调用次数与上限（读不到为 null）。 */
  used: number | null
  limit: number | null
  /** 最新一版草稿；没存过草稿为 null。 */
  draft: { title: string; version: number; path: string; text: string; truncated: boolean } | null
}
type Result = { ok: true; value: TaskAnswer } | { ok: false; error: { code: string; message: string } }

/** 读案件根里的一个文件：自身和所在目录都不能是链接，实际位置在案件根里。 */
function readInCase(root: string, rel: string, max = MAX_DRAFT_BYTES): { text: string; truncated: boolean } | undefined {
  const file = join(root, ...rel.split('/'))
  try {
    for (let dir = file; dir.length > root.length; dir = join(dir, '..')) if (lstatSync(dir).isSymbolicLink()) return undefined
    if (!lstatSync(file).isFile()) return undefined
    const r = relative(realpathSync(root), realpathSync(file))
    if (!r || r.startsWith('..') || isAbsolute(r)) return undefined
    const buf = readFileSync(file)
    const truncated = buf.length > max
    return { text: buf.subarray(0, max).toString('utf8').replace(/^\uFEFF/, ''), truncated }
  } catch {
    return undefined
  }
}

const num = (v: unknown): number | null => (typeof v === 'number' && Number.isInteger(v) && v >= 0 ? v : null)

/**
 * 读某任务给对话区显示的结果。
 * @param root - 案件根（界面当前案件的 root）。
 * @param taskId - 任务编号。
 */
export function readTaskAnswer(root: unknown, taskId: unknown): Result {
  const fail = (code: string, message: string): Result => ({ ok: false, error: { code, message } })
  if (typeof root !== 'string' || !root || !isAbsolute(root) || typeof taskId !== 'string' || !TASK_ID.test(taskId)) {
    return fail('INVALID_ARGUMENT', '请求参数有误')
  }
  const base = `工作区/任务/${taskId}`
  const resultRaw = readInCase(root, `${base}/result.json`, 4 * 1024 * 1024)
  if (!resultRaw) return fail('TASK_NOT_FOUND', NO_TASK)
  let result: { status?: unknown; usage?: { model_calls?: unknown }; drafts?: Array<{ title?: unknown; path?: unknown; version?: unknown }> }
  let task: { session_id?: unknown; budget?: { model_calls?: unknown } } = {}
  try {
    result = JSON.parse(resultRaw.text)
    const taskRaw = readInCase(root, `${base}/task.json`, 1024 * 1024)
    if (taskRaw) task = JSON.parse(taskRaw.text)
  } catch {
    return fail('TASK_NOT_FOUND', NO_TASK)
  }
  const ok = draftPathOf(taskId)
  const drafts = (Array.isArray(result.drafts) ? result.drafts : [])
    .filter((d) => typeof d?.path === 'string' && ok.test(d.path) && typeof d.title === 'string' && num(d.version) !== null)
  const last = drafts[drafts.length - 1]
  let draft: TaskAnswer['draft'] = null
  if (last) {
    const body = readInCase(root, last.path as string)
    if (body) draft = { title: last.title as string, version: num(last.version)!, path: last.path as string, text: body.text, truncated: body.truncated }
  }
  return {
    ok: true,
    value: {
      status: typeof result.status === 'string' ? result.status : 'unknown',
      session_id: typeof task.session_id === 'string' ? task.session_id : null,
      used: num(result.usage?.model_calls),
      limit: num(task.budget?.model_calls),
      draft,
    },
  }
}
