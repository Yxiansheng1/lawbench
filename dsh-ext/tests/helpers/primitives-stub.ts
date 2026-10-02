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
