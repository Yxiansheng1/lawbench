# T17 第三步"活着的句柄"第七轮返修后累计（第八轮）· Reviewer A（改动纪律与可维护性）

- target：line-A `d0ab339`（已 rebase 到 main 69b0376）；本轮重审 `d0ab339`
- 冻结清单：`review-综合裁决-第七轮.md` 第 2 节
- 派发：两名 Opus 5.5 只读复核员同一条消息并发派出，素材相同，互相看不到
- 复核克隆：scratchpad `rv-A30`
- 归档：主编排于 2026-10-02 15:18 (+08:00) 从复核员交回原文抄录，未改内容

## 复核员原文
## Reviewer A（改动纪律与可维护性）· T17 第七轮返修后累计 · target `d0ab339`

先说结论：冻结清单的每一条都关掉了，本轮没有引入 P0、P1、P2。只有三条 P3 和几条 NOTE，都不阻断合并。

**核实 target**：rv-A30 的 HEAD 是 `d0ab3398bb3e…`，`git status --short` 为 0 行，main `69b0376` 是它的祖先。本次提交 13 个文件，+378/−94。

### 一、发现

**P3-1｜T17 的 `mutate_check.py` 有一个变异已经失效（归类：此前既有，本轮重导出后暴露；独立后续，不阻断）**
- 问题：用新导出的清单跑 `mutate_check.py`，结果为"1 项不符合预期"。失败项是"customSkillDirs 两个目录顺序对调"，退出码 0（期望 1）。原因是它找的锚点 `[process.getBuiltinModule('node:path').join(process.env.ProgramData` 是 T20 改表达式之前的写法。在新的 `plugin-tree.txt` 里，preset-lawbench 段已经没有这段文字，锚点落到了第 1475 行 legal-host 的 `skillDirs` 上。那一项检查不看，所以变异等于没做。
- 旁证：用旧导出跑，基线就不过。这是因为 T20 `9ee3e5c` 已经改了 `check_plugin_tree.py` 的期望值。所以 1b024f8 时三件套本来就对不上，本轮重导出修好了基线，但把这条暴露了。
- 影响：只影响证据工具。`customSkillDirs` 顺序被调换时，这个变异测不出来。产品不受影响。作者的交付说明只声称 `check_plugin_tree` 通过，没有声称 `mutate_check` 通过。
- 最小修复：把 `docs\plan\evidence\T17\mutate_check.py` 第 61 行的锚点改成新表达式里的 `[p.join(process.env.ProgramData`。

**P3-2｜两处说明文字没跟上 B-F1 的新条件（归类：本次引入，只是文字滞后）**
- PATCHES.md 依赖清单那一行，第 2 列仍写"名单刷新后根不在名单上的，Agent 空闲时放下写入者"，少了"且还在盘上"。第 3 列仍写"十例"，用例名也还是旧的（"拔出期间刷新后接回、放下后被拒过不接回"）；现在实际是十四例，第 6、7 例的含义也变了。
- `dsh-ext\session-store\index.ts:132` 的注释同样是旧条件。
- 最小修复：这两处各改一句。

**P3-3｜放下超时后，旧句柄在后台关的那段时间里，被拒那一轮的事件仍可能写进旧处（归类：本次引入的有界边角；依据是读代码推出来的，没有在真的慢盘上实测）**
- 原因：超时后 `w.detached = true`，但原版 `close()` 要到最后才注销写入者（`storage.ts:224–260`，`release` 在最后），而且关的过程会循环把"关的期间又进来的事件"也落盘。所以盘慢、复制的情形下，律师那一句和 `turn/start`、`turn/end(blocked)` 仍可能落进旧处。界面照样会拒绝并提示，不是静默。
- 任务点名要核的"和接回竞争"：**不会竞争**。接回时 `open(id,'write')` 会走 `claimWrite`，旧句柄没注销前会抛 `SessionAlreadyOwnedError`（`index.ts:377`、`storage.ts:430`）。接回只记一条 `writer_reattach_failed`、保持失效，下次刷新再试。不会两个写入者并存，也不会接错序号。
- 最小修复：在 10.4 和 `router.ts:197` 的注释里各补一句"盘慢到超时时，关完之前进来的事件仍落旧处"。

