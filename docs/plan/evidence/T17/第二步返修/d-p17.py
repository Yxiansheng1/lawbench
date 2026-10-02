# P-17 增补（T17 第二步返修，1516 令小项①、B-F9、A-P3-2）：用量页和强制更新窗口也不交给系统浏览器；
# 中文网址比较前先 decodeURI；注释里的字面 \n 改成真换行。用法：python d-p17.py <dsh 根目录>
import io, sys
root = sys.argv[1].rstrip('\\/') + '/'


def edit(name, pairs):
    p = root + name
    s = io.open(p, encoding='utf-8', newline='').read()
    nl = '\r\n' if '\r\n' in s else '\n'
    s = s.replace('\r\n', '\n')
    for a, b in pairs:
        assert s.count(a) == 1, (name, a[:80], s.count(a))
        s = s.replace(a, b)
    io.open(p, 'w', encoding='utf-8', newline='').write(s.replace('\n', nl))


# ① 用量页（platform-view）：新窗口一律拒绝，不再交给系统浏览器
edit('apps/desktop/src/platform-view.ts', [
    ("import { WebContentsView, session, shell, type Session, type View, type WebFrameMain } from 'electron'",
     "import { WebContentsView, session, type Session, type View, type WebFrameMain } from 'electron'"),
    ("""    // External payment and documentation pages open without the embedded session or token.
    view.webContents.setWindowOpenHandler(({ url }) => {
      const destination = new URL(url)
      if (destination.protocol === 'https:' && !destination.username && !destination.password) {
        void shell.openExternal(url).catch(() => {
          // An OS browser-launch failure leaves the embedded page available for retry.
        })
      }
      return { action: 'deny' }
    })""", """    // lawbench P-17: nothing leaves for the system browser; new windows are refused outright.
    view.webContents.setWindowOpenHandler(() => ({ action: 'deny' }))"""),
])
edit('apps/desktop/tests/platform-view.spec.ts', [
    ("""it('opens HTTPS payment links in the system browser without an embedded child window', async () => {
  const { manager, owner } = setup()
  await manager.open(owner, 'top-up', bounds)
  const handler = view().webContents.setWindowOpenHandler.mock.calls[0]![0] as (details: { url: string }) => { action: string }
  expect(handler({ url: 'https://payment.example/order' })).toEqual({ action: 'deny' })
  expect(state.openExternal).toHaveBeenCalledWith('https://payment.example/order')
  vi.mocked(state.openExternal).mockClear()
  for (const url of ['file:///tmp/test', 'javascript:alert(1)', 'https://user:pass@payment.example/order']) {""",
     """it('lawbench P-17: refuses every new window without handing it to the system browser', async () => {
  const { manager, owner } = setup()
  await manager.open(owner, 'top-up', bounds)
  const handler = view().webContents.setWindowOpenHandler.mock.calls[0]![0] as (details: { url: string }) => { action: string }
  for (const url of ['https://payment.example/order', 'file:///tmp/test', 'javascript:alert(1)', 'https://user:pass@payment.example/order']) {"""),
])

