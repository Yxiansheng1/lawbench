# T17 第三步"活着的句柄"第七轮返修后累计（第八轮）· Reviewer B（影响半径、边缘情况与回归安全）

- target：line-A `d0ab339`（已 rebase 到 main 69b0376）；本轮重审 `d0ab339`
- 冻结清单：`review-综合裁决-第七轮.md` 第 2 节
- 派发：两名 Opus 5.5 只读复核员同一条消息并发派出，素材相同，互相看不到
- 复核克隆：scratchpad `rv-A30`
- 归档：主编排于 2026-10-02 15:23 (+08:00) 从复核员交回原文抄录，未改内容

## 复核员原文
## 复核员 B（影响半径、边缘情况、回归安全）· T17 N55 ② 第七轮返修后累计 · line-A `d0ab339`

我亲自核过克隆 rv-A30：HEAD 是 `d0ab3398bb3e…`，`git status` 干净，`69b0376` 是它的祖先。实验在 `git archive` 导出的副本里做。DSH 是我自己 clone 的 `477b4f4`，13 个补丁按 PATCHES 顺序 `git apply --check` 全部无错并已应用。依赖用 `pnpm install --offline`（store 用 `D:\.pnpm-store`）在副本里装，然后整体 `pnpm run build`。

**结论**：本轮两条阻断按清单修好了。拔盘那一轮的回答保住了（E2/E2b）；接回竞态在 0–30 毫秒扫描里 36 次全部正常，第七轮 A 报的 2–12 毫秒窗口没有了。

但 B-F1 改成"搬家不放下"之后，有一处影响半径作者的测试照不到：DSH 生产插件树里有 `session-checkpoint-policy`，桌面端运行时清单显示它 enabled、active。作者的 live-writer 测试环境没加载这个插件。加载后，**搬家路径上每一轮都报 DSH 的英文 ENOENT 错误（带完整路径），不再出现 CASE_MOVED 中文提示**。这是 N55 ② 的主路径，不变量 ② 在真实组合下破了。按判法 → REJECT。修法约 4 行，我在副本里试过有效。

---

### Findings

**F1【P1｜本次引入的回归｜范围内阻断】搬家后在新位置打开、回老会话发话：没有中文提示，只有英文报错（含完整路径）**

- **问题**：根不在盘上时写入者不再放下，被拒那一轮的"律师那句话"事件进了原版写入者的缓冲。
  - DSH 的 `session-checkpoint-policy` 在 `agent/pre-step` 里先 `sessions.flush(session)`。往已不存在的旧路径写缓冲失败（ENOENT），flush 抛错（`core/session/src/index.ts:1209`）。
  - 我方 Agent 插件的 pre-step 是先 `await next()` 再判 `caseMoved`（`dsh-ext\agent\index.ts:197-198`），所以永远走不到我方的判断。
  - 结果：这一轮按 `agent/error` 结束，`noteTurnBlocked` 没被调，界面拿不到 CASE_MOVED。
- **影响**：
  - 律师看到的是 DSH 自己的英文错误，错误文字含旧案件文件夹的完整路径，看不到"刚才这句没有发出，重启软件后请重新发送"。
  - 没调模型，旧处、新处、全盘都 0 写入，重启后续写照常。所以不变量 ①、③ 守住，② 破了。
- **证据**（`rv-A30-B-specs\zz-rvb30.spec.ts`，live-writer 同一套真 AgentLoop + 我方会话存储、Agent 插件、Host caseOpen，另加载 checkpoint 插件）：
  - `C0[none]`（不加载，等同作者测试）：`notice:"CASE_MOVED", errors:[]`。
  - `C0[after]`、`C0[before]`（插件在我方之后或之前加载，两种顺序都试了）：两轮都是 `notice:null, errors:["Error:ENOENT: no such file or directory, open '<旧路径>…"]`。
  - 两种模式下都是 `calls:0`、`oldExists:false`、`newSame:true`、`tmpHasOne:0`，重启后 `hasMoved:false`。
  - 对照：把 `toDetach` 改回 `1b024f8` 的条件（去掉 `existsSync`）后，`C0[after]` 恢复为 `notice:"CASE_MOVED", errors:[]`。说明是本轮引入的。按原字节写回，SHA256 一致。
  - 运行时清单 `docs\plan\evidence\T17\plugin-inventory-desktop.json`：`include:session-checkpoint-policy … "enabled":true,"fiberPhase":"active"`。
- **顺带**：同一机制让"盘暂时不在、名单没变"（第 5 例，C2）也只有英文错误。这是 `1b024f8` 起就有的，下面的修法一并修好。
- **最小修复（副本实测有效）**：在 `agent/index.ts` 另登记一个 `prepend: true` 的 pre-step，在调 `next()` 之前先判位置失效：
  ```ts
  ctx.on('agent/pre-step', (async (payload, next) =>
    (payload.step === 1 && (ctx.get?.('sessionPersistence') as …)?.caseMoved?.(payload.agent.id) === true
      ? agent.preStep(payload.agent, 1, { kind: 'enter', messages: [] } as never) : next())) as never, { prepend: true })
  ```
  - 实测：C0、C2 在 after、before 两种顺序下都回到 `CASE_MOVED, errors:[]`。
  - E2（C3）、E2b（C3b）、接回（C5）不变。
  - live-writer + agent 两个 spec 26 项通过。按原字节写回。
  - 另须把 `session-checkpoint-policy` 加进 live-writer 的环境，至少搬家一例要加，不然这一路没有测试守着。

