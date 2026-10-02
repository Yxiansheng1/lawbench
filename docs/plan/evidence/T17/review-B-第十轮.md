# T17 第三步"活着的句柄"第九轮返修后累计（第十轮，硬止损轮）· Reviewer B（影响半径、边缘情况与回归安全）

- target：line-A `fec9f79`（父 `e567539` = merge main `e85f14b`）
- 冻结清单：`review-综合裁决-第九轮.md` 第 2 节（R10-1/2/3），硬止损条款第 3 节
- 派发：两名 Opus 5.5 只读复核员同一条消息并发派出（20:20），素材相同，互相看不到
- 复核克隆：`D:\lawbench-rv\rv-A32`
- 归档：主编排于 2026-10-02 21:04 (+08:00) 从复核员交回原文抄录，未改内容

## 复核员原文# T17 第十轮（硬止损轮）· Reviewer B 复核记录：影响半径、边缘情况与回归安全

- target：line-A `fec9f79`（父 `e567539`）。复核克隆 `D:\lawbench-rv\rv-A32` 已亲验：HEAD 是 `fec9f79`，工作区干净。
- 实验环境：从克隆用 robocopy 导出到 `D:\lawbench-rv\rvB32`（`git archive` + tar 遇到中文文件名报错，改用 robocopy）。为了对照，另建 `rvB32p`，把 3 个产品文件换成父提交的版本。dsh 用联接只读指向 `D:\lawbench-A\dsh`。TEMP、TMP、LOCALAPPDATA、APPDATA、DSH_HOME 都指到 `D:\lawbench-rv\rvB32-tmp`。

## 先说一句白话

这一轮改的是一个不变量：一个**还没落过盘的新对话**（比如进案件时 DSH 默认建的空白对话），案件文件夹被搬走以后：
- 律师在里面说话会被整轮拒绝，并给中文提示；
- 旧路径不能被重建，话也不能写进原路径上新建的别的案件。

做法：拒绝之前，先把这个写入者"放下"——清空原版的缓冲，再关句柄。名单刷新后，这类写入者不再要求"根还在盘上"才放下。另外，接回时关新句柄加了 3 秒上限。

## Findings

**P3-1 · 本次引入的回归，只出现在不加 checkpoint 插件的组合；生产插件组合实测不触发 → 不阻断，建议记已知限制或独立后续**

- **问题**：`seen`（"这个会话已落过盘"）是懒更新的。新会话第一轮已经落盘以后，只有两种情况会把它置真：
  - 有人在根还在、也在名单上时调 `caseMoved`；
  - 路由的 `flush()` 被调到。
  checkpoint 插件的 `ctx.sessions.flush(session)` 走的是 `session/flush` 事件，由原版 JSONL 实例直接处理，**不经过路由**（见 `core/session/src/index.ts:1194`、`storage.ts:540`）。
- **触发顺序**：新会话第一轮正在跑时盘被拔出，回答写不进去、留在缓冲里。这时 `seen` 仍为假：
  - 律师再说一句 → `releaseMoved` 把缓冲清掉（第一轮的回答也一起清掉）再关；
  - 或者拔出期间名单刷新过 → `toDetach` 对 `!seen` 直接放下 → 关句柄落不了盘 → 回答丢掉。
- **影响**：不变量③（不丢）被破。插回后仍提示位置失效；重启后第一轮回答没了。
- **证据**：我的实验 X1（真 AgentLoop + 假模型，新会话 s2 第一轮回答延迟 1.5 秒，第 700 ms 时用改名模拟拔盘）。

| 组合 | target `fec9f79` | 父提交（rvB32p，同一实验） |
|---|---|---|
| none，不刷新 | 插回后旧处没有回答（`oldHasReply:0`），重启后 `reply:false`，日志有 `writer_detached` | 回答保住（`oldHasReply:1`，重启后 `reply:true`） |
| none，拔出期间刷新 | 同样丢（`oldHasReply:0`，重启后 `reply:false`），日志有 `writer_detach_failed` + `writer_detached` | 回答保住 |
| after / before，刷新与不刷新 | 回答保住（`oldHasReply:1`，重启后 `reply:true`，没有 `writer_detached`） | — |

