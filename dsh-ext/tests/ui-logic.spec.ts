// 界面纯逻辑：胶囊管理（U-11）、确认框文字（Q10）、页码解析。
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { addCapsule, checkBeforeSave, moveCapsule, moveGroup, newCapsuleId, rename, toggleHidden, visible, type Capsules } from '../ui/capsules.ts'
import { ocrConfirmText, pageRanges, parsePageRanges, sumUnits, wikiConfirmText, type Material } from '../ui/format.ts'
import { validateRoot } from '../shared/contracts.ts'

const defaults = JSON.parse(readFileSync(join(__dirname, '..', '..', 'skills', 'capsules.default.json'), 'utf8')) as Capsules
const CAPS_ID = 'lawbench://contracts/skill/capsules.schema.json'
const installed = new Set(['contract-review', 'contract-draft', 'doc-revise'])

describe('胶囊管理', () => {
  it('同组、跨组拖动；原对象不变', () => {
    const a = moveCapsule(defaults, 'contract-draft', 'civil', 0)
    expect(a.groups[0]!.items[0]!.id).toBe('contract-draft')
    const b = moveCapsule(a, 'invoice', 'criminal', 1)
    expect(b.groups.find((g) => g.id === 'criminal')!.items[1]!.id).toBe('invoice')
    expect(b.groups.find((g) => g.id === 'office')!.items.some((x) => x.id === 'invoice')).toBe(false)
    expect(defaults.groups[0]!.items[0]!.id).toBe('contract-review')
    expect(moveGroup(defaults, 'office', 0).groups[0]!.id).toBe('office')
    expect(validateRoot(CAPS_ID, b)).toEqual([])
  })

  it('改名有长度限制（分组 8 字、胶囊 12 字）', () => {
    expect(rename(defaults, 'civil', '')).toMatch(/1 到 8/)
    expect(rename(defaults, 'civil', '一二三四五六七八九')).toMatch(/1 到 8/)
    expect(rename(defaults, 'contract-review', '一二三四五六七八九十一二三')).toMatch(/1 到 12/)
    const r = rename(defaults, 'contract-review', '  审合同  ') as Capsules
    expect(r.groups[0]!.items[0]!.name).toBe('审合同')
    expect(validateRoot(CAPS_ID, r)).toEqual([])
  })

  it('隐藏 / 显示；首页不显示隐藏的', () => {
    const h = toggleHidden(toggleHidden(defaults, 'criminal'), 'invoice')
    expect(visible(h).map((g) => g.id)).not.toContain('criminal')
    expect(visible(h).flatMap((g) => g.items.map((x) => x.id))).not.toContain('invoice')
    expect(visible(toggleHidden(h, 'criminal')).map((g) => g.id)).toContain('criminal')
  })

  it('新增胶囊：id 不重复、custom 为真、只能选已安装的 Skill；结果合契约', () => {
    expect(newCapsuleId(defaults)).toBe('custom-1')
    const a = addCapsule(defaults, 'civil', '我的审查', { kind: 'skill', skills: ['contract-review', 'doc-revise'] }, installed) as Capsules
    const added = a.groups[0]!.items.at(-1)!
    expect(added).toMatchObject({ id: 'custom-1', custom: true, hidden: false, kind: 'skill' })
    expect(newCapsuleId(a)).toBe('custom-2')
    expect(addCapsule(defaults, 'civil', 'x', { kind: 'skill', skills: ['not-installed'] }, installed)).toMatch(/未安装/)
    expect(addCapsule(defaults, 'civil', 'x', { kind: 'skill', skills: [] }, installed)).toMatch(/至少/)
    const t = addCapsule(a, 'office', '再来一个发票', { kind: 'tool', tool: 'invoice' }, installed) as Capsules
    expect(validateRoot(CAPS_ID, t)).toEqual([])
    expect(checkBeforeSave(t, defaults)).toEqual([])
  })

  it('保存前检查：删掉默认胶囊、改提示语、改共用 Skill、编号重复都不让存', () => {
    const del = structuredClone(defaults); del.groups[0]!.items.shift()
    expect(checkBeforeSave(del, defaults)).toContain('默认胶囊只能隐藏，不能删除')
    const hint = { ...structuredClone(defaults), hint: '改了' }
    expect(checkBeforeSave(hint, defaults)).toContain('分流提示语不能改')
    const shared = { ...structuredClone(defaults), shared: [] }
    expect(checkBeforeSave(shared, defaults)).toContain('共用 Skill 不能改')
    const dup = structuredClone(defaults); dup.groups[1]!.items.push(structuredClone(dup.groups[0]!.items[0]!))
    expect(checkBeforeSave(dup, defaults).some((p) => p.startsWith('编号重复'))).toBe(true)
  })
})

