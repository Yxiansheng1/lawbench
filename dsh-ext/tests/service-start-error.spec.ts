// 令 2048：干净机上服务 0.4 秒退出码 1，Host 日志只有 service.exit——要能看出为什么。
// 取服务标准错误最后 20 行里的最后一条"异常类名: 消息"，路径换掉，律师看到"本机服务未能启动：<消息>"。
import { lastErrorLine, Supervisor, type ChildHandle } from '../host/supervisor.ts'
import { scrubPaths, unavailableText } from '../host/index.ts'

const TRACE = [
  'Traceback (most recent call last):',
  '  File "<frozen runpy>", line 198, in _run_module_as_main',
  '  File "E:\\law\\service\\lawbench\\__main__.py", line 3, in <module>',
  '  File "E:\\law\\python\\Lib\\sqlite3\\__init__.py", line 57, in <module>',
  '    from sqlite3.dbapi2 import *',
  'ImportError: DLL load failed while importing _sqlite3: 应用程序控制策略已阻止此文件。',
  '',
].join('\r\n')

describe('服务起不来时说出原因（令 2048）', () => {
  it('取最后一条异常行；安装目录换成"<安装目录>"，别处的绝对路径只留文件名', () => {
    expect(lastErrorLine(TRACE)).toBe('ImportError: DLL load failed while importing _sqlite3: 应用程序控制策略已阻止此文件。')
    expect(lastErrorLine('no traceback here\nplain text')).toBeUndefined()
    expect(scrubPaths('OSError: cannot open E:\\law\\python\\DLLs\\_sqlite3.pyd', 'E:\\law')).toBe('OSError: cannot open <安装目录>\\python\\DLLs\\_sqlite3.pyd')
    expect(scrubPaths('FileNotFoundError: C:\\Users\\张三\\Desktop\\x.txt', 'E:\\law')).toBe('FileNotFoundError: x.txt')
  })

  it('反复退出到 failed：service.start_failed 带异常行，律师看到这句', async () => {
    const logged: Array<Record<string, unknown> | undefined> = []
    const s = new Supervisor({
      spawn(): ChildHandle {
        let done!: (c: number | null) => void
        const exited = new Promise<number | null>((r) => { done = r })
        setTimeout(() => done(1), 10)
        return { pid: 1, exited, kill: () => done(null), errorText: () => TRACE }
      },
      probe: async () => undefined,
      pickPort: async () => 18400,
      newToken: () => 't'.repeat(32),
      expectedVersion: '1.1',
      scrubPaths: (t) => scrubPaths(t, 'E:\\law'),
      log: (_l: string, e: string, m?: Record<string, unknown>) => { if (e === 'service.start_failed') logged.push(m) },
    })
    await s.start()
    const t0 = Date.now()
    while (s.state !== 'failed' && Date.now() - t0 < 5000) await new Promise((r) => setTimeout(r, 20))
    expect(s.state).toBe('failed')
    expect(logged).toEqual([{ reason: 'exited', exitCode: 1, error: 'ImportError: DLL load failed while importing _sqlite3: 应用程序控制策略已阻止此文件。' }])
    expect(unavailableText(s)).toBe('本机服务未能启动：ImportError: DLL load failed while importing _sqlite3: 应用程序控制策略已阻止此文件，请联系技术支持')
    s.stop()
  })
})
