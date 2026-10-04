// Build-time only (packaging\build.ps1 'package' step, T20 review P2-2): compare the third-party packages of two
// pnpm lock files of the bundled DSH runtime. Local package-set tarballs (keys with "@file:") are rebuilt every time
// and are left out; every other package must be the same name@version in both.
// Usage: node runtime-lock-compare.mjs <pinned pnpm-lock.yaml> <resolved pnpm-lock.yaml>
// Exit 0 = same third-party set; 1 = differs (the differences are printed).
import { readFileSync } from 'node:fs'

function thirdParty(file) {
  const text = readFileSync(file, 'utf8').replace(/\r\n/g, '\n')
  const start = text.indexOf('\npackages:\n')
  if (start < 0) throw new Error(`no packages: section in ${file}`)
  const rest = text.slice(start + '\npackages:\n'.length)
  const end = rest.search(/\n\S/)
  const section = end < 0 ? rest : rest.slice(0, end)
  const keys = new Set()
  for (const m of section.matchAll(/^ {2}'?([^'\s][^']*?)'?:\s*$/gm)) {
    if (!m[1].includes('@file:')) keys.add(m[1])
  }
  return keys
}

const [pinned, resolved] = process.argv.slice(2)
if (!pinned || !resolved) { console.error('usage: node runtime-lock-compare.mjs <pinned> <resolved>'); process.exit(2) }
const a = thirdParty(pinned)
const b = thirdParty(resolved)
const missing = [...a].filter((k) => !b.has(k)).sort()
const added = [...b].filter((k) => !a.has(k)).sort()
console.log(`runtime lock: ${a.size} pinned third-party packages, ${b.size} resolved`)
for (const k of missing) console.log(`  - ${k}`)
for (const k of added) console.log(`  + ${k}`)
process.exit(missing.length || added.length ? 1 : 0)
