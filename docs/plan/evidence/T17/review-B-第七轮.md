# T17 第三步"活着的句柄"按 N55 ② 改做法（第七轮）· Reviewer B（影响半径、边缘情况与回归安全）

- target：line-A `26b5cde`（已 rebase 到 main af55f84）；本轮重审 `26b5cde`（不搬写入者；偏离：空闲时放下 / 盘回来接回约 30 行）
- 派发：两名 Opus 5.5 只读复核员同一条消息并发派出，素材相同，互相看不到
- 复核克隆：scratchpad `rv-A29`
- 归档：主编排于 2026-10-02 13:47 (+08:00) 从复核员交回原文抄录，未改内容

## 复核员原文
## 复核员 B（影响半径、边缘情况、回归安全）· T17 按 N55 ② 改做法 · line-A `26b5cde`

我亲自核过克隆 rv-A29：HEAD 是 `26b5cde2657d…`，`git status` 干净，`af55f84` 是它的祖先。实验在 `git archive` 导出的副本里做，DSH 用的是自己 clone 的 `477b4f4`，13 个补丁按 PATCHES 顺序 `git apply --check` 全部通过。

**结论先说**：主路径守住了，包括复制或搬家后在新位置打开、发消息被拒且有提示、旧处新处逐字节不变、重启后在新位置续写、刷新失败或服务回空列表时不误判。但本轮新加的"空闲时放下写入者"带进一个真实路径上的静默丢失：盘在一轮当中拔出，插回前名单刷新过一次，这一轮的回答就永久丢了，插回后还会一直要求重启。按派单判法（②在真实路径破）→ REJECT。修法是一行条件，我实测过。

---

### Findings

**F1【P1｜本次引入的回归｜范围内阻断】盘在一轮当中拔出，插回前名单刷新过一次：这一轮的回答静默丢失，插回后仍一直拒绝**
- **问题**：拔盘后这一轮的事件写不进盘，原版留在缓冲里。接着名单刷新成功，服务报 `exists:false`，根被移出名单。Agent 一空闲，`recheckOnce` 就放下写入者，即 `closeHandle`。close 往盘上落缓冲失败，原版照样注销写入者（storage.ts:223–260），缓冲就此丢弃。
- **影响**：
  - 盘插回后，盘上比内存短，`n !== eventCount`，不接回，这个会话一直 `CASE_MOVED`。提示说"文件夹已经不在原来的位置，请重启"，可文件夹其实没挪过。
  - 重启后，律师在屏幕上看过的那条回答不见了，没有任何说明。
  - 不放下时（原版行为、本轮 10.2 自己写的"盘暂时不在…插回后接上"），这条回答在插回后会照常写上。
- **触发条件**：名单刷新成功的时机包括：会话列表、检索走 `sessionPersistence.list()` 触发的后台刷新（5 秒节流），打开任何案件，服务重启。U 盘或网络盘掉线几秒内碰上其中之一就够了。
- **证据**：真 AgentLoop + 我方会话存储、Agent 插件、Host caseOpen，用改名模拟拔盘，三次运行三次复现。
  - E2（拔盘→这一轮结束→刷新→插回→刷新）：`caseMoved_after_plugback=true`，`next_turn_calls=0`，`notice=CASE_MOVED`，`restart_has_REPLY=false`。
  - 对照 E2b（同样拔插，但不刷新）：`restart_has_REPLY=true`，续写正常。
  - 输出在 `scratchpad\rv-A29-B-specs\rvb29-out-target.txt`，用例是同目录的 `zz-rvb29.spec.ts`。
- **最小修复**：根已经不在盘上时（拔盘、搬家）不放下，只在根还在盘上时放下（复制的情形，只有这种情形写旧处才有害）。`router.ts` `recheckOnce` 第一分支改成：
  ```ts
  if (!w.detached && !this.current(w.at) && existsSync(w.at.caseRoot!)) {
  ```
  - 我在副本里实测：E2 回答保住，插回后解除、能续写（`rvb29-out-with-fix.txt`：`caseMoved_after_plugback=false`、`restart_has_REPLY=true`）。
  - live-writer 十例里只有第 7 例变红。那一例断言的正是这个缺陷（"放下后被拒过就不接回"），要改断言：插回后解除，被拒那轮作为"被拦下"落回原处，同第 5 例。
  - 其余 104 项都通过。改过的 router.ts 已按原字节写回，SHA256 与克隆一致。

**F2【P2｜范围内｜要主编排定性】正在跑的一轮当中，律师在新位置打开之后又发的话会写进旧处（排队发送、停止后立刻重发）**
- **问题**：DSH 运行中发消息默认是 `followup`，进下一轮队列（界面上叫"排队发送"）。消息入队那一刻（`agent/inbox/spliced`）就经仍在登记的写入者写进旧处。下一轮在同一个 running 阶段里开始，中间没有 idle，被 pre-step 拒绝，`turn/start`、`turn/end(blocked)` 也写进旧处。
- **影响**：不是静默的，`CASE_MOVED` 提示照常出现，新位置也没变。但旧副本里多了一句被拒的话。"全盘特征串为 0"只对一轮结束后再发的话成立。
- **证据**：
  - E1：状态只有 `["running","idle"]`；`old_has_QUEUED=1`、`new_has_QUEUED=0`、`notice=CASE_MOVED`、`modelCallsForQueued=0`。
  - 第六轮 R3（带插件、停止后立刻重发）：`oldMsg=1, oldAns=0, notes=[CASE_MOVED]`。
