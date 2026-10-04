// 设置页"律师工作台"一节的草稿与离开确认（令 1609 第 2 条，用户："回下滑保存按钮就会滑上去，律师会以为保存成功直接离开"）。
// 草稿放在界面状态里（不放组件里）：DSH 的设置是弹窗，切到别的一节、关掉设置时这一节会卸下，草稿不能跟着丢。
// 带着未保存的修改卸下（切到别的页面）或关窗口时弹"修改尚未保存，离开将丢失"：保存 / 不保存 / 取消；
// 取消 = 草稿留着，并尝试重新打开设置（DSH 的设置快捷键 Ctrl+,），回到设置时修改还在。
import { createStore } from './store.ts'
import { app, lb, pushDialog } from './state.ts'
import { lawyerMessage } from './format.ts'

export interface SettingsDraft<T = Record<string, unknown>> {
  /** 服务那边此刻的设置（最近一次读到或保存成功的）。 */
  loaded: T | null
  /** 页面上正在改的。 */
  draft: T | null
  /** 最近一次保存成功的时刻（保存条显示"已保存 HH:mm"两秒）。 */
  savedAt: number | null
}

export const settingsDraft = createStore<SettingsDraft>({ loaded: null, draft: null, savedAt: null })

export const isDirty = (s: SettingsDraft = settingsDraft.get()): boolean =>
  !!s.draft && !!s.loaded && JSON.stringify(s.draft) !== JSON.stringify(s.loaded)

export const UNSAVED_TITLE = '修改尚未保存'
export const UNSAVED_TEXT = '设置里"律师工作台"一节的修改还没有保存，离开将丢失。'
export type UnsavedChoice = 'save' | 'discard' | 'cancel'

/** 弹"修改尚未保存"三选一。 */
export function askUnsaved(): Promise<UnsavedChoice> {
  return new Promise((resolve) => pushDialog({ kind: 'unsaved', title: UNSAVED_TITLE, text: UNSAVED_TEXT, resolve }))
}

/** 保存草稿（服务器地址、OCR 开关原样带回，不在这里改）；返回出错说明，成功为 null。 */
export async function saveDraft(): Promise<string | null> {
  const { loaded, draft } = settingsDraft.get()
  if (!loaded || !draft) return null
  try {
    await lb().putSettings({ ...draft, servers: loaded.servers, ocr_fallback_llm: loaded.ocr_fallback_llm })
    settingsDraft.set({ loaded: structuredClone(draft), draft, savedAt: Date.now() })
    const d = draft as { defaults?: unknown; skill_presets?: unknown; profile?: { lawyer_name?: string | null } }
    app.set((st) => ({ ...st, defaults: d.defaults as never, presets: d.skill_presets as never, lawyerName: d.profile?.lawyer_name ?? null }))
    return null
  } catch (e) {
    return lawyerMessage((e as Error).message)
  }
}

export function discardDraft(): void {
  const { loaded } = settingsDraft.get()
  settingsDraft.set((s) => ({ ...s, draft: loaded ? structuredClone(loaded) : null }))
}

/** 重新打开设置：发 DSH 设置快捷键（Ctrl+,）。打不开也没关系，草稿留着，下次进设置还在。 */
export function reopenSettings(): void {
  try { document.dispatchEvent(new KeyboardEvent('keydown', { key: ',', code: 'Comma', ctrlKey: true, bubbles: true })) } catch { /* 草稿仍在 */ }
}

/**
 * 这一节卸下时（切到别的页面、关掉设置）：有未保存的修改就问。
 * @returns 用户的选择（没有修改时为 null）。
 */
export async function onLeaveSettings(): Promise<UnsavedChoice | null> {
  if (!isDirty()) return null
  const choice = await askUnsaved()
  if (choice === 'save') {
    const err = await saveDraft()
    if (err) { pushDialog({ kind: 'notice', title: '没有保存成功', text: `${err}。修改还在，回到设置里再保存一次。` }) }
  } else if (choice === 'discard') discardDraft()
  else reopenSettings()
  return choice
}

let closingAnyway = false
/**
 * 关窗口时（beforeunload）：有未保存的修改先拦下，弹三选一；保存或不保存之后再关。返回解除函数。
 * Electron 里 beforeunload 设了 returnValue 就不关、也不弹系统框，所以由我们自己的弹框接着问。
 */
export function installUnloadGuard(win: Window = window): () => void {
  const onBefore = (e: BeforeUnloadEvent) => {
    if (closingAnyway || !isDirty()) return
    e.preventDefault()
    e.returnValue = ''
    void askUnsaved().then(async (choice) => {
      if (choice === 'cancel') return
      if (choice === 'save' && await saveDraft()) return // 没存成：不关，修改还在
      if (choice === 'discard') discardDraft()
      closingAnyway = true
      win.close()
    })
  }
  win.addEventListener('beforeunload', onBefore)
  return () => win.removeEventListener('beforeunload', onBefore)
}
