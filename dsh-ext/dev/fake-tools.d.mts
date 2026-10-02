// 类型声明（tests\fake-tools.spec.ts 用）：开发假服务的发票与委托材料接口
export function makeTools(deps: {
  arg(name: string, dflt: string | null): string | null
  flag(name: string): boolean
  check(id: string, def: string, value: unknown): string[]
  fail(code: string, message: string): unknown
  ok(value: unknown): unknown
  settings(): { office?: { dir?: string | null; invoice_buyer?: string | null } } | undefined
}): { handle(method: string, path: string, body: unknown): Promise<unknown> | null; close(): void }