- **为什么生产组合不触发**：after/before 下，我方 Agent 插件里"先 `next()` 再判"的那个 step-1 `caseMoved` 跑在 checkpoint flush 之后，`recordGone` 把 `seen` 置真了。也就是说，生产组合的安全依赖这个隐含的先后顺序，变异和注释里都没写明。
- **对照**：老会话（`seen` 为真）走同样的顺序（X3），三种组合都保住了。
- **最小修复（建议，非本轮必须）**：判"没落过盘"时也看原版句柄的私有 `state.materialized`（与 `buffered` 同类的私有依赖，记进 PATCHES ⑩）；或者在 10.4 / PATCHES 里写明 `seen` 在生产里靠 Agent 插件 step-1 判在 checkpoint flush 之后。
- **归类**：本次引入的回归，但只在非生产插件组合下出现。按硬止损条款记已知限制或独立后续，**不阻断**。

**NOTE-1 · 接回最坏要等约 6 秒**：接回时读挂住、关也挂住，`recheck` 在真实 3000 ms 上限下约 6 秒返回（F5c：`ms:6014`，`returned`，仍算失效）。如果打开那一步也挂住，最坏约 9 秒。有上限，不阻断。

**NOTE-2 · R10-3 已知限制的文字核实**：S2（一轮当中搬家）在 after 组合下，这一轮以英文 `ENOENT` 错误结束、含完整路径，`caseMoved` 随后为真。与 R10-3 的已知限制文字一致。

## 三条冻结项核对表

| 项 | 结论 | 独立证据 |
|---|---|---|
| R10-1 | **关闭** | 前任的 M1、M1b、M2 原样重跑三种组合，全部拒绝、提示 `CASE_MOVED`，`errors:[]`，旧路径不重建（`oldRecreated:false`，关软件后也是），不写进别的案件（`otherCaseHasSay:0`）。父提交上 M1b(none) 仍是 `oldRecreated:true, oldHasSay:1`，说明修法确实起作用。<br>清 `buffered` 不误丢已落盘的会话：`seen` 为真的老会话直接跳过，X3 三种组合回答保住。例外见 P3-1：`seen` 是"假的假"时会误丢，只在 none 组合下出现。<br>"`seen` 为假、缓冲里有多轮事件"能发生：none 组合下第一轮回答 + 被拒一轮同在缓冲里。 |
| R10-2 | **关闭** | F5b：读挂住 + 关挂住，第一次 `recheck` 409 ms 返回，第二次也返回。F5c 用真实上限约 6 秒返回，之后仍失效、不接回，日志有 `writer_reattach_failed`。B-F5：F5a 迟到的句柄随后被关（`closes:2`）。 |
| R10-3 | **关闭** | `交付说明.md` 10.4 和 PATCHES.md 依赖行都加了这一条，文字与裁决一致（10.4 多了"已落盘的内容"的限定）。 |

**回归**：

