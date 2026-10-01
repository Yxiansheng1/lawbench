# T17 第五轮复核（活着的句柄）返修：逐个撤回修法，看对应用例是否变红；每次按原字节写回。
# 用法：python mutate.py <输出文件>（在仓库根下跑）
import io, re, subprocess, sys

EXT = 'dsh-ext/'
MUTS = [
    ('F1：名单变了以后不搬写入者', EXT + 'session-store/index.ts',
     "    for (const id of router.staleWriters()) {", "    for (const id of [] as string[]) {",
     ['tests/live-writer.spec.ts']),
    ('F1：打开案件后的刷新不顺带搬写入者', EXT + 'session-store/index.ts',
     "    await refresh(true)\n    await relocateStale()\n", "    await refresh(true)\n",
     ['tests/live-writer.spec.ts']),
    ('F1：正在跑的一轮不等结束就搬（不看 Agent 状态）', EXT + 'session-store/index.ts',
     "      if (agents?.get(id)?.status !== 'running') { await relocateOne(id); continue }", "      { await relocateOne(id); continue }",
     ['tests/live-writer.spec.ts']),
    ('F1：不补旧处多出来的事件', EXT + 'session-store/router.ts',
     "          if (prefix && events.length < all.length) {", "          if (false) {",
     ['tests/live-writer.spec.ts']),
    ('F1：不逐条比对旧处（两处分叉也照样搬）', EXT + 'session-store/router.ts',
     "          same = prefix && JSON.stringify(events) === JSON.stringify(all)", "          same = true",
     ['tests/live-writer.spec.ts', 'tests/session-store.spec.ts']),
    ('F1：不核对内存里的会话长度（搬家后只在内存里的那几句之后照样搬）', EXT + 'session-store/router.ts',
     "      if (expectedEvents !== undefined && events.length !== expectedEvents) same = false\n", "",
     ['tests/live-writer.spec.ts']),
    ('F1：同一会话的搬动不排队', EXT + 'session-store/router.ts',
     "    const run = prev.catch(() => 'kept' as const).then(() => this.relocateOnce(id, expectedEvents))", "    const run = this.relocateOnce(id, expectedEvents)",
     ['tests/live-writer.spec.ts']),
    ('F1：挂回时动内存里记录头还是旧位置的会话（去掉再挂不上，进"未分组"）', EXT + 'host/attach-sessions.ts',
     "  const stale = candidates.filter((h) => { const cwd = liveCwd(h.id); return cwd === undefined || pathKey(cwd) === key })\n", "  const stale = candidates\n",
     ['tests/workspace-attach.spec.ts']),
    ('F1：Host 不告诉挂回哪些会话活着', EXT + 'host/index.ts',
     "(id) => sessions?.get?.(id)?.header?.cwd)", "() => undefined)",
     ['tests/case-open.spec.ts']),
    ('F1：写入位置失效时 Agent 插件不拒绝', EXT + 'agent/index.ts',
     "    if (step === 1 && this.writerLost(agent.id)) {", "    if (false) {",
     ['tests/agent.spec.ts']),
    ('F1：输入区不提示 CASE_MOVED', EXT + 'ui/dock.tsx',
     "        if (r.ok && r.value?.code === 'CASE_MOVED') showNotice(CASE_MOVED_TITLE, CASE_MOVED_TEXT)\n", "",
     ['tests/dock-a19.spec.ts']),
    ('F2：挂回结果不报 listed', EXT + 'host/index.ts',
     "      return { ok: true, value: listed === false ? { ...r, listed } : r }", "      return { ok: true, value: r }",
     ['tests/case-open.spec.ts']),
    ('F2：界面不提示名单没刷新', EXT + 'ui/index.tsx',
     "    if (r?.ok && r.value.listed === false) notice(ROOTS_NOT_REFRESHED[0], ROOTS_NOT_REFRESHED[1])", "    void r",
     ['tests/intake.spec.ts']),
    ('A-P3-1：打开案件后的刷新不等途中那次', EXT + 'session-store/index.ts',
     "    if (inFlight) await inFlight.catch(() => undefined)\n    await refresh(true)\n", "    await refresh(true)\n",
     ['tests/case-open.spec.ts']),
]


def run(tests):
    r = subprocess.run(['node', 'scripts/test.mjs', '--maxWorkers=1', *tests], cwd=EXT, capture_output=True, text=True, encoding='utf-8', errors='replace')
    text = r.stdout + r.stderr
    fails = sorted(set(l.strip() for l in re.findall(r'(?m)^\s*(?:FAIL|×)\s+(.+?)(?:\s+\d+ms)?$', text)))
    summary = re.findall(r'(?m)^\s+Tests\s+(\d.+)$', text)
    return (summary[-1].strip() if summary else '?'), fails


out = []
for name, path, a, b, tests in MUTS:
    raw = io.open(path, encoding='utf-8', newline='').read()
    nl = '\r\n' if '\r\n' in raw else '\n'
    src = raw.replace('\r\n', '\n')
    assert src.count(a) == 1, (name, src.count(a))
    try:
        io.open(path, 'w', encoding='utf-8', newline='').write(src.replace(a, b).replace('\n', nl))
        summary, fails = run(tests)
    finally:
        io.open(path, 'w', encoding='utf-8', newline='').write(raw)
    out.append(f'## {name}\n文件：{path}；跑：{"、".join(tests)}\n结果：{summary}\n' + '\n'.join('- ' + f for f in fails) + '\n')
    print(out[-1], flush=True)
report = '# T17 第五轮返修（活着的句柄）变异（撤回单处修法）\n\n' + '\n'.join(out)
io.open(sys.argv[1], 'w', encoding='utf-8').write(report)
