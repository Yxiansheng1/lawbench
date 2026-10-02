// 凭据插件 legal-credentials（Spec 8.1、D9；T7 步骤 4、执行令 Q1/Q2）。全局行。
// 提供 Cordis 服务 credentials，接口与 credentials-local 相同（按鸭子类型）；补丁里原 credentials 行设 disabled。
// Q2 裁决：只认 LAWFIRM_KEY，从 Windows 凭据管理器读写；其他名字一律"未配置"；
// 授权记录读取返回空、写入拒绝；不读环境变量（环境变量优先会留一个绕过凭据管理器的口子）。
import { deleteKey, readKey, writeKey } from './credman.ts'
import type { Logger } from '../shared/core-client.ts'
import { defaultAppData, makeLogger } from '../shared/file-log.ts'

export const name = 'lawbench-credentials'

export const KEY_REF = 'LAWFIRM_KEY'
/** 允许写入内存的授权记录种类（目前只有 DSH 连接插件的浏览器会话密钥）。 */
export const ALLOWED_RECORDS: ReadonlySet<string> = new Set(['client-connection/browser-session'])
const SOURCE = 'windows-credential-manager'
const CACHE_MS = 5 * 60_000

export interface Store {
  read(): Promise<string | undefined>
  write(value: string): Promise<void>
  remove(): Promise<unknown>
}

/** 凭据变化事件（T7 第一轮 P3-7）：写入或删除之后发出，DSH 的模型选择据此刷新模型目录（ui-model-selection 监听这两个事件）。 */
export type Notify = (event: 'credentials/reference-updated' | 'credentials/record-updated', subject: string) => void

/** credentials-local 接口的我方实现。Key 只放在内存缓存（5 分钟），不落盘。 */
export class LawbenchCredentials {
  private cache: { value: string | undefined; at: number } | undefined

  constructor(
    private readonly store: Store,
    private readonly now: () => number = Date.now,
    private readonly log: Logger = () => {},
    private readonly notify: Notify = () => {},
  ) {}

  /** 发事件；监听方出错不影响已完成的写入（同官方 credentials 的 fanOut 约定）。 */
  private emit(event: Parameters<Notify>[0], subject: string): void {
    try { this.notify(event, subject) } catch { this.log('warn', 'credentials.notify_failed', { event }) }
  }

  /** 写入计数（T7 第三轮 P2-2）：读取期间发生过写入的，这次读到的值不进缓存。 */
  private writes = 0

  private async current(): Promise<string | undefined> {
    const t = this.now()
    if (this.cache && t - this.cache.at < CACHE_MS) return this.cache.value
    const writesBefore = this.writes
    const value = await this.store.read()
    if (this.writes === writesBefore) this.cache = { value, at: t }
    return value
  }

  async resolve(ref: string): Promise<{ value: string; source: string } | undefined> {
    if (ref !== KEY_REF) return undefined
    const value = await this.current()
    return value ? { value, source: SOURCE } : undefined
  }

  async describe(ref: string): Promise<{ configured: boolean; source?: string; writable: boolean }> {
    if (ref !== KEY_REF) return { configured: false, writable: false }
    const configured = (await this.current()) !== undefined
    return configured ? { configured, source: SOURCE, writable: true } : { configured, writable: true }
  }

  async set(ref: string, value: string): Promise<void> {
    if (ref !== KEY_REF) throw new Error(`只能设置 ${KEY_REF}`)
    if (typeof value !== 'string' || value.length === 0) throw new Error('Key 不能为空')
    // 写之前先作废缓存：写入超时时可能已经写成功，之后的读取必须回到凭据管理器核对（T7 第二次返修）
    this.writes++
    this.cache = undefined
    // 写入报错（含超时）时实际可能已写成，所以不论成败都发事件，让模型目录重新读一次
    try { await this.store.write(value) } finally { this.writes++; this.cache = undefined; this.emit('credentials/reference-updated', KEY_REF) }
  }

  async unset(ref: string): Promise<void> {
    if (ref !== KEY_REF) return
    this.writes++
    this.cache = undefined
    try { await this.store.remove() } finally { this.writes++; this.cache = undefined; this.emit('credentials/reference-updated', KEY_REF) }
  }

  // ── 授权记录 ─────────────────────────────────────────────────────────────
  // Q2 原裁决是"读取返回空、写入拒绝"。实测 DSH 自己的连接插件（client-connection）启动时要用
  // modifyRecord 保存浏览器会话密钥（packages/client/connection/lib/index.js:330 initializeSecret），
  // 写入拒绝会让桌面端起不来。所以改为：记录只放在进程内存，不落盘、不进凭据管理器，每次启动重新生成。
  // Key 仍然只在凭据管理器（上面的 resolve/set 与记录无关）。主编排 2026-09-29 23:32 注记同意，
  // 并要求只收已知的记录种类：其他写入拒绝并记日志（只记记录名，不记内容），DSH 升级多出新种类时能看见。
  private readonly records = new Map<string, Record<string, unknown>>()

  async readRecord(key: string): Promise<Record<string, unknown> | undefined> { return this.records.get(key) }

  async describeRecord(key: string): Promise<{ configured: boolean; kind?: string; writable: true }> {
    const r = this.records.get(key)
    return r ? { configured: true, kind: r.kind as string, writable: true } : { configured: false, writable: true }
  }

  async listRecords(): Promise<ReadonlyArray<{ key: string; kind: string }>> {
    return [...this.records].map(([key, r]) => ({ key, kind: r.kind as string }))
  }

  async modifyRecord(
    key: string,
    mutate: (cur: Record<string, unknown> | undefined) => Promise<Record<string, unknown> | undefined>,
  ): Promise<Record<string, unknown> | undefined> {
    if (!ALLOWED_RECORDS.has(key)) {
      this.log('warn', 'credentials.record_rejected', { record: key })
      throw new Error('律师工作台不保存这类授权记录')
    }
    const next = await mutate(this.records.get(key))
    if (next === undefined) this.records.delete(key)
    else this.records.set(key, next)
    this.emit('credentials/record-updated', key)
    return next
  }

  async deleteRecord(key: string): Promise<void> {
    if (this.records.delete(key)) this.emit('credentials/record-updated', key)
  }
}

type Ctx = {
  provide(name: string, value: unknown): () => void
  emit(event: string, ...args: unknown[]): unknown
  effect(fn: () => () => void, label?: string): void
  logger?(name: string): { info(...a: unknown[]): void; warn(...a: unknown[]): void; error(...a: unknown[]): void }
}

export function apply(ctx: Ctx): void {
  const log = makeLogger('credentials', defaultAppData(), ctx.logger?.('lawbench-credentials'))
  const impl = new LawbenchCredentials({ read: () => readKey(), write: (v) => writeKey(v), remove: () => deleteKey() }, Date.now, log,
    (event, subject) => { ctx.emit(event, subject) })
  ctx.effect(() => ctx.provide('credentials', impl), 'lawbench-credentials: provider')
}
