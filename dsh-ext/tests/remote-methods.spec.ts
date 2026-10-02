// T13 执行令 Q1：界面插件自己 $mount 手写描述（不改 DSH 源码），本测试守着 Host 方法表与界面描述一致（方法名、参数名）。
import { LawbenchRemote } from '../host/index.ts'
import { LAWBENCH_REMOTE } from '../ui/remote.ts'
import { LAWBENCH_NAMESPACE, LAWBENCH_SERVICE, REMOTE_METHODS } from '../shared/remote-methods.ts'

const MARKER = '@deepseek-ai/dsh-typert-protocol/remote-methods'

/** 取函数的形参名（去掉默认值、类型已被编译去掉）。 */
function paramNames(fn: Function): string[] {
  const src = fn.toString()
  const open = src.indexOf('(')
  let depth = 0
  let close = open
  for (let i = open; i < src.length; i++) {
    if (src[i] === '(') depth++
    else if (src[i] === ')' && --depth === 0) { close = i; break }
  }
  return src.slice(open + 1, close).split(',').map((p) => p.trim().split(/[\s=]/)[0]!).filter(Boolean)
}

describe('lawbench 远程方法表', () => {
  const proto = LawbenchRemote.prototype as unknown as Record<string, unknown>

  it('方法表里的每个方法 Host 都有实现，形参名与顺序一致', () => {
    for (const { method, params } of REMOTE_METHODS) {
      const fn = proto[method]
      expect(typeof fn, method).toBe('function')
      expect(paramNames(fn as Function), method).toEqual([...params])
    }
  })

  it('Host 暴露给网关的方法标记恰好是方法表', () => {
    const marker = Object.getOwnPropertyDescriptor(LawbenchRemote.prototype, MARKER)?.value as { methods: { method: string, invocation: { kind: string } }[] }
    expect(marker.methods.map((m) => m.method)).toEqual(REMOTE_METHODS.map((m) => m.method))
    for (const m of marker.methods) expect(m.invocation.kind).toBe('direct')
  })

  it('界面 $mount 描述与方法表一致（方法名、参数名、服务、命名空间）', () => {
    expect(LAWBENCH_REMOTE.package).toBe('lawbench-dsh')
    expect(LAWBENCH_REMOTE.descriptors.map((d) => d.method)).toEqual(REMOTE_METHODS.map((m) => m.method))
    for (const [i, d] of LAWBENCH_REMOTE.descriptors.entries()) {
      const spec = REMOTE_METHODS[i]!
      expect(d.service).toBe(LAWBENCH_SERVICE)
      expect(d.namespace).toBe(LAWBENCH_NAMESPACE)
      expect(d.id).toBe(`lawbench-dsh#${LAWBENCH_NAMESPACE}/${spec.method}`)
      expect(d.parameters.map((p) => p.name)).toEqual([...spec.params])
      expect(d.parameters.map((p) => p.wire)).toEqual([...spec.params])
      for (const p of d.parameters) expect(p.codec.mode).toBe('strict')
      expect(d.result.mode).toBe('strict')
    }
  })

  it('描述的 id 与编解码器类型标识互不重复（网关遇重复端点会拒绝挂载）', () => {
    const ids = LAWBENCH_REMOTE.descriptors.map((d) => d.id)
    expect(new Set(ids).size).toBe(ids.length)
    const symbols = LAWBENCH_REMOTE.descriptors.flatMap((d) => [d.result.typeSymbol, ...d.parameters.map((p) => p.codec.typeSymbol)])
    expect(new Set(symbols).size).toBe(symbols.length)
  })
})

describe('界面调用的方法名都在方法表里（返修一并做：方法表盲点）', () => {
  // 两边都由 REMOTE_METHODS 生成，从表里删掉一个方法时两边一起消失、上面的测试仍绿；界面按字符串调用，要另外守
  const { readdirSync, readFileSync } = require('node:fs') as typeof import('node:fs')
  const { join } = require('node:path') as typeof import('node:path')
  const uiDir = join(__dirname, '..', 'ui')
  const sources = readdirSync(uiDir).filter((f: string) => /\.tsx?$/.test(f)).map((f: string) => readFileSync(join(uiDir, f), 'utf8')).join('\n')
  const called = new Set<string>()
  for (const m of sources.matchAll(/\bcall(?:<[\s\S]*?>)?\(\s*'([A-Za-z]+)'/g)) called.add(m[1]!)
  for (const m of sources.matchAll(/\blb\(\)\.([A-Za-z]+)\(/g)) called.add(m[1]!)

  it('找到的调用不少于已知的这些（防止扫描写法失效）', () => {
    for (const name of ['caseOpen', 'materialsImport', 'taskCreate', 'tasksList', 'importPastedImage', 'listSkills', 'getSettings', 'putSettings', 'setupState']) {
      expect(called, name).toContain(name)
    }
  })

  it('每一个都在方法表里', () => {
    const table = new Set(REMOTE_METHODS.map((m) => m.method))
    expect([...called].filter((n) => !table.has(n))).toEqual([])
  })
})