**NOTE**
- 超时错误在日志里记的错误名是 `Error`，和真正的关闭失败分不开。可以给 `within` 的错误起个名字，不要求本轮做。
- 11.5 律师说明最后一句"这句话会留在原来的文件夹里"只对复制成立。搬家时原文件夹已经不在，这句话只留在内存里。
- 10.1 和 10.3 第 6 例仍是第六轮的描述。10.4 已注明改写，按历史记录看可以接受。
- X2 用例靠包住 `sessions.get` 来注入竞争，和 `liveSeq` 的调用位置绑在一起。但"在 open 之前取数"的变异能让它变红，够用。

### 二、hunk 清点
- **必需实现**：
  - `router.ts`：`toDetach`、`writersToRecheck`、`recheckOnce` 的放下与接回、`liveSeq` 选项、代理分两支并转给 `w.cur`、两条 warn 日志、文件头和方法注释。
  - `session-store\index.ts`：注入 `liveSeq`，`recheckOne` 不再取 seq，注释改准。
  - `host\index.ts` 两处、`attach-sessions.ts` 一处：只改注释（B-F4）。
  - `dock.tsx`：`CASE_MOVED_TEXT` 新文字。
  - `PATCHES.md`：一行。
- **必需验证**：`live-writer.spec.ts`、`session-store.spec.ts`、`mutate.py`、`mutate.txt`、`plugin-tree.txt`、`plugin-inventory-desktop.json`、交付说明第 11 节和 10.4。
- **无关改动**：无。没有新抽象，代理拆成两支只是为了去掉 `w!`，在 A-P3-3 范围内。
- **搬迁器残留**：grep `relocate`、`writerLost`、`staleWriters` 为零。`agent.spec` 里的 `lost` 只是局部变量名。

### 三、冻结清单逐条核对
| 编号 | 结论 | 证据 |
|---|---|---|
| B-F1 | 关 | `toDetach` 要求根不在名单上且 `existsSync` 为真；`writersToRecheck` 用同一判断。拔盘、搬家不放下。第 7 例断言改为"解除、被拦下那一轮落回原处"，E2 已收为用例。变异"根不在盘上也放下"让 E2 和改后的第 7 例两例变红（我亲跑）。 |
| A-P2-1 | 关 | 顺序是 `open` 先登记写入者，再 `await read()`，然后同步调 `this.opts.liveSeq(id)` 比对，紧接着同步做 `w.cur = fresh; w.detached = false`。比对到赋值之间没有 `await`，没有新开窗口。open 之后进来的事件由新写入者接住：读到了就一致，没读到就判不一样长、不接回、关 fresh 时落盘，是保守方向。open 之前进来的事件会被丢，但比对会判不一样长。X2 已收为用例。"在 open 之前取数"的变异让 X2 变红（亲跑）。 |
| B-F2 / A-P3-1 | 关 | 10.4 已写明"这一轮跑着时律师又排了下一句、或停止后立刻重发"，注明非静默；11.5 有律师说明。 |
| A-P3-2 | 关 | 两条 warn 只记 `{ index: w.at.index, error: 错误名 }`，没有路径和内容。"不记日志"的变异变红（亲跑）。 |
| A-P3-3 | 关 | 写句柄的代理除 `header` 和 `close` 外都转给 `w.cur`。"转给最初那个句柄"的变异变红（亲跑）。 |
| A-P3-4 / B-F6 | 关 | PATCHES.md 已补"`close()` 可重复调用（`storage.ts:224` `closing ??=`）"，我在源码核过行号；也补了"放下依赖我方 Agent 插件同时生效"。10.4 已补"放下期间标题等事件不保存"。同一行的其余文字滞后见 P3-2。 |
| B-F4 | 关 | 放下套 `within(…, caseRootTimeoutMs ?? 3000)`；四处注释已改。"不设上限"的变异变红（亲跑）。和接回不竞争，理由见 P3-3；超时期间的副作用见 P3-3。 |
| 提示文字 | 关 | `CASE_MOVED_TEXT` 已补"刚才这句没有发出，重启软件后请在这个对话里重新发送这句话"；`check_ui_words.py` 零命中。 |
| A-NOTE-1 | 关（附 P3-1） | 静态树只差 `customSkillDirs` 一处（我 diff 过）；运行时清单 190 条，只有第 188、189 两条的 `entryId` 变了，模块名、启用和激活状态全部一致（脚本逐条比对）；`check_plugin_tree --inventory-overlay` 通过。`mutate_check` 有 1 项不符，见 P3-1。 |

