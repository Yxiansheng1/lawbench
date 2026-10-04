// 输入区选能力（执行令 1156 第 3 条改版后）：点第二层的胶囊按钮；不在当前分类就逐个点第一层分类找；两层收起时先点"选能力"。
// id 为空串：点小标签上的 ×（回到自由对话）。
import { act } from 'react'

const click = async (el: Element) => { await act(async () => { (el as HTMLElement).click() }) }

export async function pickCapsule(container: HTMLElement, id: string): Promise<void> {
  if (id === '') {
    const x = container.querySelector('[aria-label="取消这项能力"]')
    if (x) await click(x)
    return
  }
  const find = () => container.querySelector(`[data-capsule-id="${id}"]`)
  if (!find()) {
    const toggle = [...container.querySelectorAll('button')].find((b) => b.textContent === '选能力')
    if (toggle) await click(toggle)
  }
  if (!find()) {
    for (const tab of container.querySelectorAll('[aria-label="能力入口"] [role=tab]')) {
      await click(tab)
      if (find()) break
    }
  }
  const btn = find()
  if (!btn) throw new Error(`没有这个胶囊：${id}`)
  await click(btn)
}

/** 输入区此刻选中的能力（胶囊 id；自由对话为"自由对话"）。 */
export const shownCapsule = (container: HTMLElement): string =>
  container.querySelector('[data-lawbench-dock]')?.getAttribute('data-capsule') || '自由对话'
