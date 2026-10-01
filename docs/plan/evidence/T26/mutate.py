# T26 第 1、2 步（发票整理页、委托材料窗口）：逐个撤回一处做法，看对应用例是否变红；每次按原字节写回。
# 用法：python mutate.py <输出文件>（在仓库根下跑；DSH 那几处要先按 PATCHES.md 打好补丁）
import io, os, re, subprocess, sys

EXT = 'dsh-ext/'
DSH = 'dsh/apps/desktop/src/'
MUTS = [
    ('发票：ENGINE_BUSY 不停用按钮', EXT + 'ui/invoice.tsx',
     "  const blocked = running !== null || busyUntil > 0", "  const blocked = running !== null", 'ext', ['tests/invoice.spec.ts']),
    ('发票：动作进行中不停用按钮', EXT + 'ui/invoice.tsx',
     "  const blocked = running !== null || busyUntil > 0", "  const blocked = busyUntil > 0", 'ext', ['tests/invoice.spec.ts']),
    ('发票：确认已报销不先预览', EXT + 'ui/invoice-logic.ts',
     "  reimburse: { preview: 'self',", "  reimburse_: { preview: 'self',", 'ext', ['tests/invoice.spec.ts']),
    ('发票：取消批次用 apply:false 预览（服务对 cancel 一律带 --apply，会直接取消）', EXT + 'ui/invoice-logic.ts',
     "  cancel: { preview: 'report',", "  cancel: { preview: 'self',", 'ext', ['tests/invoice.spec.ts']),
    ('发票：人工排除不先确认', EXT + 'ui/invoice.tsx',
     "    if (action === 'exclude' && !(await confirm(", "    if (false && !(await confirm(", 'ext', ['tests/invoice.spec.ts']),
    ('发票：failed 不标红', EXT + 'ui/invoice-logic.ts',
     "  if (v.failed) return 'err'\n", "", 'ext', ['tests/invoice.spec.ts']),
    ('发票：没设日常办公文件夹也放行', EXT + 'ui/invoice.tsx',
     "  const ready = office !== null && office !== 'fail' && !!office.dir && !!office.buyer", "  const ready = office !== null && office !== 'fail'", 'ext', ['tests/invoice.spec.ts']),
    ('发票：短超时（10 分钟）', EXT + 'shared/api-routes.ts',
     "timeoutMs: INVOICE }", "timeoutMs: LONG }", 'ext', ['tests/invoice.spec.ts']),
    ('委托材料：关窗后不停驱动', EXT + 'ui/retainer.ts',
     "  if (result.kind === 'already-open') return\n  await stopDriver()\n", "  if (result.kind === 'already-open') return\n", 'ext', ['tests/retainer.spec.ts']),
    ('委托材料：stop 回 running:true 时不提示', EXT + 'ui/retainer.ts',
     "  else if (r.value.running) notice(TEXT.stopTitle, r.value.message)\n", "", 'ext', ['tests/retainer.spec.ts']),
    ('委托材料：ZIP 不解压', EXT + 'ui/retainer.ts',
     "  if (yes) await runImport(current, r.files, RETAINER_TARGET, zip)", "  if (yes) await runImport(current, r.files, RETAINER_TARGET, false)", 'ext', ['tests/retainer.spec.ts']),
    ('委托材料：主进程没认案件也导入', EXT + 'ui/retainer.ts',
     "  if (!r.inCase || !current) {", "  if (!current) {", 'ext', ['tests/retainer.spec.ts']),
    ('委托材料：不问律师直接导入', EXT + 'ui/retainer.ts',
     "  const yes = await confirm(", "  const yes = true || await confirm(", 'ext', ['tests/retainer.spec.ts']),
    ('P-11：分区不设白名单', DSH + 'lawbench-retainer.ts',
     "    callback({ cancel: !lawbenchRequestAllowed(details.url, RETAINER_DRIVER_URL, pageDir) })", "    callback({ cancel: false })", 'dsh', ['apps/desktop/tests/lawbench-retainer.spec.ts']),
    ('P-11：分区开拼写检查', DSH + 'lawbench-retainer.ts',
     "  ses.setSpellCheckerEnabled(false)\n", "", 'dsh', ['apps/desktop/tests/lawbench-retainer.spec.ts']),
    ('P-11：不禁跳转', DSH + 'lawbench-retainer.ts',
     "  contents.on('will-navigate', (event) => { event.preventDefault() })\n", "", 'dsh', ['apps/desktop/tests/lawbench-retainer.spec.ts']),
    ('P-11：允许新窗口', DSH + 'lawbench-retainer.ts',
     "  contents.setWindowOpenHandler(() => ({ action: 'deny' }))", "  contents.setWindowOpenHandler(() => ({ action: 'allow' }))", 'dsh', ['apps/desktop/tests/lawbench-retainer.spec.ts']),
    ('P-11：同名下载不改名（覆盖）', DSH + 'lawbench-retainer.ts',
     "    const name = freeName(owner.dir, safeDownloadName(item.getFilename()), owner.taken)", "    const name = safeDownloadName(item.getFilename())", 'dsh', ['apps/desktop/tests/lawbench-retainer.spec.ts']),
    ('P-11：下载名不去目录', DSH + 'lawbench-retainer.ts',
     r"  const last = name.split(/[\\/]/u).pop() ?? ''", "  const last = name", 'dsh', ['apps/desktop/tests/lawbench-retainer.spec.ts']),
    ('P-11：不核对是不是主窗口顶层发来的', DSH + 'lawbench-retainer.ts',
     "    if (main === undefined || main.isDestroyed() || event.sender !== main.webContents || event.senderFrame !== main.webContents.mainFrame) {", "    if (main === undefined) {", 'dsh', ['apps/desktop/tests/lawbench-retainer.spec.ts']),
    ('P-11：不核对是不是案件文件夹（任何目录都当案件）', DSH + 'lawbench-retainer.ts',
     "    return top.isDirectory() && !top.isSymbolicLink() && work.isDirectory() && !work.isSymbolicLink() ? root : undefined", "    return root", 'dsh', ['apps/desktop/tests/lawbench-retainer.spec.ts']),
    ('P-11：窗口不用独立分区', DSH + 'lawbench-retainer.ts',
     "      partition: RETAINER_PARTITION,\n", "", 'dsh', ['apps/desktop/tests/lawbench-retainer.spec.ts']),
]


