# P-9 增补（T17 第二步返修 B-F7、A-P3-3/B-F6、A-P3-4）：主窗口不开 webview、侧栏浏览器的 IPC 不注册、关拼写检查；
# 协议白名单去掉 chrome:、chrome-extension:；file: 只放行本应用 renderer 目录里的本机文件（首次配置窗口用 loadFile 打开它），
# 其余本机文件和 file://主机/共享 一律拒绝；about: 写明为什么留。用法：python d-p9.py <dsh 根目录>
import io, sys
root = sys.argv[1].rstrip('\\/') + '/apps/desktop/'


def edit(name, pairs):
    p = root + name
    s = io.open(p, encoding='utf-8', newline='').read()
    nl = '\r\n' if '\r\n' in s else '\n'
    s = s.replace('\r\n', '\n')
    for a, b in pairs:
        assert s.count(a) == 1, (name, a[:80], s.count(a))
        s = s.replace(a, b)
    io.open(p, 'w', encoding='utf-8', newline='').write(s.replace('\n', nl))


edit('src/main.ts', [
    ("""      webSecurity: true,
      webviewTag: primary,
      devTools: true,
    },
  })""", """      webSecurity: true,
      // lawbench P-9: no <webview> in any window (the sidebar browser's guest would sit outside the
      // default-session request filter), and no spellchecker (it fetches dictionaries from the network).
      webviewTag: false,
      spellcheck: false,
      devTools: true,
    },
  })"""),
    ("""  ipcMain.handle(DESKTOP_IPC.browserAcquire, (event, workspace: unknown) => {
    assertProductSender(event)
    return browserGuests.acquire(event.sender, workspace)
  })
  ipcMain.handle(DESKTOP_IPC.browserRelease, (event, lease: unknown) => {
    assertProductSender(event)
    return browserGuests.release(event.sender, lease)
  })
""", """  // lawbench P-9: the sidebar browser channel (browserAcquire / browserRelease) is not registered: a
  // renderer script could otherwise open a separate-partition webview outside the request filter.
  void browserGuests
"""),
    ("""    callback({ cancel: !lawbenchRequestAllowed(details.url, hostUrl) })""",
     """    callback({ cancel: !lawbenchRequestAllowed(details.url, hostUrl, join(app.getAppPath(), 'renderer')) })"""),
])
edit('src/lawbench-request-policy.ts', [
    ("""/** Non-network schemes that never leave the machine. */
const LOCAL_SCHEMES = new Set(['dsh-app:', 'data:', 'blob:', 'devtools:', 'file:', 'chrome:', 'chrome-extension:', 'about:'])""",
     """import { fileURLToPath } from 'node:url'
import { resolve, sep } from 'node:path'

/**
 * Non-network schemes the application itself uses, none of which leaves the machine:
 * `dsh-app:` the bundled UI; `data:` / `blob:` inline and in-memory resources the renderer builds;
 * `devtools:` the developer tools window; `about:` the `about:blank` a frame or window starts on.
 * `chrome:` / `chrome-extension:` are not listed (no internal pages or extensions are used).
 * `file:` is handled separately: only the application's own renderer files (the first-run window
 * is loaded from there with `loadFile`), never other local files or `file://host/share` (SMB).
 */
const LOCAL_SCHEMES = new Set(['dsh-app:', 'data:', 'blob:', 'devtools:', 'about:'])

/** Whether a `file:` URL names a local file inside the application's renderer directory. */
function appFile(target: URL, appFiles: string | undefined): boolean {
  if (appFiles === undefined || target.host !== '') return false
  let path: string
  try { path = resolve(fileURLToPath(target)) } catch { return false }
  const fold = (p: string): string => (process.platform === 'win32' ? p.toLowerCase() : p)
  const root = fold(resolve(appFiles))
  return fold(path).startsWith(root + sep)
}"""),
    ("""/**
 * Whether a default-session request may proceed.
 * @param url - the request URL as Electron reports it.
 * @param hostUrl - the local Host URL once known (only its exact host:port is allowed, over http or ws).
 * @returns true when the request stays inside the application or reaches the Host itself.
 */
export function lawbenchRequestAllowed(url: string, hostUrl: string | undefined): boolean {
  let target: URL
  try { target = new URL(url) } catch { return false }
  if (LOCAL_SCHEMES.has(target.protocol)) return true""",
     """/**
 * Whether a default-session request may proceed.
 * @param url - the request URL as Electron reports it.
 * @param hostUrl - the local Host URL once known (only its exact host:port is allowed, over http or ws).
 * @param appFiles - the application's renderer directory; `file:` URLs are allowed only inside it.
 * @returns true when the request stays inside the application or reaches the Host itself.
 */
export function lawbenchRequestAllowed(url: string, hostUrl: string | undefined, appFiles?: string): boolean {
  let target: URL
  try { target = new URL(url) } catch { return false }
  if (LOCAL_SCHEMES.has(target.protocol)) return true
  if (target.protocol === 'file:') return appFile(target, appFiles)"""),
])
edit('tests/lawbench-request-policy.spec.ts', [
    ("""import { describe, expect, it } from 'vitest'
import { lawbenchRequestAllowed } from '../src/lawbench-request-policy.ts'
""", """import { describe, expect, it } from 'vitest'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
import { lawbenchRequestAllowed } from '../src/lawbench-request-policy.ts'
"""),
    ("""    for (const url of ['dsh-app://app/index.html', 'dsh-app://shell/welcome.html', 'data:image/png;base64,AA==', 'blob:dsh-app://app/1', 'devtools://devtools/x', 'file:///C:/x.html', 'about:blank']) {""",
     """    for (const url of ['dsh-app://app/index.html', 'dsh-app://shell/welcome.html', 'data:image/png;base64,AA==', 'blob:dsh-app://app/1', 'devtools://devtools/x', 'about:blank']) {"""),
    ("""  it('allows only the Host itself over http and ws', () => {""",
     """  it('file: only for the application renderer files (first-run window); other local files and shares refused', () => {
    const app = join(process.cwd(), 'apps-desktop-fixture', 'renderer')
    expect(lawbenchRequestAllowed(pathToFileURL(join(app, 'welcome.html')).href, HOST, app)).toBe(true)
    expect(lawbenchRequestAllowed(pathToFileURL(join(app, 'assets', 'welcome.js')).href, HOST, app)).toBe(true)
    for (const url of [
      pathToFileURL(join(app, '..', 'secret.html')).href,
      pathToFileURL(`${app}-other${join('/', 'x.html')}`).href,
      'file:///C:/x.html',
      'file://192.168.1.20/share/a.png',
    ]) {
      expect(lawbenchRequestAllowed(url, HOST, app), url).toBe(false)
    }
    expect(lawbenchRequestAllowed(pathToFileURL(join(app, 'welcome.html')).href, HOST)).toBe(false) // root unknown
  })
  it('refuses chrome: and chrome-extension: (no internal pages or extensions are used)', () => {
    for (const url of ['chrome://gpu', 'chrome-extension://abc/x.js']) {
      expect(lawbenchRequestAllowed(url, HOST), url).toBe(false)
    }
  })
  it('allows only the Host itself over http and ws', () => {"""),
])
edit('tests/main-startup.spec.ts', [
    ("""  it('lawbench P-9: cancels default-session requests except app resources and the Host itself', async () => {""",
     """  it('lawbench P-9: no window may host a webview or spellcheck, and the sidebar browser IPC is not registered', async () => {
    await readyForUpdate()
    expect(harness.windows.length).toBeGreaterThan(0)
    for (const window of harness.windows) {
      const prefs = (window.options as { webPreferences?: { webviewTag?: boolean; spellcheck?: boolean } }).webPreferences
      if (prefs === undefined) continue
      expect(prefs.webviewTag).toBe(false)
      expect(prefs.spellcheck).toBe(false)
    }
    expect(harness.handlers.has(DESKTOP_IPC.browserAcquire)).toBe(false)
    expect(harness.handlers.has(DESKTOP_IPC.browserRelease)).toBe(false)
  })

  it('lawbench P-9: cancels default-session requests except app resources and the Host itself', async () => {"""),
])
print('P-9 delta ok')
