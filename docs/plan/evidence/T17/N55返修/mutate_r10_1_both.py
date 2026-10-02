# 第十轮 R10-1 两处一起撤回（Agent 插件拒绝前不调 releaseMoved + toDetach 对没落过盘的也要求根在盘上），看 M1/M1b/M2 九例；用法：在仓库根下 python 本文件 > mutate_r10_1_both.txt
import io, subprocess
A = ('dsh-ext/agent/index.ts', "    await store()?.releaseMoved?.(payload.agent.id).catch(() => undefined)\n", "")
B = ('dsh-ext/session-store/router.ts', "    return !w.detached && !this.current(w.at) && (!w.seen || existsSync(w.at.caseRoot!))", "    return !w.detached && !this.current(w.at) && existsSync(w.at.caseRoot!)")
raws = {}
try:
    for p, a, b in (A, B):
        raw = io.open(p, encoding='utf-8', newline='').read()
        raws[p] = raw
        assert raw.count(a) == 1
        io.open(p, 'w', encoding='utf-8', newline='').write(raw.replace(a, b))
    r = subprocess.run(['node', 'scripts/test.mjs', '--maxWorkers=1', 'tests/live-writer.spec.ts'], cwd='dsh-ext', capture_output=True, text=True, encoding='utf-8', errors='replace')
    t = r.stdout + r.stderr
    for l in t.splitlines():
        if l.strip().startswith(('×', 'FAIL')) or 'Tests ' in l:
            print(l.strip()[:110])
finally:
    for p, raw in raws.items():
        io.open(p, 'w', encoding='utf-8', newline='').write(raw)
