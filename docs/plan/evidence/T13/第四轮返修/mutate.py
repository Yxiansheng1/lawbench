# T13 第四轮返修：逐个撤回修法（及 R1、Y7 对应的两处），看新用例是否变红；每次按原字节写回。
# 用法：python mutate.py <输出文件>（在仓库根下跑）
import io, re, subprocess, sys
EXT = 'dsh-ext/'
P = 'ui/dock.tsx'
MUTS = [
    ('P2-1 撤回：已保存就不写（不看显示的键）',
     "    if (!stored || (stored.saved && (serverKey.current === null || key === serverKey.current))) return\n",
     "    if (!stored || stored.saved) return\n"),
    ('P3-1 撤回：挂上时读回与取提示并行',
     "    void notice().then(() => { if (alive) load() })\n    // 一轮结束",
     "    load()\n    void notice()\n    // 一轮结束"),
    ('P3-2 撤回：写成时不清提示',
     "          clearStaleServer(sid)\n          clearInputChanged(sid)\n",
     "          clearStaleServer(sid)\n"),
    ('P3-3 撤回：切走后取到的提示丢掉',
     "      if (r.ok && r.value.code === 'INPUT_CHANGED') { markInputChanged(sid); if (alive) setLoadedFor(null) }",
     "      if (!alive) return\n      if (r.ok && r.value.code === 'INPUT_CHANGED') { markInputChanged(sid); setLoadedFor(null) }"),
    ('R1：写成后 staleServer 不清',
     "          clearStaleServer(sid)\n          clearInputChanged(sid)\n",
     "          clearInputChanged(sid)\n"),
    ('Y7：挂上、换会话时不取提示（只在一轮结束时取）',
     "    void notice().then(() => { if (alive) load() })\n    // 一轮结束",
     "    load()\n    // 一轮结束"),
]
TESTS = ['tests/dock-a19.spec.ts', 'tests/dock-review.spec.ts']
raw = io.open(EXT + P, encoding='utf-8', newline='').read()
nl = '\r\n' if '\r\n' in raw else '\n'
src = raw.replace('\r\n', '\n')
out = []
try:
    for name, a, b in MUTS:
        assert src.count(a) == 1, (name, src.count(a))
        io.open(EXT + P, 'w', encoding='utf-8', newline='').write(src.replace(a, b).replace('\n', nl))
        r = subprocess.run(['node', 'scripts/test.mjs', '--maxWorkers=2', *TESTS], cwd=EXT, capture_output=True, text=True, encoding='utf-8', errors='replace')
        text = r.stdout + r.stderr
        fails = sorted(set(l.strip() for l in re.findall(r'(?m)^\s*(?:FAIL|×)\s+(.+?)(?:\s+\d+ms)?$', text)))
        summary = re.findall(r'(?m)^\s+Tests\s+(\d.+)$', text)
        out.append(f'## {name}\n结果：{summary[-1].strip() if summary else "?"}\n' + '\n'.join('- ' + f for f in fails) + '\n')
finally:
    io.open(EXT + P, 'w', encoding='utf-8', newline='').write(raw)
report = '# T13 第四轮返修 变异（撤回单处修法），跑 ' + '、'.join(TESTS) + '\n\n' + '\n'.join(out)
io.open(sys.argv[1], 'w', encoding='utf-8').write(report)
print(report)
