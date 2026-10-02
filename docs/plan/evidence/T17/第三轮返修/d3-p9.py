# T17 第三轮返修 A-P3-1：默认会话上关拼写检查（首次配置窗口、强制更新层都用默认会话），与各窗口 spellcheck: false 并存。
# 用法：python d3-p9.py <dsh 根>
import io, sys


def edit(p, pairs):
    raw = io.open(p, encoding='utf-8', newline='').read()
    nl = '\r\n' if '\r\n' in raw else '\n'
    s = raw.replace('\r\n', '\n')
    for a, b in pairs:
        assert s.count(a) == 1, (p, a[:60], s.count(a))
        s = s.replace(a, b)
    io.open(p, 'w', encoding='utf-8', newline='').write(s.replace('\n', nl))


root = sys.argv[1]
edit(root + '/apps/desktop/src/main.ts', [(
    """  // lawbench P-9 (N38): the default session only reaches app resources and the local Host; other network requests are cancelled.
  session.defaultSession.webRequest.onBeforeRequest((details, callback) => {""",
    """  // lawbench P-9: no spellchecker in any default-session window (main, first-run setup, mandatory update);
  // it would fetch dictionaries from the network.
  session.defaultSession.setSpellCheckerEnabled(false)

  // lawbench P-9 (N38): the default session only reaches app resources and the local Host; other network requests are cancelled.
  session.defaultSession.webRequest.onBeforeRequest((details, callback) => {""")])
edit(root + '/apps/desktop/tests/main-startup.spec.ts', [
    ("""menu, popup, socketHeaders: vi.fn(), requestFilter: vi.fn(), updateCheck,""",
     """menu, popup, socketHeaders: vi.fn(), requestFilter: vi.fn(), spellChecker: vi.fn(), updateCheck,"""),
    ("""setPermissionCheckHandler: vi.fn(), setPermissionRequestHandler: vi.fn(), webRequest:""",
     """setPermissionCheckHandler: vi.fn(), setPermissionRequestHandler: vi.fn(), setSpellCheckerEnabled: harness.spellChecker, webRequest:"""),
    ("""  it('lawbench P-9: no window may host a webview or spellcheck, and the sidebar browser IPC is not registered', async () => {
    await readyForUpdate()
    expect(harness.windows.length).toBeGreaterThan(0)""",
     """  it('lawbench P-9: no window may host a webview or spellcheck, and the sidebar browser IPC is not registered', async () => {
    await readyForUpdate()
    // the default session (main, first-run setup and mandatory-update windows) has its spellchecker off
    expect(harness.spellChecker).toHaveBeenCalledWith(false)
    expect(harness.windows.length).toBeGreaterThan(0)"""),
])
print('d3-p9 ok')
