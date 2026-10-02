// 点草稿正文里的出处打开原文：识别、拆出每一处、核对的纯逻辑；T17 P-16 起出处由 DSH 画成按钮，这里守着交给 DSH 的标记和 DSH 那一侧的服务。
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { CITATION_PATTERN, citationItem, citationItemRanges, citationMark, citationScanner, openCitation, resolveCitation, type MaterialLite } from '../ui/citation.ts'

const repo = join(__dirname, '..', '..')

describe('出处写法以契约为准', () => {
  it('CITATION_PATTERN 与 contracts\\common.schema.json 的 citation_text 逐字一致', () => {
    const common = JSON.parse(readFileSync(join(repo, 'contracts', 'common.schema.json'), 'utf8'))
    expect(CITATION_PATTERN).toBe(common.$defs.citation_text.pattern)
  })

  it('比契约宽的写法不认', () => {
    for (const s of ['见〔借款合同 第二页〕', '见〔借款合同〕', '见〔借款 合同 第2页〕', '见[借款合同 第2页]', '见〔借款合同 第2张〕']) {
      expect([...s.matchAll(citationScanner())], s).toEqual([])
    }
  })
})

describe('一个出处括号里拆出每一处（交给 DSH 画按钮，P-16）', () => {
  const match = (text: string) => [...text.matchAll(citationScanner())].map((m) => m[0])

  it('一个括号多处：每一处一个范围，括号和顿号留在外面', () => {
    const m = match('依据〔借款合同 第2页、银行流水 流水!B12:D12、借条 第1-3页〕可知')[0]!
    const items = citationItemRanges(m).map(([a, b]) => m.slice(a, b))
    expect(items).toEqual(['借款合同 第2页', '银行流水 流水!B12:D12', '借条 第1-3页'])
    expect(citationItem(items[1]!)).toEqual({ text: '银行流水 流水!B12:D12', name: '银行流水', loc: '流水!B12:D12' })
  })

  it('〔未找到依据〕〔推断〕不是出处：不成按钮', () => {
    for (const m of match('金额〔未找到依据〕，日期〔推断〕')) expect(citationItemRanges(m), m).toEqual([])
  })

  it('交给 DSH 的只有正则、范围、标签和打开函数；打开时核对后开原文', async () => {
    const opened: string[] = []
    const mark = citationMark({
      caseId: () => 'c1',
      materials: async () => [{ material_id: 'M0001', name: '借款合同', unit: 'page', unit_count: 6, status: 'parsed' }],
      notice: () => {},
      openSource: (id, cite) => { opened.push(`${id} ${cite}`) },
    })
    expect(Object.keys(mark).sort()).toEqual(['label', 'open', 'pattern', 'ranges'])
    expect(mark.pattern.source).toBe(CITATION_PATTERN.slice(1, -1))
    expect(mark.label('借款合同 第2页')).toBe('打开原文：借款合同 第2页')
    mark.open('借款合同 第2页')
    await new Promise((r) => setTimeout(r, 0))
    expect(opened).toEqual(['M0001 〔借款合同 第2页〕'])
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

describe('DSH 那一侧的出处按钮服务还在（P-16 补丁；DSH 升级时这里会先变红）', () => {
  const file = join(repo, 'dsh', 'packages', 'client', 'ui-chat', 'src', 'client', 'inline-marks.ts')
  it('ui-chat 提供 chatInlineMarks，登记接口收正则、范围、标签、打开函数', () => {
    // 返修 B3 的做法：找不到 DSH 源码时给出中文原因
    if (!existsSync(file)) throw new Error(`找不到 DSH 源码 ${file}：dsh 子模块没有初始化、没有打 P-16 补丁，或换了目录结构`)
    const src = readFileSync(file, 'utf8')
    for (const word of ['register(mark: ChatInlineMark)', 'readonly pattern: RegExp', 'readonly ranges?:', 'readonly label:', 'readonly open:']) expect(src, word).toContain(word)
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
