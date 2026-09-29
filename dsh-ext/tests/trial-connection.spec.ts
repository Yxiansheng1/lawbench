// T7 返修 P3-5："测试连接"先保存再测；测试失败时恢复成测试前的地址和 Key，之前没有的删掉；成功的保留。
import { existsSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { LawbenchRemote, type CredentialsLike } from '../host/index.ts'
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

  it('Key 格式不对直接拒绝，不动任何东西', async () => {
    const { c, get } = memCredentials('sk-old-12345678')
    await expect(new LawbenchRemote(supervisorFor(fake), fake.appdata, () => c).trialConnection(good, 'a b')).rejects.toThrow('请求参数有误')
    expect(existsSync(settingsFile())).toBe(false)
    expect(get()).toBe('sk-old-12345678')
  })
})
