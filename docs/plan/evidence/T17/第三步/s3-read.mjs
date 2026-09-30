// 用 DSH 自己的 JSONL 包读一个根下的全部会话，报每个会话的事件数、记录头 cwd 是否为给定目录、是否含特征串（不输出内容）。
// 用法：node s3-read.mjs <根> <特征串>
import { createRequire } from 'node:module'
import { realpathSync } from 'node:fs'
import { pathToFileURL } from 'node:url'
const [root, token] = process.argv.slice(2)
const pkg = 'D:/lawbench-A/dsh/packages/session/session-persistence-jsonl'
const req = createRequire(pkg + '/package.json')
const { Context } = await import(pathToFileURL(realpathSync(req.resolve('@deepseek-ai/cordis'))).href)
const Jsonl = (await import(pathToFileURL(pkg + '/lib/index.js').href)).default
const ctx = new Context()
const fiber = await ctx.plugin(Jsonl, { root })
for (const s of await ctx.sessionPersistence.list()) {
  const h = await ctx.sessionPersistence.open(s.header.id, 'read')
  const { events } = await h.read()
  console.log(JSON.stringify({ id: s.header.id, events: events.length, types: [...new Set(events.map((e) => e.type))].slice(0, 8), hasToken: JSON.stringify(events).includes(token) }))
  await h.close()
}
await fiber.dispose()
