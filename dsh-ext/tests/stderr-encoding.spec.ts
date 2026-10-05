// 复核 P2-2：服务以 -I 启动，中文系统上 stderr 接管道按 cp936（GBK）编码，Host 按 UTF-8 读 → 异常消息中文乱码。
// 修法：随包的 sitecustomize.py 把 stderr 改成 UTF-8（-I 下 site 照样导入它）。这里用本机 Python 照服务的方式（-I）跑一遍：
// 不加载它时输出是 GBK 字节（按 UTF-8 解就是乱码），加载后是 UTF-8。本机没有 Python 或系统代码页不是 GBK 时跳过对照那一半。
import { spawnSync } from 'node:child_process'
import { join } from 'node:path'
import { lastErrorLine } from '../host/supervisor.ts'

const SITECUSTOMIZE = join(__dirname, '..', '..', 'packaging', 'python', 'sitecustomize.py')
const MSG = 'DLL load failed while importing _sqlite3: 应用程序控制策略已阻止此文件。'
const python = (() => { const r = spawnSync('python', ['-c', 'import sys;print(sys.version_info[0])']); return r.status === 0 ? 'python' : undefined })()

function run(load: boolean): Buffer {
  const code = `${load ? `import runpy; runpy.run_path(r'${SITECUSTOMIZE}')\n` : ''}raise ImportError(${JSON.stringify(MSG)})`
  const env = { ...process.env }
  delete env.PYTHONIOENCODING
  delete env.PYTHONUTF8
  return spawnSync(python!, ['-I', '-c', code], { env }).stderr
}

describe.skipIf(!python)('服务标准错误的编码（复核 P2-2）', () => {
  it('加载 sitecustomize 后 stderr 是 UTF-8：Host 取到的异常行中文完好', () => {
    expect(lastErrorLine(run(true).toString('utf8'))).toBe(`ImportError: ${MSG}`)
  })

  it('对照：不加载时（中文系统）是 GBK 字节，按 UTF-8 解成乱码——这正是用户新机上看到的', () => {
    const cp = spawnSync(python!, ['-I', '-c', 'import locale;print(locale.getpreferredencoding(False))']).stdout.toString().trim()
    if (cp !== 'cp936') return
    const raw = run(false)
    expect(lastErrorLine(raw.toString('utf8'))).not.toBe(`ImportError: ${MSG}`)
    expect(new TextDecoder('gbk').decode(raw)).toContain(MSG)
  })
})
