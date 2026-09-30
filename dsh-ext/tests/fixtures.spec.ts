import { readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { validate } from '../shared/contracts.ts'

// 界面假数据（虚构）：每个文件对应一个 /api 契约的请求或响应，按契约校验。
const dir = join(__dirname, '..', 'ui', 'fixtures')
const CASE_ID = '8c5e2a17-4b9d-4f36-a1c8-6d2e9b073f54'
const files = readdirSync(dir).filter((f) => f.endsWith('.json')).sort()

type Kind = 'request' | 'response'
function classify(file: string): { name: string; def: Kind } {
  const base = file.replace(/\.json$/, '')
  if (base.endsWith('.req')) return { name: base.slice(0, -4), def: 'request' }
  if (base.endsWith('.fail')) return { name: base.slice(0, -5), def: 'response' }
  return { name: base, def: 'response' }
}
const load = (f: string): { text: string; data: any } => {
  const text = readFileSync(join(dir, f), 'utf8')
  return { text, data: JSON.parse(text) }
}

describe('界面假数据', () => {
  it('目录里有假数据文件', () => {
    expect(files.length).toBeGreaterThanOrEqual(23)
  })

  for (const f of files) {
    const { name, def } = classify(f)
    it(`${f} 符合 api/${name} 的 ${def}`, () => {
      const { text, data } = load(f)
      expect(text.charCodeAt(0)).not.toBe(0xfeff)
      expect(text).not.toContain('\r')
      expect(validate(`lawbench://contracts/api/${name}.schema.json`, def, data)).toEqual([])
      if (f.endsWith('.fail.json')) expect(data.ok).toBe(false)
      else if (def === 'response') expect(data.ok).toBe(true)
    })
  }

  it('每个成功响应文件都齐全', () => {
    const need = ['case_open', 'case_recent', 'materials_scan', 'materials_import', 'materials_list', 'ocr_submit', 'ocr_list', 'ocr_cancel', 'task_create', 'task_current', 'pipeline_run', 'pipeline_status', 'pipeline_cancel', 'tasks_list', 'redline', 'wiki_suggestions', 'outputs_confirm', 'outputs_list', 'source', 'search', 'capsules', 'capsules_reset', 'archive_build', 'invoice_run', 'retainer_driver']
    for (const n of need) expect(files).toContain(`${n}.json`)
  })

  it('ocr_submit 请求不去水印', () => {
    expect(load('ocr_submit.req.json').data.dewatermark).toBe(false)
  })

  it('凡带 case_id 的，都是同一个虚构案件', () => {
    for (const f of files) {
      const { data } = load(f)
      const id = data?.value?.case_id ?? data?.case_id
      if (id !== undefined) expect(id, f).toBe(CASE_ID)
    }
  })

  it('材料、识别任务、任务编号互相对得上', () => {
    const ids = new Set<string>(load('materials_list.json').data.value.materials.map((m: any) => m.material_id))
    for (const j of load('ocr_list.json').data.value.jobs) expect(ids.has(j.material_id), j.material_id).toBe(true)
    expect(ids.has(load('ocr_submit.req.json').data.material_id)).toBe(true)
    expect(ids.has(load('search.json').data.value.hits[0].material_id)).toBe(true)
    const tasks = new Set<string>(load('tasks_list.json').data.value.tasks.map((t: any) => t.task_id))
    for (const s of load('wiki_suggestions.json').data.value.suggestions) expect(tasks.has(s.task_id), s.task_id).toBe(true)
    expect(tasks.has(load('pipeline_run.json').data.value.task_id)).toBe(true)
    // task_create 的编号不查：契约 1.2 起它是"当前选择"的编号，发消息时服务另复制出新编号执行，不会出现在任务列表（T13 返修小项①）
  })

  it('材料列表覆盖各种状态', () => {
    const ms = load('materials_list.json').data.value.materials
    expect(ms.length).toBeGreaterThanOrEqual(6)
    expect(ms.length).toBeLessThanOrEqual(10)
    const statuses = new Set(ms.map((m: any) => m.status))
    for (const s of ['parsed', 'needs_ocr', 'ocr_running', 'failed', 'source_deleted']) expect(statuses.has(s), s).toBe(true)
    expect(ms.some((m: any) => m.type === 'xlsx' && m.unit === 'cell')).toBe(true)
    expect(ms.some((m: any) => m.error)).toBe(true)
  })

  it('task_create 请求的入口胶囊存在于默认胶囊表', () => {
    const caps = load('capsules.json').data.value
    const ids = caps.groups.flatMap((g: any) => g.items.map((i: any) => i.id))
    expect(ids).toContain(load('task_create.req.json').data.entry)
    expect(load('capsules.req.json').data).toEqual(caps)
  })

  it('不含疑似密钥的 sk- 片段', () => {
    for (const f of files) expect(load(f).text, f).not.toContain('sk-')
  })
})
