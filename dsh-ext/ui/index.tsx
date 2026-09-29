// 界面插件 legal-ui（T13）的浏览器半边。经 DSH 的 modules 行加载（行名 = 包名 lawbench-dsh，导出 ./client）。
// 不得有读写案件文件的途径、不得有 127.0.0.1 以外的网络访问：一切数据经 ctx.remote.lawbench（Host 转工作台服务）。
import { useEffect, useState } from 'react'
import { LAWBENCH_REMOTE } from './remote.ts'

export const inject = ['slots', 'remote']

type Ctx = {
  slots: {
    inject(name: string, fn: () => unknown): unknown
    register(options: Record<string, unknown>, component: unknown): unknown
  }
  remote: { $mount(contribution: unknown): Promise<() => Promise<void>>; lawbench?: Record<string, (...a: unknown[]) => Promise<unknown>> }
  effect(fn: () => unknown, label?: string): void
  // cordis：子上下文只能读声明过的属性；remote.lawbench 要在 $mount 之后单独 inject 才能取（同 DSH 实验插件 voice-input 的写法）
  inject(deps: string[], apply: (ctx: Ctx) => void): Promise<void> & { dispose(): Promise<void> }
}

function SetupStatus({ load }: { load: () => Promise<unknown> }) {
  const [text, setText] = useState('读取中…')
  useEffect(() => {
    load().then((v) => setText(JSON.stringify(v)), (e: unknown) => setText(`读取失败：${(e as Error)?.message ?? ''}`))
  }, [load])
  return <div style={{ padding: 16 }}><h2>律师工作台</h2><p>工作台服务状态：{text}</p></div>
}

function registerUi(ctx: Ctx): void {
  const load = () => ctx.remote.lawbench!.setupState()
  ctx.slots.inject('settings.section', () => ctx.slots.register({
    name: 'settings.section', id: 'lawbench', order: -20, label: () => '律师工作台',
    inject: () => ({ load }),
  }, SetupStatus))
}

export async function apply(ctx: Ctx): Promise<() => Promise<void>> {
  const disposeRemote = await ctx.remote.$mount(LAWBENCH_REMOTE)
  const ui = ctx.inject(['remote.lawbench', 'slots'], registerUi)
  try { await ui } catch (error) { await ui.dispose(); await disposeRemote(); throw error }
  return async () => { await ui.dispose(); await disposeRemote() }
}
