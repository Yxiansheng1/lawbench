# T17 绗笁姝?娲荤潃鐨勫彞鏌?绗節杞繑淇悗绱锛堢鍗佽疆锛岀‖姝㈡崯杞級路 Reviewer B锛堝奖鍝嶅崐寰勩€佽竟缂樻儏鍐典笌鍥炲綊瀹夊叏锛?
- target锛歭ine-A `fec9f79`锛堢埗 `e567539` = merge main `e85f14b`锛?- 鍐荤粨娓呭崟锛歚review-缁煎悎瑁佸喅-绗節杞?md` 绗?2 鑺傦紙R10-1/2/3锛夛紝纭鎹熸潯娆剧 3 鑺?- 娲惧彂锛氫袱鍚?Opus 5.5 鍙澶嶆牳鍛樺悓涓€鏉℃秷鎭苟鍙戞淳鍑猴紙20:20锛夛紝绱犳潗鐩稿悓锛屼簰鐩哥湅涓嶅埌
- 澶嶆牳鍏嬮殕锛歚D:\lawbench-rv\rv-A32`
- 褰掓。锛氫富缂栨帓浜?2026-10-02 21:04 (+08:00) 浠庡鏍稿憳浜ゅ洖鍘熸枃鎶勫綍锛屾湭鏀瑰唴瀹?
## 澶嶆牳鍛樺師鏂# Reviewer A（改动纪律与可维护性）· T17 第十轮（硬止损轮）· target line-A `fec9f79`

**一句话说清要求的行为**：律师在一个还没落过盘的新对话（比如进案件时默认建的空白对话）里打字，如果这时案件文件夹已经搬走或复制走，这一轮要被拒绝并给出中文提示 `CASE_MOVED`。旧路径不能被重建，话也不能写进原路径上新建的别的案件。另外，接回写入者时关新句柄要有时间上限；"一轮进行中搬家"这种情况记为已知限制。

**结论**：三条冻结项都有我自己跑出来的关闭证据。"一并做"五条已落实，没有改坏既有用例。没有无关改动。新发现的边角按硬止损条款全部归"独立后续 / 已知限制"，不阻断。

**target 身份**：克隆 `D:\lawbench-rv\rv-A32` 的 HEAD 是 `fec9f79b49…`，工作区干净。这是单个 `T17:` 提交，父提交 `e567539`（合入 main `e85f14b` 的合并提交）。增量 11 个文件，+438/−92，与作者自报一致。

**逐 hunk 归类**：

| 文件 | 改了什么 | 归类 |
|---|---|---|
| `agent/index.ts` | 拒绝前调 `releaseMoved` | R10-1 必需实现 |
| `agent/index.ts` | 拒绝逻辑抽成 `rejectMoved` | B-NOTE（一并做） |
| `session-store/index.ts` | 对外暴露 `releaseMoved` | R10-1 必需实现 |
| `router.ts` | `toDetach` 改为 `(!w.seen \|\| existsSync)` | R10-1 |
| `router.ts` | 新加 `releaseMoved` | R10-1 |
| `router.ts` | 抽出 `queue`，放下、接回、`releaseMoved` 同一队列 | R10-1 所需 |
| `router.ts` | `opening` 迟到句柄关掉 | B-F5 |
| `router.ts` | 关新句柄套 `within` | R10-2 |
| `router.ts` | `encodeSegment` 导出，空串报错 | A-P3-3 |
| `live-writer.spec.ts` | M1/M1b/M2 × 三种插件顺序 | R10-1 必需验证 |
| `live-writer.spec.ts` | C4 加 `none` 顺序 | A-P3-1 |
| `session-store.spec.ts` | F5b、F5a、编码对照 | R10-2、A-P3-2、B-F5、A-P3-3 |
| `PATCHES.md` | ⑩、已知限制、用例数 | 必需 |
| `交付说明.md` 10.4 与第 13 节 | R10-3 文字与交付记录 | 必需 |
| `mutate*.py/txt` | 变异脚本与结果 | 必需验证 |

