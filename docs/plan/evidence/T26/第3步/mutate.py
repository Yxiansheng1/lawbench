# T26 第 3 步归档面板：逐个撤回修法，看 tests\archive.spec.ts 是否变红；每次按原字节写回。
# 用法：python mutate.py <输出文件>（在仓库根下跑）
import io, re, subprocess, sys

EXT = 'dsh-ext/'
T = ['tests/archive.spec.ts']
MUTS = [
    ('办案结果没选也能生成', EXT + 'ui/archive-logic.ts',
     "  if (p.result === null) return '请先点选办案结果'\n", ""),
    ('点按钮不再核对能否生成（直接发请求）', EXT + 'ui/archive.tsx',
     "    if (!plan || loaded.state !== 'ok' || blocker(plan)) return // 办案结果没选不发请求", "    if (!plan || loaded.state !== 'ok') return"),
    ('按钮不随办案结果停用', EXT + 'ui/archive.tsx',
     "disabled={!plan || !!why || busy}", "disabled={!plan || busy}"),
    ('调顺序不生效', EXT + 'ui/archive-logic.ts',
     "          ;[m[e.index], m[j]] = [m[j], m[e.index]]\n", ""),
    ('名称不去首尾空白', EXT + 'ui/archive-logic.ts',
     "    items: p.items.map((it) => ({ ...it, name: it.name.trim() })),\n", ""),
    ('空着的承办律师不交 null', EXT + 'ui/archive-logic.ts',
     "    lawyer: blank(p.lawyer),\n", ""),
    ('服务端错误不显示', EXT + 'ui/archive.tsx',
     "    if (!r.ok) { setError(errorText(r.error)); return }", "    if (!r.ok) { return }"),
    ('要人手处理的事项不显示', EXT + 'ui/archive.tsx',
     "      {v.manual.length ? (", "      {false ? ("),
    ('页码范围不对上名称', EXT + 'ui/archive-logic.ts',
     "    return `${r.code}. ${name.get(r.code) ?? '（程序生成）'}：${pages}`", "    return `${r.code}. ：${pages}`"),
    ('Host 读方案不按契约校验', EXT + 'host/archive-plan.ts',
     "  if (validate(toolId('case_save_archive_plan'), 'plan', plan).length) return fail('INVALID_ARGUMENT', BAD_PLAN)\n", ""),
    ('Host 读方案不拦链接', EXT + 'host/archive-plan.ts',
     "    if (lstatSync(dir).isSymbolicLink() || lstatSync(file).isSymbolicLink() || !lstatSync(file).isFile()) return fail('TASK_NOT_FOUND', NO_PLAN)\n    const rel = relative(realpathSync(root), realpathSync(file))\n    if (!rel || rel.startsWith('..') || isAbsolute(rel)) return fail('OUT_OF_CASE', NO_PLAN)\n", ""),
    ('Host 读方案不核任务编号格式', EXT + 'host/archive-plan.ts',
     " || typeof taskId !== 'string' || !TASK_ID.test(taskId)) {", " || typeof taskId !== 'string') {"),
]


def run(tests):
    r = subprocess.run(['node', 'scripts/test.mjs', '--maxWorkers=1', *tests], cwd=EXT, capture_output=True, text=True, encoding='utf-8', errors='replace')
    text = r.stdout + r.stderr
    fails = sorted(set(l.strip() for l in re.findall(r'(?m)^\s*(?:FAIL|×)\s+(.+?)(?:\s+\d+ms)?$', text)))
    summary = re.findall(r'(?m)^\s+Tests\s+(\d.+)$', text)
    return (summary[-1].strip() if summary else '?'), fails


out = []
for name, path, a, b in MUTS:
    raw = io.open(path, encoding='utf-8', newline='').read()
    nl = '\r\n' if '\r\n' in raw else '\n'
    src = raw.replace('\r\n', '\n')
    assert src.count(a) == 1, (name, src.count(a))
    try:
        io.open(path, 'w', encoding='utf-8', newline='').write(src.replace(a, b).replace('\n', nl))
        summary, fails = run(T)
    finally:
        io.open(path, 'w', encoding='utf-8', newline='').write(raw)
    out.append(f'## {name}\n文件：{path}\n结果：{summary}\n' + '\n'.join('- ' + f for f in fails) + '\n')
    print(out[-1], flush=True)
io.open(sys.argv[1], 'w', encoding='utf-8').write('# T26 第 3 步归档面板变异（撤回单处修法）\n\n' + '\n'.join(out))
