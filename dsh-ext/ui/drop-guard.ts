// 拖文件进对话区、往对话框粘贴文件时给中文提示，不生成引用标签、不进附件（T17 第一步补，执行令 2026-09-30 09:39 第 2 节）。
// 过渡做法：ui-reference 关掉后，DSH 把拖入的文件做成引用标签却发不出去、也没有提示；P-5 源码补丁落地（候 N36）后
// 对话框拖入改为直接导入案件文件夹，那时 conversationFileIntake 在，本守卫让路（intakeActive）。
// - DSH 的附件视图在 document 上监听拖入（ui-attachment/src/client/drop-events.ts），拖到对话区、左侧栏等处都会变成标签，
//   所以只要页面上有对话输入框，就在 document 捕获阶段先接住带文件的拖入；
// - 我方自己的拖入区（材料面板、首页案件卡片，标 data-lawbench-drop）一律不碰，它们照常导入；
// - 粘贴只看对话输入框里的粘贴，且剪贴板里有文件时才拦，纯文字照常。

/** DSH 对话输入框的标记（ui-conversation 输入框元素上的属性；tests\drop-guard.spec.ts 核对 DSH 源码里仍有它）。 */
export const DSH_COMPOSER_INPUT = '[data-composer-input]'
export const OUR_DROP_ZONE = '[data-lawbench-drop]'
export const DROP_TITLE = '没有加进对话'
export const DROP_TEXT = '请把文件拖到右侧的材料面板或首页的案件卡片导入。'

export interface DropGuardDeps {
  notice(title: string, text: string): void
  /** P-5 的对话框导入在不在；在就不拦。 */
  intakeActive(): boolean
}

type FileTransfer = { types: ArrayLike<string> & Iterable<string>; files?: ArrayLike<File>; dropEffect?: string } | null | undefined

const hasFiles = (dt: FileTransfer): boolean => !!dt && [...dt.types].includes('Files')

/** 这次拖入要不要接住：带文件、页面上有对话输入框、不在我方拖入区里、P-5 不在。 */
export function shouldGuardDrag(f: { hasFiles: boolean; composerPresent: boolean; inOurZone: boolean; intakeActive: boolean }): boolean {
  return f.hasFiles && f.composerPresent && !f.inOurZone && !f.intakeActive
}

/** 装上监听；返回卸载函数。 */
export function installDropGuard(deps: DropGuardDeps): () => void {
  const guarded = (e: Event): boolean => {
    const target = e.target instanceof Element ? e.target : null
    return shouldGuardDrag({
      hasFiles: hasFiles((e as DragEvent).dataTransfer as FileTransfer),
      composerPresent: document.querySelector(DSH_COMPOSER_INPUT) !== null,
      inOurZone: !!target?.closest(OUR_DROP_ZONE),
      intakeActive: deps.intakeActive(),
    })
  }
  // dragenter / dragover 也接住：DSH 不再显示"拖到此处即可添加"，同时允许放下，放下时才能给提示
  const onDragMove = (e: Event): void => {
    if (!guarded(e)) return
    e.preventDefault()
    e.stopPropagation()
  }
  const onDrop = (e: Event): void => {
    if (!guarded(e)) return
    e.preventDefault()
    e.stopPropagation()
    deps.notice(DROP_TITLE, DROP_TEXT)
  }
  const onPaste = (e: Event): void => {
    const target = e.target instanceof Element ? e.target : null
    const data = (e as ClipboardEvent).clipboardData
    const files = data?.files
    if (!target?.closest(DSH_COMPOSER_INPUT) || !files || files.length === 0 || deps.intakeActive()) return
    e.preventDefault()
    e.stopPropagation()
    deps.notice(DROP_TITLE, DROP_TEXT)
    // 剪贴板同时带文字（如从 Excel 复制单元格，会另带一张位图）：只拦文件，文字照常交给 DSH（复核 B-F2）。
    // DSH 的粘贴处理按鸭子类型读 clipboardData（ui-conversation/src/client/input/editor/keymap.ts），
    // 这里派发一个只含文字的 paste；它不带文件，本守卫不会再拦。
    const text = data?.getData('text/plain') ?? ''
    if (text === '') return
    const textOnly = new Event('paste', { bubbles: true, cancelable: true })
    Object.defineProperty(textOnly, 'clipboardData', {
      value: { types: ['text/plain'], items: [], files: { length: 0 }, getData: (type: string) => (type === 'text/plain' ? text : '') },
    })
    target.dispatchEvent(textOnly)
  }
  const events: Array<[string, (e: Event) => void]> = [['dragenter', onDragMove], ['dragover', onDragMove], ['drop', onDrop], ['paste', onPaste]]
  for (const [name, fn] of events) document.addEventListener(name, fn, true)
  return () => { for (const [name, fn] of events) document.removeEventListener(name, fn, true) }
}
