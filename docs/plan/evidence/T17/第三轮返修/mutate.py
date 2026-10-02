# T17 第三轮返修：逐个撤回修法，看对应用例是否变红；每次按原字节写回。
# 用法：python mutate.py <输出文件> [--only ext|dsh]（在仓库根下跑；--only 只跑一套，结果写到另一个输出文件）
import io, re, subprocess, sys

EXT = 'dsh-ext/'
DSH = 'dsh/'
# (名称, 文件, 原串, 改成, 跑哪套, 用例文件)
MUTS = [
    ('B-F1 撤回：名单刷新时没列出的保留（旧做法）', EXT + 'session-store/case-roots.ts',
     "    const byKey = new Map<string, string>()\n    for (const c of cases) {\n      if (typeof c.root !== 'string' || !c.root || !c.exists) continue\n",
     "    const byKey = new Map(this.roots.map((r) => [pathKey(r), r]))\n    for (const c of cases) {\n      if (typeof c.root !== 'string' || !c.root) continue\n      if (!c.exists) { byKey.delete(pathKey(c.root)); continue }\n",
     'ext', ['tests/session-store.spec.ts', 'tests/workspace-attach.spec.ts']),
    ('B-F2 撤回：打开案件不请 Host 挂回游离会话', EXT + 'ui/index.tsx',
     "    await call('attachCaseSessions', { root }).catch(() => undefined)\n", "",
     'ext', ['tests/intake.spec.ts']),
    ('B-F2 撤回：挂不上的不再挂第二次', EXT + 'host/attach-sessions.ts',
     "  for (const id of todo) if (!failedIds.has(id) && !ws.sessionIds.includes(id)) await attach(id)\n", "",
     'ext', ['tests/workspace-attach.spec.ts']),
    ('B-F2：只挂不在任何工作区里的（启动时按旧位置算进旧工作区的不挂）', EXT + 'host/attach-sessions.ts',
     " && !ws.sessionIds.includes(h.id))", " && !registry.list().some((w) => w.sessionIds.includes(h.id)))",
     'ext', ['tests/workspace-attach.spec.ts']),
    ('B-F2：挂之前不用现在的记录头重建登记的索引', EXT + 'host/attach-sessions.ts',
     "  if (stale.length && typeof registry.indexHeaders === 'function') {", "  if (false) {",
     'ext', ['tests/workspace-attach.spec.ts']),
    ('B-F2：不从旧工作区去掉（同一编号记在两处，下次启动登记不一致；侧栏不更新）', EXT + 'host/attach-sessions.ts',
     "        await w.detachSession?.(id)\n", "",
     'ext', ['tests/workspace-attach.spec.ts']),
    ('B-F2：只看过滤后的 sessionIds 决定从哪里去掉（纯搬家后旧工作区的登记记录里留着它）', EXT + 'host/attach-sessions.ts',
     "    return (raw ?? w.sessionIds).includes(id)", "    return w.sessionIds.includes(id)",
     'ext', ['tests/workspace-attach.spec.ts']),
    ('B-F2：对别的工作区一律去掉（不在名单上的案件的会话被剪掉）', EXT + 'host/attach-sessions.ts',
     "    return (raw ?? w.sessionIds).includes(id)", "    return true",
     'ext', ['tests/workspace-attach.spec.ts']),
    ('B-F2：先挂后去掉（中途断掉会留下同一编号记在两处）', EXT + 'host/attach-sessions.ts',
     "  for (const id of todo) {\n    for (const w of recordedIn(id)) {", "  for (const id of todo) await attach(id)\n  for (const id of todo) {\n    for (const w of recordedIn(id)) {",
     'ext', ['tests/workspace-attach.spec.ts']),
    ('A-P2-1 撤回：不接投影缓存', EXT + 'session-store/index.ts',
     "  if (pc && (pc.impl || pc.module)) {", "  if (pc && false) {",
     'ext', ['tests/projection-cache.spec.ts']),
    ('A-P2-1：搬家后身份 cwd 不换成现根', EXT + 'session-store/projection-cache.ts',
     "    if (at && cwd !== undefined && pathKey(cwd) !== pathKey(at.caseRoot))", "    if (false)",
     'ext', ['tests/projection-cache.spec.ts']),
    ('A-P2-1：默认根的会话也落盘（落到 $DSH_HOME）', EXT + 'session-store/projection-cache.ts',
     "    if (!caseRoot || !SAFE_ID.test(id)) return undefined\n    const dir = join(caseRoot, CASE_CACHE_DIR)",
     "    if (!SAFE_ID.test(id)) return undefined\n    const dir = join(caseRoot ?? 'dsh-home-fallback', CASE_CACHE_DIR)",
     'ext', ['tests/projection-cache.spec.ts']),
    ('A-P3-3 撤回：默认根的旧会话可续写', EXT + 'session-store/router.ts',
     "    if (access === 'write' && !s.caseRoot && !this.opts.allowOutsideCase) throw new Error(OUTSIDE_CASE)\n", "",
     'ext', ['tests/session-store.spec.ts']),
    ('B-F4 撤回：名单为空时列表不等第一次刷新', EXT + 'session-store/router.ts',
     "    if (first && !first.done() && this.roots.list().length === 0) {", "    if (false) {",
     'ext', ['tests/session-store.spec.ts']),
    ('B-F4 撤回：拿不到名单时仍说"不是案件"', EXT + 'session-store/router.ts',
     "    else if (header.cwd && first && !first.done()) throw new Error(NOT_READY)\n", "",
     'ext', ['tests/session-store.spec.ts']),
    ('B-F5 撤回：案件根读取不加上限', EXT + 'session-store/router.ts',
     "    return s.caseRoot ? within(p, this.opts.caseRootTimeoutMs ?? 3000) : p", "    return p",
     'ext', ['tests/session-store.spec.ts']),
    ('B-F6 撤回：表里的实例说没有就照原样报错', EXT + 'session-store/router.ts',
     "      if (!known || !isNotFound(error)) throw error", "      if (known || !known) throw error",
     'ext', ['tests/session-store.spec.ts']),
    ('A-P3-5 撤回：列表等服务刷新', EXT + 'session-store/router.ts',
     "      void this.opts.refresh?.().catch(() => undefined)\n    }", "      await this.opts.refresh?.().catch(() => undefined)\n    }",
     'ext', ['tests/session-store.spec.ts']),
    ('A-P3-5 撤回：缓存读坏不记日志', EXT + 'session-store/case-roots.ts',
     "      if ((error as NodeJS.ErrnoException)?.code !== 'ENOENT') this.log?.(", "      if (false) this.log?.(",
     'ext', ['tests/session-store.spec.ts']),
    ('A-P3-2：flush 只刷默认根', EXT + 'session-store/router.ts',
     "    const stores = [this.defaultStore, ...this.stores.values()]", "    const stores = [this.defaultStore]",
     'ext', ['tests/session-store.spec.ts']),
    ('A-P3-2：重复编号不跳过', EXT + 'session-store/router.ts',
     "        if (seen.has(row.header.id)) {", "        if (false) {",
     'ext', ['tests/session-store.spec.ts']),
    ('A-P3-1 撤回：默认会话不关拼写检查', DSH + 'apps/desktop/src/main.ts',
     "  session.defaultSession.setSpellCheckerEnabled(false)\n", "",
     'dsh', ['apps/desktop/tests/main-startup.spec.ts']),
    ('A-P3-6：addFiles 不再问导入钩子', DSH + 'packages/client/ui-conversation/src/client/apply.ts',
     "          const taken = askIntake(files, directories)\n          if (taken !== undefined) return taken\n", "",
     'dsh', ['packages/client/ui-conversation']),
]


