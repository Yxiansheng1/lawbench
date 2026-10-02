# T17 N55 ② 与第七至九轮返修（活着的会话所在案件挪走了：不搬写入者，整轮拒绝并提示重启）：逐个撤回修法，看对应用例是否变红；每次按原字节写回。
# 用法：python mutate.py <输出文件>（在仓库根下跑）
import io, re, subprocess, sys

EXT = 'dsh-ext/'
LIVE = ['tests/live-writer.spec.ts']
ONLY = sys.argv[2:]  # 给了名字片段就只跑名字含这些片段的
MUTS = [
    ('判定：不看名单（根不在名单上也不算失效）', EXT + 'session-store/router.ts',
     "    return !this.current(w.at) || !existsSync(w.at.caseRoot!) || this.recordGone(w)", "    return !existsSync(w.at.caseRoot!) || this.recordGone(w)",
     LIVE + ['tests/session-store.spec.ts']),
    ('判定：不看盘（根不在盘上也不算失效）', EXT + 'session-store/router.ts',
     "    return !this.current(w.at) || !existsSync(w.at.caseRoot!) || this.recordGone(w)", "    return !this.current(w.at) || this.recordGone(w)",
     LIVE + ['tests/session-store.spec.ts']),
    ('判定：放下过的不算失效（放下后又被拒过一轮、根回到名单就放行）', EXT + 'session-store/router.ts',
     "    return !!w && (w.detached || this.invalid(w))", "    return !!w && this.invalid(w)",
     LIVE),
    ('判定：关掉的写句柄不从表里去掉', EXT + 'session-store/router.ts',
     "      if (this.writers.get(w.id) === w) this.writers.delete(w.id)\n", "",
     ['tests/session-store.spec.ts']),
    ('拒绝：Agent 插件不看位置失效', EXT + 'agent/index.ts',
     "    if (step === 1 && this.caseMoved(agent.id)) {", "    if (false) {",
     LIVE + ['tests/agent.spec.ts']),
    ('第八轮 B-F1：位置失效的判断不排在最前（只剩先 next() 再判的那个）', EXT + 'agent/index.ts',
     "    (payload.step === 1 && caseMoved(payload.agent.id)", "    (false && caseMoved(payload.agent.id)",
     LIVE),
    ('第八轮 B-F2：不判会话自己的记录还在不在', EXT + 'session-store/router.ts',
     "    return !this.current(w.at) || !existsSync(w.at.caseRoot!) || this.recordGone(w)", "    return !this.current(w.at) || !existsSync(w.at.caseRoot!)",
     LIVE),
    ('第八轮 B-F2：新建会话不等原版落盘就判记录在不在', EXT + 'session-store/router.ts',
     "    if (!w.seen) {\n      w.seen = this.onDisk(w)\n      return false\n    }\n", "",
     LIVE),
    ('第八轮 B-F5：接回时以写方式打开不设上限', EXT + 'session-store/router.ts',
     "        fresh = await within(w.at.backend.open(id, 'write'), this.opts.caseRootTimeoutMs ?? 3000)", "        fresh = await w.at.backend.open(id, 'write')",
     ['tests/session-store.spec.ts']),
    ('不写旧处：根不在名单上时不放下写入者', EXT + 'session-store/router.ts',
     "    if (this.toDetach(w)) {", "    if (false) {",
     LIVE),
    ('第七轮 B-F1：根不在盘上（拔盘）也放下', EXT + 'session-store/router.ts',
     "    return !w.detached && !this.current(w.at) && existsSync(w.at.caseRoot!)", "    return !w.detached && !this.current(w.at)",
     LIVE),
    ('第七轮 A-P2-1：接回核对的内存事件数在打开新句柄之前取', EXT + 'session-store/router.ts',
     "      let fresh: Handle\n      try {\n        fresh = await within(w.at.backend.open(id, 'write'), this.opts.caseRootTimeoutMs ?? 3000)\n      } catch (e) { fail('session_store.writer_reattach_failed', e); return }\n      let n = -1\n      try {\n        n = (await within((fresh.read as () => Promise<{ events: unknown[] }>).call(fresh), this.opts.caseRootTimeoutMs ?? 3000)).events.length\n      } catch (e) { fail('session_store.writer_reattach_failed', e) }\n      if (n !== this.opts.liveSeq(id) ||",
     "      const early = this.opts.liveSeq(id)\n      let fresh: Handle\n      try {\n        fresh = await within(w.at.backend.open(id, 'write'), this.opts.caseRootTimeoutMs ?? 3000)\n      } catch (e) { fail('session_store.writer_reattach_failed', e); return }\n      let n = -1\n      try {\n        n = (await within((fresh.read as () => Promise<{ events: unknown[] }>).call(fresh), this.opts.caseRootTimeoutMs ?? 3000)).events.length\n      } catch (e) { fail('session_store.writer_reattach_failed', e) }\n      if (n !== early ||",
     LIVE),
    ('第七轮 B-F4：放下不设上限（关句柄挂住就一直等）', EXT + 'session-store/router.ts',
     "      await within(closeHandle(w.cur), this.opts.caseRootTimeoutMs ?? 3000)", "      await closeHandle(w.cur)",
     ['tests/session-store.spec.ts']),
    ('第七轮 A-P3-2：放下失败不记日志', EXT + 'session-store/router.ts',
     ".catch((e: unknown) => fail('session_store.writer_detach_failed', e))", ".catch(() => undefined)",
     ['tests/session-store.spec.ts']),
    ('第七轮 A-P3-3：代理方法转给最初那个句柄（接回后不是同一个）', EXT + 'session-store/router.ts',
     "        const v = Reflect.get(w.cur, prop, w.cur)\n        return typeof v === 'function' ? v.bind(w.cur) : v",
     "        const v = Reflect.get(h, prop, h)\n        return typeof v === 'function' ? v.bind(h) : v",
     ['tests/session-store.spec.ts']),
    ('不写旧处：打开案件后的刷新不等放下写入者就返回', EXT + 'session-store/index.ts',
     "    await refresh(true)\n    await recheckWriters()\n", "    await refresh(true)\n",
     LIVE),
    ('不写旧处：先记"已放下"再关（并发的另一次 recheck 不等关完）', EXT + 'session-store/router.ts',
     "      await within(closeHandle(w.cur), this.opts.caseRootTimeoutMs ?? 3000).catch((e: unknown) => fail('session_store.writer_detach_failed', e))\n      w.detached = true\n",
     "      w.detached = true\n      await within(closeHandle(w.cur), this.opts.caseRootTimeoutMs ?? 3000).catch((e: unknown) => fail('session_store.writer_detach_failed', e))\n",
     LIVE),
    ('正在跑的一轮：不等结束就放下（不看 Agent 状态）', EXT + 'session-store/index.ts',
     "      if (agents?.get(id)?.status !== 'running') { await recheckOne(id); continue }", "      { await recheckOne(id); continue }",
     LIVE),
    ('解除：根回到名单不在原处接回', EXT + 'session-store/router.ts',
     "    } else if (w.detached && !this.invalid(w) && this.opts.liveSeq) {", "    } else if (false) {",
     LIVE),
    ('解除：接回时不核对盘上与内存一样长', EXT + 'session-store/router.ts',
     "      if (n !== this.opts.liveSeq(id) || this.writers.get(id) !== w) {", "      if (this.writers.get(id) !== w) {",
     LIVE),
    ('解除：同一会话的 recheck 不排队', EXT + 'session-store/router.ts',
     "    const run = (this.rechecking.get(id) ?? Promise.resolve()).then(() => this.recheckOnce(id))", "    const run = this.recheckOnce(id)",
     LIVE),
    ('提示：输入区不提示 CASE_MOVED', EXT + 'ui/dock.tsx',
     "        if (r.ok && r.value?.code === 'CASE_MOVED') showNotice(CASE_MOVED_TITLE, CASE_MOVED_TEXT)\n", "",
     ['tests/dock-a19.spec.ts']),
    ('提示：输入区不提示 CASE_NOT_FOUND', EXT + 'ui/dock.tsx',
     "        if (r.ok && r.value?.code === 'CASE_NOT_FOUND') showNotice(CASE_MOVED_TITLE, CASE_NOT_FOUND_TEXT)\n", "",
     ['tests/dock-a19.spec.ts']),
]


def run(tests):
    r = subprocess.run(['node', 'scripts/test.mjs', '--maxWorkers=1', *tests], cwd=EXT, capture_output=True, text=True, encoding='utf-8', errors='replace')
    text = r.stdout + r.stderr
    fails = sorted(set(l.strip() for l in re.findall(r'(?m)^\s*(?:FAIL|×)\s+(.+?)(?:\s+\d+ms)?$', text)))
    summary = re.findall(r'(?m)^\s+Tests\s+(\d.+)$', text)
    return (summary[-1].strip() if summary else '?'), fails


out = []
for name, path, a, b, tests in MUTS:
    if ONLY and not any(k in name for k in ONLY):
        continue
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
report = '# T17 N55 ② 与第七至九轮返修变异（撤回单处修法）\n\n' + '\n'.join(out)
io.open(sys.argv[1], 'w', encoding='utf-8').write(report)
