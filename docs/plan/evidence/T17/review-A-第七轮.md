# T17 第三步"活着的句柄"按 N55 ② 改做法（第七轮）· Reviewer A（改动纪律与可维护性）

- target：line-A `26b5cde`（已 rebase 到 main af55f84）；本轮重审 `26b5cde`（不搬写入者；偏离：空闲时放下 / 盘回来接回约 30 行）
- 派发：两名 Opus 5.5 只读复核员同一条消息并发派出，素材相同，互相看不到
- 复核克隆：scratchpad `rv-A29`
- 归档：主编排于 2026-10-02 13:47 (+08:00) 从复核员交回原文抄录，未改内容

## 复核员原文
# T17 N55 ② 第三步"活着的句柄"（line-A `26b5cde`）· Reviewer A（改动纪律与可维护性）· 克隆 rv-A29

**结论：AMEND。** 拒绝整轮、提示重启、"放下写入者"这几处做法本身成立。但作者偏离加的"接回"有一个时序漏洞，是本次修正引入的：盘拔出后插回、名单刷新的那一刻，律师恰好发出一句话（本机实测窗口约 2–12 毫秒），软件会照样接回。之后这一会话的每一轮都照常回答，但哪一轮都存不下来，重启后全部消失，界面上什么提示都没有。改起来只要约 2 行，我在实验副本里试过，有效。

## 一、发现

**P2-1（本次修正引入，范围内阻断）接回时用的"内存事件数"取早了，竞态下误接回，之后整段对话静默不落盘**
- **问题**：`index.ts` 的 `recheckOne` 先同步取 `sessions.get(id).seq`，再排队进 `router.recheck` → `recheckOnce` → `await w.at.backend.open(id,'write')` → `read()`，然后拿 `n !== eventCount` 比对。
  - 取数之后、`open` 登记写入者之前，律师发出的那句会被拒，但被拒那一轮的事件仍然会发出来。这时没有写入者，事件被原版直接丢掉，内存比盘上多出几条。
  - 可是比对用的是旧数，于是判"一样长"，照样接回。之后的事件序号接不上游标，原版的 `assertContiguous` 失败，`drainPaused` 卡住，之后每一轮都写不进去。
  - `caseMoved` 却返回 false，所以 Agent 照常回答。
- **影响**：
  - 盘拔出又插回（或名单暂时报 `exists:false`）后，在那次刷新的几毫秒内发出消息，此后本次运行的整段对话都不落盘，重启后丢失，界面没有任何提示。
  - 网络盘、U 盘上 `open` 更慢，窗口更宽。
  - 这正是第六轮被否的"空档静默丢"那一类问题。
- **证据**（实验 spec 写在我的导出副本里，用的是真 AgentLoop 加我方插件）：
  - **X2**（测试里给 `sessions.get` 包一层，取数后的下一个微任务里律师发一句）：结果 `{"caseMoved":false,"calls":1,"afterNotice":null,"flushErr":"lawbench session store flush failed","diskHasAfter":false}`。模型照常回答，没有提示，flush 失败，重启后读不到那条回答。
  - **X4**（不插桩，只扫时序：根回到名单的那次 `refreshCaseRoots()` 发出后 k 毫秒发一句）：
    - k=0、1：`moved:ok`（正确，没接回）
    - k=2、3、4、5、6、8、10、12：`attached:FLUSH-FAIL`
    - k=15 以上：`attached:ok`
- **最小修复**：
  - 比对改用 `read()` 之后再取的内存 seq，例如给路由传一个取数函数，不传数值。
  - 补一例回归测试（X2 可以直接收）。
  - 我在导出副本里试过：给 router 加 `liveSeq` 回调，比对改成 `n !== (this.liveSeq?.(id) ?? eventCount)`，index 里注入。改后 X4 在 2–12 毫秒全部变为 `moved:ok`，`live-writer` 加 `session-store` 加实验共 101 项全过。试完已按原字节复原，再删掉整个副本。
  - 另一种做法：放下过的写入者一律不接回、一直要求重启。这样少约 10 行，但执行令第 2 条"根回到名单自动解除"在这种情形下就做不到了。

