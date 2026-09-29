import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { CONTRACT_VERSION, TOOL_NAMES, coreId, toolId, toolParameters, validate } from '../shared/contracts.ts'

const repo = join(__dirname, '..', '..')
const example = (name: string): unknown => JSON.parse(readFileSync(join(repo, 'contracts', 'examples', name), 'utf8'))

describe('契约加载', () => {
  it('版本号取自 contracts/VERSION', () => {
    expect(CONTRACT_VERSION).toBe(readFileSync(join(repo, 'contracts', 'VERSION'), 'utf8').trim())
  })

  it('恰好 11 个 case_* 工具', () => {
    expect(TOOL_NAMES).toHaveLength(11)
    for (const t of TOOL_NAMES) expect(t).toMatch(/^case_[a-z_]+$/)
  })

  it('工具参数展开后不含 $ref、$id、$schema', () => {
    for (const t of TOOL_NAMES) {
      const s = JSON.stringify(toolParameters(t))
      expect(s).not.toContain('"$ref"')
      expect(s).not.toContain('"$id"')
      expect(s).not.toContain('"$schema"')
      expect(toolParameters(t).type).toBe('object')
    }
  })

  it('展开保留约束：case_read_material.max_chars 上限 8000', () => {
    const p = toolParameters('case_read_material') as { properties: { max_chars: { maximum: number } } }
    expect(p.properties.max_chars.maximum).toBe(8000)
  })
})

describe('按契约校验', () => {
  it('官方样例通过', () => {
    expect(validate(coreId('task_begin'), 'request', example('core_task_begin.req.json'))).toEqual([])
    expect(validate(coreId('task_begin'), 'response', example('core_task_begin.res.json'))).toEqual([])
    expect(validate(coreId('task_begin'), 'response', example('core_task_begin.fail.json'))).toEqual([])
    expect(validate(coreId('context'), 'response', example('core_context.res.json'))).toEqual([])
    expect(validate(coreId('task_end'), 'request', example('core_task_end.req.json'))).toEqual([])
    expect(validate(toolId('case_list_materials'), 'result', example('tool_list.result.json'))).toEqual([])
    expect(validate(toolId('case_read_material'), 'args', example('tool_read.args.json'))).toEqual([])
    expect(validate(toolId('case_read_material'), 'result', example('tool_read.result.json'))).toEqual([])
  })

  it('坏样例被拒', () => {
    expect(validate(toolId('case_calc_sentence'), 'args', example('tool_calc_sentence.args_bad.json')).length).toBeGreaterThan(0)
    expect(validate(coreId('progress'), 'request', { task_id: 'T-1', text: '', model_calls: -1, tool_calls: 0 }).length).toBeGreaterThan(0)
  })

  it('错误信息不带数据内容', () => {
    const errs = validate(coreId('progress'), 'request', { task_id: '机密材料名', text: 1, model_calls: 0, tool_calls: 0 })
    expect(errs.join(' ')).not.toContain('机密材料名')
  })
})
