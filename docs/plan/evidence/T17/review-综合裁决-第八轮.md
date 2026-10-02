# T17 第三步"活着的句柄"第七轮返修后累计（第八轮）· 双人复核综合裁决

- 裁决人：主编排（ORCH）；用户在场
- target：`d0ab339`（line-A，已 rebase 到 main `69b0376`）
- 两份记录：`review-A-第八轮.md`、`review-B-第八轮.md`。同一条消息并发派出，素材相同，互相看不到
- 落件时刻：2026-10-02 15:24 (+08:00)

## 1. 结论

| 轴 | Reviewer | Verdict | 阻断证据 | 要求动作 |
|---|---|---|---|---|
| 改动纪律 | A | PASS | 无。第七轮冻结清单全关并各有变异为证；接回时序经核在 `read()` 后同步比对无新窗口；插件清单重导出核对一致 | P3 三条：`mutate_check.py` 锚点旧写法（T20 改表达式后暴露）；PATCHES.md/`index.ts:132` 文字未跟上"且还在盘上"；放下超时后台关期间事件仍可能落旧处（10.4 补一句）。另如实报告一次清理失误：`dir /AL /S` 顺着联接列进线 A 目录树，`rmdir` 因父联接先删全部报"找不到路径"未执行，线 A 核过完好 |
| 影响半径 | B | **REJECT** | **F1（P1，本次引入）**：加载 DSH 生产插件树里的 `session-checkpoint-policy`（运行时清单 enabled/active；作者测试环境未加载）后，搬家路径每一轮：该插件在 `pre-step` 先 `sessions.flush` → 旧路径 ENOENT 抛错 → 整轮按 `agent/error` 结束，我方 pre-step 在 `next()` 之后判 `caseMoved` 永远走不到 → **无 `CASE_MOVED` 中文提示，只有含完整旧路径的英文错误**。不写旧处、不丢、重启续写正常（①③④守住），② 破。修法 ~4 行（我方另登记 `prepend: true` 的 pre-step 先判位置失效），副本实测有效；"盘暂时不在"第 5 例同一机制一并修好。**F2（P2）**：搬家后原路径又建了别的案件并打开 → 旧根回名单且在盘上 → 误放行，无 checkpoint 时模型回答落不了盘（静默丢）。**F3（P2，归 T20）**：干净 clone 打完 13 补丁 `pnpm run build` 报 TS7016 缺 `lawbench-product.d.mts` 声明——`build.ps1` dsh 步会撞上。F4/F5/F6 P3 | F1、F2 修 + 测试环境加载 `session-checkpoint-policy`；F3 归 T20 P-4 补丁补 `.d.mts` |

**综合：AMEND，有界返修一轮（第九轮）；不触发止损。** 用户 15:2x 同意（"可以呀，按你推荐的来"）。理由：F1 根因是"与 DSH 检查点插件的 pre-step 顺序"，与第六轮（搬写入者空档）、第七轮（放下/接回边角）均不同；N55 ② 本体不变量①③④在生产组合下仍守住；修法确定、复核员已实测；测试环境缺生产插件是暴露面问题，一并补上后这类问题不再漏。

## 2. 返修清单（冻结）

| 编号 | 做什么 |
|---|---|
| B-F1 | `agent/index.ts` 另登记 `prepend: true` 的 `agent/pre-step`：step 1 且 `caseMoved(agent.id)` 为真 → 直接走我方拒绝（`noteTurnBlocked` + `CASE_MOVED`），不调 `next()`；原 pre-step 保留。live-writer 测试环境加载 `session-checkpoint-policy`（至少搬家、盘暂时不在两例在 after/before 两种加载顺序下跑）；收复核员 C0/C2 为用例（spec 在 `D:\lawbench-coord\附件-T17第八轮-复核员B实验\`） |
| B-F2 | `invalid(w)` 不只判 `caseRoot`：加判该会话自己的记录文件是否仍在（`existsSync(w.at.root)` 或会话文件），或写入者后台写失败一次即位置失效；收 C4 为用例 |
| B-F3（T20 P-4） | P-4 补丁带上 `apps/desktop/scripts/lawbench-product.d.mts`（或调用处改 `.ts`）；在干净 clone 打补丁后 `pnpm run build` 过——T20 交付说明补 |
| A-P3-1 | `docs\plan\evidence\T17\mutate_check.py` 锚点改新表达式 `[p.join(process.env.ProgramData`（T20 第三轮 P3-b 同条，一并） |
| A-P3-2 | PATCHES.md 依赖行"且还在盘上"、用例数十四例与用例名；`index.ts:132` 注释 |
| A-P3-3 / B-F4 | 10.4 与 `router.ts:197` 注释补"盘慢到超时时，后台关完之前进来的事件仍落旧处" |
| B-F5 | 接回的 `open`/`read` 也套 `within(…,3000)` |
| B-F6 | DSH 自身 warn/agent-error 带完整路径——记已知限制（DSH 侧日志卫生，独立后续） |
| A-NOTE 11.5 | "这句话会留在原来的文件夹里"只对复制成立，搬家时只在内存——改准 |

返修后换新双人复核累计范围；通过则 line-A 整条合并。
