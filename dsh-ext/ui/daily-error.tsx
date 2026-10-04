// 日常事务建不了、且不会自己好时（如"日常办公文件夹"在云同步文件夹里），侧栏底部一行说明（令 1347 一并做 P3-1）。
import { app } from './state.ts'
import { useStore } from './store.ts'
import { C } from './kit.tsx'

export const dailyErrorText = (e: { message: string }): string => `日常事务未能创建：${e.message}，请在设置里改"日常办公文件夹"。`

export function DailyErrorLine({ wide = true }: { wide?: boolean }) {
  const err = useStore(app, (s) => s.dailyError)
  if (!err || !wide) return null
  return <div role="alert" style={{ padding: '4px 8px', fontSize: 12, color: C.err, lineHeight: 1.5 }}>{dailyErrorText(err)}</div>
}