**F2【P2｜本次引入的回归（角落）｜可放进同一轮返修或记独立后续】搬家后，原路径又建了另一个案件并打开，回老会话发话**

- **问题**：旧根重新上了名单、也在盘上，所以 `caseMoved=false`，这一轮放行。但会话文件在新文件夹里不存在，写不进去。
- **证据**（C4）：
  - 生产组合（加载 checkpoint 插件）：`calls:0, notice:null`，只有英文 ENOENT 错误。
  - 不加载 checkpoint 插件时：`calls:1, notice:null, errors:[]`，模型回答了，盘上 0 处，重启后没有。这是静默丢，生产里被 checkpoint 插件挡成报错。
  - 修前（去掉 `existsSync` 的对照）：`caseMoved:true, notice:"CASE_MOVED"`。
- **最小修复**：`invalid(w)` 判"这个会话自己的记录还在"，例如 `existsSync(w.at.root)` 或查会话文件，不只判 `caseRoot`；或者写入者后台写失败过一次就算位置失效。

**F3【P2｜独立后续（T20 / P-4，不属 T17）】干净 clone 打完 13 个补丁后 `pnpm run build` 编译失败**

- **证据**：
  - `apps/desktop/scripts/development-app.ts`、`package-macos.ts`、`package-target.ts`、`smoke-packaged-runtime.ts`、`tests/package-macos.spec.ts` 五处报 `TS7016 Could not find a declaration file for module './lawbench-product.mjs'`。
  - `packaging\build.ps1:85` 的 dsh 步就是 `pnpm run build`。
  - 我在副本里临时补了一行 `lawbench-product.d.mts` 才编过去，补的文件随实验目录一起删了。
  - 线 A 自己的 dsh 能编，大概率靠增量编译缓存（未确证）。
- **最小修复**：P-4 补丁带上 `lawbench-product.d.mts`，或在调用处改成 `.ts`。

**F4【P3｜臆测，静态推断】放下超时转后台后，这期间的事件会写进旧处**

- 原版 `close()` 的循环会把关闭期间新进缓冲的事件一起落盘（`storage.ts:231-240`），律师在后台关闭期间发的那句会在盘恢复后写进旧处。
- 只在盘挂住超过 3 秒时出现，属于不变量 ① 的边角。建议在 10.4 记一句。

**F5【P3｜臆测，静态推断】接回时的 `open`、`read` 没有上限**

- `router.ts:230-234` 没套 `within`。复制后在挂住的网络盘上重新打开原位置，`refreshNow` 会一直等，caseOpen 不返回。B-F4 只给"关"加了上限。

**F6【P3｜独立后续】DSH 自己的日志带完整路径**

- 原版后台写失败的 warn 是 `String(error)`，含完整路径（`storage.ts:537`）；F1 的 agent/error 文字也含路径。
- 本轮起，搬家后每被拒一轮记一次（拔盘时原来就有）。属于日志卫生，DSH 侧要么过滤，要么记已知限制。

**NOTE｜派单第 2 项"搬家不放下会不会内存涨、静默丢"的答复**

- 缓冲里只有被拒那几轮的事件（每轮约 3 条：话、开始、被拦下）。dispose 36 毫秒、不报错，量级可以忽略。
- 内容就是被拒的那句话，提示里已经说了"没有发出、请重新发送"，10.4 也写了"被拒的那句话不保存"。所以不算新的静默丢——前提是 F1 修好、提示能出来。旧路径不会被重建：已落盘的会话追加用 `open(path,'a')`，不 mkdir，实测 `oldExists:false`。

---

### 冻结清单逐条核对（`review-综合裁决-第七轮.md` 第 2 节）

| 编号 | 结论 |
|---|---|
| B-F1 | 已做，E2/E2b 实测回答保住、插回解除。**带出 F1、F2** |
| A-P2-1 | 已做，X4 0–30 毫秒共 36 次（两种模式）全部正常，flush 无错 |
| B-F2 已知限制 | 10.4、11.5 已写；E1 实测有 CASE_MOVED 提示（`old_has_QUEUED=1`，非静默） |
| A-P3-1 | 已做 |
| A-P3-2 | 已做，只记 `{index, error 名}` |
| A-P3-3 | 已做，代理转给 `w.cur`，session-store.spec 有例 |
| A-P3-4 / B-F6 | PATCHES.md 已补"close 可重复调用"和"放下依赖 Agent 插件" |
| B-F4 | 已做，`within(…,3000)`，注释已改；F4、F5 为余项 |
| 提示文字 | 已改，界面用语检查零命中 |
| A-NOTE-1 重导出插件清单 | 两份文件已更新（我没有独立重导） |
| B-F5、B-F7、A-NOTE-2 | 按定性记独立后续 |

