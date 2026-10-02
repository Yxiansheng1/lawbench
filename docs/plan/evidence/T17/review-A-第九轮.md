# T17 第三步"活着的句柄"第八轮返修后累计（第九轮）· Reviewer A（改动纪律与可维护性）

- target：line-A `cb21fad`（父 `6212f64`；line-A 已 rebase 到 main `d2f4b23`）
- 冻结清单：`review-综合裁决-第八轮.md` 第 2 节
- 派发：两名 Opus 5.5 只读复核员同一条消息并发派出（17:45），素材相同，互相看不到
- 复核克隆：scratchpad `rv-A31`
- 归档：主编排于 2026-10-02 18:05 (+08:00) 从复核员交回原文抄录，未改内容

## 复核员原文## Reviewer A（改动纪律与可维护性）· T17 第三步"活着的句柄"第九轮 · target line-A `cb21fad`

**本轮要求的行为（白话）**：律师正在某个对话里工作时，如果把案件文件夹复制走、搬走，或者拔了盘，下一句话要整轮拒绝，并给出中文提示 `CASE_MOVED`。即使 DSH 生产插件 `session-checkpoint-policy` 先动了存储，也必须这样。具体要求四条：
1. 旧处一个字节都不写；
2. 不能只冒一条带完整路径的英文报错；
3. 搬走以后原路径上又建了别的案件，老会话也要判为失效；
4. 重启后在新位置续写照常。

**target 身份**：rv-A31 的 HEAD 是 `cb21fad237071c…`，`git status` 为 0 行，是单个 `T17:` 提交，13 个文件，+342/−72。
- 派单写父提交是 `d2f4b23`，不准确：实际父提交是 `6212f64`（第七轮的返修提交）。`d2f4b23` 是它的祖先，line-A 整条已 rebase 到 main `d2f4b23`，交付说明第 12 节的说法属实。
- main 现在到了 `69f0218`（T12 的两个提交）。line-A 落后这两个提交，不影响本轮。

先说结论：冻结清单 9 条全部关闭。没有 P0、P1、P2，只有 3 条 P3 和几条 NOTE，都不阻断合并。

---

### 一、发现

**P3-1｜flush 之后把会话标为"见过"的那一行没有用例守着（归类：本次引入，属于测试覆盖不足）**
- **问题**：`router.ts` 的 `flush()` 新加了一行 `for (const w of this.writers.values()) if (!w.seen && !w.detached) w.seen = this.onDisk(w)`。把这行删掉，全套测试照样全绿。
- **原因**：C4 只在默认的"加载 checkpoint 插件"组合下跑。这个组合下，原来那个 pre-step 先 `next()`，checkpoint 插件在 `next()` 里先把记录落盘；之后 `preStep` 第二次调 `caseMoved`，`recordGone` 顺带把 `seen` 置真。flush 那一行在这里没起作用。只有不加载 checkpoint 插件时，它才是唯一能把 `seen` 置真的地方。
- **影响**：
  - 生产组合下目前没事。
  - 但"见过"何时置真，依赖一个判断函数（`recordGone`）的副作用和 pre-step 的调用顺序，这层关系没有写出来。以后谁去掉 `preStep` 里那次重复判断，或者调整插件顺序，C4 这条路会悄悄失效。
- **证据**（在我的副本上做的变异，做完逐字节写回，SHA256 一致）：
  - 删掉 flush 那一行，跑 session-store 与 live-writer 两个 spec：108 passed，变异存活。
  - C4 改成不加载 checkpoint（`'none'`）、产品代码不动：1 passed。
  - C4 改成 `'none'` 并删掉 flush 那一行：1 failed（`expected false to be true`）。
- **最小修复（二选一）**：
  - C4 也按 `'none'` 再跑一次（`for (const cp of ['after','none'])`，一行）；
  - 或者在 `recordGone` 和 flush 旁边写一句注释，说明"见过"在生产里靠的是哪一次调用。

