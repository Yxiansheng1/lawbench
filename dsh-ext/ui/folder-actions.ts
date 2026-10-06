// 右栏"材料""成果"的两个按钮（令 2043 第 2 条，律师第一批反馈）：打开所在文件夹、移除此材料。
// 都经 Host（界面不能动本机文件）；移除 = Host 删文件 + 现有的重新扫描，服务据此把它从材料表和索引里去掉（N61）。
import { DEFAULT_TARGET } from './cases.ts'
import { errorText, type Material } from './format.ts'
import { call, confirm, notice, type CaseRef } from './state.ts'

/** 成果文件夹（服务的 OUTPUT_DIR，在案件根下）。 */
export const OUTPUT_DIR = '成果'

/**
 * 在资源管理器里打开案件下的文件夹。材料区开默认导入位置（还没建出来时开案件根）；成果区开"成果"。
 * @returns 打开了为 true。
 */
export async function openCaseFolder(c: CaseRef, which: 'materials' | 'outputs'): Promise<boolean> {
  const rel = which === 'materials' ? DEFAULT_TARGET : OUTPUT_DIR
  let r = await call<{ opened: true }>('openFolder', { root: c.root, rel })
  if (!r.ok && r.error.code === 'NOT_FOUND' && which === 'materials') r = await call<{ opened: true }>('openFolder', { root: c.root, rel: '' })
  if (!r.ok) { notice('文件夹没能打开', errorText(r.error)); return false }
  return true
}

/**
 * "移除此材料"暂不可用（令 2043 第 2 条的退路）：服务对删掉的原件只标"原件已删除"、保留文本，检索表也照样留着它的文字
 * （service/lawbench/case/materials.py 开头、search/fts.py refresh 只跳过 failed）——删文件 + 重新扫描做不到"从索引里去掉"。
 * 按令只做按钮禁用态，交主编排记 1.4；服务有了删除 / 重建索引的接口后把它改为 true，Host 的 materialRemove 和下面的确认流程已备好。
 */
export const MATERIAL_REMOVE_ENABLED = false
export const REMOVE_DISABLED_TIP = '暂不能在这里移除：删掉文件后，检索里还会留着它的文字。后续版本会支持；现在需要的话请联系技术支持。'

export const REMOVE_TITLE = '移除这份材料？'
export const removeText = (m: Pick<Material, 'name' | 'rel_path'>): string =>
  `会从案件文件夹里删掉"${m.rel_path}"这个文件，并从材料列表和检索里去掉。删掉的文件不进回收站，需要时请先自己留一份。已有的成果和 wiki 里引用到它的地方需要复核。`

/**
 * 移除一份材料：先确认，再让 Host 删文件并重新扫描。
 * @returns 移除了为 true（取消或失败为 false）。
 */
export async function removeMaterial(c: CaseRef, m: Pick<Material, 'name' | 'rel_path'>): Promise<boolean> {
  if (!await confirm(REMOVE_TITLE, removeText(m), '移除')) return false
  const r = await call<{ removed: number; review_needed: boolean }>('materialRemove', { case_id: c.case_id, root: c.root, rel_path: m.rel_path })
  if (!r.ok) { notice('材料没能移除', errorText(r.error)); return false }
  notice('已移除', `"${m.name}"已从案件里移除。${r.value.review_needed ? '材料有变化，案件 wiki 和已有成果需要复核。' : ''}`)
  return true
}
