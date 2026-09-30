// 点草稿正文里的出处打开原文（T13 后续项，走 A）：识别、定位、核对的纯逻辑，以及对 DSH 标记结构的依赖守护。
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { CITATION_PATTERN, citationAt, citationRanges, DSH_ASSISTANT_KIND, DSH_FLOW_ATTR, joinedOffset, openCitation, resolveCitation, shouldHandleClick, type ClickFacts, type MaterialLite } from '../ui/citation.ts'

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
  // 返修 B3：找不到 DSH 源码时给出中文原因，而不是原始的文件读取错误
  const source = (file: string) => {
    const p = join(chat, file)
    if (!existsSync(p)) throw new Error(`找不到 DSH 源码 ${p}：dsh 子模块没有初始化或换了目录结构。这条测试守着出处点击依赖的对话区标记，请先检出 dsh 子模块再跑`)
    return readFileSync(p, 'utf8')
  }
  it(`节点属性 ${DSH_FLOW_ATTR} 仍按节点种类取值，助手回答节点的 key 仍是 ${DSH_ASSISTANT_KIND}`, () => {
    expect(source('ChatNodeSeat.tsx')).toContain(`${DSH_FLOW_ATTR}={routedNode.kind}`)
    expect(source('register-node-renderers.ts')).toContain(`key: '${DSH_ASSISTANT_KIND}'`)
  })
})

describe('这次点击要不要接手（返修 B1）', () => {
  const base: ClickFacts = { button: 0, modifier: false, inAnswer: true, inSkipped: false, selectionCollapsed: true, detail: 1 }
  it('回答块里、左键、没选文字、单击：接手', () => {
    expect(shouldHandleClick(base)).toBe(true)
  })
  it('回答块以外（用户消息、原文查看、wiki 建议里同样的写法）不接手', () => {
    expect(shouldHandleClick({ ...base, inAnswer: false })).toBe(false)
  })
  it('链接、按钮、代码、输入框里不接手', () => {
    expect(shouldHandleClick({ ...base, inSkipped: true })).toBe(false)
  })
  it('正在选文字不接手', () => {
    expect(shouldHandleClick({ ...base, selectionCollapsed: false })).toBe(false)
  })
  it('右键、中键、带修饰键不接手', () => {
    expect(shouldHandleClick({ ...base, button: 2 })).toBe(false)
    expect(shouldHandleClick({ ...base, button: 1 })).toBe(false)
    expect(shouldHandleClick({ ...base, modifier: true })).toBe(false)
  })
  it('双击、三击的后几下不接手（返修 B2）', () => {
    expect(shouldHandleClick({ ...base, detail: 2 })).toBe(false)
    expect(shouldHandleClick({ ...base, detail: 3 })).toBe(false)
  })
})

describe('核对后打开原文；不通过都给中文提示（返修 B1）', () => {
  const ms: MaterialLite[] = [
    { material_id: 'M0001', name: '借款合同', unit: 'page', unit_count: 6, status: 'parsed' },
    { material_id: 'M0002', name: '催款函', unit: 'page', unit_count: 0, status: 'failed' },
    { material_id: 'M0003', name: '借款合同补充协议', unit: 'page', unit_count: 3, status: 'parsed' },
  ]
  const run = async (item: { name: string; loc: string }, over: Partial<{ caseId: string | undefined; materials: MaterialLite[] | undefined }> = {}) => {
    const notices: string[] = []
    const opened: Array<[string, string]> = []
    await openCitation({ ...item, text: `${item.name} ${item.loc}` }, {
      caseId: () => ('caseId' in over ? over.caseId : 'c1'),
      materials: async () => ('materials' in over ? over.materials : ms),
      notice: (_t, text) => { notices.push(text) },
      openSource: (id, cite) => { opened.push([id, cite]) },
    })
    return { notices, opened }
  }
  it('对得上：打开，传材料编号和这一处出处', async () => {
    expect(await run({ name: '借款合同', loc: '第2页' })).toEqual({ notices: [], opened: [['M0001', '〔借款合同 第2页〕']] })
  })
  it('找不到、超出范围、没有案件、读不到材料列表：提示，不打开', async () => {
    for (const [item, over, re] of [
      [{ name: '不存在', loc: '第1页' }, {}, /没有"不存在"/],
      [{ name: '借款合同', loc: '第9页' }, {}, /超出范围/],
      [{ name: '借款合同', loc: '第1页' }, { caseId: undefined }, /不在已打开的案件里/],
      [{ name: '借款合同', loc: '第1页' }, { materials: undefined }, /读不到本案材料列表/],
    ] as const) {
      const r = await run(item, over as never)
      expect(r.opened, item.name).toEqual([])
      expect(r.notices[0], item.name).toMatch(re)
    }
  })
  it('解析失败（没有可读内容）的材料：提示准确，不说"只有 0 页"（返修 B5）', async () => {
    const r = await run({ name: '催款函', loc: '第1页' })
    expect(r.opened).toEqual([])
    expect(r.notices[0]).toMatch(/没有可读的内容/)
    expect(r.notices[0]).not.toMatch(/0 页/)
  })
  it('前缀名字不会开错：借款合同补充 不会打开 借款合同补充协议（返修 B5）', async () => {
    const r = await run({ name: '借款合同补充', loc: '第1页' })
    expect(r.opened).toEqual([])
    expect(r.notices[0]).toMatch(/没有"借款合同补充"/)
  })
})