- **处理**：消息入队时就落盘，所以只要"正在跑的一轮照原处落完"，这一点就绕不开。
  - 如果主编排认为它属于执行令第 3 条的例外，就在交付说明 10.4 和律师说明里写明："那一轮还在回答时又发的话、点停止后重发的话，也会留在旧副本里，并被拒"。
  - 不属于的话，只能在 caseOpen 时立刻放下，代价是正在跑那一轮的剩余内容落不到任何地方。

**F3【NOTE｜已记限制】一轮刚结束到放下之间的竞态窗口实测不到 20 毫秒**
- E3、E3b：idle 后 0 毫秒发，会写进旧处。
- E3c：idle 后 20、100、300、1000 毫秒发，都是 `old_has_RACE=0`，且都有 CASE_MOVED。
- 排队是服务端的（inbox `next-turn`），界面不会在 idle 后自动补发，所以人手发消息碰不到这个窗口。和 10.4 写的相符。

**F4【P3｜独立后续｜臆测，未实测】打开案件现在要等放下（close）做完，没有上限；"上限 3 秒"的注释已经不准**
- `refreshNow` 会 `await recheckWriters()`，对空闲会话再 `await closeHandle`。网络盘挂住时，close 落缓冲、放锁可能一直卡着，这次打开案件就一直不返回。
- `host/index.ts:401–405` 和 `attach-sessions.ts:47` 的注释仍写"上限 3 秒"。
- **建议**：给放下套上 `within(…, 3000)`，超时就让它在后台接着做；注释改准。

**F5【P3｜独立后续｜静态推断，未实测】放下之后点赞、点踩或删除反馈会报英文错误**
- `message-feedback` 对活会话会先 `live.append`，再 `sessions.flush(live)`。放下后没有任何写入者参与 flush，会抛 `no durability listener participated`，这条事件只留在内存里。
- 律师要么接着就被要求重启，要么不再点，影响小。

**F6【NOTE】"放下"必须和 Agent 插件的拒绝一起才安全**
- 第六轮 S2 是不带 Agent 插件跑的：放下后每轮照常调模型，但哪里都不写（内存 1619 条，盘上 1603 条），属于静默丢。
- 生产里组合包缺失会被 P-14 拦下，所以不是现行问题。建议在 PATCHES 那一行补一句"放下依赖我方 Agent 插件同时生效"。

**F7【NOTE｜臆测】路由的写入者表可能被别的写句柄顶掉**
- E5 用强制 resume 模拟：在另一个实例上成功打开同号写句柄、随后又关掉，会把活会话的那条记录顶掉再删掉。之后 `caseMoved=false`，回落到 `CASE_NOT_FOUND`。E5 里仍然被拒，旧处不变，因为当时已经放下了。
- DSH 会话控制器对活会话直接返回现成的 Agent，不会再 resume（agent.ts:451–455）。现在不是真实路径，记作加固项。

**关于"要不要补一句'刚才那句没有保存，重启后请重发'"——技术意见：要补，但措辞改成"刚才那句没有发出，重启后请重新发送这句话"。**
- 按 CASE_MOVED 且已放下的情形，"没有保存"是对的：E4 全盘 0 处，J1 重启后也看不到。
- 但在"盘暂时不在、名单没变"（第 5 例）、F2 排队，以及 CASE_NOT_FOUND 这几种情形里，那句话作为"被拦下"其实落在原处了，说"没有保存"不准。
- "没有发出、请重新发送"在所有情形下都对，也和标题"这条消息没有发出"一致。`CASE_NOT_FOUND` 的提示文字可以照现在的用。

---

### 不变量核对

| 不变量 | 结论 | 依据 |
|---|---|---|
| ① 复制或搬家后旧处字节不变、新处不被写 | 主路径守住；F2 例外待定性 | live-writer 1、2、9；rvb22-agent、rvb22-move；J1；E4 |
| ② 每轮被拒并有中文提示，不静默 | **破（F1）** | 被拒提示都在（CASE_MOVED、CASE_NOT_FOUND，dock-a19）；F1 回答静默丢 |
| ③ 重启后在新位置续写照常 | 守住 | live-writer 1、2、3；J2；rvb22-agent 重启 |
| ④ 不误判 | 刷新失败、服务回空列表、盘暂时不在且名单没变：守住；拔盘＋刷新＋这一轮有事件：**破（F1，直到重启）** | 第 4 例；Y2 hang/500/reset；E6 `caseMoved=false`；第 5 例；E2b；N1 |
| ⑤ 登记不记两处 | 守住 | Y4、Y5、Y7 "reboot registry ok"；workspace-attach |
| ⑥ 案件外不能新建、不能续写 | 守住 | Y8（NOT_READY）；session-store 套件 |

### 影响地图与活性

