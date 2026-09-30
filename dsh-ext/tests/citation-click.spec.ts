// @vitest-environment jsdom
// 出处点击的 DOM 层（ui\citation-click.ts）：在 jsdom 里装上监听，发真的 click 事件。
// jsdom 不做排版：取光标接口（caretPositionFromPoint）和字的位置（Range.getClientRects）由各用例指定。
import { installCitationClick, OPEN_DELAY_MS } from '../ui/citation-click.ts'
import { DSH_ASSISTANT_KIND, DSH_FLOW_ATTR, type MaterialLite, type OpenDeps } from '../ui/citation.ts'

const MATERIALS: MaterialLite[] = [
  { material_id: 'M0001', name: '借款合同', unit: 'page', unit_count: 6, status: 'parsed' },
  { material_id: 'M0003', name: '委托代理合同', unit: 'para', unit_count: 42, status: 'parsed' },
]

/** 下一次点击时取光标接口返回的位置；pointerOnChar=false 表示指针没压在字上（点在行尾空白处）。 */
let caret: { offsetNode: Node; offset: number } | null = null
let pointerOnChar = true
let caseId: string | undefined
let uninstall: () => void
const opened: Array<[string, string]> = []
const notices: string[] = []

const deps: OpenDeps = {
  caseId: () => caseId,
  materials: async () => MATERIALS,
  notice: (_t, text) => { notices.push(text) },
  openSource: (id, citation) => { opened.push([id, citation]) },
}

function answer(html: string): HTMLElement {
  const box = document.createElement('div')
  box.setAttribute(DSH_FLOW_ATTR, DSH_ASSISTANT_KIND)
  box.innerHTML = html
  document.body.appendChild(box)
  return box
}

/** 指向 node 的第 offset 个字并点一下。 */
function clickAt(node: Node, offset: number, detail = 1, target: Element = node.parentElement ?? document.body): MouseEvent {
  caret = { offsetNode: node, offset }
  const e = new MouseEvent('click', { bubbles: true, cancelable: true, detail, button: 0, clientX: 5, clientY: 5 })
  target.dispatchEvent(e)
  return e
}

async function waitOpen(): Promise<void> {
  await vi.advanceTimersByTimeAsync(OPEN_DELAY_MS)
  await Promise.resolve()
}

beforeEach(() => {
  vi.useFakeTimers()
  document.body.innerHTML = ''
  caret = null; pointerOnChar = true; caseId = 'C1'
  opened.length = 0; notices.length = 0
  ;(document as unknown as { caretPositionFromPoint: () => unknown }).caretPositionFromPoint = () => caret
  Range.prototype.getClientRects = function () {
    const rects = pointerOnChar ? [{ left: 0, right: 10, top: 0, bottom: 10 }] : []
    return rects as unknown as DOMRectList
  }
  window.getSelection()?.removeAllRanges()
  uninstall = installCitationClick(deps)
})

afterEach(() => {
  uninstall()
  vi.useRealTimers()
})

describe('出处点击（DOM 层）', () => {
  it('点中出处：等 300 毫秒后打开对应材料，并拦下这次点击', async () => {
    const box = answer('<p>依据〔借款合同 第2页〕认定。</p>')
    const text = box.querySelector('p')!.firstChild!
    const e = clickAt(text, 5)
    expect(e.defaultPrevented).toBe(true)
    await vi.advanceTimersByTimeAsync(OPEN_DELAY_MS - 1)
    expect(opened).toEqual([])
    await waitOpen()
    expect(opened).toEqual([['M0001', '〔借款合同 第2页〕']])
  })

  it('出处跨加粗：点在加粗里的字也按整段认出同一处', async () => {
    const box = answer('<p>见〔借款合同 第2页〕、〔委托代理合同 <strong>第3</strong>段〕。</p>')
    const bold = box.querySelector('strong')!.firstChild!
    clickAt(bold, 1)
    await waitOpen()
    expect(opened).toEqual([['M0003', '〔委托代理合同 第3段〕']])
  })

  it('助手回答块以外、链接里、〔推断〕上、指针没压在字上：都不接手', async () => {
    const outside = document.createElement('p')
    outside.textContent = '〔借款合同 第2页〕'
    document.body.appendChild(outside)
    const e1 = clickAt(outside.firstChild!, 2)
    const box = answer('<p><a href="#">〔借款合同 第2页〕</a>另见〔推断〕</p>')
    const e2 = clickAt(box.querySelector('a')!.firstChild!, 2)
    const e3 = clickAt(box.querySelector('p')!.lastChild!, 3)
    pointerOnChar = false
    const inner = answer('<p>〔借款合同 第2页〕</p>').querySelector('p')!.firstChild!
    const e4 = clickAt(inner, 2)
    pointerOnChar = true
    const e5 = clickAt(inner, 2, 1, outside) // 点到的元素在回答块外（如盖在上面的浮层），光标接口却落进回答里
    await waitOpen()
    expect([e1, e2, e3, e4, e5].map((e) => e.defaultPrevented)).toEqual([false, false, false, false, false])
    expect(opened).toEqual([])
  })

  it('等待期间换了案件：不打开（F1）', async () => {
    const text = answer('<p>〔借款合同 第2页〕</p>').querySelector('p')!.firstChild!
    clickAt(text, 2)
    caseId = 'C2'
    await waitOpen()
    expect(opened).toEqual([])
    expect(notices).toEqual([])
  })

  it('连点两处：只按后一下打开一次，前一下的定时器已清掉（F3）', async () => {
    const box = answer('<p>〔借款合同 第2页〕和〔委托代理合同 第3段〕</p>')
    const text = box.querySelector('p')!.firstChild!
    clickAt(text, 2)
    await vi.advanceTimersByTimeAsync(100)
    clickAt(text, 13)
    await waitOpen()
    await waitOpen()
    expect(opened).toEqual([['M0003', '〔委托代理合同 第3段〕']])
  })

  it('读材料列表期间换了案件：不打开（F1，openCitation 里再核一次）', async () => {
    const text = answer('<p>〔借款合同 第2页〕</p>').querySelector('p')!.firstChild!
    const slow = { ...deps, materials: async () => { caseId = 'C2'; return MATERIALS } }
    uninstall()
    uninstall = installCitationClick(slow)
    clickAt(text, 2)
    await waitOpen()
    expect(opened).toEqual([])
    expect(notices).toEqual([])
  })

  it('卸下插件后，等着的那一下不再打开（F3）', async () => {
    const text = answer('<p>〔借款合同 第2页〕</p>').querySelector('p')!.firstChild!
    clickAt(text, 2)
    uninstall()
    uninstall = () => {}
    await waitOpen()
    expect(opened).toEqual([])
  })

  it('双击（第二下）或期间选中了文字：不打开', async () => {
    const text = answer('<p>〔借款合同 第2页〕</p>').querySelector('p')!.firstChild!
    clickAt(text, 2)
    clickAt(text, 2, 2)
    await waitOpen()
    expect(opened).toEqual([])
    clickAt(text, 2)
    window.getSelection()!.selectAllChildren(text.parentElement!)
    await waitOpen()
    expect(opened).toEqual([])
  })
})
