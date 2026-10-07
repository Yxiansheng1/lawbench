// 令 2048：干净机上服务 0.4 秒退出码 1，Host 日志只有 service.exit——要能看出为什么。
// 取服务标准错误最后 20 行里的最后一条"异常类名: 消息"，路径换掉，律师看到"本机服务未能启动：<消息>"。
import { lastErrorLine, MAX_STARTUP_TIMEOUTS, Supervisor, type ChildHandle } from '../host/supervisor.ts'
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
  it('取最后一条异常行；安装目录换成"<安装目录>"，别处的绝对路径整个换成"<路径>"、不留文件名（复核 P2-3）', () => {
    expect(lastErrorLine(TRACE)).toBe('ImportError: DLL load failed while importing _sqlite3: 应用程序控制策略已阻止此文件。')
    expect(lastErrorLine('no traceback here\nplain text')).toBeUndefined()
    expect(scrubPaths('OSError: cannot open E:\\law\\python\\DLLs\\_sqlite3.pyd', 'E:\\law')).toBe('OSError: cannot open <安装目录>\\python\\DLLs\\_sqlite3.pyd')
    expect(scrubPaths('FileNotFoundError: C:\\Users\\张三\\Desktop\\x.txt', 'E:\\law')).toBe('FileNotFoundError: <路径>')
  })

  it('网络路径、带空格的路径（引号里、不带引号）、Python repr 的双反斜杠：都不漏出案件名、材料名', () => {
    const out = (t: string) => scrubPaths(t, 'E:\\law')
    expect(out("FileNotFoundError: [Errno 2] No such file or directory: '\\\\\\\\fs01\\\\案卷\\\\张某甲诈骗案\\\\起诉书.pdf'"))
      .toBe("FileNotFoundError: [Errno 2] No such file or directory: '<路径>'")
    expect(out('OSError: cannot open \\\\fs01\\案卷\\张某甲诈骗案\\起诉书.pdf')).toBe('OSError: cannot open <路径>')
    expect(out('PermissionError: "D:\\案件 2026\\李某 合同纠纷\\证据 清单.docx" is locked')).toBe('PermissionError: "<路径>" is locked')
    expect(out('OSError: D:\\案件 2026\\李某合同纠纷\\证据.docx busy')).toBe('OSError: <路径> busy')
    for (const t of ['张某甲', '李某', '起诉书', '证据', '案卷']) {
      expect(out("x: '\\\\\\\\fs01\\\\案卷\\\\张某甲诈骗案\\\\起诉书.pdf' D:\\案件 2026\\李某 合同\\证据.docx")).not.toContain(t)
    }
  })

  it('不带引号、最后一段带空格（令 1337 第 5 条）：吃到最后一个扩展名；没有扩展名吃到行尾；宁多吃', () => {
    const out = (t: string) => scrubPaths(t, 'E:\\law')
    expect(out('OSError: cannot open D:\\案件\\李某 合同纠纷 起诉书 定稿.docx')).toBe('OSError: cannot open <路径>')
    expect(out('OSError: D:\\案件\\证据 清单 第二版.pdf: permission denied')).toBe('OSError: <路径>: permission denied')
    expect(out('PermissionError: \\\\fs01\\案卷\\张某甲 诈骗案 卷宗 一.pdf busy\nnext line')).toBe('PermissionError: <路径> busy\nnext line')
    // 末段没有扩展名（文件夹）：吃到行尾，不吃下一行
    expect(out('NotADirectoryError: D:\\案件\\李某 合同纠纷\nTraceback')).toBe('NotADirectoryError: <路径>\nTraceback')
    // 复核 P2-1：日期、版本号里的点不是扩展名（扩展名须字母开头）
    expect(out('NotADirectoryError: D:\\案卷\\2026.10.07 张三 诉 李四')).toBe('NotADirectoryError: <路径>')
    expect(out('OSError: D:\\案卷\\张三 诉 李四 2026.10 定稿')).toBe('OSError: <路径>')
    expect(out('OSError: D:\\案卷\\孙八 案 第2.3稿 起诉状')).toBe('OSError: <路径>')
    // 同一行里两个扩展名：吃到最后一个（宁多吃）
    expect(out('OSError: D:\\x\\张三 证据.pdf and 李四 证言.docx')).toBe('OSError: <路径>')
    for (const t of ['李某', '合同纠纷', '起诉书', '清单', '张某甲', '卷宗', '张三', '李四']) {
      expect(out('a D:\\案件\\李某 合同纠纷 起诉书.docx\nb \\\\fs01\\案卷\\张某甲 卷宗.pdf x\nc D:\\x\\张三 证据.pdf 李四 清单.doc')).not.toContain(t)
    }
  })

  it('安装目录开头、但同一段里又夹着别的路径：整段换成"<路径>"，不留尾巴', () => {
    const out = (t: string) => scrubPaths(t, 'E:\\law')
    expect(out('OSError: E:\\law\\python\\x.pyd from C:\\Users\\张三\\证据 一.txt')).toBe('OSError: <路径>')
    // 复核 P2-2：后面跟的是 \\服务器\共享（归一化会把它压成 \服务器，要对原串查）
    expect(out('OSError: E:\\law\\python\\x.pyd from \\\\fs01\\案卷\\张三 诉 李四.pdf')).not.toContain('张三')
    expect(out('OSError: E:\\law\\python\\x.pyd from \\\\fs01\\案卷\\张三 诉 李四.pdf')).toBe('OSError: <路径>')
    expect(out('OSError: cannot open E:\\law\\python\\DLLs\\_sqlite3.pyd')).toBe('OSError: cannot open <安装目录>\\python\\DLLs\\_sqlite3.pyd')
    expect(out('ImportError: E:\\law\\python\\DLLs\\_sqlite3.pyd: 应用程序控制策略已阻止此文件。')).toBe('ImportError: <安装目录>\\python\\DLLs\\_sqlite3.pyd: 应用程序控制策略已阻止此文件。')
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

describe('一直没就绪（复核 P2-1）', () => {
  it('连续两次 30 秒没就绪就转 failed，写 service.start_failed（startup_timeout），不再一直"请稍后重试"', async () => {
    let t = 0
    const logged: Array<Record<string, unknown> | undefined> = []
    let spawns = 0
    const s = new Supervisor({
      spawn(): ChildHandle {
        spawns++
        let done!: (c: number | null) => void
        const exited = new Promise<number | null>((r) => { done = r })
        return { pid: spawns, exited, kill: () => done(null) }
      },
      probe: async () => { t += 10_000; return undefined }, // 虚拟时钟：每探一次过 10 秒
      pickPort: async () => 18500,
      newToken: () => 't'.repeat(32),
      expectedVersion: '1.1',
      now: () => t,
      log: (_l: string, e: string, m?: Record<string, unknown>) => { if (e === 'service.start_failed') logged.push(m) },
    })
    await s.start()
    const t0 = Date.now()
    while (s.state !== 'failed' && Date.now() - t0 < 15_000) await new Promise((r) => setTimeout(r, 20))
    expect(s.state).toBe('failed')
    expect(spawns).toBe(MAX_STARTUP_TIMEOUTS)
    expect(logged).toEqual([{ reason: 'startup_timeout' }])
    expect(unavailableText(s)).toBe('本机服务未能启动：30 秒内没有就绪，请联系技术支持')
  }, 20_000)
})