**P3-1（本次修正引入，文档与代码不一致）排在正在跑那一轮后面的下一句会写进旧处**
- **问题**：律师在一轮还没跑完时又发一句，DSH 跑完这一轮不经过空闲，直接开下一轮（`agent.ts:373–378`）。下一轮被拒，但它的事件仍经还登记着的写入者写进旧处。这时放下还没做，因为放下要等 `agent/status` 变 idle。
- **证据**：X1（复制情形，跑一轮期间在新位置打开，再排一句）：`{"queuedInOld":1,"queuedInNew":0,"notice":"CASE_MOVED"}`。
- **影响**：复制情形下旧处多出律师这句原话，不过界面有提示，不算静默丢。10.4 只写了"关句柄的几毫秒"，范围说窄了。搬家情形下这句在放下时落盘失败被丢掉（见 P3-2）。
- **修法**：10.4 那条改写为"这一轮跑着时律师又排了下一句"。

**P3-2（本次修正引入）放下和接回的失败被静默吞掉**
- **问题**：
  - `recheckOnce` 里 `closeHandle(w.cur).catch(() => undefined)` 不记日志。搬家情形下，跑着那一轮剩下的事件（B-F6）和 P3-1 那句恰恰在这里落盘失败、被注销，一点痕迹都不留。
  - 接回时 `open` 失败、`read` 失败（→ -1）同样不记。
- **修法**：各加一条只含元数据的 warn 日志，例如 `session_store.writer_detach_failed {index, error: name}`。

**P3-3（本次修正引入，可维护性）代理的方法转发对象不一致**
- **问题**：`handle()` 把 `movingWriter` 并进来以后，代理上除了 `close`，其余属性都转给最初那个句柄 `target`，而 `close` 关的是 `w.cur`。接回之后两者不是同一个句柄。
- **为什么现在无害**：DSH 只在发布前用句柄的 `read`/`append`（`agent-loop/src/index.ts:698–705、852–864`），之后只在收掉 Agent 时调 `close`（`:556`）。
- **修法**：转给 `w.cur`，或者写一行注释说明为什么可以不转。闭包里的 `w!` 也可以顺手收紧。

**P3-4（本次修正引入，文档）依赖清单和已知限制漏了两处**
- PATCHES.md 本轮那一行没写"`close()` 可重复调用"（`storage.ts:224` 的 `closing ??=`）。放下之后 Agent 收掉时会再关一次，要靠这一点。
- 10.4 只写了"被拒的那句话不保存"。放下期间对这个会话的其他改动（比如侧栏改标题等会话事件）同样不保存。执行令第 4 条点名过"标题等"。

**NOTE-1（此前既有，T20 `aaec54b` 引起，记独立后续或合并前检查）插件树检查对 T17 存档输入跑不通过**
- **现象**：`docs\plan\evidence\T17\check_plugin_tree.py` 拿 T17 存档的 `plugin-inventory-desktop.json`、`plugin-tree.txt` 跑报"不通过"，`mutate_check.py` 报"1 项不符合预期"。
- **原因**：T20 已把 `customSkillDirs` 的期望改成新的打包感知表达式，和当前 `cordis.patch.yml` 一致；但 T17 的这份存档是 `8eadfc1`（10-01）导出的，还是旧表达式。
- **与本提交的关系**：没有关系，本提交不碰配置。T13 那份副本照常通过。
- **建议**：合并前在桌面端重新导出一次清单。

**NOTE-2** `tests\agent.spec.ts` 里局部变量还叫 `lost`，只是名字残留。

**NOTE-3（文字技术意见；主编排已定要补）**
- `CASE_MOVED_TEXT` 建议补一句"刚才这句话可能没有保存，重启后请重新发送。"
  - 用"可能"，是因为"盘暂时不在、名单没变"的情形下，被拒那一轮在插回后会落回原处（第 5 例）。
  - 这一句也顺带覆盖了 B-F6"上一轮可能没保存"。
  - 这句不含禁用词。
- `CASE_NOT_FOUND` 不要补：那一轮落在原处（第 10 例 `has(oldR,'NOT-FOUND')=1`）。

## 二、偏离的机制判断（任务第 2 条）
1. **被拒一轮仍写事件：属实。** `agent.ts:154–160` 的 `send()` 先 `inbox.splice`，这一步在 `inbox.ts:235` 同步 `session.append('agent/inbox/spliced')`；然后 `wakeDriver` → `turn()` 里 `append('turn/start')`（:305），之后才进 `preStep`（:316），拒绝后 `turn/end{blocked}`（:318、368）。我的实验 X3 看到内存比盘上多 4 条：`agent/inbox/spliced`、`turn/start`、`agent/inbox/spliced`、`turn/end`，和作者说的一致。
2. **放下时缓冲里的事件：**
   - 原版 `close()`（`storage.ts:223–260`）先落盘缓冲，再注销写入者，落盘失败也注销。
   - 复制情形：旧处还在，缓冲落进旧处，包括跑着那一轮的剩余部分和 P3-1 那句。
   - 搬家情形：落盘失败，事件丢掉，错误被吞（P3-2），这就是 B-F6 那条。
