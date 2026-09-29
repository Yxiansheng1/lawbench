// T7 返修 P3-5："测试连接"先保存再测；测试失败时恢复成测试前的地址和 Key，之前没有的删掉；成功的保留。
import { existsSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { LawbenchRemote, RESTORE_FAILED, type CredentialsLike } from '../host/index.ts'
import type { Supervisor } from '../host/supervisor.ts'
import { startFake, type Fake } from './helpers/fake.ts'

let fake: Fake
beforeAll(async () => { fake = await startFake(18801) })
afterAll(() => fake.stop())

function memCredentials(initial?: string) {
  let value = initial
  const c: CredentialsLike = {
    describe: async () => ({ configured: value !== undefined }),
    resolve: async () => (value === undefined ? undefined : { value }),
    set: async (_r, v) => { value = v },
    unset: async () => { value = undefined },
  }
  return { c, get: () => value }
}

const supervisorFor = (f: Fake) => ({ endpoint: () => ({ port: f.port, token: f.token }), state: 'running' }) as unknown as Supervisor
const settingsFile = () => join(fake.appdata, 'settings.json')
const example = JSON.parse(readFileSync(join(__dirname, '..', '..', 'contracts', 'examples', 'file_settings.json'), 'utf8'))
const good = example.servers
const bad = { ...good, llm_base_url: 'http://llm.invalid:8000/v1' }

beforeEach(() => { rmSync(settingsFile(), { force: true }) })

describe('trialConnection', () => {
  it('失败时恢复：原有设置和 Key 都回到测试前', async () => {
    const old = { ...example, servers: { ...good, prep_alt_base_url: null } }
    writeFileSync(settingsFile(), JSON.stringify(old), 'utf8')
    const { c, get } = memCredentials('sk-old-12345678')
    const r = await new LawbenchRemote(supervisorFor(fake), fake.appdata, () => c).trialConnection(bad, 'sk-typo-87654321')
    expect(r.restored).toBe(true)
    expect(JSON.parse(readFileSync(settingsFile(), 'utf8')).servers).toEqual(old.servers)
    expect(get()).toBe('sk-old-12345678')
  })

  it('失败时恢复：测试前没有设置文件和 Key 的，删掉', async () => {
    const { c, get } = memCredentials(undefined)
    const r = await new LawbenchRemote(supervisorFor(fake), fake.appdata, () => c).trialConnection(bad, 'sk-new-12345678')
    expect(r.restored).toBe(true)
    expect(existsSync(settingsFile())).toBe(false)
    expect(get()).toBeUndefined()
  })

  it('成功时保留新的地址和 Key', async () => {
    const { c, get } = memCredentials('sk-old-12345678')
    const r = await new LawbenchRemote(supervisorFor(fake), fake.appdata, () => c).trialConnection(good, 'sk-new-12345678')
    expect(r.restored).toBe(false)
    expect(JSON.parse(readFileSync(settingsFile(), 'utf8')).servers).toEqual(good)
    expect(get()).toBe('sk-new-12345678')
  })

  it('不改 Key（key 为 null）且失败时，原 Key 不动', async () => {
    const { c, get } = memCredentials('sk-old-12345678')
    const r = await new LawbenchRemote(supervisorFor(fake), fake.appdata, () => c).trialConnection(bad, null)
    expect(r.restored).toBe(true)
    expect(get()).toBe('sk-old-12345678')
  })

  // ── T7 第二次返修 F1 / F2 / F6 ──────────────────────────────────────────

  it('F1 恢复时服务不可用：地址恢复失败不影响 Key 恢复；给出"未能恢复"提示', async () => {
    writeFileSync(settingsFile(), JSON.stringify(example), 'utf8')
    const { c, get } = memCredentials('sk-old-12345678')
    let calls = 0
    // 前两次取端点（getSettings、putSettings）正常，之后服务"消失"：测试和恢复地址都会失败
    const sup = { endpoint: () => (++calls <= 2 ? { port: fake.port, token: fake.token } : undefined), state: 'running' } as unknown as Supervisor
    await expect(new LawbenchRemote(sup, fake.appdata, () => c).trialConnection(bad, 'sk-typo-87654321')).rejects.toThrow(RESTORE_FAILED)
    expect(get()).toBe('sk-old-12345678')
  })

  it('F1 恢复 Key 超时、实际已写回：读回核对一致，算恢复成功', async () => {
    const { c, get } = memCredentials('sk-old-12345678')
    const origSet = c.set
    c.set = async (r, v) => { await origSet(r, v); if (v === 'sk-old-12345678') throw new Error('凭据管理器操作超时（15 秒）') }
    const r = await new LawbenchRemote(supervisorFor(fake), fake.appdata, () => c).trialConnection(bad, 'sk-typo-87654321')
    expect(r.restored).toBe(true)
    expect(get()).toBe('sk-old-12345678')
  })

  it('F1 恢复 Key 超时、没写回：读回核对不符，给出"未能恢复"提示', async () => {
    const { c } = memCredentials('sk-old-12345678')
    const origSet = c.set
    c.set = async (r, v) => { if (v === 'sk-old-12345678') throw new Error('凭据管理器操作超时（15 秒）'); await origSet(r, v) }
    await expect(new LawbenchRemote(supervisorFor(fake), fake.appdata, () => c).trialConnection(bad, 'sk-typo-87654321')).rejects.toThrow(RESTORE_FAILED)
  })

  it('F1 过程中出错且恢复成功：抛"……；已恢复为测试前的配置"，地址和 Key 都回到原样', async () => {
    writeFileSync(settingsFile(), JSON.stringify(example), 'utf8')
    const { c, get } = memCredentials('sk-old-12345678')
    const origSet = c.set
    c.set = async (r, v) => { if (v === 'sk-new-12345678') throw new Error('凭据管理器操作失败（退出码 1）：拒绝访问'); await origSet(r, v) }
    await expect(new LawbenchRemote(supervisorFor(fake), fake.appdata, () => c).trialConnection(good, 'sk-new-12345678')).rejects.toThrow('已恢复为测试前的配置')
    expect(JSON.parse(readFileSync(settingsFile(), 'utf8')).servers).toEqual(example.servers)
    expect(get()).toBe('sk-old-12345678')
  })

  it('F2 两次测试连接并发：串行执行，第二次不会把第一次写进去的错误值当旧值', async () => {
    writeFileSync(settingsFile(), JSON.stringify(example), 'utf8')
    const { c, get } = memCredentials('sk-old-12345678')
    // 记下凭据操作的先后：串行时第二次的快照（resolve）必须在第一次的恢复（写回旧 Key）之后
    const ops: string[] = []
    const origResolve = c.resolve; const origSet = c.set
    c.resolve = async (r) => { ops.push('resolve'); return origResolve(r) }
    c.set = async (r, v) => { ops.push(`set:${v}`); await origSet(r, v) }
    const remote = new LawbenchRemote(supervisorFor(fake), fake.appdata, () => c)
    const first = remote.trialConnection(bad, 'sk-typo-87654321')   // 会失败并恢复
    const second = remote.trialConnection(bad, 'sk-typo2-8765432')  // 也失败：应恢复到原始值，而不是第一次的错误值
    const [r1, r2] = await Promise.all([first, second])
    expect(r1.restored).toBe(true)
    expect(r2.restored).toBe(true)
    expect(ops).toEqual([
      'resolve', 'set:sk-typo-87654321', 'set:sk-old-12345678',
      'resolve', 'set:sk-typo2-8765432', 'set:sk-old-12345678',
    ])
    expect(JSON.parse(readFileSync(settingsFile(), 'utf8')).servers).toEqual(example.servers)
    expect(get()).toBe('sk-old-12345678')
  })

  it('F6 没改 Key 且测试没通过：不碰 Key（不写不删）', async () => {
    const { c, get } = memCredentials('sk-old-12345678')
    let writes = 0
    const origSet = c.set; const origUnset = c.unset
    c.set = async (r, v) => { writes++; await origSet(r, v) }
    c.unset = async (r) => { writes++; await origUnset(r) }
    const r = await new LawbenchRemote(supervisorFor(fake), fake.appdata, () => c).trialConnection(bad, null)
    expect(r.restored).toBe(true)
    expect(writes).toBe(0)
    expect(get()).toBe('sk-old-12345678')
  })

  it('Key 格式不对直接拒绝，不动任何东西', async () => {
    const { c, get } = memCredentials('sk-old-12345678')
    await expect(new LawbenchRemote(supervisorFor(fake), fake.appdata, () => c).trialConnection(good, 'a b')).rejects.toThrow('请求参数有误')
    expect(existsSync(settingsFile())).toBe(false)
    expect(get()).toBe('sk-old-12345678')
  })
})