**P3-2｜B-F5 只有"打开挂住"有用例，"读取挂住"没有（归类：本次引入，测试覆盖不足）**
- **证据**：把接回时 `read()` 外面的 `within(…,3000)` 去掉，session-store 加 live-writer 共 108 项全过，变异存活。`open` 的上限有用例守着：去掉后 1 项变红，和作者的结果一致。
- **影响**：只影响证据完整度。代码本身已经套了上限（我读过 `router.ts:277`）。
- **最小修复**：`FakeBackend` 加一个 `hangRead`，在 B-F5 那条用例里补两行断言。

**P3-3｜`encodeSegment` 是抄来的，和原版不完全一样，测试也测不出差别（归类：本次引入，可维护性）**
- **能不能直接 import**：不能。原版 `@deepseek-ai/dsh-session-persistence-jsonl` 的主入口 `lib/index.js` 不导出它，只有 `./src/*` 这个 `.ts` 源码子路径；组合包是纯 ESM 的 `lib/*.js`，运行时不能从 node_modules 加载 `.ts`。所以照抄有道理，而且 PATCHES.md 依赖第 ⑨ 条已经登记。
- **两处小问题**：
  - 抄的版本少了原版遇到空字符串就抛错的那一句（`format.ts:200`）；
  - 测试里的会话编号都是 `s1`、`s2`，只含安全字符，编码那条分支等于没测。哪天原版改了编码规则，这里测不出来。
- **最小修复**：
  - 注释里写明"空串原版会抛错，这里不会"，或者把那句补上；
  - 加一个单元断言，对含 `~`、中文、`.` 的编号与原版 `src/format.ts` 的结果比对（测试环境可以直接 import `.ts`）。

**NOTE**
- **B-F1 两处判断不算两个事实来源**：两个 handler 都调同一个本地闭包 `caseMoved` → `router.caseMoved`。拒绝动作（记日志、`noteBlocked('CASE_MOVED')`、`tasks.delete`）只有 `LegalAgent.preStep` 一处；`CASE_MOVED` 的提示文字只有 `dock.tsx:21-22` 一份（我 grep 过）。前置的 handler 借一个假的 `{kind:'enter'}` 决定去调 `preStep` 触发拒绝，绕了一点，但正好让拒绝逻辑保持一处，就是复核员 B 给的写法。`preStep` 里原来那次判断在生产里是冗余的，但它恰好是 P3-1 里给 `seen` 置真的那次调用，不能随手删。
- **B-F2 的 `seen` 是新增的状态**：1 个字段、3 处写入（建句柄时、`recordGone`、`flush`）。我考虑过更简单的写法：案件根名单只存路径，不存案件编号，没法比"是不是同一个案件"；只看 `existsSync(w.at.root)` 挡不住 C4，因为新建的案件同样有 `工作区\会话`。所以按目前的结构，这已经接近最小。
- **"补了断言变异才红"是真约束，不是钉在实现上**：
  - 我复现了作者的说法：把那条单元断言退回补之前的样子，"不看盘"变异 108 项全过；补上以后 1 项变红。
  - 补的断言是"新建、还没落过盘的会话，盘不在时也算失效"，对应真实情形：新开一个对话、第一句还没发，盘就拔了。这时没有 `existsSync(caseRoot)`，`recordGone` 对没见过的会话返回 false，这一轮会放行，到 checkpoint 那里撞成英文错。
  - 同时把 `FakeBackend.create` 改成交出写句柄，这和原版一致（`session-persistence-jsonl/src/index.ts:332` 的 `create` 返回 `'write'`），是修正假实例，不是迁就实现。
  - 这条约束只有单元层（假实例）守着，live-writer 里没有"新会话加拔盘"这一例。
- **PATCHES.md 依赖行第 3 列的行为概述**仍写"位置失效（根不在名单上或不在盘上）"，没提"或会话自己的记录已不在"。第 2 列第 ⑨ 条写了，属于文字滞后。
- **`onDisk` 每次是同步的 `readdirSync` 加 `existsSync`**，每轮第 1 步调两次。网络盘挂住时会卡主进程。这和第五轮起的 `existsSync(caseRoot)` 是同一类问题，不是本轮新开的口子，留给复核员 B 判断。
- **B-F3（T20 的 P-4 补丁）并进了 `T17:` 提交**。执行令写的是 B-F3"可单独一个 `T20:` 提交"，可以分开但没要求，交付说明 12.1 也写明了，不算违规。