### 不变量核对（真 AgentLoop + 真会话存储 + 我方插件；"生产组合"指另加 checkpoint 插件）

| 不变量 | 结论 | 依据 |
|---|---|---|
| ① 复制或搬家后旧处字节不变、新处不被写 | 守住；B-F2 是已知限制，F4 臆测 | C0、C1、E4 全盘 0；X4 `newHasSay=0` |
| ② 每轮被拒有中文提示、不静默丢回答 | **破（F1，生产组合的搬家主路径）**；F2 是角落 | C0[after]、C0[before] |
| ③ 重启后在新位置续写照常 | 守住 | live-writer 1、2；C0.restart |
| ④ 不误判 | 刷新失败、空列表（E6）、盘暂时不在、E2 都守住；生产组合下第 5 例只有英文错（原来就有，F1 修法一并修好） | C2、C3、C3b |
| ⑤ 登记不记两处 | 守住 | rvb22 Y 系列 |
| ⑥ 案件外不能新建、不能续写 | 守住 | 全量套件 |

### 活性

- 放下有 3 秒上限（session-store.spec 100 毫秒那例）。
- 等 idle 不设超时，但只监听一次、`waiting` 去重，不死锁。
- pre-step 不死循环：E1 状态只有 running→idle。
- 名单刷新只遍历活写句柄，有限。
- 例外：接回那一路没有上限（F5）。

### 八项清单

- **契约一致**：没有改契约。
- **边界输入**：F1、F2、F4。
- **错误路径**：F1 不通过。
- **日志不含正文**：我方新日志通过；DSH 自身日志带路径，见 F6。
- **路径闸门**：没被绕过。
- **无外连**：只到 127.0.0.1。
- **测试覆盖新代码**：不足，测试环境缺生产插件 checkpoint-policy，F1 漏了。
- **无机密入库**：通过。

### 回归

- **dsh-ext 全量**：31 个文件，498 项通过、5 项跳过。T13 N51、T26 第 1、2 步、T20 自检的用例都在其中。
- **其他检查**：`tsc` 通过，`build.mjs` 通过，`check_ui_words` 零命中，`check_examples` 通过。
- **前几轮 B 的 spec**（第五轮 Y、第六轮 J/S/R/N/L/P、第七轮 E1–E6/E3c，`writerLost`→`caseMoved` 改断言）：46 项里 44 项通过。没过的 Y1、R1 和第七轮一样，是测试自身与新做法不符。
- **第二步补丁测试**（DSH 补丁新增或改动的 29 个测试文件，含 P-9/P-15/P-5 的 main-startup、lawbench-request-policy、media-references.host、apply-inject、input-bar）：529 项通过。
  - 3 项在机器忙时 5 秒超时，单独加长时限重跑 20/20 通过。
  - `ui-settings-general/apply.client.spec` 整个套件起不来：测试运行时解析不了 `dsh-web-app`。是否属于基线没核，见证据缺口。

### 实际跑过的命令

- `git rev-parse`、`status`、`merge-base --is-ancestor`、`show`。
- DSH clone（`core.longpaths`）、checkout `477b4f4`、13 个补丁 `apply --check` 并应用。
- `corepack pnpm install --offline --store-dir=D:\.pnpm-store`；`pnpm run build`（失败一次即 F3，补 d.mts 后通过）。
- `git archive` 导出，python 解压；robocopy dsh-ext 的 `node_modules`，重建 12 个目录联接。
- `node scripts\test.mjs` 全量和指定文件；zz-rvb30 的 C 系列在 none/after/before 三种模式各跑一遍；X4 在 after/none 两种模式；`toDetach` 回退变异；F1 修法试验。两处变异都按原字节写回，SHA256 一致。
- DSH 根目录 vitest 跑补丁测试；`tsc --noEmit`、`build.mjs`、`check_ui_words.py`、`check_examples.py`。

### 残留审计

- 实验目录 `rv-A30-B-lab` 已用 `rmdir /s /q` 删掉（不跟随联接）。
- 没有留下 node 进程，19311–19319 没有监听。
- 克隆 rv-A30 的 HEAD 不变、status 干净；`D:\lawbench-A\dsh` 的 status 仍是 108 项，我没碰过它。
- 留下 `scratchpad\rv-A30-B-specs\`：spec 和输出，路径里的用户名已改成 `<用户>`。
- 离线安装读了 `D:\.pnpm-store`，pnpm 可能更新了 store 的元数据，没有下载任何东西。

### 证据缺口

- **桌面端没起**：F1 是包测试层加载了生产插件得出的，界面上 agent/error 具体怎么显示没看到（不管显示成什么，CASE_MOVED 提示都确实没有）。
- **拔盘、搬家用改名模拟**。
- 用例的假服务监听 127.0.0.1 的随机端口，不在 19311–19319 内，跑完即关。
- 想用联接借用 `D:\lawbench-A\dsh` 的依赖被权限拒了，改为自己的副本装依赖、整体编译。
- `apply.client.spec` 起不来是否属于基线没核。
- F4、F5 没实测。

REJECT
﻿