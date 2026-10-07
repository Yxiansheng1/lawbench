// desk-actions.ts 的 DeskDeps 用真文件系统和真进程的实现（Host 里用）。
// 启动的程序与 Host 脱离（detached、不接输入输出），去掉 Electron 当 Node 跑的那个环境变量，免得小工具或资源管理器被它影响。
import { spawn } from 'node:child_process'
import { existsSync, statSync } from 'node:fs'
import { mkdir, rm } from 'node:fs/promises'
import { homedir } from 'node:os'
import { openableFolder, type DeskDeps } from './desk-actions.ts'

function start(file: string, args: string[]): Promise<void> {
  return new Promise((resolve, reject) => {
    const env = { ...process.env }
    delete env.ELECTRON_RUN_AS_NODE
    const child = spawn(file, args, { detached: true, stdio: 'ignore', windowsHide: false, env })
    child.once('error', reject)
    child.once('spawn', () => { child.unref(); resolve() })
  })
}

export function nodeDeskDeps(installDir: string | undefined, platform: NodeJS.Platform = process.platform): DeskDeps {
  return {
    installDir,
    userProfile: process.env.USERPROFILE ?? homedir(),
    exists: (p) => existsSync(p),
    isDir: (p) => { try { return statSync(p).isDirectory() } catch { return false } },
    openable: (root, rel) => openableFolder(root, rel),
    launch: (file, args) => start(file, args),
    // explorer.exe 打开成功也常返回非 0，这里只看能不能启动起来
    openPath: (dir) => (platform === 'darwin' ? start('open', [dir]) : start(`${process.env.SystemRoot ?? 'C:\\Windows'}\\explorer.exe`, [dir])),
    remove: (file) => rm(file, { force: false }),
    mkdir: async (dir) => { await mkdir(dir, { recursive: true }) },
  }
}
