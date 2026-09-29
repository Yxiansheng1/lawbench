// 点草稿正文（对话区助手回答）里的出处打开原文（T13 后续项，主编排 06:34 注记裁决走 A：插件内命中测试，不改 DSH 源码）。
// - 只看助手回答那一块（DSH 的 `[data-chat-flow-kind="assistant-step"]`）里的点击，别处一律不碰、不拦；
// - 在 document 的捕获阶段监听，用 caretPositionFromPoint 取点中的文字，按段落整体文字换算位置（出处跨加粗等行内元素也能认）；
// - 不改 DOM：出处下划线用 CSS 自定义高亮（CSS.highlights），不包 span，不和 React 抢节点；
// - 依赖的 DSH 属性名、取值写在下面的常量里，tests\citation.spec.ts 核对 DSH 源码里仍有它们，PATCHES.md 升级核对清单里也记了一行。
// 已知限制：键盘和读屏够不着（不是真按钮），见交付说明。
import { citationAt, citationRanges, DSH_ASSISTANT_KIND, DSH_FLOW_ATTR, resolveCitation, type MaterialLite } from './citation.ts'
import { TABS } from './cases.ts'
import { getNav } from './kit.tsx'
import { app, call, currentCase, notice } from './state.ts'

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

async function openCitation(item: { text: string; name: string; loc: string }): Promise<void> {
  const c = currentCase(app.get())
  if (!c) { notice('没有打开原文', '这个会话不在已打开的案件里。请从首页打开案件后再点出处。'); return }
  const r = await call<{ materials: MaterialLite[] }>('materialsList', { case_id: c.case_id })
  if (!r.ok) { notice('没有打开原文', '读不到本案材料列表，请稍后重试。'); return }
  const v = resolveCitation(item, r.value.materials)
  if (!v.ok) { notice('没有打开原文', v.message); return }
  getNav().openTab(TABS.source, { material_id: v.material.material_id, citation: `〔${item.text}〕` })
}

function onClick(e: MouseEvent): void {
  if (e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return
  const target = e.target instanceof Element ? e.target : null
  if (!target || !target.closest(ASSISTANT_SELECTOR) || target.closest(SKIP_SELECTOR)) return
  const sel = window.getSelection()
  if (sel && !sel.isCollapsed) return // 在选文字，不打扰
  const caret = caretAt(e.clientX, e.clientY)
  if (!caret || !caret.node.parentElement?.closest(ASSISTANT_SELECTOR)) return
  const ch = charUnderPointer(caret.node, caret.offset, e.clientX, e.clientY)
  if (ch === undefined) return
  const block = caret.node.parentElement.closest(BLOCK_SELECTOR) ?? caret.node.parentElement
  const nodes = textNodesOf(block)
  const index = nodes.indexOf(caret.node)
  if (index < 0) return
  const whole = nodes.map((n) => n.data).join('')
  const offset = nodes.slice(0, index).reduce((n, t) => n + t.data.length, 0) + ch
  const hit = citationAt(whole, offset)
  if (hit.kind !== 'item') return // 不是出处，或是〔未找到依据〕〔推断〕：不反应
  e.preventDefault()
  e.stopPropagation()
  void openCitation(hit.item)
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

/** 装上监听；返回卸载函数。 */
export function installCitationClick(): () => void {
  document.addEventListener('click', onClick, true)
  const stopHighlights = startHighlights()
  return () => { document.removeEventListener('click', onClick, true); stopHighlights() }
}
