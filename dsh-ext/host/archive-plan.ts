// 归档面板（T26 第 3 步，U-15）读归档方案。方案由 Agent 工具 case_save_archive_plan 写在
// <案件>\工作区\任务\<任务ID>\归档方案.json（契约 tools/case_save_archive_plan 的说明）；工作台服务没有读它的接口，
// Host 只读这一个文件、按契约 $defs/plan 校验后交给界面。界面改好后连同这个相对路径交 /api/archive/build，生成全在服务端。
// 只读、不写；任务编号按服务的格式核对，路径不出案件根，方案文件或它所在的目录是链接时不读。
import { lstatSync, readFileSync, realpathSync } from 'node:fs'
import { join, relative, isAbsolute } from 'node:path'
import { toolId, validate } from '../shared/contracts.ts'

/** 服务的任务编号格式（service\lawbench\case\task.py 的 rel）。 */
const TASK_ID = /^[TP]-\d{14}-[0-9a-f]{4}$/
export const PLAN_NAME = '归档方案.json'
/** 交 /api/archive/build 的 plan：相对案件根、正斜杠（同服务的 tasks.rel）。 */
export const planRel = (taskId: string): string => `工作区/任务/${taskId}/${PLAN_NAME}`

export const NO_PLAN = '这个任务还没有保存归档方案。请先在对话里让它整理归档方案，再回来生成归档文件。'
export const BAD_PLAN = '归档方案的内容不完整，请在对话里让它重新保存一次归档方案。'

type Result = { ok: true; value: { plan: unknown; path: string } } | { ok: false; error: { code: string; message: string } }

/**
 * 读某任务的归档方案。
 * @param root - 案件根（界面当前案件的 root）。
 * @param taskId - 任务编号。
 */
export function readArchivePlan(root: unknown, taskId: unknown): Result {
  const fail = (code: string, message: string): Result => ({ ok: false, error: { code, message } })
  if (typeof root !== 'string' || !root || !isAbsolute(root) || typeof taskId !== 'string' || !TASK_ID.test(taskId)) {
    return fail('INVALID_ARGUMENT', '请求参数有误')
  }
  const dir = join(root, '工作区', '任务', taskId)
  const file = join(dir, PLAN_NAME)
  let text: string
  try {
    // 目录和文件都不能是链接（链接可能指到案件外）；实际位置仍须在案件根里
    if (lstatSync(dir).isSymbolicLink() || lstatSync(file).isSymbolicLink() || !lstatSync(file).isFile()) return fail('TASK_NOT_FOUND', NO_PLAN)
    const rel = relative(realpathSync(root), realpathSync(file))
    if (!rel || rel.startsWith('..') || isAbsolute(rel)) return fail('OUT_OF_CASE', NO_PLAN)
    text = readFileSync(file, 'utf8')
  } catch {
    return fail('TASK_NOT_FOUND', NO_PLAN)
  }
  let plan: unknown
  try {
    plan = JSON.parse(text.replace(/^﻿/, ''))
  } catch {
    return fail('INVALID_ARGUMENT', BAD_PLAN)
  }
  if (validate(toolId('case_save_archive_plan'), 'plan', plan).length) return fail('INVALID_ARGUMENT', BAD_PLAN)
  return { ok: true, value: { plan, path: planRel(taskId) } }
}
