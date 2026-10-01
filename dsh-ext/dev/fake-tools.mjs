// 开发期假服务（fake-service.mjs）的发票整理与委托材料两条接口（T26 界面开发和桌面端截图用，不属于产品）。
// /api/invoice/run：按契约 1.3 校验请求，按动作回一段虚构的引擎输出；一个动作"进行中"（--invoice-delay 毫秒）时
//   后到的请求回 ENGINE_BUSY（真服务等锁 2 秒）；日常办公文件夹没设时回 OFFICE_DIR_NOT_SET（env_check 除外）；
//   --invoice-blocked <动作,…> 这些动作回 [BLOCKED] 失败体（failed:true）。
// /api/retainer/driver：给了 --retainer-python <python.exe> 时真的起 engines\retainer\tools\ocr-driver\driver.py
//   （只监听 127.0.0.1:17801，同 T25 真服务的命令行），否则只记状态；--retainer-stop-stuck：stop 回 running:true。
import { spawn } from 'node:child_process'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const ENGINES = join(dirname(fileURLToPath(import.meta.url)), '..', '..', 'engines')

const OUT = {
  env_check: [0, '[OK] 引擎运行环境已就绪\n[OK] 本地识别可用\n[OK] 台账目录可写'],
  history: [0, '历史未报 2 张（虚构）：\n  044002400111  2026-07-12  办公用品  312.00\n  044002400112  2026-08-03  交通  88.50\n清单已存：_任务\\{period}\\历史未报清单.json'],
  plan: [0, '已建本期任务 {period}（渠道 {channel}，历史票 {history}）'],
  run: [2, '导入 5 张：新增 3 张，重复 1 张，待核 1 张（抬头不符）\n明细见 _任务\\{period}\\收集对账表.xlsx'],
  analyze: [2, '对账：可入账 3 张，待核 1 张，重复 1 张'],
  import: [0, '入账 3 张，台账已更新'],
  prepare: [0, '贴票包已生成：{ledger}\\_打印\\{batch}\\'],
  reprint: [0, '已重印：{ledger}\\_打印\\{batch}\\'],
  cancel: [0, '批次 {batch} 已取消'],
  reimburse_preview: [0, '[预览] 批次 {batch}：3 张，合计 1,566.50 元。确认后标为已报销'],
  reimburse: [0, '批次 {batch} 已标为已报销'],
  // 真引擎对不带 --confirm 的 review 直接报错（workflow.py:155），没有预览
  review_preview: [2, '[BLOCKED] ValueError 逐张核对原票后，填写reviewer并加--confirm'],
  review: [0, '核验结果已写入台账'],
  exclude: [0, '已排除 1 项；本期不再计入该票'],
  // 同真引擎 invoice_db.py report：整个台账的统计，没有批次参数
  report: [0, '台账统计（全部）：已入账 12 张，合计 8,431.20 元\n  已报销 9 张，6,864.70 元\n  待报销 3 张，1,566.50 元\n  未入批次 1 张'],
  check_schema: [0, '台账结构正常'],
}

export function makeTools({ arg, flag, check, fail, ok, settings }) {
  const delay = Number(arg('--invoice-delay', '600'))
  const blocked = new Set((arg('--invoice-blocked', '') ?? '').split(',').filter(Boolean))
  const python = arg('--retainer-python', null)
  const stuck = flag('--retainer-stop-stuck')
  let busy = false
  let driver = null
  let driverRunning = false

  const health = async () => {
    try { const r = await fetch('http://127.0.0.1:17801/health', { signal: AbortSignal.timeout(800) }); return r.ok ? await r.json() : null } catch { return null }
  }

  async function invoice(body) {
    const v = check('api/invoice_run', 'request', body)
    if (v.length) return [fail('INVALID_ARGUMENT', '请求参数有误'), v]
    if (busy) {
      await new Promise((r) => setTimeout(r, 2000))
      if (busy) return [fail('ENGINE_BUSY', '发票整理正在进行中，请稍后再试')]
    }
    const office = settings()?.office ?? {}
    if (body.action !== 'env_check' && !office.dir) return [fail('OFFICE_DIR_NOT_SET', '还没有设置日常办公文件夹')]
    busy = true
    try {
      await new Promise((r) => setTimeout(r, delay))
      if (blocked.has(body.action)) return [ok({ exit_code: 2, attention: false, failed: true, output: '[BLOCKED] ValueError 收集任务有待处理或数量不符项', files: [] })]
      const key = (body.action === 'reimburse' || body.action === 'review') && !(body.apply || body.confirm) ? `${body.action}_preview` : body.action
      const ledger = `${office.dir}\\发票台账`
      const [code, text] = OUT[key]
      const output = text.replace(/\{(\w+)\}/g, (_m, k) => ({ ledger, ...body }[k] ?? ''))
      if (output.startsWith('[BLOCKED]')) return [ok({ exit_code: code, attention: false, failed: true, output, files: [] })]
      const files = body.action === 'run' && office.invoice_buyer ? [`${ledger}\\_打印\\${body.batch}\\贴票清单（${office.invoice_buyer}）.html`] : []
      return [ok({ exit_code: code, attention: code === 2, failed: false, output, files })]
    } finally { busy = false }
  }

  async function retainer(body) {
    const v = check('api/retainer_driver', 'request', body)
    if (v.length) return [fail('INVALID_ARGUMENT', '请求参数有误'), v]
    const value = (running, message) => ok({ running, port: 17801, message })
    if (body.action === 'status') return [value(driverRunning, driverRunning ? '证件识别已启动' : '证件识别未启动')]
    if (body.action === 'start') {
      if (!python) { driverRunning = true; return [value(true, '证件识别已启动（假服务，未起驱动）')] }
      if ((await health())?.ready) { driverRunning = true; return [value(true, '证件识别已启动')] }
      const dir = join(ENGINES, 'retainer', 'tools', 'ocr-driver')
      driver = spawn(python, [join(dir, 'driver.py'), '--port', '17801', '--host', '127.0.0.1', '--engine', 'rapidocr'], { cwd: dir, stdio: 'ignore', windowsHide: true })
      for (let i = 0; i < 60; i++) {
        if ((await health())?.ready) { driverRunning = true; return [value(true, '证件识别已启动')] }
        await new Promise((r) => setTimeout(r, 500))
      }
      return [value(false, '证件识别没有启动成功')]
    }
    if (stuck) return [value(true, '关闭未完成，请稍后再试')]
    if (driver) { driver.kill(); driver = null }
    driverRunning = false
    return [value(false, '证件识别已停止')]
  }

  return {
    handle(method, path, body) {
      if (method === 'POST' && path === '/api/invoice/run') return invoice(body)
      if (method === 'POST' && path === '/api/retainer/driver') return retainer(body)
      return null
    },
    close() { if (driver) driver.kill() },
  }
}
