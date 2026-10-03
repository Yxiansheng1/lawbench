// 测试替身：DSH 界面原件包（@deepseek-ai/dsh-client-ui-primitives）只取我方用到的 Button、Modal，渲染成普通元素。
import { createElement, type ButtonHTMLAttributes, type ReactNode } from 'react'

export function Button(p: ButtonHTMLAttributes<HTMLButtonElement> & { size?: string; variant?: string }) {
  const { size: _size, variant: _variant, ...rest } = p
  return createElement('button', { type: 'button', ...rest })
}

/** 对话框：open 时就地渲染标题、内容、底部按钮（不做浮层与焦点管理）。 */
export function Modal(p: { open: boolean; title?: ReactNode; footer?: ReactNode; children?: ReactNode; onClose?: () => void; closeLabel?: string }) {
  if (!p.open) return null
  return createElement('div', { role: 'dialog', 'aria-label': typeof p.title === 'string' ? p.title : undefined },
    createElement('h2', null, p.title), p.children, createElement('footer', null, p.footer))
}

/** Markdown 正文：不解析 Markdown，整段按 inlineMarks 拆开，出处画成 button（与真组件一样是可点的按钮，带读屏标签）。 */
export function MarkdownText(p: { text: string; inlineMarks?: { split(v: string): ReadonlyArray<string | { text: string; label: string; open: () => void }> | undefined } }) {
  const parts = p.inlineMarks?.split(p.text) ?? [p.text]
  return createElement('div', { 'data-markdown': '' }, ...parts.map((x, i) => typeof x === 'string' ? x
    : createElement('button', { key: i, type: 'button', 'aria-label': x.label, onClick: x.open }, x.text)))
}
