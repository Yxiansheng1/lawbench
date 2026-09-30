// 点草稿正文（对话区助手回答）里的出处打开原文（T13 后续项，主编排 06:34 注记裁决走 A：插件内命中测试，不改 DSH 源码）。
// - 只看助手回答那一块（DSH 的 `[data-chat-flow-kind="assistant-step"]`）里的点击，别处一律不碰、不拦；
// - 在 document 的捕获阶段监听，用 caretPositionFromPoint 取点中的文字，按段落整体文字换算位置（出处跨加粗等行内元素也能认）；
// - 不改对话区的内容：出处下划线用 CSS 自定义高亮（CSS.highlights），不包 span，不和 React 抢节点（只往页面头部加一个样式元素）；
// - 依赖的 DSH 属性名、取值写在下面的常量里，tests\citation.spec.ts 核对 DSH 源码里仍有它们，PATCHES.md 升级核对清单里也记了一行。
// - 取当前案件、读材料列表、打开原文都由调用方注入（index.tsx 接到工作台状态），本文件不接状态，测试可在 DOM 环境里直接装上。
// 已知限制：键盘和读屏够不着（不是真按钮）；双击慢于 300 毫秒时第一下仍会打开原文。见交付说明。
import { citationAt, citationRanges, DSH_ASSISTANT_KIND, DSH_FLOW_ATTR, joinedOffset, openCitation, shouldHandleClick, type OpenDeps } from './citation.ts'

const ASSISTANT_SELECTOR = `[${DSH_FLOW_ATTR}="${DSH_ASSISTANT_KIND}"]`
/** 这些元素里的点击不接手（链接、按钮、代码、输入框各有各的用途）。 */
const SKIP_SELECTOR = 'a,button,pre,code,input,textarea,select,[contenteditable="true"]'
const BLOCK_SELECTOR = 'p,li,td,th,h1,h2,h3,h4,h5,h6,blockquote,dd,dt'
const HIGHLIGHT = 'lawbench-citation'

type CaretDoc = Document & {
  caretPositionFromPoint?: (x: number, y: number) => { offsetNode: Node; offset: number } | null
  caretRangeFromPoint?: (x: number, y: number) => Range | null
}

function caretAt(x: number, y: number): { node: Text; offset: number } | undefined {
  const d = document as CaretDoc
  const pos = d.caretPositionFromPoint?.(x, y)
  if (pos && pos.offsetNode.nodeType === Node.TEXT_NODE) return { node: pos.offsetNode as Text, offset: pos.offset }
  const r = d.caretRangeFromPoint?.(x, y)
  if (r && r.startContainer.nodeType === Node.TEXT_NODE) return { node: r.startContainer as Text, offset: r.startOffset }
  return undefined
}

/** 取光标接口会吸附到最近的文字：确认指针确实压在某个字上（offset 或 offset-1 那个字）。 */
function charUnderPointer(node: Text, offset: number, x: number, y: number): number | undefined {
  for (const o of [offset, offset - 1]) {
    if (o < 0 || o >= node.data.length) continue
    const r = document.createRange()
    r.setStart(node, o); r.setEnd(node, o + 1)
    for (const rect of r.getClientRects()) {
      if (x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom) return o
    }
  }
  return undefined
}

function textNodesOf(block: Element): Text[] {
  const out: Text[] = []
  const w = document.createTreeWalker(block, NodeFilter.SHOW_TEXT)
  for (let n = w.nextNode(); n; n = w.nextNode()) out.push(n as Text)
  return out
}

/** 双击、三击选字时第一下单击不立即打开：等这么久，期间有第二下或选中了文字就作罢（返修 B2）。 */
export const OPEN_DELAY_MS = 300

