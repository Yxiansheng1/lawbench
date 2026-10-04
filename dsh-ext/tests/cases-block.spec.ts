// @vitest-environment jsdom
// 取消单独首页后（执行令 1156 第 3 条）：侧栏"案件"一块常显当前案件名；胶囊管理在设置页。
import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { CapsuleSettings } from '../ui/home.tsx'
import { app, caseBlockLabel, setApi, type LawbenchApi } from '../ui/state.ts'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
const fixture = (name: string) => JSON.parse(readFileSync(join(__dirname, '..', 'ui', 'fixtures', name), 'utf8'))
const CASE = fixture('case_recent.json').value.cases[0]
let root: Root | undefined
let box: HTMLDivElement
beforeEach(() => { box = document.createElement('div'); document.body.appendChild(box) })
afterEach(async () => { await act(async () => { root?.unmount() }); root = undefined; box.remove(); setApi(undefined) })

describe('侧栏案件块', () => {
  it('名字常显当前会话所在的案件；没有时写"未选择"', () => {
    const s = { ...app.get(), cases: [CASE], currentRoot: CASE.root }
    expect(caseBlockLabel(s)).toBe(`案件：${CASE.name}`)
    expect(caseBlockLabel({ ...s, currentRoot: null })).toBe('案件：未选择')
    expect(caseBlockLabel({ ...s, currentRoot: 'D:\别处' })).toBe('案件：未选择')
  })
})

describe('设置页的胶囊管理（U-11）', () => {
  it('"管理胶囊"打开排序、改名、隐藏的编辑页', async () => {
    setApi({ getCapsules: async () => fixture('capsules.json'), listSkills: async () => ({ ok: true, value: { skills: [] } }) } as unknown as LawbenchApi)
    root = createRoot(box)
    await act(async () => { root!.render(createElement(CapsuleSettings)) })
    await act(async () => { await Promise.resolve() })
    const btn = [...box.querySelectorAll('button')].find((b) => b.textContent === '管理胶囊')!
    expect(btn.disabled).toBe(false)
    await act(async () => { btn.click() })
    expect(box.textContent).toContain('拖动胶囊或分组调整顺序')
  })
})
