import { randomBytes } from 'node:crypto'
import { deleteKey, readKey, writeKey } from '../credentials/credman.ts'

// 只在 Windows 上跑；用独立的测试目标名，测试结束删除，不碰正式条目 lawbench/LAWFIRM_KEY
const TEST_TARGET = `lawbench/T7-TEST-${randomBytes(4).toString('hex')}`
const FAKE_KEY = `sk-fake-${randomBytes(12).toString('hex')}`

describe.runIf(process.platform === 'win32')('Windows 凭据管理器读写', () => {
  afterAll(async () => { await deleteKey(TEST_TARGET) })

  it('不存在时读到 undefined', async () => {
    expect(await readKey(TEST_TARGET)).toBeUndefined()
  })

  it('写入后读回一致；覆盖写入后读到新值', async () => {
    await writeKey(FAKE_KEY, TEST_TARGET)
    expect(await readKey(TEST_TARGET)).toBe(FAKE_KEY)
    await writeKey(FAKE_KEY + 'x', TEST_TARGET)
    expect(await readKey(TEST_TARGET)).toBe(FAKE_KEY + 'x')
  })

  it('用户名不符时不返回', async () => {
    expect(await readKey(TEST_TARGET, 'someone-else')).toBeUndefined()
  })

  it('拒绝不可见字符', async () => {
    await expect(writeKey('a b', TEST_TARGET)).rejects.toThrow()
  })

  it('删除后读不到', async () => {
    expect(await deleteKey(TEST_TARGET)).toBe(true)
    expect(await readKey(TEST_TARGET)).toBeUndefined()
    expect(await deleteKey(TEST_TARGET)).toBe(false)
  })
})
