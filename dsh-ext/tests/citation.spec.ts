// 点草稿正文里的出处打开原文（T13 后续项，走 A）：识别、定位、核对的纯逻辑，以及对 DSH 标记结构的依赖守护。
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { CITATION_PATTERN, citationAt, citationRanges, DSH_ASSISTANT_KIND, DSH_FLOW_ATTR, joinedOffset, resolveCitation, type MaterialLite } from '../ui/citation.ts'

const repo = join(__dirname, '..', '..')

describe('出处写法以契约为准', () => {
  it('CITATION_PATTERN 与 contracts\\common.schema.json 的 citation_text 逐字一致', () => {
    const common = JSON.parse(readFileSync(join(repo, 'contracts', 'common.schema.json'), 'utf8'))
    expect(CITATION_PATTERN).toBe(common.$defs.citation_text.pattern)
  })

  it('比契约宽的写法不认', () => {
    for (const s of ['见〔借款合同 第二页〕', '见〔借款合同〕', '见〔借款 合同 第2页〕', '见[借款合同 第2页]', '见〔借款合同 第2张〕']) {
      expect(citationRanges(s), s).toEqual([])
    }
  })
})

describe('点中的是哪一处', () => {
  const text = '依据〔借款合同 第2页、银行流水 流水!B12:D12、借条 第1-3页〕可知'
  const at = (needle: string, d = 0) => text.indexOf(needle) + d

  it('一个括号多处：点到哪一处开哪一处', () => {
    expect(citationAt(text, at('借款合同', 1))).toMatchObject({ kind: 'item', item: { name: '借款合同', loc: '第2页', text: '借款合同 第2页' } })
    expect(citationAt(text, at('流水!B12', 2))).toMatchObject({ kind: 'item', item: { name: '银行流水', loc: '流水!B12:D12' } })
    expect(citationAt(text, at('借条', 0))).toMatchObject({ kind: 'item', item: { name: '借条', loc: '第1-3页' } })
  })

  it('点在括号或顿号上分不清：开第一处', () => {
    expect(citationAt(text, at('〔'))).toMatchObject({ kind: 'item', item: { name: '借款合同' } })
    expect(citationAt(text, at('、银行'))).toMatchObject({ kind: 'item', item: { name: '借款合同' } })
    expect(citationAt(text, at('〕'))).toMatchObject({ kind: 'item', item: { name: '借款合同' } })
  })

  it('括号外、普通文字：不是出处', () => {
    expect(citationAt(text, 0)).toEqual({ kind: 'none' })
    expect(citationAt(text, text.length - 1)).toEqual({ kind: 'none' })
  })

  it('〔未找到依据〕〔推断〕不是出处，点了不反应；下划线也不画', () => {
    const t = '金额〔未找到依据〕，日期〔推断〕'
    expect(citationAt(t, t.indexOf('未找到') + 1)).toEqual({ kind: 'fixed' })
    expect(citationAt(t, t.indexOf('推断'))).toEqual({ kind: 'fixed' })
    expect(citationRanges(t)).toEqual([])
  })

  it('出处跨了加粗等行内元素：按段落整体文字换算后照样认', () => {
    // <p>证据见<strong>〔借款</strong>合同 第2页〕。</p> 的三个文字节点
    const segments = ['证据见', '〔借款', '合同 第2页〕', '。']
    const whole = segments.join('')
    expect(citationAt(whole, joinedOffset(segments, 1, 1))).toMatchObject({ kind: 'item', item: { name: '借款合同', loc: '第2页' } })
    expect(citationAt(whole, joinedOffset(segments, 2, 4))).toMatchObject({ kind: 'item', item: { name: '借款合同' } })
    expect(citationAt(whole, joinedOffset(segments, 3, 0))).toEqual({ kind: 'none' })
  })
})

describe('按材料列表核对（找不到、超出范围、原件没了都给中文提示，不猜别的材料）', () => {
  const ms: MaterialLite[] = [
    { material_id: 'M0001', name: '借款合同', unit: 'page', unit_count: 6, status: 'parsed' },
    { material_id: 'M0002', name: '银行流水', unit: 'cell', unit_count: 3, status: 'parsed' },
    { material_id: 'M0003', name: '委托代理合同', unit: 'para', unit_count: 42, status: 'parsed' },
    { material_id: 'M0004', name: '对账单', unit: 'cell', unit_count: 2, status: 'source_deleted' },
    { material_id: 'M0005', name: '重名', unit: 'page', unit_count: 1, status: 'parsed' },
    { material_id: 'M0006', name: '重名', unit: 'page', unit_count: 1, status: 'parsed' },
  ]
  const item = (name: string, loc: string) => ({ name, loc, text: `${name} ${loc}` })

  it('对得上的返回那份材料', () => {
    expect(resolveCitation(item('借款合同', '第2-6页'), ms)).toMatchObject({ ok: true, material: { material_id: 'M0001' } })
    expect(resolveCitation(item('银行流水', '流水!B12'), ms)).toMatchObject({ ok: true, material: { material_id: 'M0002' } })
    expect(resolveCitation(item('委托代理合同', '第42段'), ms)).toMatchObject({ ok: true })
  })

  it('不通过的给中文说明', () => {
    const cases: Array<[string, string, RegExp]> = [
      ['不存在的材料', '第1页', /没有"不存在的材料"/],
      ['借款合同', '第7页', /只有 6 页.*超出范围/],
      ['借款合同', '第3-2页', /超出范围/],
      ['借款合同', '第2段', /按页定位/],
      ['委托代理合同', '第1页', /按段定位/],
      ['借款合同', '表!A1', /不是表格/],
      ['对账单', '表!A1', /原件已经删除/],
      ['重名', '第1页', /2 份材料都叫/],
    ]
    for (const [name, loc, re] of cases) {
      const r = resolveCitation(item(name, loc), ms)
      expect(r.ok, `${name} ${loc}`).toBe(false)
      expect(!r.ok && r.message, `${name} ${loc}`).toMatch(re)
      expect(!r.ok && /[一-鿿]/.test(r.message)).toBe(true)
    }
  })

  it('出处文字只拿去比对：像路径的名字当普通名字，找不到就提示', () => {
    const r = resolveCitation(item('..\\..\\Windows', '第1页'), ms)
    expect(r.ok).toBe(false)
  })
})

describe('依赖的 DSH 对话区标记结构还在（DSH 升级时这里会先变红）', () => {
  const chat = join(repo, 'dsh', 'packages', 'client', 'ui-chat', 'src', 'client', 'chat')
  it(`节点属性 ${DSH_FLOW_ATTR} 仍按节点种类取值，助手回答节点的 key 仍是 ${DSH_ASSISTANT_KIND}`, () => {
    expect(readFileSync(join(chat, 'ChatNodeSeat.tsx'), 'utf8')).toContain(`${DSH_FLOW_ATTR}={routedNode.kind}`)
    expect(readFileSync(join(chat, 'register-node-renderers.ts'), 'utf8')).toContain(`key: '${DSH_ASSISTANT_KIND}'`)
  })
})
