// @vitest-environment jsdom
// 改编自契约 1.2 第三轮复核员的实验 rv-a19-skl3.spec.ts（E3）与 rv-a19-ic.spec.ts（E4、E6、E7、E8、E8b、E11、E12、E13，两种挂载模式），
// 收为回归用例（T13 第四轮返修）：打印改为断言，复核员原有断言保留；夹具见 helpers/dock-lab.ts。
import { act } from 'react'
import { INPUT_CHANGED_TEXT } from '../ui/dock.tsx'
import { app, setIntent } from '../ui/state.ts'
import { A, B, begin, button, CASE, click, flush, h, mount, paramsPanel, pick, send, setup, status, teardown, turnEnded, unmount, verdict, X } from './helpers/dock-lab.ts'

const IC = INPUT_CHANGED_TEXT
beforeEach(setup)
afterEach(teardown)

// P2-1：Skill 列表比"防抖 0.5 秒 + 写成"还慢，默认参数先写成、记为已保存；列表回来后参数框改显示 Skill 预设，要重写
it('E3 首页胶囊 A，Skill 列表慢 1.5 秒：写给服务的参数与参数框一致，发送后参数框不变', async () => {
  h.svc.skillsDelay = 1500
  setIntent(CASE.case_id, { capsuleId: A, skill: A, params: null, inputs: [] })
  await mount('S1')
  for (let i = 0; i < 50; i++) await flush(50)
  await click('参数')
  const panel = paramsPanel()
  expect(panel).toMatchObject({ window: '64K' })
  expect(h.svc.cur('S1')?.params).toEqual(panel)
  expect(app.get().selections['S1']?.saved).toBe(true)
  const r = await send('S1')
  expect(verdict(r)).toBe('一致')
  expect(paramsPanel()).toEqual(panel)
})

async function prepA_X(go: (s: string) => Promise<void>, s = 'S1') {
  await go(s); await pick(A); await act(async () => { setIntent(CASE.case_id, { inputs: [X] }) }); await flush(700)
  expect(h.svc.cur(s)).toMatchObject({ entry: A, inputs: [X] })
}

