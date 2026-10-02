// 第三步验收：全盘搜特征字符串（UTF-8 与 UTF-16LE，zstd 压缩的文件解压后再搜）。
// 用法：node s3-search.mjs <特征串> <开始时刻 ISO> <案件目录> <DSH_HOME> <TEMP> <LOCALAPPDATA>
// 案件目录、DSH_HOME 全部文件都搜；TEMP、LOCALAPPDATA 只搜开始之后改过的文件（其余不可能含本次的特征串）。
// 只输出命中文件相对各根的位置和命中方式，不输出文件内容。
import { readdirSync, statSync, readFileSync } from 'node:fs'
import { join, relative } from 'node:path'
import { zstdDecompressSync } from 'node:zlib'

const [token, startIso, caseDir, dshHome, temp, localAppData] = process.argv.slice(2)
const start = new Date(startIso).getTime() - 2000
const needles = [Buffer.from(token, 'utf8'), Buffer.from(token, 'utf16le')]
const MAX = 200 * 1024 * 1024

function* walk(dir) {
  let entries
  try { entries = readdirSync(dir, { withFileTypes: true }) } catch { return }
  for (const e of entries) {
    const p = join(dir, e.name)
    if (e.isSymbolicLink()) continue
    if (e.isDirectory()) yield* walk(p)
    else if (e.isFile()) yield p
  }
}

function hit(buf) {
  if (needles.some((n) => buf.includes(n))) return 'raw'
  try {
    const out = zstdDecompressSync(buf)
    if (needles.some((n) => out.includes(n))) return 'zstd'
  } catch { /* 不是 zstd */ }
  return null
}

function scan(label, root, onlyRecent, skip = []) {
  const found = []
  let files = 0
  for (const p of walk(root)) {
    if (skip.some((s) => p.toLowerCase().startsWith(s.toLowerCase()))) continue
    let st
    try { st = statSync(p) } catch { continue }
    if (onlyRecent && st.mtimeMs < start) continue
    if (st.size > MAX) continue
    files++
    let buf
    try { buf = readFileSync(p) } catch { continue }
    const how = hit(buf)
    if (how) found.push(`${relative(root, p)}（${how}）`)
  }
  console.log(`## ${label}：检查 ${files} 个文件，命中 ${found.length} 个`)
  for (const f of found) console.log(`  ${f}`)
  return found.length
}

scan('案件目录（全部文件）', caseDir, false)
scan('$DSH_HOME（全部文件）', dshHome, false)
scan('%TEMP%（开始后改过的）', temp, true)
// LOCALAPPDATA 里 DSH_HOME 已单独搜过；Temp 在 LOCALAPPDATA 下也已单独搜过
scan('%LOCALAPPDATA%（开始后改过的，除上面两处）', localAppData, true, [dshHome, temp])
