# T14 联调派修（执行令 1541）：逐个撤回 dsh-ext 侧修法，看对应用例是否变红；每次按原字节写回。
# 用法：python mutate.py <输出文件>（在仓库根下跑）。DSH 侧 P-9 的变异见交付说明（vitest 在 dsh\ 里跑）。
import io, re, subprocess, sys

EXT = 'dsh-ext/'
ONLY = sys.argv[2:]  # 给了名字片段就只跑名字含这些片段的
MUTS = [
    ('派修 2：Agent 到达用量上限时不记 BUDGET_STOPPED', EXT + 'agent/index.ts',
     "      this.noteBlocked(agent.id, BUDGET_STOPPED, state.taskId)\n", "", ['tests/agent.spec.ts']),
    ('派修 2：输入区收到 BUDGET_STOPPED 不显示草稿', EXT + 'ui/dock.tsx',
     "        if (r.ok && r.value?.code === BUDGET_STOPPED && typeof r.value.task_id === 'string') showTaskAnswer(sid, r.value.task_id)\n", "",
     ['tests/answer.spec.ts']),
    ('派修 2：Host turnNotice 不带任务编号', EXT + 'shared/turn-notices.ts',
     "    if (taskId !== undefined) this.tasks.set(sessionId, taskId)\n", "", ['tests/answer.spec.ts', 'tests/turn-notices.spec.ts']),
    ('派修 2：读草稿不核路径（result.json 写的任何 .md 都读）', EXT + 'host/task-answer.ts',
     "    .filter((d) => typeof d?.path === 'string' && ok.test(d.path) && typeof d.title === 'string' && num(d.version) !== null)",
     "    .filter((d) => typeof d?.path === 'string' && typeof d.title === 'string' && num(d.version) !== null)", ['tests/answer.spec.ts']),
    ('派修 2：草稿不设上限（整个读进来）', EXT + 'host/task-answer.ts',
     "    return { text: buf.subarray(0, max).toString('utf8').replace(/^\\uFEFF/, ''), truncated }",
     "    return { text: buf.toString('utf8').replace(/^\\uFEFF/, ''), truncated: false }", ['tests/answer.spec.ts']),
    ('派修 2：草稿正文出处不成按钮（不给 inlineMarks）', EXT + 'ui/answer.tsx',
     "<MarkdownText text={v.draft.text} labels={LABELS} inlineMarks={marks} />", "<MarkdownText text={v.draft.text} labels={LABELS} />", ['tests/answer.spec.ts']),
    ('派修 2：成果页"在对话区查看"不转会话', EXT + 'ui/results.tsx',
     "  if (target !== currentSession) getNav().openSession(target)\n", "", ['tests/answer.spec.ts']),
    ('派修 4：Host 没起来不记日志', EXT + 'session-store/index.ts',
     "if (core() === undefined) log('error', 'session_store.host_missing', { after_s: HOST_WAIT_S })", "if (core() === undefined) void 0",
     ['tests/session-store.spec.ts']),
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
report = '# T14 联调派修变异（撤回单处修法）\n\n' + '\n'.join(out)
io.open(sys.argv[1], 'w', encoding='utf-8').write(report)
