// 我方插件的本机日志（元数据）：<应用数据>\logs\plugins-YYYYMMDD.log，一行一条 JSON。
// 只记事件名和元数据（命令、状态码、耗时、错误码、次数、端口），不记材料名、检索词、模型输入输出（Spec 4.5）。
import { appendFileSync, mkdirSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'
import type { Logger } from './core-client.ts'

export function defaultAppData(): string {
  return join(process.env.LOCALAPPDATA ?? homedir(), 'lawbench')
}

type CtxLogger = { info(...a: unknown[]): void; warn(...a: unknown[]): void; error(...a: unknown[]): void } | undefined

/** 同时写 DSH 的 ctx.logger（如有）和本机日志文件；写文件失败不影响功能。 */
export function makeLogger(source: string, appData: string, ctxLogger: CtxLogger): Logger {
  const dir = join(appData, 'logs')
  return (level, event, meta) => {
    ctxLogger?.[level](`${event}${meta ? ' ' + JSON.stringify(meta) : ''}`)
    try {
      mkdirSync(dir, { recursive: true })
      const d = new Date()
      const day = `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, '0')}${String(d.getDate()).padStart(2, '0')}`
      appendFileSync(join(dir, `plugins-${day}.log`), JSON.stringify({ ts: d.toISOString(), source, level, event, ...(meta ?? {}) }) + '\n', 'utf8')
    } catch { /* 日志写不进去不影响功能 */ }
  }
}