### 二、逐 hunk 归类
- **必需实现**：
  - `agent/index.ts`：抽出 `caseMoved` 闭包，加 `prepend` 的 pre-step（B-F1）；
  - `router.ts`：`readdirSync` 导入、`seen`、`encodeSegment`、`handle(…, existing)`、`invalid/onDisk/recordGone`、flush 置"见过"（B-F2）；`within` 套在 `open/read` 外（B-F5）；注释（B-F4）；
  - `session-store/index.ts` 注释（A-P3-2）；
  - `P-4-brand.patch` 与 PATCHES.md 的 P-4 行（B-F3）。
- **必需验证**：
  - `live-writer.spec.ts`、`session-store.spec.ts`（含 `FakeBackend.create`、`hangOpen`）；
  - `mutate.py`、`mutate.txt`、`mutate_check.py`；
  - PATCHES.md 依赖行；T17 交付说明的 10.4、11.5 和第 12 节；T20 交付说明末节与 `clean-build.txt`。
- **无关改动**：无。diff 里没有 Key、用户名或路径。

### 三、冻结清单逐条核对（第八轮综合裁决第 2 节）

| 编号 | 结论 | 证据（自己跑或读的） |
|---|---|---|
| B-F1 | 关 | `prepend: true` 的 pre-step 在第 1 步遇到位置失效就不调 `next()`，原来那个 pre-step 保留。live-writer 加载了真的 `session-checkpoint-policy`：搬家、盘暂时不在两例按 after / before / none 三种顺序各跑，复制一例在 after 下跑，都断言 `['CASE_MOVED', []]`。变异"前置判断关掉"：7 红（和作者一致）。我自加的变异"只去掉 `prepend:true`"：before 顺序的 2 例变红，说明三种顺序真起作用。 |
| B-F2 | 关（附 P3-1、P3-3） | 收了 C4，另加"新建会话第一轮不误判"一例。变异"不判记录还在不在"：C4 红；"新建会话不等落盘就判"：作者报 20 例全红，我没重跑这一条。 |
| B-F3 | 关 | 自己 clone DSH 到 `477b4f4`，13 个补丁按顺序 `apply --check` 加 `apply` 全部 0 错；`lawbench-product.d.mts` 在补丁里，和 `D:\lawbench-A\dsh` 那份哈希一致。tsc 实测：同一个 import 有这个声明文件时退出码 0，去掉后报 TS7016。完整的离线安装加 `pnpm run build` 我没重跑，见证据缺口。 |
| A-P3-1 | 关 | 锚点 `[p.join(process.env.ProgramData` 落在 preset-lawbench 段内（第 1427 行，段在 1403–1454）。`mutate_check.py` 跑出"变异全部被报出，基线通过"，"customSkillDirs 两个目录顺序对调"这项报出了；输出与 `mutate-check.txt` 逐字相同。 |
| A-P3-2 | 关（附 NOTE 文字滞后） | 依赖行补了"且还在盘上（复制）"、⑧、⑨；用例数写"二十例"。我数过 spec：4 + 1 + 1 + 3 + 11 = 20，列出的 16 个名字展开后正好 20。`index.ts` 注释已改。 |
| A-P3-3 / B-F4 | 关 | 10.4 和 `router.ts` 注释都补了"后台关完之前进来的事件仍落旧处"。 |
| B-F5 | 关（附 P3-2） | `open`、`read` 都套了 `within(…, caseRootTimeoutMs ?? 3000)`；`open` 有用例，`read` 没有。 |
| B-F6 | 关 | 10.4 记为已知限制和独立后续。 |
| A-NOTE 11.5 | 关 | 已分开写：复制时"留在原来的文件夹"，搬走时"不会保存"。 |