def run(kind, tests):
    if kind == 'ext':
        cmd, cwd = ['node', 'scripts/test.mjs', '--maxWorkers=2', *tests], EXT
    else:
        cmd, cwd = ['node_modules\\.bin\\vitest.CMD', 'run', '--maxWorkers=3', *tests], DSH  # 经 cmd 跑，路径用反斜杠
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding='utf-8', errors='replace', shell=(kind == 'dsh'))
    text = r.stdout + r.stderr
    fails = sorted(set(l.strip() for l in re.findall(r'(?m)^\s*(?:FAIL|×)\s+(.+?)(?:\s+\d+ms)?$', text)))
    summary = re.findall(r'(?m)^\s+Tests\s+(\d.+)$', text)
    return (summary[-1].strip() if summary else '?'), fails


only = sys.argv[sys.argv.index('--only') + 1] if '--only' in sys.argv else None
out = []
for name, path, a, b, kind, tests in MUTS:
    if only and kind != only:
        continue
    raw = io.open(path, encoding='utf-8', newline='').read()
    nl = '\r\n' if '\r\n' in raw else '\n'
    src = raw.replace('\r\n', '\n')
    assert src.count(a) == 1, (name, src.count(a))
    try:
        io.open(path, 'w', encoding='utf-8', newline='').write(src.replace(a, b).replace('\n', nl))
        summary, fails = run(kind, tests)
    finally:
        io.open(path, 'w', encoding='utf-8', newline='').write(raw)
    out.append(f'## {name}\n文件：{path}；跑：{"、".join(tests)}\n结果：{summary}\n' + '\n'.join('- ' + f for f in fails) + '\n')
    print(out[-1], flush=True)
report = '# T17 第三轮返修 变异（撤回单处修法）\n\n' + '\n'.join(out)
io.open(sys.argv[1], 'w', encoding='utf-8').write(report)
