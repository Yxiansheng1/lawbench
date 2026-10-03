// DSH 共享模块表里的界面组件库（packages/client/web/src/seed.ts）。运行时由 DSH 提供，这里只给宽松的类型，
// 真实签名见 dsh\packages\client\ui-primitives\src\（Button.tsx、Modal.tsx、Input.tsx 等）。
declare module '@deepseek-ai/dsh-client-ui-primitives' {
  import type { ComponentType, ReactNode } from 'react'
  type Loose = ComponentType<any>
  export const Button: ComponentType<{ variant?: 'primary' | 'ghost' | 'outline' | 'toolbar'; size?: 'md' | 'sm'; icon?: ReactNode; children?: ReactNode; [k: string]: unknown }>
  export const Modal: ComponentType<{
    open: boolean; onClose: () => void; title?: ReactNode; closeLabel?: string; description?: ReactNode
    children?: ReactNode; footer?: ReactNode; className?: string; contentClassName?: string; headless?: boolean
  }>
  /** P-16：settled 文字里的可点片段（出处）；我方画对话区草稿时用（T14 派修 2）。 */
  export const MarkdownText: ComponentType<{
    text: string; streaming?: boolean; variant?: 'body' | 'compact'
    labels: { code: { copyLabel: string; copiedLabel: string }; footnotes: string }
    inlineMarks?: { split(value: string): ReadonlyArray<string | { text: string; label: string; open: () => void }> | undefined }
  }>
  export const Input: Loose
  export const Checkbox: Loose
  export const Switch: Loose
  export const SegmentedTabs: Loose
  export const Tag: Loose
  export const StateDot: Loose
  export const Toast: Loose
}
