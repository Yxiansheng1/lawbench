// P-5 的我方一半（Spec D13、U-12；T13 执行令 Q3）：拖到对话框、粘贴、选择的文件不作为聊天附件，而是导入当前案件文件夹。
// DSH 一半是源码补丁（ui-conversation 的 addFiles 先问登记的导入钩子，并去掉"+"按钮），补丁提供服务 conversationFileIntake。
// 没打补丁时这个服务不存在，本文件什么都不做。
// - 有本机路径的文件、文件夹：弹导入确认框（选子文件夹），确认后 /api/materials/import；
// - 粘贴的截图（没有本机路径）：读成字节交给 Host 的 importPastedImage（Host 存临时文件后导入 02案件材料/粘贴图片，不论成败删临时文件）；
//   同一次粘贴还带着非空文字时不导入（T17 第二步返修 B-F2：Excel、WPS 复制单元格时剪贴板里常同时有文字和一张截图，
//   律师要的是文字，文字照常贴进输入框）。
import { startImport } from './cases.ts'
import { errorText } from './format.ts'
import { getNav } from './kit.tsx'
import { app, call, notice, samePath, type CaseRef } from './state.ts'

export type IntakeHook = (sessionId: string, files: readonly File[], directories: ReadonlySet<File>) => string | null | undefined

/** 最近一次粘贴：时刻和剪贴板里有没有非空文字。捕获阶段记下，先于 DSH 输入框的粘贴处理。 */
let lastPaste = { at: 0, hasText: false }

/** 在窗口上（捕获阶段）记下每次粘贴是否带文字；返回撤销函数。 */
export function installPasteTextWatch(target: Window = window): () => void {
  const onPaste = (e: Event) => {
    const text = (e as ClipboardEvent).clipboardData?.getData('text/plain') ?? ''
    lastPaste = { at: Date.now(), hasText: text.trim() !== '' }
  }
  target.addEventListener('paste', onPaste, true)
  return () => target.removeEventListener('paste', onPaste, true)
}

/** 这一刻的粘贴（1 秒内）是否带着非空文字。 */
export const pasteCarriedText = (now: number = Date.now()): boolean => lastPaste.hasText && now - lastPaste.at < 1000

async function toBase64(file: File): Promise<string> {
  const bytes = new Uint8Array(await file.arrayBuffer())
  let s = ''
  for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode(...bytes.subarray(i, i + 0x8000))
  return btoa(s)
}

/**
 * 生成导入钩子。
 * @param cwdOf - 会话 id → 工作目录（案件文件夹）。
 * @param pasteHadText - 这批文件是否来自一次带文字的粘贴（默认看 installPasteTextWatch 记下的）。
 */
export function makeIntakeHook(cwdOf: (sessionId: string) => string | undefined, pasteHadText: () => boolean = () => pasteCarriedText()): IntakeHook {
  return (sessionId, files) => {
    const root = cwdOf(sessionId)
    const caseRef: CaseRef | undefined = root ? app.get().cases.find((c) => samePath(c.root, root)) : undefined
    // 不在已登记案件里的会话（如默认工作区）：不接手也不能按附件处理——拒绝并说明
    if (!caseRef) return '材料只能导入到案件里。请先从首页打开案件，再把文件拖进来。'
    const nav = getNav()
    const withPath = files.map((f) => ({ f, path: nav.pathFor(f) }))
    const paths = withPath.filter((x) => x.path).map((x) => x.path)
    // 带文字的粘贴里的位图（没有本机路径）：不导入，也不作为附件（钩子照样接手），文字由输入框照常贴进去
    const pasted = pasteHadText() ? [] : withPath.filter((x) => !x.path).map((x) => x.f)
    if (paths.length) startImport(caseRef, paths, '对话框')
    for (const file of pasted) {
      if (!/^image\/(png|jpeg)$/.test(file.type)) { notice('没有导入', '粘贴的内容不是 PNG 或 JPEG 图片。要导入文件，请把文件拖进来或点材料面板的"导入文件"。'); continue }
      void toBase64(file).then(async (b64) => {
        const r = await call<{ copied: Array<{ to: string }> }>('importPastedImage', { case_id: caseRef.case_id, image_base64: b64 })
        if (!r.ok) { notice('粘贴的图片没有导入', errorText(r.error)); return }
        notice('已导入粘贴的图片', `已放进"${caseRef.name}"的 02案件材料/粘贴图片。`, r.value.copied.map((c) => c.to))
        window.dispatchEvent(new CustomEvent('lawbench:materials-changed', { detail: caseRef.case_id }))
      })
    }
    return null
  }
}
