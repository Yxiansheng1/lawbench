// 开发假服务（dev\fake-tools.mjs）的发票动作与真引擎一致（T26 第二轮复核记录项③）：
// review 不带 confirm 回 [BLOCKED] 失败体（真引擎 workflow.py:155 直接报错，没有预览）；带 confirm 正常写入。
import { makeTools } from '../dev/fake-tools.mjs'

const SHA = 'e'.repeat(64)
const tools = makeTools({
  arg: (name: string, dflt: string | null) => (name === '--invoice-delay' ? '0' : dflt),
  flag: () => false,
  check: () => [],
  fail: (code: string, message: string) => ({ ok: false, error: { code, message } }),
  ok: (value: unknown) => ({ ok: true, value }),
  settings: () => ({ office: { dir: 'D:\\日常办公（虚构）', invoice_buyer: '某律师事务所（虚构）' } }),
})
const run = async (body: Record<string, unknown>) => ((await tools.handle('POST', '/api/invoice/run', body)) as [{ ok: boolean; value: { exit_code: number; attention: boolean; failed: boolean; output: string } }])[0]

describe('开发假服务：发票人工核验', () => {
  it('不带 confirm：[BLOCKED] 失败体（failed:true、attention:false、退出码 2），同真引擎', async () => {
    const r = await run({ action: 'review', sha256: SHA, reviewer: '张律师', confirm: false })
    expect(r.ok).toBe(true)
    expect(r.value).toMatchObject({ exit_code: 2, attention: false, failed: true })
    expect(r.value.output.startsWith('[BLOCKED]')).toBe(true)
  })
  it('带 confirm：写入台账', async () => {
    const r = await run({ action: 'review', sha256: SHA, reviewer: '张律师', confirm: true })
    expect(r.value).toMatchObject({ exit_code: 0, failed: false })
  })
})
