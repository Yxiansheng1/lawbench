# P-15 增补（T17 第二步返修 B-F3/B-F4）：realpath 之前先拒绝网络路径和设备路径前缀；越界与不存在统一 403；读取用规范路径。
# 用法：python d-p15.py <dsh 根目录>
import io, sys
root = sys.argv[1].rstrip('\\/') + '/packages/api/session-controller/'


def edit(name, pairs):
    p = root + name
    s = io.open(p, encoding='utf-8', newline='').read()
    nl = '\r\n' if '\r\n' in s else '\n'
    s = s.replace('\r\n', '\n')
    for a, b in pairs:
        assert s.count(a) == 1, (name, a[:80], s.count(a))
        s = s.replace(a, b)
    io.open(p, 'w', encoding='utf-8', newline='').write(s.replace('\n', nl))


edit('src/media-references.ts', [
    ("""  // lawbench P-15: canonicalize (`..`, links, long-path prefixes) and require an allowed root; the path is never echoed
  let canonical: string
  try { canonical = await realpath(resolve(path)) } catch { return fail(404, 'not found') }
  if (!lawbenchPathInside(canonical, await servedRoots(rootsOf))) return fail(403, 'outside the allowed folders')
  try {
    const target = await fs.resolve(path, { signal: request.signal })""",
     """  // lawbench P-15: network (\\\\host, //host) and device (\\\\?\\, \\\\.\\) paths are refused before any filesystem
  // access, so the Host never reaches out to SMB; then canonicalize (`..`, links) and require an allowed root.
  // Outside and missing answer the same 403 (no existence probe); the path is never echoed.
  const refuse = (): Response => fail(403, 'outside the allowed folders')
  if (/^[\\\\/]{2}/.test(path)) return refuse()
  let canonical: string
  try { canonical = await realpath(resolve(path)) } catch { return refuse() }
  if (!lawbenchPathInside(canonical, await servedRoots(rootsOf))) return refuse()
  try {
    // lawbench P-15: read the checked canonical path, not the request's spelling (a link swapped in between cannot redirect it)
    const target = await fs.resolve(canonical, { signal: request.signal })"""),
    ("""      if (info === undefined) return fail(404, 'not found')""",
     """      if (info === undefined) return refuse()"""),
    ("""      FS_NOT_FOUND: 404,""", """      FS_NOT_FOUND: 403, // lawbench P-15: same answer as outside"""),
])
edit('tests/media-references.host.spec.ts', [
    ("""    expect((await route.call(join(root, 'missing'), { method: 'HEAD' })).status).toBe(404)""",
     """    expect((await route.call(join(root, 'missing'), { method: 'HEAD' })).status).toBe(403) // lawbench P-15: missing = outside"""),
    ("""    expect((await route.call(join(root, 'missing.png'))).status).toBe(404)""",
     """    expect((await route.call(join(root, 'missing.png'))).status).toBe(403) // lawbench P-15: missing = outside"""),
    ("""      expect((await route.call(join(outside, 'missing.png'))).status).toBe(404)""",
     """      expect((await route.call(join(outside, 'missing.png'))).status).toBe(403) // lawbench P-15: no existence probe"""),
    ("""      ['FS_PERMISSION_DENIED', 403], ['FS_SANDBOX_DENIED', 403], ['FS_NOT_FOUND', 404],""",
     """      ['FS_PERMISSION_DENIED', 403], ['FS_SANDBOX_DENIED', 403], ['FS_NOT_FOUND', 403],"""),
    ("""  it('lawbench P-15: serves nothing when no workspace is registered', async () => {""",
     """  it('lawbench P-15: refuses network and device path prefixes before touching the filesystem, even for a file inside the case', async () => {
    const route = await mount(DEFAULT_LIMIT, [root])
    const inCase = join(root, 'case.png')
    await writeFile(inCase, PNG_BYTES)
    expect((await route.call(inCase)).status).toBe(200)
    for (const path of ['\\\\\\\\127.0.0.1\\\\share\\\\x.png', '//127.0.0.1/share/x.png', `\\\\\\\\?\\\\${inCase}`, `\\\\\\\\.\\\\${inCase}`, `//?/${inCase}`]) {
      const response = await route.call(path)
      expect(response.status, path).toBe(403)
      expect(await response.text()).not.toContain('share')
    }
  })

  it('lawbench P-15: reads the canonical path that was checked, not the request spelling', async () => {
    const route = await mount(DEFAULT_LIMIT, [root])
    await mkdir(join(root, 'sub'))
    const inCase = join(root, 'case.png')
    await writeFile(inCase, PNG_BYTES)
    const resolveSpy = vi.spyOn(route.fs, 'resolve')
    // a literal, un-normalized spelling (join() would already fold the `..`), and on Windows a different letter case
    const { sep } = await import('node:path')
    const spelled = `${root}${sep}sub${sep}..${sep}${process.platform === 'win32' ? 'CASE.PNG' : 'case.png'}`
    expect(await responseBytes(await route.call(spelled))).toEqual(PNG_BYTES)
    expect(resolveSpy.mock.calls[0]![0]).not.toBe(spelled)
    expect(resolveSpy.mock.calls[0]![0]).toBe(await realpath(inCase))
  })

  it('lawbench P-15: serves nothing when no workspace is registered', async () => {"""),
])
print('P-15 delta ok')
