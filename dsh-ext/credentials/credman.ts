// Windows 凭据管理器"普通凭据"读写（Spec 8.1，D9）。
// 经 PowerShell 调 advapi32 的 CredReadW / CredWriteW / CredDeleteW：
// - 脚本用 -EncodedCommand 传入，脚本里没有 Key；
// - Key 只经标准输入 / 标准输出传递，不出现在命令行参数里（进程列表看不到）；
// - 凭据内容按 UTF-16LE 存，Python keyring 的 Windows 后端按 UTF-16 解码，读写对得上。
import { spawn } from 'node:child_process'

export const TARGET = 'lawbench/LAWFIRM_KEY'
export const USER = 'lawbench'

const PREAMBLE = String.raw`
$ErrorActionPreference = 'Stop'
Add-Type -TypeDefinition @'
using System; using System.Runtime.InteropServices; using System.Text;
public static class LbCred {
  [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
  public struct CREDENTIAL { public int Flags; public int Type; public string TargetName; public string Comment;
    public long LastWritten; public int CredentialBlobSize; public IntPtr CredentialBlob; public int Persist;
    public int AttributeCount; public IntPtr Attributes; public string TargetAlias; public string UserName; }
  [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)] static extern bool CredReadW(string t, int type, int flags, out IntPtr p);
  [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)] static extern bool CredWriteW(ref CREDENTIAL c, int flags);
  [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)] static extern bool CredDeleteW(string t, int type, int flags);
  [DllImport("advapi32.dll")] static extern void CredFree(IntPtr p);
  public static string Read(string target, string user) {
    IntPtr p; if (!CredReadW(target, 1, 0, out p)) return null;
    try { var c = (CREDENTIAL)Marshal.PtrToStructure(p, typeof(CREDENTIAL));
      if (c.UserName != user) return null;
      var b = new byte[c.CredentialBlobSize]; Marshal.Copy(c.CredentialBlob, b, 0, b.Length);
      return Encoding.Unicode.GetString(b); } finally { CredFree(p); } }
  public static void Write(string target, string user, string secret) {
    var b = Encoding.Unicode.GetBytes(secret); var h = Marshal.AllocHGlobal(b.Length);
    try { Marshal.Copy(b, 0, h, b.Length);
      var c = new CREDENTIAL { Type = 1, TargetName = target, UserName = user, CredentialBlob = h, CredentialBlobSize = b.Length, Persist = 2 };
      if (!CredWriteW(ref c, 0)) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error()); } finally { Marshal.FreeHGlobal(h); } }
  public static bool Delete(string target) { return CredDeleteW(target, 1, 0); }
}
'@
[Console]::InputEncoding = [Text.Encoding]::UTF8
[Console]::OutputEncoding = [Text.Encoding]::UTF8
`

/** PowerShell 子进程的总时限（T7 返修 P3-3）：挂住时结束它并报错，免得首次配置页和模型请求一直等。 */
export const TIMEOUT_MS = 15_000

function run(script: string, stdin: string, timeoutMs = TIMEOUT_MS): Promise<string> {
  const encoded = Buffer.from(PREAMBLE + script, 'utf16le').toString('base64')
  return new Promise((resolve, reject) => {
    const child = spawn('powershell.exe', ['-NoLogo', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded], { windowsHide: true })
    let out = ''
    let err = ''
    let timedOut = false
    const timer = setTimeout(() => { timedOut = true; child.kill() }, timeoutMs)
    child.stdout.setEncoding('utf8').on('data', (d: string) => { out += d })
    child.stderr.setEncoding('utf8').on('data', (d: string) => { err += d })
    child.on('error', (e) => { clearTimeout(timer); reject(e) })
    child.on('close', (code) => {
      clearTimeout(timer)
      if (timedOut) { reject(new Error(`凭据管理器操作超时（${timeoutMs / 1000} 秒）`)); return }
      // stderr 可能含异常信息，但不含 Key（Key 只在 stdin 里）；只取第一行给调用方
      if (code === 0) resolve(out)
      else reject(new Error(`凭据管理器操作失败（退出码 ${code}）：${err.split(/\r?\n/)[0] ?? ''}`))
    })
    child.stdin.end(stdin, 'utf8')
  })
}

/** 测试用：跑一段不带 Key 的脚本，用于验证超时。 */
export function runForTest(script: string, timeoutMs: number): Promise<string> { return run(script, '', timeoutMs) }

/** 读 Key；没有该条目（或用户名不符）返回 undefined。 */
export async function readKey(target = TARGET, user = USER): Promise<string | undefined> {
  const out = await run(
    `$v = [LbCred]::Read('${target}', '${user}'); if ($null -eq $v) { [Console]::Out.Write('0') } else { [Console]::Out.Write('1' + [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($v))) }`,
    '',
  )
  if (!out.startsWith('1')) return undefined
  return Buffer.from(out.slice(1).trim(), 'base64').toString('utf8')
}

/** 写 Key：Key 经标准输入传给 PowerShell。 */
export async function writeKey(secret: string, target = TARGET, user = USER): Promise<void> {
  if (!/^[\x21-\x7e]+$/.test(secret)) throw new Error('Key 只能是可见的 ASCII 字符')
  await run(`$s = [Console]::In.ReadToEnd(); [LbCred]::Write('${target}', '${user}', $s)`, secret)
}

/** 删除条目；不存在时返回 false。 */
export async function deleteKey(target = TARGET): Promise<boolean> {
  const out = await run(`[Console]::Out.Write([int][LbCred]::Delete('${target}'))`, '')
  return out.trim() === '1'
}