- `live-writer.spec`（30 例）改成按环境变量选组合：after 30/30、before 30/30。none 下 29/30，唯一失败的 M2(none) 发生在机器睡眠期间（20:33–20:50 有 Kernel-Power 42/107 事件，该例记了 1010 秒），同一例在另两次运行和全量里都通过，判定为环境原因。E2、X2、C4、复制后接回、复制后被拒过不接回，都在三种组合下通过。
- 我的实验里 C0、C2、C4、C4b 三种组合结果与预期一致。
- dsh-ext 全量 529 过、5 跳过（534），与作者自报一致。第一次跑缺 `skills\` 目录，导致 2 例失败、1 个文件起不来；补齐后这两个文件 46/46 通过。
- 用 dsh 自带的 typescript 跑 tsc，退出码 0；`build.mjs` 通过。

**变异**（6 条单撤 + 两处合撤，每次都按原字节复原，复原后哈希与克隆一致）：

| 变异 | 结果 |
|---|---|
| 拒绝前不调 `releaseMoved` | M1b 三种组合红 |
| 放下前不清缓冲 | M1b 三种组合红 |
| `toDetach` 对没落过盘的也要求根在盘上 | M2 三种组合红 |
| R10-2 关新句柄不设上限 | F5b 红 |
| B-F5 迟到句柄不关 | F5a 红 |
| 第七轮 B-F1（拔盘也放下） | E2 等 2 例红 |
| 两处合撤 | M1、M1b、M2 九例全红 |

全部与 `mutate.txt`、`mutate_r10_1_both.txt` 一致。注意：`mutate_r10_1_both.py` 没有处理 CRLF，在 CRLF 检出的树上会断言失败；我在 scratchpad 里改了一份能处理 CRLF 的副本来跑。

**活性**：
- `releaseMoved` 与 `recheck` 按会话各排一队。L1 实验：两个会话关句柄都挂住，在 300 ms 上限时各自返回（303 / 303 / 303 ms），互不拖累；同一会话第二次调用直接返回。
- pre-step 里 `await releaseMoved` 可能排在同一会话正在进行的接回后面，最多约 9 + 3 秒，有上限。
- 这条队列不等 Agent 状态，没有互等。`recheckWriters` 按会话串行是既有行为。

## 影响地图

- **调用方**：`agent/index.ts` 排在最前的 pre-step → `sessionPersistence.releaseMoved`（`session-store/index.ts`）→ `router.releaseMoved`。`toDetach` 影响名单刷新后的 `recheckWriters`。
- **持久化**：放下时清空原版私有 `buffered`，新依赖已记进 PATCHES ⑩；字段不存在时降级为记日志、照常关。
- **并发**：与 `recheck` 共用每会话一条队列。
- **失败语义**：关句柄最多 3 秒，超时也记"已放下"。
- **可观测性**：新增 `buffer_drop_unsupported` 日志，只记元数据。
- **打包**：没有改补丁和配置行。

## 八项清单

| 项 | 结论 |
|---|---|
| 契约一致 | 没动 `contracts\` |
| 边界输入 | `encodeSegment` 空串报错，与原版逐个比对 |
| 错误路径 | 有上限、有日志 |
| 日志不含正文 | 新日志只有 index 和错误名 |
| 路径闸门 | 没被绕过 |
| 产品无外连 | 产品代码没有外连；实验期间我自己出了一次外连，见残留审计 |
| 测试覆盖新代码 | 覆盖了，但缺 none 组合下 X1 的用例（P3-1） |
| 无机密入库 | 是 |

## 实际跑过的命令

- `git rev-parse` / `git status` / `git diff fec9f79~1 fec9f79`
- `node scripts\test.mjs`（全量，以及两个文件补跑）
- 我的实验 spec `zz-rvb32.spec.ts`，三种组合各跑一次；父提交对照跑 X1、X4、M1b
- `zz-rvb32-f5.spec.ts`（F5a、F5b、F5c、L1）
- `live-writer` 按组合参数化的副本，三种组合各跑一次
- `mutate.py`（6 条），`mutate_r10_1_both`（CRLF 版副本）
- `node ..\dsh\node_modules\typescript\bin\tsc -p tsconfig.json --noEmit`、`node scripts\build.mjs`

## 残留审计

- **违规一次，须说明**：第一次 typecheck 我用了 `npx tsc`，npx 从 npm 公网下载并执行了 `tsc@2.0.4` 包（一个占位包，只打印了一段提示）。这违反了"实验不外连"。缓存落在我的实验目录 `rvB32-tmp\LA\npm-cache`，已随目录删除。之后改用 dsh 自带的 typescript。
- **进程**：我起的 node 和 python 都已结束。机器上 `exp32` 的进程（PID 42488、39052、28972）属于别人，没碰。
- **端口**：19310–19319 没有监听，本轮也没起服务。
- **联接**：删目录前先只删联接本身（`rmdir`），复查 `D:\lawbench-A\dsh\node_modules` 顶层 27 个联接、包内深层 16 个联接都完好。
- **目录**：`rvB32`、`rvB32p`、`rvB32-tmp`、`rvb32*.txt`、scratchpad 里的脚本都已删除。`rv-A32` 仍干净、在 `fec9f79`。

## 证据缺口

- 拔盘用改名模拟，没有用真 U 盘。
- 没有做桌面端实测。
- none 组合下 M2 那一次失败是机器睡眠所致，没有单独再跑一次 none 组合的全文件，但该例在其余 4 次运行中都通过。
- P3-1 在生产组合下"不触发"，依赖 Agent 插件 step-1 判在 checkpoint flush 之后这个顺序；只做了 after/before 两种顺序的实测。

PASS

