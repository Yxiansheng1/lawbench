// 新建案件时的子文件夹（令 1852 第 17 条，第七版待办 17）：律师在列表里勾选，默认全不勾，可自填一级目录。
// 界面（勾选框、自填名检查）和 Host（按名单建文件夹）共用这一份；不依赖 node，界面也能用。
// 两套标准目录同 contracts\formats.md 第 1.1 节、服务 service\lawbench\case\registry.py 的 TEMPLATES（tests\case-folders.spec.ts 读源码对照）。

export type CaseKind = 'civil' | 'criminal'

export interface TemplateFolder {
  /** 一级目录名。 */
  readonly name: string
  /** 二级目录（勾了一级就一并建）。 */
  readonly subs: readonly string[]
}

const TRIAL6 = ['我方文件', '我方证据', '对方文件', '对方证据', '庭审准备', '法院文书'] as const
const INVEST5 = ['我方文件', '我方证据', '对方文件', '对方证据', '法律研究'] as const

export const CASE_TEMPLATES: Readonly<Record<CaseKind, readonly TemplateFolder[]>> = {
  civil: [
    { name: '01委托手续', subs: [] },
    { name: '02案件材料', subs: [] },
    { name: '03一审', subs: TRIAL6 },
    { name: '04二审', subs: TRIAL6 },
    { name: '05执行', subs: ['执行申请', '财产线索', '法院文书'] },
    { name: '06法律研究', subs: [] },
  ],
  criminal: [
    { name: '01委托手续', subs: [] },
    { name: '02案件材料', subs: ['会见笔录', '家属沟通', '涉案证据'] },
    { name: '03侦查阶段', subs: INVEST5 },
    { name: '04审查起诉阶段', subs: INVEST5 },
    { name: '05一审', subs: TRIAL6 },
    { name: '06二审', subs: TRIAL6 },
    { name: '07申诉与再审', subs: [] },
    // 名字里的"/"与服务、委托材料工具（engines\retainer\data\config.json）一致：实际建成"08执行（财产刑"下的"民事赔偿）"两级
    { name: '08执行（财产刑、民事赔偿）', subs: [] },
  ],
}

export const KIND_WORD: Readonly<Record<CaseKind, string>> = { civil: '民商事', criminal: '刑事' }

/** 律师选了哪些：标准目录里勾的一级目录名、自己填的一级目录名。 */
export interface FolderChoice {
  readonly tops: readonly string[]
  readonly custom: readonly string[]
}

/** 服务自己建、律师不能拿来当子文件夹的名字（同 gate.py 的 WORK、OUTPUT）。 */
export const RESERVED_TOPS = ['工作区', '成果'] as const
/** 自填最多几项、每项最长几个字（同 safeFolderName 截的长度）。 */
export const MAX_CUSTOM = 20
export const MAX_NAME = 80

/**
 * Windows 设备名，与服务 service\lawbench\case\gate.py 的 is_device_name / DEVICE_NAMES 同一套（注记 0934 ②）：
 * 去尾部点和空格、取第一个点之前的部分再去尾部空格，不分大小写比对；含 com0/lpt0、com¹²³/lpt¹²³、conin$/conout$（"CON .txt" 同样算）。
 */
const DEVICE_NAMES = new Set(['con', 'prn', 'aux', 'nul', 'conin$', 'conout$',
  ...['com', 'lpt'].flatMap((d) => [...'0123456789¹²³'].map((n) => d + n))])
export function isDeviceName(name: string): boolean {
  return DEVICE_NAMES.has(name.replace(/[ .]+$/, '').split('.')[0]!.replace(/ +$/, '').toLowerCase())
}

/** 文件夹名里 Windows 不许的字符换成"_"，去掉首尾空格和点；空了用"新案件"。 */
export function safeFolderName(name: unknown): string {
  const s = typeof name === 'string' ? name : ''
  // 复核 P3：先截长度再去首尾空格和点（截完末尾可能又是空格或点）；保留名带扩展名也不行（CON.txt）
  const t = s.replace(/[<>:"/\\|?*\u0000-\u001f]/g, '_').slice(0, MAX_NAME).replace(/^[\s.]+|[\s.]+$/g, '')
  return t === '' || isDeviceName(t) ? '新案件' : t
}

/**
 * 自填的一级目录名有什么问题（复用 safeFolderName：它会改动的名字就不收，不替律师改名）。
 * @returns 一句给律师看的说明；没问题为 null。
 */
export function customFolderProblem(name: string): string | null {
  if (name.trim() === '') return '请填文件夹名'
  if (name.length > MAX_NAME) return `文件夹名最多 ${MAX_NAME} 个字`
  if (/[<>:"/\\|?*\u0000-\u001f]/.test(name)) return '文件夹名里不能有 \\ / : * ? " < > | 这些符号'
  if (/^[\s.]|[\s.]$/.test(name)) return '文件夹名不能以空格或点开头、结尾'
  if (isDeviceName(name) || safeFolderName(name) !== name) return `"${name}"是 Windows 保留的名字，不能用作文件夹名`
  if (RESERVED_TOPS.some((r) => r.toLowerCase() === name.toLowerCase())) return `"${name}"由工作台自己建，不用另加`
  return null
}

/**
 * 按律师的选择列出要建的相对路径（正斜杠），顺序同标准目录、自填的排在后面；一级目录后紧跟它的二级目录。
 * 标准目录里没有的一级名、有问题的自填名、重复的都不列（Host 收到的请求再核一遍）。
 */
export function folderRels(kind: CaseKind, choice: FolderChoice): string[] {
  const tops = new Set(choice.tops)
  const out: string[] = []
  const seen = new Set<string>()
  const add = (rel: string) => { const k = rel.toLowerCase(); if (!seen.has(k)) { seen.add(k); out.push(rel) } }
  for (const f of CASE_TEMPLATES[kind]) {
    if (!tops.has(f.name)) continue
    add(f.name)
    for (const s of f.subs) add(`${f.name}/${s}`)
  }
  for (const c of choice.custom) if (customFolderProblem(c) === null) add(c)
  return out
}
