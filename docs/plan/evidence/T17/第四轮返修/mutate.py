# T17 第三步最后一轮返修（第四轮复核清单）：逐个撤回修法，看对应用例是否变红；每次按原字节写回。
# 用法：python mutate.py <输出文件>（在仓库根下跑）
import io, re, subprocess, sys

EXT = 'dsh-ext/'
MUTS = [
    ('B-F1：caseOpen 成功后不刷新名单', EXT + 'host/index.ts',
     "        if (r.ok) await this.refreshCaseRoots()\n", "",
     ['tests/case-open.spec.ts']),
    ('B-F1：挂回之前不刷新名单', EXT + 'host/attach-sessions.ts',
     "  await persistence.refreshCaseRoots?.().catch(() => undefined)\n", "",
     ['tests/case-open.spec.ts']),
    ('B-F1：会话存储不提供 refreshCaseRoots', EXT + 'session-store/index.ts',
     "    refreshCaseRoots() { return refreshNow() }\n", "",
     ['tests/case-open.spec.ts']),
    ('B-F1 / B-F3：哪里都找不到时不强制刷新再找（open、stat 四处）', EXT + 'session-store/router.ts',
     "  private async refreshOnMiss(): Promise<boolean> {\n    if (", "  private async refreshOnMiss(): Promise<boolean> {\n    return false\n    if (",
     ['tests/case-open.spec.ts', 'tests/session-store.spec.ts']),
    ('A-P2-2：编号表里指向旧根的条目不作废', EXT + 'session-store/router.ts',
     "    if (known && known !== miss && this.current(known)) return known\n", "    if (known && known !== miss) return known\n",
     ['tests/session-store.spec.ts', 'tests/case-open.spec.ts']),
    ('A-P2-2：ownerOf 不看名单（投影缓存仍往旧位置写）', EXT + 'session-store/router.ts',
     "    return s && this.current(s) ? s.caseRoot : undefined\n", "    return s?.caseRoot\n",
     ['tests/session-store.spec.ts']),
    ('A-P2-1 = B-F2：去掉失败照样挂', EXT + 'host/attach-sessions.ts',
     "    if (failedIds.has(id)) continue // 还记在别处：不挂，免得同一编号记成两处\n", "",
     ['tests/workspace-attach.spec.ts']),
    ('A-P2-1 = B-F2：私有字段 table 不在时照样挂', EXT + 'host/attach-sessions.ts',
     "  if (typeof registry.indexHeaders !== 'function' || typeof table?.get !== 'function') {", "  if (typeof registry.indexHeaders !== 'function') {",
     ['tests/workspace-attach.spec.ts']),
    ('A-P2-1 = B-F2：私有方法 indexHeaders 不在时照样挂', EXT + 'host/attach-sessions.ts',
     "  if (typeof registry.indexHeaders !== 'function' || typeof table?.get !== 'function') {", "  if (typeof table?.get !== 'function') {",
     ['tests/workspace-attach.spec.ts']),
    ('B-F4：每次都等满首刷上限', EXT + 'session-store/index.ts',
     "      waiting ??= new Promise<void>((resolve) => {", "      waiting = new Promise<void>((resolve) => {",
     ['tests/session-store.spec.ts']),
    ('B-F6：服务返回空列表时名单清空', EXT + 'session-store/case-roots.ts',
     "    if (cases.length === 0) return false\n", "",
     ['tests/session-store.spec.ts']),
    ('A-P3-3：Host 包装参数不对也照做', EXT + 'host/index.ts',
     "    if (typeof root !== 'string' || !root) return fail('INVALID_ARGUMENT', BAD_ARGS)\n    const registry = this.service('workspaceRegistry') as RegistryLike | undefined\n",
     "    const registry = this.service('workspaceRegistry') as RegistryLike | undefined\n",
     ['tests/case-open.spec.ts']),
]


def run(tests):
    r = subprocess.run(['node', 'scripts/test.mjs', '--maxWorkers=2', *tests], cwd=EXT, capture_output=True, text=True, encoding='utf-8', errors='replace')
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
report = '# T17 第三步最后一轮返修 变异（撤回单处修法）\n\n' + '\n'.join(out)
io.open(sys.argv[1], 'w', encoding='utf-8').write(report)
