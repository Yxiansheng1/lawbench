// 胶囊管理（U-11、F-CAP-02、Spec 10.3）的纯函数：排序、改名、隐藏 / 显示、新增。没有删除。
// 保存时服务端还会校验（PUT /api/capsules）；这里先按同样的规则拦一遍，给律师即时提示。

export interface SkillCapsule { id: string; name: string; kind: 'skill'; skills: string[]; outputs: string[]; hidden: boolean; custom: boolean }
export interface ToolCapsule { id: string; name: string; kind: 'tool'; tool: 'invoice' | 'retainer'; hidden: boolean; custom: boolean }
export type Capsule = SkillCapsule | ToolCapsule
export interface Group { id: string; name: string; hidden: boolean; items: Capsule[] }
export interface Capsules { v: 1; hint: string; shared: string[]; groups: Group[] }

export const GROUP_NAME_MAX = 8
export const CAPSULE_NAME_MAX = 12
export const TOOL_WORD: Record<ToolCapsule['tool'], string> = { invoice: '发票整理', retainer: '文件生成' }

const clone = (c: Capsules): Capsules => structuredClone(c)

/** 把胶囊移到某组的某个位置（同组、跨组都可以）。 */
export function moveCapsule(c: Capsules, id: string, toGroup: string, toIndex: number): Capsules {
  const out = clone(c)
  let moved: Capsule | undefined
  for (const g of out.groups) {
    const i = g.items.findIndex((x) => x.id === id)
    if (i >= 0) { moved = g.items.splice(i, 1)[0]; break }
  }
  const target = out.groups.find((g) => g.id === toGroup)
  if (!moved || !target) return c
  target.items.splice(Math.max(0, Math.min(toIndex, target.items.length)), 0, moved)
  return out
}

/** 分组整体移动位置。 */
export function moveGroup(c: Capsules, id: string, toIndex: number): Capsules {
  const out = clone(c)
  const i = out.groups.findIndex((g) => g.id === id)
  if (i < 0) return c
  const [g] = out.groups.splice(i, 1)
  out.groups.splice(Math.max(0, Math.min(toIndex, out.groups.length)), 0, g!)
  return out
}

/** 改名：去掉首尾空白；空名或超长返回错误提示。 */
export function rename(c: Capsules, id: string, name: string): Capsules | string {
  const n = name.trim()
  const out = clone(c)
  const g = out.groups.find((x) => x.id === id)
  if (g) {
    if (!n || [...n].length > GROUP_NAME_MAX) return `分组名称要 1 到 ${GROUP_NAME_MAX} 个字`
    g.name = n
    return out
  }
  for (const grp of out.groups) {
    const item = grp.items.find((x) => x.id === id)
    if (item) {
      if (!n || [...n].length > CAPSULE_NAME_MAX) return `胶囊名称要 1 到 ${CAPSULE_NAME_MAX} 个字`
      item.name = n
      return out
    }
  }
  return c
}

export function toggleHidden(c: Capsules, id: string): Capsules {
  const out = clone(c)
  for (const g of out.groups) {
    if (g.id === id) { g.hidden = !g.hidden; return out }
    const item = g.items.find((x) => x.id === id)
    if (item) { item.hidden = !item.hidden; return out }
  }
  return c
}

function allIds(c: Capsules): Set<string> {
  return new Set(c.groups.flatMap((g) => [g.id, ...g.items.map((x) => x.id)]))
}

/** 新胶囊的 id：custom-1、custom-2……，全局不重复（契约 id 只能是小写字母、数字、连字符）。 */
export function newCapsuleId(c: Capsules): string {
  const ids = allIds(c)
  let n = 1
  while (ids.has(`custom-${n}`)) n++
  return `custom-${n}`
}

/** 新增胶囊（F-CAP-02：从已安装的 Skill 或两个内置工具里选，并起名）。 */
export function addCapsule(
  c: Capsules, groupId: string, name: string,
  pick: { kind: 'skill'; skills: string[] } | { kind: 'tool'; tool: ToolCapsule['tool'] },
  installed: ReadonlySet<string>,
): Capsules | string {
  const n = name.trim()
  if (!n || [...n].length > CAPSULE_NAME_MAX) return `胶囊名称要 1 到 ${CAPSULE_NAME_MAX} 个字`
  const g = c.groups.find((x) => x.id === groupId)
  if (!g) return '请选择放在哪个分组'
  if (pick.kind === 'skill') {
    if (!pick.skills.length) return '请至少选一个 Skill'
    if (pick.skills.some((s) => !installed.has(s))) return '选的 Skill 里有未安装的'
  }
  const id = newCapsuleId(c)
  const item: Capsule = pick.kind === 'skill'
    ? { id, name: n, kind: 'skill', skills: [...pick.skills], outputs: [], hidden: false, custom: true }
    : { id, name: n, kind: 'tool', tool: pick.tool, hidden: false, custom: true }
  const out = clone(c)
  out.groups.find((x) => x.id === groupId)!.items.push(item)
  return out
}

/**
 * 保存前检查（同服务端 Spec 10.3）：id 全局唯一；默认配置里的每个分组和胶囊 id 都还在；shared、hint 与默认相同。
 * 返回问题说明；空数组表示可以保存。
 */
export function checkBeforeSave(c: Capsules, defaults: Capsules): string[] {
  const problems: string[] = []
  const seen = new Set<string>()
  for (const id of c.groups.flatMap((g) => [g.id, ...g.items.map((x) => x.id)])) {
    if (seen.has(id)) problems.push(`编号重复：${id}`)
    seen.add(id)
  }
  for (const id of allIds(defaults)) if (!seen.has(id)) problems.push('默认胶囊只能隐藏，不能删除')
  if (c.hint !== defaults.hint) problems.push('分流提示语不能改')
  if (JSON.stringify(c.shared) !== JSON.stringify(defaults.shared)) problems.push('共用 Skill 不能改')
  return [...new Set(problems)]
}

/** 首页显示用：去掉隐藏的分组和胶囊。 */
export function visible(c: Capsules): Group[] {
  return c.groups.filter((g) => !g.hidden).map((g) => ({ ...g, items: g.items.filter((x) => !x.hidden) }))
}