无关改动：0。

## Findings

- **NOTE-1 依赖 DSH 私有字段 `buffered`（偏离执行令）：我的判断是接受，而且它比改 DSH 补丁小。**
  - **`buffered` 里装的是什么**：我读了钉在 `477b4f4` 的原版 `storage.ts:90/274–316/223–260`。`buffered` 只装经 `enqueueLive` 进来、还没落盘的事件，批量计时器 `LIVE_WRITE_BATCH_MAX_DELAY_MS = 200` 到点后落盘；`close()` 会先把它落完。
  - **会不会丢该保存的东西**：`releaseMoved` 只在 `seen === false` 时清缓冲。生产插件树里有 `session-checkpoint-policy`，每步前调 `router.flush`，`router.ts:464` 随后把 `seen` 置真。所以只要一轮正常走过一步，`seen` 就是真。生产里 `seen` 为假，就是从没成功落过盘，缓冲里只有被拒这一轮的事件，清掉不丢该保存的东西。
  - **`seen` 守卫有用例守着**：变异 m9 删掉 `w.seen` 判断后，"盘暂时不在"三种顺序和"拔出期间又被拒"共 4 例红。
  - **字段改名有用例守着**：变异 m7 把字段名改成 `bufferedX`，模拟原版改名、走降级分支，结果 M1b 三例红。将来升级 DSH 会被测试拦下；生产里也会留一条 `buffer_drop_unsupported` 日志。
  - **和改 DSH 补丁比**：改补丁要新增一个补丁文件、重建 DSH 的 lib、重核 13 补丁的干净克隆构建链，还要改句柄的接口形状。耦合程度同样是"依赖原版内部"，代价大得多。
  - 归类：独立后续（升级 DSH 时按 PATCHES ⑩ 核对）。请主编排拍板。
- **P3-1（臆测，没实跑）缓冲清空的两个边角。** 归类：已知限制 / 独立后续。
  - ① 不带 checkpoint 插件（`none`，非生产配置）时，`seen` 可能落后。如果第一轮回答在拔盘时没落进去，下一句被拒时会连同上一轮的回答一起清掉。
  - ② `releaseMoved` 要排队。如果队里正有一次耗时超过 200 ms 的 recheck，原版计时器可能抢先落盘、重建旧路径。M1b 的路径上名单没刷新、队列是空的，所以概率很低。
- **P3-2 降级分支没有直接的单元断言。** `buffer_drop_unsupported` 那条日志本身没有用例断言，只靠 M1b 间接守。归类：独立后续。
- **NOTE-2 盘暂时拔出时空白对话会一直提示重启。** 按 R10-1 的规定，没落过盘的会话放下后一直算位置失效，所以"拔盘、空白对话里打字、插回"之后，这个对话会一直提示重启，直到重启软件。这是冻结条文本身规定的行为，只提醒主编排知悉。
- **NOTE-3 R10-3 措辞比冻结文字多三个字。** 10.4 写的是"生产插件组合下不丢**已落盘的内容**"，冻结文字是"不丢"。改后的说法更准确（一轮当中搬家时，这一轮还在缓冲里的部分确实落不下），建议接受。
- **NOTE-4 `preStep` 自己那道检查在生产组合下已走不到。** 变异"Agent 插件不看位置失效"现在只有 `agent.spec` 一例红（原来 live 也有 13 例红），因为排在最前的 pre-step 先拦下了。它留作后备，拒绝逻辑仍然只有 `rejectMoved` 一处，不重复。

## 三条冻结项核对表

| 编号 | 关闭证据（我自己跑的） | 结论 |
|---|---|---|
| R10-1 | live-writer 30/30。单撤 `releaseMoved` 调用：M1b 三例红。单撤清缓冲：M1b 三例红。单撤 `toDetach`：M2 三例红。两处合撤：M1/M1b/M2 九例全红。结果与 `mutate.txt`、`mutate_r10_1_both.txt` 逐条一致。另加 m7（字段改名）M1b 三红，m9（去掉 `seen` 守卫）4 红。`releaseMoved` 和放下、接回走同一个 `queue`，没有新状态，只复用 `detached`。 | 关闭 |
| R10-2 | 撤掉 `within`，F5b 红（1.5 秒判卡住）。还原后 91/91。 | 关闭 |
| R10-3 | 交付说明 10.4 已加这一条，PATCHES 依赖行已同步。措辞见 NOTE-3。 | 关闭 |

