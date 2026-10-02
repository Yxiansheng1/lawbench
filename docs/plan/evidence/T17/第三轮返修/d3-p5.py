# T17 第三轮返修 A-P3-6：P-5 里"问导入钩子"的循环抽成一个小函数，intakeFirst 与 addFiles 共用。
# 用法：python d3-p5.py <dsh 根>
import io, sys
p = sys.argv[1] + '/packages/client/ui-conversation/src/client/apply.ts'
raw = io.open(p, encoding='utf-8', newline='').read()
nl = '\r\n' if '\r\n' in raw else '\n'
s = raw.replace('\r\n', '\n')
old = """      const bridge = hostPathBridge()
      return {
        keyboard: shell,
        // lawbench P-5: the composer asks the hooks before its image-limit pre-check,
        // so a batch over the chat attachment limits still reaches the import hook.
        intakeFirst: (files, directories = new Set()) => {
          if (sessions.binding(sessionId) === undefined) return undefined
          for (const hook of intakeHooks) {
            const taken = hook(sessionId, files, directories)
            if (taken !== undefined) return taken
          }
          return undefined
        },
        addFiles: (files, directories = new Set()) => {
          if (sessions.binding(sessionId) === undefined) return t('file.sessionUnavailable')
          for (const hook of intakeHooks) {
            const taken = hook(sessionId, files, directories)
            if (taken !== undefined) return taken
          }
          if (shell.snapshot.phase"""
new = """      const bridge = hostPathBridge()
      // lawbench P-5: the first hook returning a non-`undefined` result takes the files.
      const askIntake = (files: readonly File[], directories: ReadonlySet<File>): string | null | undefined => {
        for (const hook of intakeHooks) {
          const taken = hook(sessionId, files, directories)
          if (taken !== undefined) return taken
        }
        return undefined
      }
      return {
        keyboard: shell,
        // lawbench P-5: the composer asks the hooks before its image-limit pre-check,
        // so a batch over the chat attachment limits still reaches the import hook.
        intakeFirst: (files, directories = new Set()) => {
          if (sessions.binding(sessionId) === undefined) return undefined
          return askIntake(files, directories)
        },
        addFiles: (files, directories = new Set()) => {
          if (sessions.binding(sessionId) === undefined) return t('file.sessionUnavailable')
          const taken = askIntake(files, directories)
          if (taken !== undefined) return taken
          if (shell.snapshot.phase"""
assert s.count(old) == 1, s.count(old)
s = s.replace(old, new)
io.open(p, 'w', encoding='utf-8', newline='').write(s.replace('\n', nl))
print('d3-p5 ok')
