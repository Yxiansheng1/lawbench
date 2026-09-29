// 临时 Agent 插件（T4）：只注册一个 case_ping 工具，用来验证 preset-lawbench 挂载和工具白名单。
// T7 用正式的 legal-agent 替换本插件。不依赖 DSH 包，直接给出 ToolDefinition（JSON Schema 参数）。

export const name = 'lawbench-agent-ping'
export const inject = ['tools']

export function apply(ctx) {
  ctx.tools.register({
    name: 'case_ping',
    description: '检查律师工作台工具链是否连通。返回 pong 和收到的 text。',
    parameters: {
      type: 'object',
      properties: {
        text: { type: 'string', description: '任意短文本，原样返回' },
      },
      additionalProperties: false,
    },
    output: {
      schema: {
        type: 'object',
        properties: {
          pong: { type: 'boolean' },
          text: { type: 'string' },
        },
        required: ['pong', 'text'],
        additionalProperties: false,
      },
      render(_args, value) {
        return [{ type: 'text', text: JSON.stringify(value) }]
      },
    },
    async execute(args) {
      return { pong: true, text: typeof args?.text === 'string' ? args.text : '' }
    },
  })
}
