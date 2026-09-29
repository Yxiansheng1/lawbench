import { LawbenchCredentials, KEY_REF } from '../credentials/index.ts'

function memStore() {
  const s = { value: undefined as string | undefined, reads: 0 }
  return {
    s,
    store: { read: async () => { s.reads++; return s.value }, write: async (v: string) => { s.value = v }, remove: async () => { s.value = undefined } },
  }
}

describe('凭据服务（Q2 裁决）', () => {
  it('只认 LAWFIRM_KEY：其他名字未配置、不可写、resolve 为空', async () => {
    const { store } = memStore()
    const c = new LawbenchCredentials(store)
    expect(await c.describe('DEEPSEEK_API_KEY')).toEqual({ configured: false, writable: false })
    expect(await c.resolve('DEEPSEEK_API_KEY')).toBeUndefined()
    await expect(c.set('OTHER', 'x')).rejects.toThrow()
  })

  it('不读环境变量：环境变量里有 LAWFIRM_KEY 也不采用', async () => {
    process.env.LAWFIRM_KEY = 'from-env'
    try {
      const { store } = memStore()
      const c = new LawbenchCredentials(store)
      expect(await c.resolve(KEY_REF)).toBeUndefined()
      expect((await c.describe(KEY_REF)).configured).toBe(false)
    } finally { delete process.env.LAWFIRM_KEY }
  })

  it('set 后 resolve 得到值；unset 后为空；来源标凭据管理器', async () => {
    const { store } = memStore()
    const c = new LawbenchCredentials(store)
    await c.set(KEY_REF, 'sk-test-1')
    expect(await c.resolve(KEY_REF)).toEqual({ value: 'sk-test-1', source: 'windows-credential-manager' })
    expect(await c.describe(KEY_REF)).toEqual({ configured: true, source: 'windows-credential-manager', writable: true })
    await c.unset(KEY_REF)
    expect(await c.resolve(KEY_REF)).toBeUndefined()
  })

  it('读取有 5 分钟内存缓存；set 后缓存失效', async () => {
    const { s, store } = memStore()
    let t = 0
    const c = new LawbenchCredentials(store, () => t)
    s.value = 'a'
    await c.resolve(KEY_REF); await c.resolve(KEY_REF)
    expect(s.reads).toBe(1)
    t = 5 * 60_000
    await c.resolve(KEY_REF)
    expect(s.reads).toBe(2)
    await c.set(KEY_REF, 'b')
    expect((await c.resolve(KEY_REF))?.value).toBe('b')
  })

  it('授权记录只在内存：初始为空；modifyRecord 写入后可读；新实例（重启）读不到', async () => {
    const { store } = memStore()
    const c = new LawbenchCredentials(store)
    expect(await c.readRecord('client-connection/browser-session')).toBeUndefined()
    expect(await c.listRecords()).toEqual([])
    const rec = { kind: 'grant', payload: { secret: 's' } }
    expect(await c.modifyRecord('client-connection/browser-session', async (cur) => cur ?? rec)).toEqual(rec)
    expect(await c.readRecord('client-connection/browser-session')).toEqual(rec)
    expect(await c.listRecords()).toEqual([{ key: 'client-connection/browser-session', kind: 'grant' }])
    await c.deleteRecord('client-connection/browser-session')
    expect(await c.readRecord('client-connection/browser-session')).toBeUndefined()
    expect(await new LawbenchCredentials(store).readRecord('client-connection/browser-session')).toBeUndefined()
  })

  it('记录与 Key 互不影响：写记录不会写凭据管理器', async () => {
    const { s, store } = memStore()
    const c = new LawbenchCredentials(store)
    await c.modifyRecord('client-connection/browser-session', async () => ({ kind: 'grant', payload: { secret: 'zzz' } }))
    expect(s.value).toBeUndefined()
    expect(await c.resolve(KEY_REF)).toBeUndefined()
  })

  it('只收已知的记录种类：其他写入拒绝并记日志（只记记录名，不记内容）', async () => {
    const logs: Array<[string, string, Record<string, unknown> | undefined]> = []
    const c = new LawbenchCredentials(memStore().store, Date.now, (l, e, m) => { logs.push([l, e, m]) })
    await expect(c.modifyRecord('deepseek/account', async () => ({ kind: 'api-key', key: 'secret-value' }))).rejects.toThrow()
    expect(await c.readRecord('deepseek/account')).toBeUndefined()
    expect(logs).toEqual([['warn', 'credentials.record_rejected', { record: 'deepseek/account' }]])
    expect(JSON.stringify(logs)).not.toContain('secret-value')
  })

  it('读取期间发生写入：这次读到的旧值不进缓存（T7 第三轮 P2-2）', async () => {
    let value: string | undefined = 'old'
    let release!: () => void
    let slow = true
    const store = {
      read: async () => { const v = value; if (slow) { slow = false; await new Promise<void>((r) => { release = r }) } return v },
      write: async (v: string) => { value = v },
      remove: async () => { value = undefined },
    }
    const c = new LawbenchCredentials(store)
    const reading = c.resolve(KEY_REF)        // 读到 'old' 后挂起
    await new Promise((r) => setTimeout(r, 5))
    await c.set(KEY_REF, 'new')               // 读取期间写入
    release()
    expect((await reading)?.value).toBe('old') // 这次返回的是读时的值
    expect((await c.resolve(KEY_REF))?.value).toBe('new') // 但没进缓存：下一次回到存储，读到新值
  })

  it('空 Key 拒绝', async () => {
    await expect(new LawbenchCredentials(memStore().store).set(KEY_REF, '')).rejects.toThrow()
  })
})