- **空闲判定**：`AgentStatus` 只有 `idle`、`running` 两种。等用户确认、流式输出中都算 running，不会放下，这期间也开不了新的一轮。
- **maintenance（压缩等）也算 idle**：这时可能被放下，压缩事件只留在内存。复制的情形无害；拔盘时和 F1 同一类，按 F1 修法一并解决。
- **等 idle 不设超时**：不会死锁。Agent 被收掉时，监听会留到同号会话下一次 idle 才去掉，属于轻微泄漏。
- **pre-step 拒绝不会死循环**：E1 的状态序列只有一次 running→idle。
- **名单刷新的开销**：遍历的只是活写句柄，一个会话一条，每条一次同步 `existsSync`（网络盘挂住的风险即 A-P3-1）。
- **性能**：P1 实测 4803 条事件的会话，caseOpen 21 毫秒。
- **DSH 启动自动恢复上次会话**：名单缓存刷新时整份换掉，只剩新位置，重启后从新位置打开。

### 回归

- dsh-ext 全量跑了三遍：31 个文件，493 项通过、5 项跳过。T13 N51、T26 第 1、2 步、T20 启动自检的用例都在其中（dock-a19、host-api、fake-tools、selfcheck、selfcheck-banner、ui-logic 等）。
- `tsc` 通过，`build.mjs` 通过，`check_ui_words` 零命中，`check_examples` 通过。
- 第六轮 B 的 spec（`writerLost`→`caseMoved` 改断言后原样跑）：34 项里 32 项通过。没过的两项是测试本身的问题，不是产品回归：
  - Y1：测试拿裸写句柄直接 `append`，放下后报 `SessionHandleClosedError`。真 DSH 里活 Agent 不经句柄 append。
  - R1：它等的是"新位置以写方式打开"，本做法本来就不再这样做。
  - 其余结果：J1 两种语义都拒绝、旧处不变；L1、N1、R3、S1、P1、J3 全盘 0 处；Y1–Y11 中 Y3–Y11 正常。
- 第二步补丁 P-9、P-15、P-5（`main-startup`、`lawbench-request-policy`、`media-references.host`、`apply-inject`、`input-bar`）：5 个文件 249 项通过、1 项跳过。

### 八项清单
- **契约一致**：没有改契约，`CASE_NOT_FOUND` 用的是契约示例。
- **边界输入**：见 F1、F2、F3。
- **错误路径**：F1 不通过；刷新失败不误判，通过。
- **日志不含正文**：新日志 `writer_detached`、`writer_reattached` 只记 index。
- **路径闸门**：没被绕过。
- **无外连**：只到 127.0.0.1。
- **测试覆盖新代码**：有十例＋变异，但漏了 F1 这一路，第 7 例反而把缺陷固化成了预期。
- **无机密入库**：通过。

### 实际跑过的命令
- `git rev-parse`、`status`、`merge-base`、`show`。
- DSH clone `477b4f4`，13 个补丁 `git apply --check` 并应用。
- `git archive --format=zip`，用 python 解压（tar 处理不了中文文件名）。
- robocopy dsh-ext 的 `node_modules`，重建 12 个目录联接；dsh 指向 `D:\lawbench-A\dsh`（只读）。
- `node scripts\test.mjs` 跑全量和指定文件；`tsc --noEmit`；`build.mjs`；`check_ui_words.py`；`check_examples.py --skills skills`。
- 我的 `zz-rvb29*.spec.ts`（E1–E6、E3c），E2 共跑三次；第六轮 `zz-rvb22*`、`zz-rvb23`。
- DSH 根目录 vitest 跑上面那 5 个补丁测试文件。
- F1 修法变异实测，完了按原字节写回。

### 残留审计
- 实验目录 `rv-A29-lab` 已删：用不跟随联接的脚本删的，移除 4228 个联接、16512 个文件。删前删后 `D:\lawbench-A\dsh\node_modules`、`dsh\packages`、`dsh-ext\node_modules\.pnpm` 的条目数不变；`D:\lawbench-A\dsh` 的 `git status` 仍是 108 项。
- 我没有起任何常驻进程；19311–19319 没有监听；克隆 rv-A29 干净、HEAD 不变。
- 留下 `scratchpad\rv-A29-B-specs\`（spec 与输出；输出里有本机用户名路径，只在 scratchpad，不进仓库）。

### 证据缺口
- **桌面端没起**：用的是包测试层真 AgentLoop + Host caseOpen 的旅程替代。
- **拔盘是用目录改名模拟的**，不是真的拔 U 盘或断网络盘。
- **两处偏离"不写他处、只用分配端口"**：
  - 用例的假服务按 spec 原样监听 127.0.0.1 上的随机端口，不在 19311–19319 内，跑完即关。
  - DSH 补丁测试借用了 `D:\lawbench-A\dsh` 的依赖（经联接）。13:39:42 观察到 `D:\lawbench-A\dsh\node_modules\.vite-temp` 这个空目录的修改时间变了，很可能是我这次运行写了临时文件又删掉，无法确证，也没有留下文件。
- **F4、F5、F7 没实测。**

REJECT
﻿