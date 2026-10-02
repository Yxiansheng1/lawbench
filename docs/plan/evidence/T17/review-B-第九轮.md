# T17 绗笁姝?娲荤潃鐨勫彞鏌?绗叓杞繑淇悗绱锛堢涔濊疆锛壜?Reviewer A锛堟敼鍔ㄧ邯寰嬩笌鍙淮鎶ゆ€э級

- target锛歭ine-A `cb21fad`锛堢埗 `6212f64`锛沴ine-A 宸?rebase 鍒?main `d2f4b23`锛?- 鍐荤粨娓呭崟锛歚review-缁煎悎瑁佸喅-绗叓杞?md` 绗?2 鑺?- 娲惧彂锛氫袱鍚?Opus 5.5 鍙澶嶆牳鍛樺悓涓€鏉℃秷鎭苟鍙戞淳鍑猴紙17:45锛夛紝绱犳潗鐩稿悓锛屼簰鐩哥湅涓嶅埌
- 澶嶆牳鍏嬮殕锛歴cratchpad `rv-A31`
- 褰掓。锛氫富缂栨帓浜?2026-10-02 18:05 (+08:00) 浠庡鏍稿憳浜ゅ洖鍘熸枃鎶勫綍锛屾湭鏀瑰唴瀹?
## 澶嶆牳鍛樺師鏂## 复核员 B（影响半径、边缘情况、回归安全）· T17 第三步"活着的句柄"第九轮累计 · line-A `cb21fad`

我先核了克隆：rv-A31 的 HEAD 是 `cb21fad237071cba1c94d9ee76d65514c71843d5`，status 干净。本轮增量是 13 个文件、+342/−72。实验都在 `git archive` 导出的副本里做。DSH 是我自己从 `D:\lawbench-A\dsh` clone 的 `477b4f4`，13 个补丁按 PATCHES.md 的顺序 `apply --check`，全部无错，然后应用。依赖用 `pnpm install --offline --frozen-lockfile --store-dir D:\.pnpm-store` 装，再从头 `pnpm run build`。

**结论：** 冻结清单逐条都关上了。B-F1、B-F2、B-F3 我亲手复现，结果都对。第八轮的 C0、C2、C4 在 checkpoint 插件"之前、之后、不加"三种顺序下都回到 `CASE_MOVED`，没有 agent/error。

但我按派单要求查了边角，找到三处作者测试没覆盖的路径。它们都不是本轮引入的（第五到第七轮就有），但都在本卡累计范围内，其中一处直接破了不变量①：

- 空白新对话遇到搬家，旧文件夹会被重建出来；
- 一轮当中搬家，律师看到的是带完整路径的英文报错，不是中文提示；
- 接回时如果读取到时，打开案件会一直卡住。

---

### Findings

**F1【P2｜累计范围内阻断｜非本轮引入（第五/七轮起）】空白新对话遇到搬家：旧位置被重建，律师那句话写进重建出来的旧文件夹（不变量①破）**

- **问题**：DSH 进入案件时会建一个空白对话。依据是 `ui-workspace/src/client/navigation.ts:178-188` 的 `reuseOrCreateBlank`，它调 `sessions.create`。这个对话的 Agent 活着，但原版还没落过盘。
  - 案件文件夹被搬走后，律师在这个空白对话里发第一句。
  - 我方 prepend 的 pre-step 照常拒绝，`CASE_MOVED` 也有。
  - 但 DSH 仍把"这句话、turn/start、turn/end(blocked)"投给还登记着的写入者。原版对没落过盘的会话走 `materialize`，会 `mkdir(recursive)`（`session-persistence-jsonl/src/index.ts:1176-1206`）。
  - 结果：旧路径整条被重建。
- **影响**：
  - 桌面上会冒出一个"案丙\工作区\会话\…\s2\session.v4.jsonl"，里面是律师刚打的那句话。
  - 律师以为案件已经搬走，旧处其实又出现了含案件内容的文件。
  - 有中文提示，所以不算静默；但"不写旧处"破了。
  - 这条路径不需要任何罕见操作：打开案件 → 在资源管理器里拖走文件夹 → 回软件在默认的空白对话里打字。
- **证据**（`scratchpad\rv-A31-B-specs\zz-rvb31.spec.ts`，live-writer 同一套环境）：
  - M1b（不在新位置打开），after：`{"calls":0,"notice":"CASE_MOVED","errors":[],"oldRecreated":true,"oldFiles":["\\工作区\\会话\\--…--\\s2\\session.v4.jsonl"],"oldHasSay":1}`。
  - M1（新位置打开后），after/before/none 三种模式相同：`"oldRecreated":true,"oldHasSay":1`。
  - 对照组 C0（会话已落过盘）是 `oldExists:false`，原因是追加用 `open(path,'a')`，不 mkdir。
- **最小修复**：
  - 对 `seen === false` 的写入者（从没落过盘），位置失效时立刻放下。这时缓冲是空的，原版 `close()` 没有东西要落，旧处也没有东西可丢。
  - 落点有两处，都要做：一是 prepend 拒绝那一刻（拒绝前 `await within(close)`）；二是 `toDetach` 对 `!seen` 不要求"还在盘上"。
  - 收 M1、M1b 为用例。

**F2【P2｜累计范围内｜本轮修法没覆盖到的同根问题】没落过盘的会话 + 原路径上又建了别的案件：对话写进别的案件文件夹**

- **问题**：B-F2 的新判断只对"见过记录"的会话生效。空白对话（同 F1）遇上"搬家 → 新位置打开 → 原路径新建另一案件并打开"时，`recordGone` 走 `!seen` 分支，返回 false，于是放行。task/begin 按旧 cwd 取到的是另一个案件。
- **证据**：M2 在 after/before/none 三种模式下都是 `{"caseMoved":false,"calls":1,"notice":null,"errors":[],"otherCaseHasSay":1,"otherCaseHasReply":1}`。也就是模型被调用，律师的话和回答都落进了另一个案件的 `工作区\会话`。
- **影响**：
  - 律师以为自己在 A 案的对话里。
  - 实际上问答存进了 B 案文件夹，模型拿到的也是 B 案上下文。
  - 前提比 F1 窄。
- **最小修复**：同 F1。没落过盘的写入者一旦位置失效就放下并保持失效，接回时 `open` 会报找不到、不会接回。修好 F1 后 M2 一并关闭。

**F3【P2｜累计范围内｜非本轮引入】一轮当中（第 2 步之前）搬家：没有 CASE_MOVED，只有含完整路径的英文错误**

- **问题**：prepend 的拒绝只看 `step === 1`（`agent/index.ts:206`）。
  - 第 1 步发了工具调用，工具执行期间案件被搬走。
  - 第 2 步 prepend 调 `next()`，`session-checkpoint-policy` 先 `sessions.flush` 抛 ENOENT，整轮按 agent/error 结束。
  - 原来那个"先 next() 再判"的 pre-step 只在 step 1 判 `caseMoved`，所以也不会给提示。
  - 另外，checkpoint 在 `tools/execute`、`llm/stream` 边界也 flush，模型流式回答途中被搬走同样会落到这条路。
- **证据**（S2：工具 `/core/tool` 延迟 1.5 秒，第 0.6 秒时搬家）：
  - after/before 两种模式下，不论新位置打开与否：`{"calls":2,"notice":null,"errors":["Error:ENOENT: no such file or directory, open '<tmp>\\桌面\\案丙\\工作区\\会话\\--C-Users-…"]}`。重启后 `reply:false`。
  - none 模式：`calls:3`、`errors:[]`、`notice:null`，模型回答了，但哪里都没落盘（静默丢）。
  - 下一轮 step 1 会正常给 `CASE_MOVED`。
- **影响**：
  - 不变量②在"一轮当中搬家"这个变体上破了：律师看到的英文错误带案件完整路径。
  - 生产组合下没有静默丢，这一轮按报错结束；不加 checkpoint 时有静默丢。
  - 10.4 没有把"一轮当中搬家"记成已知限制，现有的只有复制和拔盘 E2。
- **最小修复**（二选一，交主编排）：
  - ① prepend 那个 pre-step 在 step>1 且 `caseMoved` 时也走 `noteBlocked('CASE_MOVED')` 加 reject；`tools/pre-execute`（已是 prepend）在 `caseMoved` 时拒绝。E2（拔盘一轮当中）是单步文本回答，不受影响，需要回归确认。
  - ② 记为已知限制，并说明错误文字含完整路径。

**F4【P2｜累计范围内｜B-F5 修得不完整（"持有时等待"）】接回时 read 到时之后，关新句柄没设上限，打开案件会一直卡住**

- **问题**：`router.ts:279` 的 `await closeHandle(fresh).catch(…)` 没有套 `within`。
  - read 到时（盘慢、网络盘挂住，正是 B-F5 要防的场景）之后，关这个新句柄（原版 close 要 `lease.release()`）也可能挂住。
  - 这时 `recheckOnce` 不返回，同一会话后面的 recheck 都排在它后面。
  - `refreshNow` → `recheckWriters` 要等它；Host 的 `caseOpen` 在 `index.ts:405` `await this.refreshCaseRoots()`，所以打开案件的调用不返回。
- **证据**：`zz-rvb31-f5.spec.ts` F5b（假实例：第二次打开后 read 和 close 永不返回，上限 100ms）输出 `{"first":"STILL-WAITING-2s","ms":3022,"second":"STILL-WAITING-1s"}`。
- **最小修复**：`await within(closeHandle(fresh), ms).catch(() => undefined)`，或改成 `void closeHandle(fresh).catch(…)`。session-store.spec 加 read 挂住加 close 挂住一例。

**F5【P3｜独立后续｜静态推断加单元实验】接回 open 到时后，迟到返回的写句柄没人关**

- **问题**：`within` 不取消原来那次 `open(id,'write')`。它迟到返回后，句柄不关，原版的写入者登记和进程内占用一直留着。
- **证据**：F5a 输出 `later:{"opened":2,"closes":1}`，说明迟到的句柄打开了却从未关闭。
- **影响**：
  - 之后再接回会被原版的 writer-held 挡住，一直 `CASE_MOVED`，直到重启。
  - 遗留的写入者可能把被拒轮次的事件写到原位置。那时原位置已经回到名单，不违反①；序号不连续时原版会拒写。
  - 整体是安全一侧的失败，重启即恢复。
- **最小修复**：`open` 的 promise 到时后挂一个 `.then(h => closeHandle(h))`。

**F6【P3｜臆测｜静态】记录目录判断是同步 IO，没有上限**

- `onDisk` 用的是 `readdirSync` 加逐个 `existsSync`，`within` 套不上。
- 调用点有三类：step 1 两次（prepend 一次、原 pre-step 一次）；`flush()` 里对每个没见过记录的写入者各一次（checkpoint 每步都 flush）；`writersToRecheck`。
- 网络盘挂住时会阻塞整个运行时主线程。这和原来就有的 `existsSync(caseRoot)` 是同一类问题，本轮只是多了几次调用，不是新类型。没有实测。

**NOTE**

- `encodeSegment` 与原版逐字一致，只差空字符串：原版抛错，我方返回 `''`，`onDisk` 会因此恒为真。会话编号不会为空，不可达。超长编号走 Node 的长路径处理，没实测。
- prepend 那条路径造了一个 `{kind:'enter',messages:[]}` 交给 `preStep`。两次 `caseMoved` 在同一同步段里，结果一致，所以实际总是拒绝。但如果将来两次判断不一致，会绕过整条 pre-step 链。建议 prepend 里直接 `noteBlocked` 加 `return {kind:'reject'}`。
- `--store-dir`：本机 `pnpm config get store-dir` 是 `undefined`。`packaging\build.ps1:84` 的 install 没带 `--store-dir`。作者自报默认 store 缺 `@stylistic/eslint-plugin`、离线装不上，这一点我没复现。如果属实，`build.ps1` 的 dsh 步在这台机器上会失败，只在 clean-build.txt 里写了一句（T20 独立后续）。
- DSH 自身日志带完整路径（B-F6）：已按定性记为已知限制。F3 说明这个问题在"一轮当中搬家"时也会显示给律师。

---

### 冻结清单逐条核对（第八轮综合裁决第 2 节）

| 编号 | 结论 | 我的证据 |
|---|---|---|
| B-F1 | **关闭** | **cordis 机制**：`vendor/cordis/src/events.ts:254-258`，`prepend` 用 `unshift`；`waterfall`（`:234-243`）按数组顺序从外向里调，不调 `next()` 就截断后面全部。checkpoint 是 `push` 登记的，所以不论加载顺序，我方 prepend 都排在它前面。**生产插件树**：运行时清单里登记 `agent/pre-step` 并且 active 的有 checkpoint、repeat-tool-reminder、goal-round-driver、tool-skill、compaction-basic、archived-session-gate，都不是 prepend。DSH 里 prepend 的 pre-step 只有 time-context 和 tmux-context，前者 disabled，后者不在清单里，而且 time-context 也是先调 `next()`。**checkpoint 真被加载**：变异"判断不排最前"有 7 例变红，全是 after/before 模式（`mut-out.md`），与作者 mutate.txt 一致。**重跑**：C0 在三种模式下 turn1/turn2 都是 `CASE_MOVED, errors:[]`，`oldExists:false`，`newSame:true`，重启 `hasMoved:false`；C2 三种模式都是 `CASE_MOVED, errors:[]`，插回后续写正常。**step>1 未覆盖**，见 F3 |
| B-F2 | **关闭**（C4 范围内）；**带出 F2** | C4 三种模式都是 `caseMoved:true, CASE_MOVED, errors:[]`，`tmpHasReply:0`，重启 `first:true`。我另做了 C4b：原路径新案件里恰好有同名项目目录，仍然判 `CASE_MOVED`。没落过盘的会话照样放行，见 F2。新会话第一轮不误判那例通过。耗时上界：同步、没有上限（F6） |
| B-F3 | **关闭** | 我自己的干净 clone 打 13 补丁，`.d.mts` 由 P-4 带入。离线安装 `rc=0`；`pnpm run build` `rc=0`，日志里 `TS7016` 0 处，`error TS` 0 处 |
| A-P3-1 | 已做 | diff 里锚点已改（没独立重跑 `mutate_check.py`） |
| A-P3-2 | 已做 | PATCHES.md 依赖行、二十例、⑧⑨，`index.ts:132` 注释 |
| A-P3-3 / B-F4 | 已做 | `router.ts:239-240` 注释、10.4 |
| B-F5 | **部分**：open/read 已加上限，单测变异变红；**后续路径**：到时后保持 `detached`，`caseMoved` 为真、整轮拒绝；放下后旧句柄已关，不写旧处；被拒那句只在内存，有提示，不算静默丢 | 关新句柄没上限（F4），迟到句柄没关（F5） |
| B-F6 | 已记已知限制 | — |
| A-NOTE 11.5 | 已改 | — |

### 不变量与受影响旅程（白话）

在案件文件夹被复制、搬走或拔盘时，正活着的对话应当满足四条：

- ① 不往旧处写：**F1 破**（空白对话）。
- ② 给中文提示 `CASE_MOVED`：**F3 破**（一轮当中搬家）。
- ③ 不丢：生产组合下守住；不加 checkpoint 时 F3 有静默丢。
- ④ 重启后续写正常：守住（C0、C4 重启）。

受影响的旅程有六条：复制后在新位置打开、搬家后在新位置打开、搬家后没打开、拔盘再插回、原路径重建别的案件、复制后又打开原位置（接回）。

### 影响地图

| 类别 | 状态 | 说明 |
|---|---|---|
| 调用方 | 受影响 | Agent 插件 pre-step（prepend 加原版）、Host `caseOpen` → `refreshCaseRoots`（F4）、会话存储 `flush` |
| 接口 | 已排除 | 契约没改；`sessionPersistence.caseMoved` 签名没变 |
| 持久化 | 受影响 | 没落过盘的会话在旧处被 materialize（F1、F2）；已落过盘的会话不重建旧处 |
| 并发与重试 | 受影响 | recheck 按会话排队里有没上限的 close（F4）；迟到的 open（F5） |
| 配置 | 已排除 | 配置行没改 |
| 打包 | 受影响、已验证 | P-4 加了 `.d.mts`，干净构建通过；`build.ps1` 没带 `--store-dir`（NOTE，未复现） |
| 可观测性 | 受影响 | F3 的 agent/error 含完整路径；我方新日志只记元数据 |
| 失败语义 | 受影响 | step>1 的失败按英文错误结束（F3） |

### 活性

- 放下：有 3 秒上限。
- 接回：open、read 各有 3 秒上限，**close 新句柄没有上限**（F4，实测会卡住 caseOpen）。
- 等空闲：没有超时，但只监听一次、有去重。
- `onDisk`：同步，没有上限（F6）。

### 八项清单

- **契约一致**：通过，契约没改。
- **边界输入**：不通过，见 F1、F2、F3。
- **错误路径**：不通过，见 F3、F4。
- **日志不含正文**：我方新日志通过；DSH 自身的错误带路径（F3、B-F6）。
- **路径闸门**：没被绕过。但 F2 让对话进了另一个已登记的案件，闸门本身拦不住这种情况。
- **无外连**：通过，只到 127.0.0.1 的随机端口，跑完即关。
- **测试覆盖新代码**：不足。没落过盘的会话遇到搬家，以及 step>1 的情形，都没有用例。
- **无机密入库**：通过。

### 回归

- dsh-ext 全量：31 个文件，504 项通过、5 项跳过，与作者报的数一致。
- `tsc --noEmit`：rc=0。
- 抽 6 条变异重跑：判定不看盘、第八轮 B-F1、B-F2 不判记录、B-F2 新建不等落盘、B-F5、第七轮 B-F1。失败数分别是 1/7/1/20/1/2，与 `mutate.txt` 逐条一致。源文件的哈希在跑前跑后相同。

### 实际跑过的命令

- `git rev-parse` / `status` / `diff --stat`、`git archive`。
- DSH：`clone --no-hardlinks`、`checkout 477b4f4`、13 次 `apply --check` 加 `apply`、robocopy 品牌图。
- `corepack pnpm@11.7.0 install --offline --frozen-lockfile --store-dir D:\.pnpm-store`，DSH 和 dsh-ext 各一次。
- `corepack pnpm@11.7.0 run build`。
- `node scripts\test.mjs`：全量；`zz-rvb31` 在 after/before/none 三种模式各跑一遍；`-t M1b`；`zz-rvb31-f5`。
- `node ..\dsh\node_modules\typescript\bin\tsc -p tsconfig.json --noEmit`。
- `python mutate.py <out> <6 个名字片段>`。
- `pnpm config get store-dir`。
- 读了 DSH 源码：`cordis/src/events.ts`、`session-checkpoint-policy`、`archived-session-gate`、`time-context`、`session-persistence-jsonl` 的 `format.ts`/`index.ts`/`storage.ts`、`session-controller` 的 `agent.ts`/`commands.ts`、`ui-workspace/navigation.ts`。

### 残留审计

- 实验目录 `rv-A31-B-lab` 已用 `rmdir /s /q`（`\\?\` 前缀，不跟随联接）删除，`Test-Path` 为 False。
- `%TEMP%` 下的 `lb-rvb31-*`、`rvb31f5-*` 为 0。19310–19319 没有监听。
- 我没留下 node 进程。现存的几个 node 都是线 A 的 `start:desktop` 和 Codex，没碰。
- rv-A31 的 HEAD 不变，status 干净。`D:\lawbench*` 和协调目录我没写过。
- 一处误操作要说明：一次递归 `Get-ChildItem` 进了 node_modules，超时转后台，已用 TaskStop 停掉，只读。
- 留下 `scratchpad\rv-A31-B-specs\`：两个 spec、四份输出（`rvb31-out.txt`、`rvb31-m1b.txt`、`rvb31-f5.txt`、`mut-out.md`），用户名已替换成 `<用户>`。
- 离线安装读了 `D:\.pnpm-store`，可能更新了 store 的元数据，没有下载任何东西。

### 证据缺口

- 桌面端没起：F1 的"空白对话"路径依据的是 DSH 源码（`reuseOrCreateBlank`）加包测试层复现，没在界面上走一遍。
- 搬家、拔盘都用改名模拟。网络盘挂住只用假实例模拟（F4、F5），没测真 SMB 的同步阻塞（F6）。
- 默认 store 离线装不上（`build.ps1` 缺 `--store-dir`）没复现。
- `mutate_check.py` 没独立重跑。

AMEND

