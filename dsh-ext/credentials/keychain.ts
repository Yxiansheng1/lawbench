// macOS 钥匙串"通用密码"读写（T28；Windows 的 credman.ts 的对应物，Spec 8.1、D9 口径不变）。
// 经系统自带的 /usr/bin/security：
// - 条目 service=lawbench/LAWFIRM_KEY、account=lawbench，与服务端 Python keyring 的 macOS 后端读的是同一条；
// - 写入走 `security -i`，命令从标准输入进，Key 按十六进制（-X）写在那一行里：Key 不出现在命令行参数里（进程列表看不到）；
//   交互模式的退出码不可靠，写完再读一次核对；
// - -T 列出可以不弹窗读取的程序：security 自己、Host（Electron）、内置 python3（服务端读 Key 用）。
import { spawn } from 'node:child_process'

export const TARGET = 'lawbench/LAWFIRM_KEY'
export const USER = 'lawbench'
export const SECURITY = '/usr/bin/security'
/** security 子进程的总时限，同 credman.ts。 */
export const TIMEOUT_MS = 15_000
/** find/delete 找不到条目时 security 的退出码（errSecItemNotFound）。 */
const NOT_FOUND = 44

export type Spawner = typeof spawn

function run(args: string[], stdin: string, spawner: Spawner = spawn, timeoutMs = TIMEOUT_MS): Promise<{ code: number | null; out: string }> {
  return new Promise((resolve, reject) => {
    const child = spawner(SECURITY, args, { windowsHide: true })
    let out = ''
    let timedOut = false
    const timer = setTimeout(() => { timedOut = true; child.kill() }, timeoutMs)
    child.stdout?.setEncoding('utf8').on('data', (d: string) => { out += d })
    child.stderr?.on('data', () => { /* 不带出诊断信息（同 credman.ts） */ })
    child.on('error', (e) => { clearTimeout(timer); reject(e) })
    child.on('close', (code) => {
      clearTimeout(timer)
      if (timedOut) { reject(new Error(`钥匙串操作超时（${timeoutMs / 1000} 秒）`)); return }
      resolve({ code, out })
    })
    child.stdin?.end(stdin, 'utf8')
  })
}

/** 读 Key；没有该条目返回 undefined。 */
export async function readKey(target = TARGET, user = USER, spawner: Spawner = spawn): Promise<string | undefined> {
  const { code, out } = await run(['find-generic-password', '-s', target, '-a', user, '-w'], '', spawner)
  if (code === NOT_FOUND) return undefined
  if (code !== 0) throw new Error(`钥匙串操作失败（退出码 ${code}）`)
  const v = out.replace(/\r?\n$/, '')
  return v.length ? v : undefined
}

/** 写 Key（已存在则覆盖）：整条命令经标准输入给 `security -i`。trusted：可免弹窗读取的程序的完整路径。 */
export async function writeKey(secret: string, trusted: readonly string[] = [], target = TARGET, user = USER, spawner: Spawner = spawn): Promise<void> {
  if (!/^[\x21-\x7e]+$/.test(secret)) throw new Error('Key 只能是可见的 ASCII 字符')
  const apps = [SECURITY, ...trusted].filter((p) => /^\/[^"\r\n]*$/.test(p)).map((p) => ` -T "${p}"`).join('')
  const hex = Buffer.from(secret, 'utf8').toString('hex')
  const line = `add-generic-password -U -s "${target}" -a "${user}"${apps} -X ${hex}\n`
  const { code } = await run(['-i'], line, spawner)
  if (code !== 0 && code !== null) throw new Error(`钥匙串操作失败（退出码 ${code}）`)
  if ((await readKey(target, user, spawner)) !== secret) throw new Error('钥匙串操作失败（写入后核对不一致）')
}

/** 删除条目；不存在时返回 false。 */
export async function deleteKey(target = TARGET, user = USER, spawner: Spawner = spawn): Promise<boolean> {
  const { code } = await run(['delete-generic-password', '-s', target, '-a', user], '', spawner)
  if (code === NOT_FOUND) return false
  if (code !== 0) throw new Error(`钥匙串操作失败（退出码 ${code}）`)
  return true
}