/** 一次装上的点击处理；pending 是等着打开的那一下（同一时刻至多一个）。 */
function makeClickHandler(deps: OpenDeps): { onClick(e: MouseEvent): void; cancel(): void } {
  let pendingOpen: ReturnType<typeof setTimeout> | undefined
  const cancel = () => { if (pendingOpen !== undefined) { clearTimeout(pendingOpen); pendingOpen = undefined } }
  const onClick = (e: MouseEvent): void => {
    const target = e.target instanceof Element ? e.target : null
    if (e.detail > 1) cancel()
    const sel = window.getSelection()
    if (!shouldHandleClick({
      button: e.button, modifier: e.ctrlKey || e.metaKey || e.shiftKey || e.altKey,
      inAnswer: !!target?.closest(ASSISTANT_SELECTOR), inSkipped: !!target?.closest(SKIP_SELECTOR),
      selectionCollapsed: !sel || sel.isCollapsed, detail: e.detail,
    })) return
    const caret = caretAt(e.clientX, e.clientY)
    if (!caret || !caret.node.parentElement?.closest(ASSISTANT_SELECTOR)) return
    const ch = charUnderPointer(caret.node, caret.offset, e.clientX, e.clientY)
    if (ch === undefined) return
    const block = caret.node.parentElement.closest(BLOCK_SELECTOR) ?? caret.node.parentElement
    const nodes = textNodesOf(block)
    const index = nodes.indexOf(caret.node)
    if (index < 0) return
    const segments = nodes.map((n) => n.data)
    const hit = citationAt(segments.join(''), joinedOffset(segments, index, ch))
    if (hit.kind !== 'item') return // 不是出处，或是〔未找到依据〕〔推断〕：不反应
    e.preventDefault()
    e.stopPropagation()
    const caseAtClick = deps.caseId()
    cancel() // 前一下还在等：以这一下为准，不留两个定时器
    pendingOpen = setTimeout(() => {
      pendingOpen = undefined
      if (window.getSelection()?.isCollapsed === false) return // 这期间选中了文字（双击、三击）：不打开
      if (deps.caseId() !== caseAtClick) return // 这期间换了案件：出处属于原来的案件，不打开
      void openCitation(hit.item, deps)
    }, OPEN_DELAY_MS)
  }
  return { onClick, cancel }
}

/** 给出处加虚下划线（有 CSS.highlights 时）；DOM 有变化时重算，只读不改。 */
function startHighlights(): () => void {
  const reg = (globalThis as { CSS?: { highlights?: Map<string, unknown> } }).CSS?.highlights
  const HighlightCtor = (globalThis as { Highlight?: new (...r: Range[]) => unknown }).Highlight
  if (!reg || !HighlightCtor) return () => {}
  const style = document.createElement('style')
  style.textContent = `::highlight(${HIGHLIGHT}) { text-decoration: underline dotted; text-underline-offset: 3px; }`
  document.head.appendChild(style)
  let timer: ReturnType<typeof setTimeout> | undefined
  const rebuild = () => {
    timer = undefined
    const ranges: Range[] = []
    for (const answer of document.querySelectorAll(ASSISTANT_SELECTOR)) {
      for (const block of answer.querySelectorAll(BLOCK_SELECTOR)) {
        if (block.closest(SKIP_SELECTOR)) continue
        const nodes = textNodesOf(block)
        const whole = nodes.map((n) => n.data).join('')
        for (const [s, t] of citationRanges(whole)) {
          const r = document.createRange()
          let acc = 0
          for (const n of nodes) {
            const len = n.data.length
            if (s >= acc && s <= acc + len) r.setStart(n, s - acc)
            if (t >= acc && t <= acc + len) { r.setEnd(n, t - acc); break }
            acc += len
          }
          ranges.push(r)
        }
      }
    }
    reg.set(HIGHLIGHT, new HighlightCtor(...ranges))
  }
  const schedule = () => { if (timer === undefined) timer = setTimeout(rebuild, 300) }
  const mo = new MutationObserver(schedule)
  mo.observe(document.body, { subtree: true, childList: true, characterData: true })
  schedule()
  return () => { mo.disconnect(); if (timer) clearTimeout(timer); reg.delete(HIGHLIGHT); style.remove() }
}

/** 装上监听；返回卸载函数（卸下时等着打开的那一下也作废）。 */
export function installCitationClick(deps: OpenDeps): () => void {
  const { onClick, cancel } = makeClickHandler(deps)
  document.addEventListener('click', onClick, true)
  const stopHighlights = startHighlights()
  return () => { document.removeEventListener('click', onClick, true); cancel(); stopHighlights() }
}