补丁层是否按原字节写回：自己 clone DSH 到 `477b4f4`，按 PATCHES.md 顺序 `git apply --check` 加 `apply` 13 个补丁，全部无错。打补丁涉及的 99 个文件和 `D:\lawbench-A\dsh` 工作区逐字节一致；其中 4 个是两边都已删除的文件。工作区多出的只有补丁后拷进去的 9 个品牌图片。

### 四、八项清单
- 契约一致：没动 `contracts\`；`check_examples` 通过。
- 边界输入：`liveSeq` 返回 undefined、read 失败、open 被拒，都走"不接回"。
- 错误路径：放下超时转后台；接回失败记 warn 并保持失效。
- 日志不含正文：是。
- 路径闸门未被绕过：没有改动相关代码。
- 无外连：只跑了单元测试和假服务。
- 测试覆盖新代码：新加的分支都有用例，并有变异证明。
- 无机密入库：diff 里没有用户名和 Key。扫到的 `sk-` 命中是 `tool-ask-user`，属误报。

### 五、实际跑过的命令
- dsh-ext 全量 `node scripts\test.mjs` 跑了两遍，两遍都是 31 个文件、498 项通过、5 项跳过。作者说"第一次有 2 个文件没跑起来"，我**没有复现**。
- `tsc -p tsconfig.json --noEmit` 退出码 0；`node scripts\build.mjs` 退出码 0，纯 ESM 导入检查通过。
- `check_ui_words.py` 零命中；`check_examples.py --skills skills` 退出码 0。
- `check_plugin_tree.py`（新导出）通过；`mutate_check.py`（新导出）1 项不符，见 P3-1。
- 作者 19 个变异里抽了 6 个复现：B-F1、A-P2-1、B-F4、A-P3-2、A-P3-3、"接回不核对长度"，**6 个全红**。之后 `router.ts` 和 `index.ts` 与 `git archive` 导出的原字节比对一致。

### 六、残留审计
- 实验目录 `rv-A30-lab` 已删除；rv-A30 的 status 为 0 行；没有遗留进程；19301–19309 端口没有监听。
- **需要报告的一次操作失误**：清理时我在实验目录上跑了 `dir /AL /S` 加逐个 `rmdir`。列目录时顺着两个只读联接（`wt\dsh\node_modules` 和 `wt\dsh\packages`，指向 `D:\lawbench-A\dsh`）进到了线 A 的目录树，列出了大约 5700 个联接。好在这两个父联接排在列表最前，先被 `rmdir` 掉了，后面所有指向 `D:\lawbench-A` 内部的 `rmdir` 都报"系统找不到指定的路径"而没有执行。我发现后立即停了任务并核查：
  - `D:\lawbench-A\dsh\node_modules` 有 40 项，其中 27 个联接，无一断链；vitest 和 tsc 都在。
  - `packages` 下 312 个包都有非空的 `node_modules`。
  - `D:\lawbench-A` 的 status 只有 ` m dsh`（补丁，正常）和 `?? .tmp-demo/`；这个目录不是我建的，近 2 小时内也没有我的写入。

  结论是线 A 没有被改动，但这一步本身违反了"不碰 D:\lawbench-A"的做法，如实说明。

### 七、证据缺口
- P3-3 是读代码推出来的，没有构造真的慢盘或挂住的网络盘来实测。
- 桌面端这次没有起，执行令也没要求。

PASS
﻿