describe('确认框文字（Q10）与页码', () => {
  const m = (unit: Material['unit'], unit_count: number, status: Material['status'] = 'parsed') =>
    ({ unit, unit_count, status }) as Material

  it('按单位合计：页、段、工作表、行', () => {
    expect(sumUnits([{ unit: 'page', count: 3 }, { unit: 'page', count: 4 }, { unit: 'para', count: 10 }, { unit: 'cell', count: 2 }, { unit: 'line', count: 5 }]))
      .toBe('7 页、10 段、2 个工作表、5 行')
    expect(sumUnits([])).toBe('0 页')
  })

  it('识别确认：写明 395、几份、共几页，不提去水印', () => {
    const t = ocrConfirmText([{ name: '甲', pages: [3, 4, 5] }, { name: '乙', pages: [1] }])
    expect(t).toContain('2 份材料、共 4 页')
    expect(t).toContain('395')
    expect(t).not.toMatch(/水印/)
  })

  it('wiki 确认：6000D；勾选 395 抽取时两台都写；无法处理的不计', () => {
    const ms = [m('page', 6), m('para', 42), m('page', 3, 'failed')]
    const t = wikiConfirmText(ms, false, false)
    expect(t).toContain('2 份材料（共 6 页、42 段）')
    expect(t).toContain('6000D')
    expect(t).not.toContain('395')
    expect(wikiConfirmText(ms, true, true)).toMatch(/更新案件 wiki.*6000D.*395/)
  })

  it('页码压缩与解析', () => {
    expect(pageRanges([6, 3, 4, 5, 9])).toBe('3-6、9')
    expect(parsePageRanges('1-3, 5、7', 10)).toEqual([1, 2, 3, 5, 7])
    expect(parsePageRanges('3至4', 10)).toEqual([3, 4])
    expect(parsePageRanges('0-2', 10)).toBeUndefined()
    expect(parsePageRanges('5-3', 10)).toBeUndefined()
    expect(parsePageRanges('11', 10)).toBeUndefined()
    expect(parsePageRanges('abc', 10)).toBeUndefined()
    expect(parsePageRanges('', 10)).toBeUndefined()
  })
})

describe('出处拆分', () => {
  it('多处出处拆开、按名字对上材料编号；固定写法和找不到的不给编号', async () => {
    const { citationTargets } = await import('../ui/format.ts')
    const ms = [{ material_id: 'M0001', name: '借条' }, { material_id: 'M0004', name: '银行流水' }]
    expect(citationTargets('〔借条 第1页、银行流水 流水!B12〕', ms)).toEqual([
      { text: '借条 第1页', material_id: 'M0001', citation: '〔借条 第1页〕' },
      { text: '银行流水 流水!B12', material_id: 'M0004', citation: '〔银行流水 流水!B12〕' },
    ])
    expect(citationTargets('〔推断〕', ms)).toEqual([{ text: '〔推断〕', citation: '〔推断〕' }])
    expect(citationTargets('〔不存在 第2页〕', ms)[0]!.material_id).toBeUndefined()
  })
})

describe('远程返回剥层', () => {
  it('成功时返回 Host 原返回值；网关失败时抛出带中文的错误', async () => {
    const { unwrapRemote } = await import('../ui/state.ts')
    const api = unwrapRemote({
      getCapsules: async () => ({ ok: true, value: { ok: true, value: { v: 1 } } }),
      setupState: async () => ({ ok: true, value: { configured: true } }),
      caseRecent: async () => ({ ok: false, error: { code: 'x', message: '传输失败' } }),
    })
    expect(await api.getCapsules!()).toEqual({ ok: true, value: { v: 1 } })
    expect(await api.setupState()).toEqual({ configured: true })
    await expect(api.caseRecent!()).rejects.toThrow('传输失败')
    await expect(api.nope!()).rejects.toThrow()
  })
})

describe('给律师看的错误提示（返修 P3-2）', () => {
  it('网关的英文技术信息换成通用中文提示；中文提示原样保留', async () => {
    const { lawyerMessage, errorText, GENERIC_ERROR } = await import('../ui/format.ts')
    const { unwrapRemote, call, setApi } = await import('../ui/state.ts')
    expect(lawyerMessage('client api: lawbench/caseRecent failed: transport failure for /api/lawbench/caseRecent: HTTP 404')).toBe(GENERIC_ERROR)
    expect(lawyerMessage(undefined)).toBe(GENERIC_ERROR)
    expect(lawyerMessage('找不到这个案件，请重新打开')).toBe('找不到这个案件，请重新打开')
    expect(errorText({ code: 'INTERNAL', message: 'Unexpected end of JSON input' })).toBe(GENERIC_ERROR)
    const api = unwrapRemote({ caseRecent: async () => ({ ok: false, error: { message: 'client api: x has no active Connection' } }) })
    await expect(api.caseRecent!()).rejects.toThrow(GENERIC_ERROR)
    setApi(api)
    const r = await call('caseRecent', {})
    expect(r).toEqual({ ok: false, error: { code: 'SERVICE_UNAVAILABLE', message: GENERIC_ERROR } })
    setApi(undefined)
  })
})

describe('wiki 整理结束的通知（第二次返修一并做）', () => {
  it('只在被观察的任务成功完成时通知；停止、失败、中断、读不到都不发', async () => {
    const { shouldNotifyWikiDone } = await import('../ui/format.ts')
    const id = 'P-20260930120000-ab12'
    expect(shouldNotifyWikiDone(id, [{ task_id: id, status: 'completed' }])).toBe(true)
    for (const status of ['cancelled', 'failed', 'interrupted', 'budget_stopped', 'running']) {
      expect(shouldNotifyWikiDone(id, [{ task_id: id, status }]), status).toBe(false)
    }
    expect(shouldNotifyWikiDone(id, [{ task_id: 'P-20260930120000-ffff', status: 'completed' }])).toBe(false)
    expect(shouldNotifyWikiDone(id, undefined)).toBe(false)
    expect(shouldNotifyWikiDone(null, [{ task_id: id, status: 'completed' }])).toBe(false)
  })
})
