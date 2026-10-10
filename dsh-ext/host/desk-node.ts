// desk-actions.ts 的 DeskDeps 用真文件系统和真进程的实现（Host 里用）。
// 启动的程序与 Host 脱离（detached、不接输入输出），去掉 Electron 当 Node 跑的那个环境变量，免得小工具或资源管理器被它影响。
import { spawn, type ChildProcess, type SpawnOptions } from 'node:child_process'
import { existsSync, statSync } from 'node:fs'
import { mkdir } from 'node:fs/promises'
import { homedir } from 'node:os'
import { openableFolder, type DeskDeps } from './desk-actions.ts'

/**
 * 交给 explorer.exe 的路径参数（第七版待办 16）：一律用双引号包起来。Node 只给含空格的参数加引号，
 * 名字里有逗号、等号而没有空格的路径会原样传过去，explorer 把逗号、等号当成参数分隔，结果打开的是"文档"（真机核过：
 * "…\甲,乙"不加引号开到"文档"，加了引号开对；文件"借款合同,补充协议.txt"同样）。Windows 路径里不会有双引号。
 * 末尾的反斜杠去掉（否则引号前的反斜杠会被当成转义）；盘根（D:\）原样传。
 */
export function explorerArg(path: string): string {
  if (/^[A-Za-z]:[\\/]*$/.test(path)) return path
  return `"${path.replace(/[\\/]+$/, '')}"`
}

/** 启动进程的做法（默认 node 的 spawn；用例换成替身，看传了什么）。 */
export type SpawnFn = (file: string, args: string[], options: SpawnOptions) => Pick<ChildProcess, 'once' | 'unref'>

function start(spawnFn: SpawnFn, file: string, args: string[], verbatim = false): Promise<void> {
  return new Promise((resolve, reject) => {
    const env = { ...process.env }
    delete env.ELECTRON_RUN_AS_NODE
    const child = spawnFn(file, args, { detached: true, stdio: 'ignore', windowsHide: false, env, windowsVerbatimArguments: verbatim })
    child.once('error', reject)
    child.once('spawn', () => { child.unref(); resolve() })
  })
}

export function nodeDeskDeps(installDir: string | undefined, platform: NodeJS.Platform = process.platform, spawnFn: SpawnFn = spawn): DeskDeps {
  return {
    installDir,
    userProfile: process.env.USERPROFILE ?? homedir(),
    exists: (p) => existsSync(p),
    isDir: (p) => { try { return statSync(p).isDirectory() } catch { return false } },
    openable: (root, rel) => openableFolder(root, rel),
    launch: (file, args) => start(spawnFn, file, args),
    // explorer.exe 打开成功也常返回非 0，这里只看能不能启动起来
    openPath: (dir) => (platform === 'darwin' ? start(spawnFn, 'open', [dir]) : start(spawnFn, `${process.env.SystemRoot ?? 'C:\\Windows'}\\explorer.exe`, [explorerArg(dir)], true)),
    mkdir: async (dir) => { await mkdir(dir, { recursive: true }) },
  }
}