**作者提的待定（`build.ps1` 要不要加 `--store-dir`）——只核事实，不拍板**：
- `D:\lawbench-A\dsh\node_modules\.modules.yaml` 记的 `storeDir` 是 `D:\.pnpm-store\v11`。
- 不指定时，默认 store 是 `C:\Users\<用户>\AppData\Local\pnpm\store\v11`。
- `packaging\build.ps1:84` 是 `install --frozen-lockfile --offline`，没有 `--store-dir`；DSH 里也没有 `.npmrc` 设 store。
- 我用只读方式查了两个 store 的索引库：默认 store 1383 条，`D:\.pnpm-store` 3729 条。默认 store 明显不全，"不指定 store 离线装不上"可信。
- 但作者点名的 `@stylistic/eslint-plugin` 5.10.0 在默认 store 的索引里**有**记录（可能文件不全）。点名哪个包没有证实，结论方向不受影响。

### 四、八项清单
- **契约一致**：没动 `contracts\`；`check_examples` 通过。
- **边界输入**：新建、没落过盘的会话；C4；盘暂时不在；接回时打开挂住——都有用例。读取挂住没有用例（P3-2）。
- **错误路径**：`onDisk` 读不了目录时返回 false，判为失效，属于保守方向；接回超时记 `writer_reattach_failed`，仍算失效。
- **日志不含正文**：新代码没加日志，原有的只记 `{index, error 名}`。
- **路径闸门**：没有被绕过。
- **无外连**：只跑了单元测试，假服务只用 127.0.0.1。
- **测试覆盖新代码**：基本覆盖，两处变异存活（P3-1、P3-2）。
- **无机密入库**：diff 扫过，没有 Key、用户名、本机路径。

### 五、实际跑过的命令
- `git rev-parse`、`status`、`log`、`merge-base --is-ancestor`、`diff`、`show`，以及 `git archive` 加 python 解压到实验目录。
- robocopy 复制 dsh-ext 的 `node_modules`，在副本内重建 12 个内部联接；`dsh\node_modules`、`dsh\packages` 用只读联接指向线 A 的 dsh。
- `node scripts\test.mjs`（全量）：31 个文件，504 通过，5 跳过。
- `tsc -p tsconfig.json --noEmit`：退出码 0。`node scripts\build.mjs`：通过。`check_ui_words.py`：零命中。`check_examples.py --skills skills`：退出码 0。
- `mutate_check.py plugin-inventory-desktop.json plugin-tree.txt`：通过，输出和存档逐字相同。
- 自写变异脚本跑了 9 个变体：
  - 重跑作者的 5 个，含"判定：不看盘"，结果都和 `mutate.txt` 一致（1 / 7 / 1 / 1 红）；
  - 另做 4 个：退回补的断言（证实作者"第一次没红"）、只退回断言当基线（全绿）、去掉 `prepend:true`（2 红）、去掉 flush 置"见过"（存活）、去掉 read 的上限（存活）。
- C4 改不加载 checkpoint 的两个对照实验。每次都逐字节写回，SHA256 一致。
- DSH clone 加 13 个补丁 `apply --check`；tsc 对照实验（有、无 `lawbench-product.d.mts`）；用只读 sqlite 查两个 pnpm store 的索引。

### 六、残留审计
- 实验目录 `rv-A31-lab` 已删：先单独 `rmdir` 掉两个指向线 A 的联接，再整体删除，没有顺着联接进入线 A。
- 删完核过：`D:\lawbench-A\dsh` 的 status 仍是 109 项（我没执行过写命令），`node_modules\vitest` 还在。
- 没有命令行含 rv-A31 的进程；19301–19309 没有监听。
- rv-A31 的 HEAD 仍是 `cb21fad`，status 0 行。
- `D:\.pnpm-store` 和默认 store 只做了只读查询，没有安装。
- 一个小插曲：有一条 PowerShell 命令被安全拦截，没有执行，没有副作用；之后改用 Write 写探针文件，用完已删。
- 我的变异输出没有另存文件，结果都写在本报告里。

### 七、证据缺口
- B-F3 我没有重跑完整的"离线 install 加 `pnpm run build`"，只做了补丁可应用和 TS7016 的对照，完整构建靠作者的 `clean-build.txt` 和复核员 B 第八轮的同类实测。
- "新建会话不等落盘就判（20 例全红）"这一条变异没有重跑。
- 默认 store 缺的是哪个包没有证实，只核实了默认 store 明显比 `D:\.pnpm-store` 小。
- 桌面端没有起，执行令也没要求。

PASS

