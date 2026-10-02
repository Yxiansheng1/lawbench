# T17 第三步"活着的句柄"第八轮返修后累计（第九轮）· 双人复核综合裁决

- 裁决人：主编排（ORCH）；用户在场
- target：line-A `cb21fad`（父 `6212f64`；line-A 已 rebase 到 main `d2f4b23`）
- 两份记录：`review-A-第九轮.md`、`review-B-第九轮.md`。同一条消息并发派出（17:45），素材相同，互相看不到
- 落件时刻：2026-10-02 18:25 (+08:00)

## 1. 结论

| 轴 | Reviewer | Verdict | 阻断证据 | 要求动作 |
|---|---|---|---|---|
| 改动纪律 | A | PASS | 无。冻结清单 9 条全关、各有独立证据（9 个变异重跑/自加，与 `mutate.txt` 一致；13 补丁 apply 0 错；tsc 有/无 `.d.mts` 对照）。P3 三条：flush 置 `seen` 那一行无用例守（删掉 108 全绿）；B-F5 的 `read` 上限无用例；`encodeSegment` 抄写缺对照断言、少了空串抛错 | P3 并入第十轮"一并做" |
| 影响半径 | B | **AMEND** | 冻结清单 9 条全关（C0/C2/C4 三种插件顺序重跑；干净 clone 13 补丁离线装 + `pnpm run build` rc=0、TS7016 0）。**新发现 4 条 P2，均非本轮引入（第五/七轮起就在），在累计范围内**：**F1** 空白新对话（DSH 进案件默认建的 `reuseOrCreateBlank` 会话，未落盘）遇搬家：有 `CASE_MOVED`，但原版 `materialize` 会 `mkdir` 把旧路径重建、律师那句话写进去（不变量①破；M1/M1b 实测 `oldRecreated:true`）；**F2** 同前提 + 原路径又建别的案件：`recordGone` 对 `!seen` 放行，问答落进别的案件（M2 三种模式 `otherCaseHasSay:1`）；**F3** 一轮当中（step>1）搬家：prepend 只判 step 1，checkpoint flush ENOENT → 英文错误带完整路径、无中文提示（S2）；**F4** 接回 `read` 到时后 `closeHandle(fresh)` 没套 `within`，网络盘挂住时 `caseOpen` 永不返回（F5b 实测 3 秒仍等）。P3：F5 迟到的 `open` 句柄没人关；F6 `onDisk` 同步 IO 无上限（臆测、同类既有） | 见第 2 节 |

**综合：AMEND，第十轮有界返修，并设硬止损。** 用户 18:2x 定："按你推荐的来"。

理由与止损判断：这是第九轮；第八轮冻结清单已全关，本轮 4 条 P2 都是复核员继续探边角找出的**既有路径**，不是返修改坏。F1/F2 同一机制、落在最常见操作顺序上（进案件→拖走文件夹→在默认空白对话里打字）、确实破不变量①，值得修；F4 是本轮刚写的代码漏一处、一行修。F3 的变体"模型回答途中拖走文件夹"少见、下一轮就有正常提示、生产组合下不丢，**记已知限制**，不扩范围。按 senior-review §6.8：高风险类别都已有证据，剩余 case 在演练同一不变量，**到此停止探索性扩张**。

## 2. 第十轮冻结清单（只有这三条阻断）

| 编号 | 做什么 |
|---|---|
| R10-1（B-F1/F2） | 没落过盘的写入者（`seen === false`）一旦位置失效立刻放下：prepend 拒绝那一刻 `await within(close)`；`toDetach` 对 `!seen` 不要求"还在盘上"。放下后保持失效，接回时 `open` 找不到即不接回。收复核员 B 的 M1、M1b、M2 为用例（spec 在 `D:\lawbench-coord\附件-T17第九轮-复核员B实验\zz-rvb31.spec.ts`） |
| R10-2（B-F4） | `router.ts:279` `closeHandle(fresh)` 套 `within(…, ms)`（或 `void closeHandle(fresh).catch`）；session-store.spec 加"read 挂住 + close 挂住"一例（`zz-rvb31-f5.spec.ts` F5b） |
| R10-3（B-F3 ②） | 10.4 已知限制加一条："模型回答途中或工具执行中把案件文件夹搬走，这一轮以英文错误结束（含路径），下一句才给中文提示；生产插件组合下不丢。" PATCHES.md 依赖行同步 |

一并做（非阻断）：A-P3-1 C4 加 `'none'` 模式跑一次或注释写明 `seen` 置真靠哪次调用；A-P3-2 `FakeBackend.hangRead` + read 上限断言；A-P3-3 `encodeSegment` 补空串抛错 + 一个含 `~`/中文/`.` 的对照断言；B-F5 `open` 到时后 `.then(h => closeHandle(h))`；B-NOTE prepend 里直接 `noteBlocked` + `return {kind:'reject'}`（不借假 `enter`）。

独立后续（记录，不做）：B-F6 `onDisk` 同步 IO（与既有 `existsSync(caseRoot)` 同类）；T20 `build.ps1` dsh 步 `--store-dir`（候 T20 收尾定）。

## 3. 硬止损（用户已定）

第十轮复核只核 R10-1/2/3 的关闭证据与"一并做"有没有改坏既有用例。**三条关了就 PASS、line-A 整条合并**；复核再找出的任何新边角一律记已知限制或独立后续，不再开第十一轮。
