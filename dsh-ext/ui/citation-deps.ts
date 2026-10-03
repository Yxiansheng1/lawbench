// 出处点击用到的工作台状态：当前案件、材料列表、打开原文标签。对话区（DSH 的出处标记）和输入区上方的草稿（T14 派修 2）共用。
import { TABS } from './cases.ts'
import { getNav } from './kit.tsx'
import { app, call, currentCase, notice } from './state.ts'
import type { MaterialLite, OpenDeps } from './citation.ts'

/** 出处点击用到的工作台状态：当前案件、材料列表、打开原文标签。 */
export const citationDeps: OpenDeps = {
  caseId: () => currentCase(app.get())?.case_id,
  materials: async (caseId) => {
    const r = await call<{ materials: MaterialLite[] }>('materialsList', { case_id: caseId })
    return r.ok ? r.value.materials : undefined
  },
  notice,
  openSource: (materialId, citation) => getNav().openTab(TABS.source, { material_id: materialId, citation }),
}