# ② 强制更新窗口："打开下载页"不再拉起系统浏览器，按打开失败处理（界面照旧提供复制地址）
edit('apps/desktop/src/mandatory-update-window.ts', [
    ("import { app, BrowserWindow, clipboard, ipcMain, shell, type IpcMainInvokeEvent } from 'electron'",
     "import { app, BrowserWindow, clipboard, ipcMain, type IpcMainInvokeEvent } from 'electron'"),
    ("""      else await shell.openExternal(url)""",
     """      // lawbench P-17: the download page never opens in the system browser; the page action reports
      // failure and the modal keeps offering to copy the address
      else throw new Error('lawbench: external pages are not opened')"""),
])
edit('apps/desktop/tests/mandatory-update-window.spec.ts', [
    ("""it('offers copy immediately while browser opening is pending and keeps navigation failures separate', async () => {
  const f = setup()
  const opened = Promise.withResolvers<undefined>()
  native.open.mockReturnValueOnce(opened.promise)
  native.read.mockResolvedValue('https://downloads.example.com/desktop')
  const pending = f.action('page')
  expect(f.view().navigation).toEqual({ page: 'requested' })
  await f.action('copy')
  expect(f.view().navigation).toEqual({ page: 'requested', copy: 'copied' })
  opened.reject(new Error('browser rejected'))
  await pending
  expect(f.view().navigation).toEqual({ page: 'failed', copy: 'copied' })
  expect(f.view().error).toBeUndefined()
  expect(f.view().policy.blocking).toBe(true)
})""", """it('lawbench P-17: the page action never opens the system browser and reports failure; copy still works', async () => {
  const f = setup()
  native.read.mockResolvedValue('https://downloads.example.com/desktop')
  await f.action('page')
  expect(f.view().navigation).toEqual({ page: 'failed' })
  await f.action('copy')
  expect(f.view().navigation).toEqual({ page: 'failed', copy: 'copied' })
  expect(native.open).not.toHaveBeenCalled()
  expect(f.view().error).toBeUndefined()
  expect(f.view().policy.blocking).toBe(true)
})"""),
    ("""  await expect(f.action('page')).rejects.toThrow(/no allowed/)
  expect(native.open).toHaveBeenCalledTimes(1)""", """  await expect(f.action('page')).rejects.toThrow(/no allowed/)
  expect(native.open).not.toHaveBeenCalled() // lawbench P-17"""),
])

# ③ render.tsx：注释里的字面 \n；中文网址比较前 decodeURI
edit('packages/client/ui-primitives/src/markdown/render.tsx', [
    (" * External link and image destinations pass a protocol allowlist (lawbench\\n * P-17: allowlisted links render as plain, copyable text, never anchors); settled",
     " * External link and image destinations pass a protocol allowlist (lawbench\n * P-17: allowlisted links render as plain, copyable text, never anchors); settled"),
    ("""/** The text already is the address (GFM literals `www.x`, `a@b` gain a scheme in the href). */
function showsAddress(text: string, href: string): boolean {
  return [text, `http://${text}`, `https://${text}`, `mailto:${text}`].includes(href)
}""", """/** A percent-encoded address as the lawyer reads it (non-ASCII paths); undecodable input stays as is. */
function decodedAddress(value: string): string {
  try { return decodeURI(value) } catch { return value }
}

/**
 * The text already is the address (GFM literals `www.x`, `a@b` gain a scheme in the href). The href
 * is percent-encoded (non-ASCII paths), so both sides compare decoded.
 */
function showsAddress(text: string, href: string): boolean {
  const target = decodedAddress(href)
  return [text, `http://${text}`, `https://${text}`, `mailto:${text}`].some(candidate => decodedAddress(candidate) === target)
}"""),
    ("  return <Fragment key={key}>{children}{`（${safeHref}）`}</Fragment>",
     "  return <Fragment key={key}>{children}{`（${decodedAddress(safeHref)}）`}</Fragment>"),
])
edit('packages/client/ui-primitives/tests/markdown.client.spec.tsx', [
    ("""  it('lawbench P-17: external links carry no site mark or globe (they are text, not anchors)', () => {""",
     """  it('lawbench P-17: an address with non-ASCII characters is shown once, not followed by its encoded form', () => {
    const { container } = render(<MarkdownText text={'见 http://例子.测试/路径 与 [说明](https://例子.测试/资料/一)'} />)
    expect(container.textContent).toBe('见 http://例子.测试/路径 与 说明（https://例子.测试/资料/一）')
    expect(container.querySelector('a')).toBeNull()
  })

  it('lawbench P-17: external links carry no site mark or globe (they are text, not anchors)', () => {"""),
])
print('P-17 delta ok')
