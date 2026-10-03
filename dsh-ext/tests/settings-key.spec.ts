// @vitest-environment jsdom
// 设置页"更换 Key"（T14 第二次实跑派修 3，执行令 1751）：输入新 Key → 调 Host changeKey → 显示测试结果；界面不回显 Key。
import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { ChangeKey } from '../ui/settings.tsx'
import { setApi, type LawbenchApi } from '../ui/state.ts'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
let root: Root | undefined
let box: HTMLDivElement
let sent: string[]
const ok = (message: string) => ({ reachable: true, key_valid: true, latency_ms: 12, route: 'primary', message })

beforeEach(() => { sent = []; box = document.createElement('div'); document.body.appendChild(box) })
afterEach(async () => { await act(async () => { root?.unmount() }); root = undefined; box.remove(); setApi(undefined) })

const button = (text: string) => [...box.querySelectorAll('button')].find((b) => b.textContent === text)!
async function changeTo(key: string) {
  root = createRoot(box)
  await act(async () => { root!.render(createElement(ChangeKey, { onChanged: () => {} })) })
  await act(async () => { button('更换 Key').click() })
  const input = box.querySelector('input[aria-label="新 Key"]') as HTMLInputElement
  expect(input.type).toBe('password')
  const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!
  await act(async () => { set.call(input, key); input.dispatchEvent(new Event('input', { bubbles: true })) })
  await act(async () => { button('保存并测试').click() })
  await act(async () => { await Promise.resolve() })
}

describe('设置页更换 Key', () => {
  it('调 changeKey 后显示两台服务器的测试结果，页面上没有 Key', async () => {
    setApi({ changeKey: async (k: string) => { sent.push(k); return { llm: ok('连接正常，Key 有效'), prep: ok('连接正常'), error: null } } } as unknown as LawbenchApi)
    await changeTo('sk-new-12345678')
    expect(sent).toEqual(['sk-new-12345678'])
    const status = box.querySelector('[role=status]')!.textContent!
    expect(status).toContain('已换成新 Key')
    expect(status).toContain('律所模型服务器：连接正常，Key 有效')
    expect(status).toContain('律所识别服务器：连接正常')
    expect(box.innerHTML).not.toContain('sk-new-12345678')
  })

  it('Key 被判无效：红字显示服务的说明', async () => {
    setApi({ changeKey: async () => ({ llm: { ...ok('Key 无效'), key_valid: false }, prep: ok('连接正常'), error: null }) } as unknown as LawbenchApi)
    await changeTo('sk-bad-12345678')
    const status = box.querySelector('[role=status]') as HTMLElement
    expect(status.textContent).toContain('律所模型服务器：Key 无效')
    expect(status.style.color).not.toBe('')
  })

  it('格式不对：不调 Host', async () => {
    setApi({ changeKey: async (k: string) => { sent.push(k); return { llm: null, prep: null, error: null } } } as unknown as LawbenchApi)
    await changeTo('短')
    expect(sent).toEqual([])
    expect(box.textContent).toContain('Key 格式不对')
  })
})