3. **"一样长"比对：**
   - 与第六轮被否的长度核对不同：第六轮比的是另一份副本对内存；这次比的是本进程自己独占写过、刚关掉的同一个文件。要出现"一样长但内容不同"，必须另有写入者（比如别的机器经网络盘写同一文件），可以视为臆测级风险。
   - 真问题在于拿来比的内存数取早了，见 P2-1。
4. **放下后被丢的事件：**
   - 每被拒一轮丢 4 条：律师原话 `agent/inbox/spliced`、`turn/start`、移出用的 `agent/inbox/spliced`、`turn/end(blocked)`。
   - 另外，放下期间界面对这个会话做的其他改动发出的会话事件（标题等）也会丢。
   - 原版依据：`storage.ts:536` 的 `writers.get(id)?.` 找不到写入者就直接丢。
   - 可以作为已知限制接受，但 10.4 要写全（P3-4）。
   - 会调 `sessions.flush` 的插件不会报错：没有写入者时 listener 返回 undefined。反馈插件需要参与 flush，但它在 `cordis.patch.yml` 里已关。
5. **比"只标记"多依赖的 DSH 私有行为：**
   - `close` 先落盘再注销、失败也注销
   - `close` 可重复调用（清单漏了，P3-4）
   - 写入者注销后原版直接丢事件
   - `open(id,'write')` 能在原处重新登记（锁已在 close 时释放）
   - 写句柄的 `read()` 返回盘上的前缀
   - 会话 `seq` 等于内存事件数
   - PATCHES.md 本轮那一行的 ①–⑦ 覆盖准确，删掉 seq 接续、逐条比对两项也准确；只差可重复 close 一条。

## 三、逐 hunk 清点（12 个文件，产品代码 +87/−127，numstat 核实）
| 文件 | 归类 | 说明 |
|---|---|---|
| `session-store/router.ts`（+61/−103） | 必需实现，含偏离 | 删掉 `movingWriter`、`relocate`/`relocateOnce`、补齐与比对、`lost`、`staleWriters`、`writerLost`；新增 `caseMoved`、`writersToRecheck`、`recheck`/`recheckOnce`、`closeHandle`；文件头注释更新。`locate`/`ownerOf`/`open`/`stat`/`list`/`refreshOnMiss` 没有 hunk |
| `session-store/index.ts`（+14/−15） | 必需实现 | `relocate*` 改成 `recheck*`，对外方法 `writerLost` 改名 `caseMoved`；`refresh`/`refreshNow` 只换了调用名 |
| `agent/index.ts`（5/5） | 必需实现 | 只是改名，step 1 拒绝逻辑不变 |
| `ui/dock.tsx`（+5/−2） | 必需实现 | `CASE_MOVED` 文字按执行令原文；新加 `CASE_NOT_FOUND` 提示（执行令第 5 条） |
| `host/attach-sessions.ts`（2/2） | 必需 | 只改注释，去掉对 `relocate` 的死引用；挂回逻辑没动 |
| `dsh-patches/PATCHES.md`（1/1） | 必需验证 | 核对清单那一行 |
| `tests/live-writer.spec.ts`、`session-store.spec.ts`、`dock-a19.spec.ts` | 必需验证 | 搬迁用例已删干净 |
| `交付说明.md` 第 10 节、`N55返修/mutate.py`、`mutate.txt` | 必需验证 | — |
| 无关改动 | 无 | — |

`relocate`/`writerLost`/`staleWriters`/`writer_lost` 在 dsh-ext 产品代码和测试里零残留，只在历史证据里出现。

## 四、执行令 1218 逐条核对
| 条 | 结果 |
|---|---|
| 1 去掉搬迁整套，名单刷新、`locate`/`ownerOf`、挂回不动 | 符合（diff 核过） |
| 2 判定只在内存、刷新失败不误判、根回到名单自动解除 | 判定符合；"放下后接回"有 P2-1 |
| 3 step 1 拒绝、执行令原文文字、正在跑的一轮不打断 | 符合；`check_ui_words` 零命中 |
| 4 不写旧处（DSH 自带事件记已知限制） | 偏离成立；残余见 P3-1，已知限制没写全（P3-4） |
| 5 用例（复制、搬家、刷新失败、盘插回、重启续写、`CASE_NOT_FOUND`） | 十例都在、都过 |
| 6 第 10 节、已知限制、"搬写入者"记 T14 后、第六轮独立后续、PATCHES 清单 | 基本符合；10.4 两处不准（P3-1、P3-4）。10.6 里 A-P3-1、A-P3-2、B-F6、律师说明、`lb-live-*` 都记了 |