def run(where, tests):
    if where == 'ext':
        cmd, cwd = ['node', 'scripts/test.mjs', '--maxWorkers=1', *tests], EXT
    else:
        cmd, cwd = ['corepack', 'pnpm@11.7.0', 'exec', 'vitest', 'run', *tests], 'dsh'
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding='utf-8', errors='replace', shell=(where == 'dsh'), env={**os.environ, 'CI': 'true'})
    text = r.stdout + r.stderr
    fails = sorted(set(l.strip() for l in re.findall(r'(?m)^\s*(?:FAIL|×)\s+(.+?)(?:\s+\d+ms)?$', text)))
    summary = re.findall(r'(?m)^\s+Tests\s+(\d.+)$', text)
    return (summary[-1].strip() if summary else '?'), fails


out = []
for name, path, a, b, where, tests in MUTS:
    raw = io.open(path, encoding='utf-8', newline='').read()
    nl = '\r\n' if '\r\n' in raw else '\n'
    src = raw.replace('\r\n', '\n')
    assert src.count(a) == 1, (name, src.count(a))
    try:
        io.open(path, 'w', encoding='utf-8', newline='').write(src.replace(a, b).replace('\n', nl))
        summary, fails = run(where, tests)
    finally:
        io.open(path, 'w', encoding='utf-8', newline='').write(raw)
    out.append(f'## {name}\n文件：{path}；跑：{"、".join(tests)}\n结果：{summary}\n' + '\n'.join('- ' + f for f in fails) + '\n')
    print(out[-1], flush=True)
report = '# T26 第 1、2 步变异（撤回单处做法）\n\n' + '\n'.join(out)
io.open(sys.argv[1], 'w', encoding='utf-8').write(report)
