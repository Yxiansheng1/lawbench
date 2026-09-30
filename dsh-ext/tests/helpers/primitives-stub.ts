// 测试替身：DSH 界面原件包（@deepseek-ai/dsh-client-ui-primitives）只取我方用到的 Button，渲染成普通按钮。
import { createElement, type ButtonHTMLAttributes } from 'react'

export function Button(p: ButtonHTMLAttributes<HTMLButtonElement> & { size?: string; variant?: string }) {
  const { size: _size, variant: _variant, ...rest } = p
  return createElement('button', { type: 'button', ...rest })
}
