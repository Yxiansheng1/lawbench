// @vitest-environment jsdom
// 对话区拖入、粘贴文件的中文提示（ui\drop-guard.ts）：在 jsdom 里装上守卫，另挂一个仿 DSH 附件视图的 document 冒泡监听，
// 看带文件的拖入 / 粘贴有没有被接住、提示有没有出、我方拖入区和纯文字粘贴是否照常。jsdom 没有 DataTransfer，用同形对象。
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { DROP_TEXT, DSH_COMPOSER_INPUT, installDropGuard, shouldGuardDrag } from '../ui/drop-guard.ts'

let intake = false
let uninstall: () => void
const notices: string[] = []
const dshGot: string[] = []
const dshListener = (e: Event) => { dshGot.push(e.type) }

function page(): { composer: HTMLElement; chat: HTMLElement; zone: HTMLElement; zoneChild: HTMLElement } {
  document.body.innerHTML = `
    <main id="chat"><div data-composer-input="" contenteditable="true"></div></main>
    <aside data-lawbench-drop=""><p id="zone-child">材料</p></aside>`
  return {
    composer: document.querySelector(DSH_COMPOSER_INPUT)!,
    chat: document.getElementById('chat')!,
    zone: document.querySelector('[data-lawbench-drop]')!,
    zoneChild: document.getElementById('zone-child')!,
  }
}

function drag(target: Element, type: string, types: string[] = ['Files']): Event {
  const e = new Event(type, { bubbles: true, cancelable: true })
  Object.defineProperty(e, 'dataTransfer', { value: { types, files: [], dropEffect: 'none' } })
  target.dispatchEvent(e)
  return e
}

function paste(target: Element, fileCount: number): Event {
  const e = new Event('paste', { bubbles: true, cancelable: true })
  Object.defineProperty(e, 'clipboardData', { value: { files: { length: fileCount } } })
  target.dispatchEvent(e)
  return e
}

beforeEach(() => {
  intake = false
  notices.length = 0; dshGot.length = 0
  for (const t of ['dragenter', 'dragover', 'drop', 'paste']) document.addEventListener(t, dshListener)
  uninstall = installDropGuard({ notice: (_t, text) => { notices.push(text) }, intakeActive: () => intake })
})

afterEach(() => {
  uninstall()
  for (const t of ['dragenter', 'dragover', 'drop', 'paste']) document.removeEventListener(t, dshListener)
})

describe('对话区拖入、粘贴文件给中文提示（T17 第一步补）', () => {
  it('拖到对话输入框：接住（DSH 收不到）、给提示', () => {
    const { composer } = page()
    const over = drag(composer, 'dragover')
    const drop = drag(composer, 'drop')
    expect([over.defaultPrevented, drop.defaultPrevented]).toEqual([true, true])
    expect(dshGot).toEqual([])
    expect(notices).toEqual([DROP_TEXT])
  })

  it('拖到对话区别处（DSH 在 document 上收拖入，同样会变成标签）：也接住', () => {
    const { chat } = page()
    drag(chat, 'dragenter'); drag(chat, 'drop')
    expect(dshGot).toEqual([])
    expect(notices).toEqual([DROP_TEXT])
  })

  it('拖到我方材料面板等拖入区：不碰，事件照常往下走', () => {
    const { zoneChild } = page()
    const drop = drag(zoneChild, 'drop')
    expect(drop.defaultPrevented).toBe(false)
    expect(dshGot).toEqual(['drop'])
    expect(notices).toEqual([])
  })

  it('不带文件的拖动（拖文字、拖胶囊）、页面上没有对话输入框、P-5 已接上：都不碰', () => {
    const { composer } = page()
    drag(composer, 'drop', ['text/plain'])
    intake = true
    drag(composer, 'drop')
    intake = false
    document.querySelector(DSH_COMPOSER_INPUT)!.remove()
    drag(document.getElementById('chat')!, 'drop')
    expect(dshGot).toEqual(['drop', 'drop', 'drop'])
    expect(notices).toEqual([])
  })

  it('往对话输入框粘贴文件：接住、给提示；粘贴纯文字、在别处粘贴文件：照常', () => {
    const { composer, chat } = page()
    const p1 = paste(composer, 1)
    expect(p1.defaultPrevented).toBe(true)
    paste(composer, 0)
    paste(chat, 2)
    expect(dshGot).toEqual(['paste', 'paste'])
    expect(notices).toEqual([DROP_TEXT])
  })

  it('卸下后不再接住', () => {
    const { composer } = page()
    uninstall()
    uninstall = () => {}
    drag(composer, 'drop')
    expect(dshGot).toEqual(['drop'])
    expect(notices).toEqual([])
  })

  it('判断函数：四个条件缺一不拦', () => {
    const all = { hasFiles: true, composerPresent: true, inOurZone: false, intakeActive: false }
    expect(shouldGuardDrag(all)).toBe(true)
    expect(shouldGuardDrag({ ...all, hasFiles: false })).toBe(false)
    expect(shouldGuardDrag({ ...all, composerPresent: false })).toBe(false)
    expect(shouldGuardDrag({ ...all, inOurZone: true })).toBe(false)
    expect(shouldGuardDrag({ ...all, intakeActive: true })).toBe(false)
  })

  it('依赖的 DSH 输入框标记还在（DSH 升级时这里会先变红）', () => {
    const file = join(__dirname, '..', '..', 'dsh', 'packages', 'client', 'ui-conversation', 'src', 'client', 'input', 'editor', 'ComposerContentEditable.tsx')
    expect(existsSync(file), `找不到 DSH 源码 ${file}：dsh 子模块没有初始化或换了目录结构，请按 dsh-patches\\PATCHES.md 的核对清单重新确认输入框标记`).toBe(true)
    expect(readFileSync(file, 'utf8')).toContain('data-composer-input')
  })
})