for (const remount of [false, true]) {
  const M = remount ? '重挂' : '不重挂'
  describe(`INPUT_CHANGED 第三轮复核实验（${M}）`, () => {
    beforeEach(async () => { await mount('S1'); if (remount) { await unmount(); await mount('S1', true) } })
    const go = (s: string) => mount(s, remount)

    it('E4（NOTE R1）重选同一份必须真 POST（计数、快照刷新），写成后 staleServer 已清', async () => {
      await prepA_X(go)
      h.svc.versions[X] = 1
      expect(await send('S1')).toBe('被拦下'); expect(status()).toBe(IC)
      const n = h.svc.creates.length
      await pick(B); await flush(200); await pick(A); await flush(700)
      expect(h.svc.creates.length - n).toBe(1)
      expect(h.svc.cur('S1')?.stamp).toEqual([1])
      expect(app.get().staleServer['S1']).toBeUndefined()
      expect(verdict(await send('S1'))).toBe('一致')
    })

    it('E6 S1 在后台被拦：S2 上不显示 S1 的提示、S2 挂上不取走 S1 的；回 S1 才显示', async () => {
      await prepA_X(go)
      await go('S2'); await flush(100)
      h.svc.versions[X] = 1
      expect(h.svc.run('S1')).toBe('被拦下'); await turnEnded('S1')
      const s2 = status()
      await go('S2'); await flush(100)
      const s2b = status()
      const still = h.svc.notices.take('S1'); h.svc.notices.note('S1', still ?? 'NONE')
      expect(s2).not.toBe(IC); expect(s2b).not.toBe(IC); expect(still).toBe('INPUT_CHANGED')
      await go('S1'); await flush(100)
      expect(status()).toBe(IC)
    })

    // P3-1：挂上时提示比读回晚到，不能把已读完的 loadedFor 清掉
    it('E7 挂上时 turnNotice 比 task/current 慢 50ms：改选写成后状态行回到就绪，成果区的选用照常带入', async () => {
      await prepA_X(go)
      await go('S2'); await flush(100)
      h.svc.versions[X] = 1
      h.svc.run('S1'); await turnEnded('S1')
      h.svc.noticeDelay = 50
      await go('S1'); await flush(100)
      expect(status()).toBe(IC)
      await pick(B); await flush(700)
      expect(status()).toContain('合同起草')
      await act(async () => { setIntent(CASE.case_id, { inputs: [] }) }); await flush(700)
      expect(app.get().intents[CASE.case_id]).toBeFalsy()
      expect(status()).toContain('合同起草')
      expect(h.svc.cur('S1')).toMatchObject({ entry: B, inputs: [] })
    })

    // P3-2：被拦那一轮前后刚改过选择，B 写成后提示要清
    it('E8 被拦下的那一轮进行中律师已改选 B（还没写）：一轮结束、B 写成后不误报，成功几轮也不出提示', async () => {
      await prepA_X(go)
      h.svc.versions[X] = 1
      expect(begin('S1')).toBe('被拦下')
      await pick(B); await flush(100)
      await turnEnded('S1')
      await flush(700)
      expect(h.svc.cur('S1')?.entry).toBe(B)
      expect(status()).not.toBe(IC)
      const r = await send('S1')
      expect(r).toBe(B); expect(verdict(r)).toBe('一致'); expect(status()).not.toBe(IC)
      const r2 = await send('S1')
      expect(verdict(r2)).toBe('一致'); expect(status()).not.toBe(IC)
    })

    it('E8b 改选 B 后 0.2 秒内发送（这一轮按服务的 A 跑、被拦下），B 随后写成：不误报', async () => {
      await prepA_X(go)
      h.svc.versions[X] = 1
      await pick(B); await flush(200)
      expect(begin('S1')).toBe('被拦下')
      await turnEnded('S1'); await flush(700)
      expect(status()).not.toBe(IC)
      const r = await send('S1')
      expect(r).toBe(B); expect(status()).not.toBe(IC)
    })

    // P3-3：取提示在途时切走，取到的提示不能丢
    it('E13 取 turnNotice 在途时律师切走：回 S1 仍显示提示，发时不会显示就绪却被拦', async () => {
      await prepA_X(go)
      await go('S2'); await flush(100)
      h.svc.versions[X] = 1
      h.svc.run('S1'); await turnEnded('S1')
      h.svc.noticeDelay = 100
      await go('S1'); await flush(20)
      await go('S2'); await flush(200)
      h.svc.noticeDelay = 0
      await go('S1'); await flush(100)
      expect(status()).toBe(IC)
      const r = begin('S1')
      expect(verdict(r)).not.toMatch(/^不一致/)
    })

    it('E11 INPUT_CHANGED 后重选同一份但写失败 → 重试成功', async () => {
      await prepA_X(go)
      h.svc.versions[X] = 1
      await send('S1')
      h.svc.mode = 'unavailable'
      await pick(B); await flush(200); await pick(A); await flush(700)
      expect(button('重试')).toBeTruthy()
      expect(verdict(begin('S1'))).not.toMatch(/^不一致/)
      h.svc.mode = 'ok'; await click('重试'); await flush(700)
      expect(h.svc.cur('S1')?.stamp).toEqual([1])
      expect(verdict(await send('S1'))).toBe('一致')
    })

    it('E12 成功一轮之后不误报：提示已显示、律师改选写成、成功一轮', async () => {
      await prepA_X(go)
      h.svc.versions[X] = 1
      await send('S1'); expect(status()).toBe(IC)
      await pick(B); await flush(200); await pick(A); await flush(700)
      const r = await send('S1')
      expect(r).toBe(A); expect(status()).not.toBe(IC)
      const r2 = await send('S1'); expect(verdict(r2)).toBe('一致')
    })
  })
}