## 一并做核对

| 编号 | 核对结果 |
|---|---|
| A-P3-1 | C4 在 `after`、`none` 两种顺序下跑，用例旁注释写明 `seen` 置真靠哪次调用。 |
| A-P3-2 | F5b 里读会挂住，断言记了 `writer_reattach_failed`。 |
| A-P3-3 | 撤掉空串报错（m8），编码用例红。对照用例与原版 `format.ts` 逐个比较。 |
| B-F5 | 撤掉迟到句柄的关闭（m6），F5a 红。 |
| B-NOTE | `rejectMoved` 只有一处实现，两个调用点。 |

既有用例：全量 529 通过、5 跳过，没有回退。

**PATCHES "三十例"**：我数了 spec 的 `it` 和循环：4+1+1+3+1+1+1+1+1+1+2+1+9+1+1+1 = 30，vitest 实跑也是 30。

## 八项清单

| 项 | 结论 |
|---|---|
| 契约一致 | `contracts\` 没动，`check_examples` 通过。 |
| 边界输入 | 空串编码报错；字段缺失走降级。 |
| 错误路径 | 关句柄有上限、出错有 catch，迟到句柄会关掉。 |
| 日志不含正文 | 新增日志只记 `index` 和错误名。 |
| 路径闸门未被绕过 | 未涉及。 |
| 无外连 | 未涉及。 |
| 测试覆盖新代码 | 覆盖到；降级日志那条只有间接覆盖（P3-2）。 |
| 无机密入库 | 是。 |

## 实际跑过的命令（实验副本 `D:\lawbench-rv\exp32`，TEMP/TMP/LOCALAPPDATA/APPDATA 都指向这里）

- `git rev-parse HEAD`、`git status`、`git diff fec9f79~1 fec9f79`
- 从 `D:\lawbench-A\dsh` clone 一份，`checkout 477b4f4`，按 PATCHES 顺序对 13 个补丁 `apply --check` 再 `apply`：全部无错。核对 `storage.ts`、`format.ts` 与线 A 的 dsh 哈希一致。
- 依赖：`dsh-ext\node_modules` 用 robocopy 拷进副本，重建 12 个指向副本内部的联接；`dsh\node_modules`、`dsh\packages` 用联接只读指向线 A。
- `node scripts\test.mjs` 全量：32 个文件，529 通过、5 跳过，rc=0。
- `tsc --noEmit` rc=0；`build.mjs` rc=0；`check_ui_words.py` 零命中；`check_examples.py --skills skills` rc=0。
- 变异 m1–m9（含 m7b）：每次按原字节写回，事后 sha256 与改前一致，`git status` 干净。
- 复跑 live-writer + session-store + agent 三个文件：133/133。

## 残留审计

- 我起的 node/python 进程：0。端口 19301–19309：没有监听。
- 两个后台等待任务已停。
- 先只删 14 个联接（不跟进目标目录），再删 `exp32`。线 A 的 `dsh\packages` 删前删后都是 60 项，`node_modules` 还在。
- `rv-A32` 仍在 `fec9f79`，工作区干净。
- 没起桌面端，没碰别人的进程。

## 证据缺口

- 第一次批量变异跑到 m7（字段改名、整份 live-writer）时，一次运行超过 900 秒没结束，被超时杀掉，文件已还原。用同一变异复跑整份文件 117 秒正常 3 红，复跑未变异的三个文件也正常。我判断是一次性的环境卡顿，原因没查清。
- P3-1 的两个边角是读代码推出来的，没写实验验证。
- 没做桌面端实测，也没做干净克隆构建（本轮没改补丁）。

PASS

