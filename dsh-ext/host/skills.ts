// Skill 列表（T13 执行令 Q4）：Host 自己读 Skill 目录里的 SKILL.md 头部，按 contracts\skill\frontmatter.schema.json 校验。
// 只读 Skill 目录，不读案件。目录顺序与服务一致（管理员目录在前），同名 Skill 以先读到的为准（Spec 10.1）。
// 正文六部分与必问问题的写法以 skills\_scripts\skill_manifest.py 为准（Spec 10.2、20.10）。
import { readdir, readFile, stat } from 'node:fs/promises'
import { join } from 'node:path'
import { parse as parseYaml } from 'yaml'
import { validateRoot } from '../shared/contracts.ts'

const FRONTMATTER_ID = 'lawbench://contracts/skill/frontmatter.schema.json'
const REQUIRED_SECTIONS = ['适用场景', '输入', '必问问题', '处理步骤', '输出模板', '自检清单']
const QUESTION = /^- ([a-z][a-z0-9_]*)：(.+)（可从材料中获取：(是|否)）$/
const MAX_BYTES = 1024 * 1024

export interface SkillQuestion { key: string; question: string; fromMaterials: boolean }

export interface SkillInfo {
  name: string
  title: string
  description: string
  mode: 'agent' | 'pipeline'
  kind: 'excerpt' | 'analysis' | 'draft'
  params: Record<string, unknown>
  inputs: string[]
  questions: SkillQuestion[]
}

/** 解析一份 SKILL.md；不合格返回 undefined。 */
export function parseSkill(text: string): SkillInfo | undefined {
  const m = /^---\r?\n([\s\S]*?)\r?\n---\r?\n([\s\S]*)$/.exec(text.replace(/^﻿/, ''))
  if (!m) return undefined
  let head: unknown
  try { head = parseYaml(m[1]!) } catch { return undefined }
  if (validateRoot(FRONTMATTER_ID, head).length) return undefined
  const body = m[2]!
  const headings = new Set([...body.matchAll(/^## (.+?)\s*$/gm)].map((x) => x[1]))
  if (!REQUIRED_SECTIONS.every((s) => headings.has(s))) return undefined
  const section = /^## 必问问题\s*$([\s\S]*?)(?=^## |(?![\s\S]))/m.exec(body)?.[1] ?? ''
  const questions: SkillQuestion[] = []
  for (const line of section.split(/\r?\n/).map((l) => l.trim()).filter(Boolean)) {
    const q = QUESTION.exec(line)
    if (q) questions.push({ key: q[1]!, question: q[2]!, fromMaterials: q[3] === '是' })
    else if (line !== '无') return undefined
  }
  const h = head as Omit<SkillInfo, 'questions'>
  return { name: h.name, title: h.title, description: h.description, mode: h.mode, kind: h.kind, params: h.params, inputs: h.inputs, questions }
}

/** 按目录顺序读全部 Skill；invalid 是不合格的份数（只计数，不记名字和内容）。 */
export async function listSkills(dirs: readonly string[]): Promise<{ skills: SkillInfo[]; invalid: number }> {
  const seen = new Map<string, SkillInfo>()
  let invalid = 0
  for (const dir of dirs) {
    let names: string[]
    try { names = (await readdir(dir)).sort() } catch { continue }
    for (const name of names) {
      if (name.startsWith('_') || name.startsWith('.')) continue
      const file = join(dir, name, 'SKILL.md')
      try {
        const st = await stat(file)
        if (!st.isFile() || st.size > MAX_BYTES) continue
      } catch { continue }
      const info = parseSkill(await readFile(file, 'utf8').catch(() => ''))
      if (!info || info.name !== name) { invalid++; continue }
      if (!seen.has(info.name)) seen.set(info.name, info)
    }
  }
  return { skills: [...seen.values()], invalid }
}