## 五、八项清单
| 项 | 结果 |
|---|---|
| 契约一致 | 是，没碰 `contracts\`；`check_examples` 通过 |
| 边界输入 | 刷新失败、盘暂时不在、并发 recheck 都有用例；放下后又被拒、但接回前那几毫秒里的消息没覆盖到（P2-1） |
| 错误路径 | 放下和接回失败被吞（P3-2）；接回误判后静默不落盘（P2-1） |
| 日志不含正文 | 是，新日志只有 `index` |
| 路径闸门未被绕过 | 是，接回只在原实例开 |
| 无外连 | 是，实验假服务只监听 `127.0.0.1:19301` |
| 测试覆盖新代码 | 主路径有；竞态没有 |
| 无机密入库 | 是，本提交 diff 里没有用户名、Key、密码 |

## 六、实际跑过的命令（实验副本 `scratchpad\rvA29A`，现已删除）
- **核实 target**：`git rev-parse HEAD` = `26b5cde`；`git status --short` 干净；`af55f84` 是 HEAD 的祖先。origin/main 已经前进到 `ae6a617`（合并了 line-C），不影响本轮。
- **补丁链**：clone `D:\lawbench-A\dsh` → `477b4f4`，按 PATCHES.md 顺序 13 个补丁 `apply --check` 和 `apply` 全部为 0，再拷入品牌图片。
  - 与 `D:\lawbench-A\dsh` 工作区逐字节比对：双方各 108 个变动文件，全部哈希相同，所以本轮确实没改 DSH 补丁。
- **`D:\lawbench-A` 工作区里的在途改动**：
  - 27 个 `ui\fixtures\*.json` 和 `packaging\brand\names.txt` 标 M，但 `git diff` 内容差为 0，只是 CRLF/LF 重新标准化后的状态，和 10.7 说的一致。
  - `.tmp-demo\` 是未跟踪的演示数据（虚构名），没入库。
- **全量测试**：`node scripts\test.mjs`：31 个文件，493 通过、5 跳过，与作者一致。
- **类型检查和构建**：`tsc -p tsconfig.json --noEmit` 退出码 0；`node scripts\build.mjs` 退出码 0。
- **静态检查**：`check_ui_words.py` 零命中；`check_examples.py --skills skills` 退出码 0；T13 的 `check_plugin_tree` 和 `mutate_check` 通过；T17 的不通过（NOTE-1）。
- **作者变异 14 抽 6**（不看名单、放下过的不算失效、根不在名单上不放下、先记已放下再关、接回不核对长度、recheck 不排队）：全红，失败数与作者 `mutate.txt` 一致（2/1/3/1/1/1）。脚本跑完写回原字节，`git status` 核过干净。
- **我的实验 X1–X4 和候选修复**：结果见第一节。候选修复按原字节复原后才删除副本。

## 七、残留审计
- 端口 19301–19309 没有在监听；最近 40 分钟没有我起的 node 进程。
- 系统 `%TEMP%` 没有 `rva29-*`。我把测试的 TEMP 指到了实验目录，作者用例的 `lb-live-*` 已自删。
- 删除副本之前，先用 `rmdir` 拆掉了 14 个联接（指向 `D:\lawbench-A\dsh` 的 2 个、副本内部的 12 个），确认 `D:\lawbench-A\dsh` 完好。删除后副本不在了。
- `D:\lawbench-A` 和 `D:\lawbench-A\dsh` 的 status 条数与开工前相同（30 / 108）。
- 没碰别人的进程；`rv-A29-lab` 是别人正在建的目录，我没动。

## 八、证据缺口
- 桌面端没有实测。
- DSH 包经联接用的是 `D:\lawbench-A\dsh\packages` 里已构建的产物；源码逐字节核过一致。
- 网络盘、U 盘上的竞态窗口没有实测，只在本机 SSD 上测到约 10 毫秒。
- T17 插件清单没有重新导出（NOTE-1）。

AMEND
﻿