# T17 第三步"活着的句柄"返修累计（第六轮）· Reviewer B（影响半径、边缘情况与回归安全）

- target：line-A `0210476`（已 rebase 到 main a0f9c26）；本轮新提交 `0210476`（N54 ①，线 A 注记 1720 改道为"搬写入者"，主编排追认）；累计另含 `fc0f801`、`116e576`、`487167a`
- 清单：执行令 1711 + 注记 1720 改道
- 派发：两名 Opus 5.5 只读复核员同一条消息并发派出，素材相同，互相看不到
- 复核克隆：scratchpad `rv-A23`
- 归档：主编排于 2026-10-01 19:15 (+08:00) 从复核员交回原文抄录，未改内容

## 复核员原文
## 复核员 B：T17 第三步"活着的句柄"（N54 ①）返修，累计范围 `a0f9c26..0210476`

结论：**REJECT**。不变量①②在真实代码路径上又被打破了：律师在"搬写入者"进行中发出的那条消息，以及这个会话此后的全部事件都没落盘，而且 `CASE_MOVED` 也没出现，律师看不到任何提示。我给出两个可复现的例子。另外一个问题影响更大：按真服务的语义，"活会话复制 → 在新位置打开 → 续写"这条旅程本身就走不通，每一轮都被静默拒绝。

我核过的环境：克隆 rv-A23 的 HEAD 是 `0210476`，工作区干净，`a0f9c26` 是它的祖先。实验在 `git archive` 导出的副本 `rv-A23-B-lab` 里做，dsh 用联接只读指向 `D:\lawbench-A\dsh`，做完已删除。

---

### 发现

**F1【P1｜本次引入的回归｜范围内阻断】搬迁进行中来的事件哪里都不写，之后这个会话的所有事件也都写不进去，没有任何提示**

- **问题**：`router.ts` 的 `relocateOnce` 先关旧句柄，关掉后旧实例里这个会话就没有写入者了。之后还要经过 `locate`（逐个案件根 stat）、在新实例以写方式打开（读校验整份记录），这期间的 `session/event` 投不到任何写入者，原版直接丢掉（`storage.ts:535` 的 `this.writers.get(id)?.enqueueLive`）。
  - 新写入者登记之后，后续事件的序号已经接不上；`assertContiguous` 失败后批量写停住（`drainPaused`），此后一直写不进去。
  - `writerLost` 仍是 false，所以没有 `CASE_MOVED`，只有一条 flush 失败的警告日志。
- **影响**：
  - 律师发的这条消息、这一轮的回答，以及本次运行里这个会话之后的每一轮都只在内存里，重启后都不见了。
  - 搬迁之前不存在这个问题：复制的情况下会写进旧处，不会丢。
- **证据**：`zz-rvb23.spec.ts`，用真 AgentLoop、真会话存储和 Host 的 `caseOpen`，**不注入任何延迟**。
  - S1：200 轮的会话复制后，在 `caseOpen` 发出后第 d 毫秒发一条消息。d=20、30、40 毫秒时新旧两处都没有这条（`newHas:0, oldHas:0, lost:false`）；d≤10 落旧处并补到新处；d≥60 落新处。
  - S2：d=20、25、30 各跑一次，3/3 复现。内存里 1619 条事件，重启后盘上只有 1603 条；这条消息和后面那一轮 `LATER-MSG` 都没有，`flush` 报 AggregateError，`lost:false`。
  - R1：新位置打开慢 400 毫秒（模拟网络盘或很长的会话），结果相同。
  - 本机 SSD 上空档约 20–40 毫秒；盘越慢、案件根越多、会话越长，空档越宽。
- **真实触发路径**：
  - 另一个窗口正开着这个会话；
  - 一轮结束、Agent 变空闲后的那一刻（等待路径就在这时触发搬迁）；
  - 停止后立刻重发（见 F3）。
- **最小修法**：搬迁期间不能有空档。
  - 搬迁期间让 Agent 插件的 pre-step 等这个会话搬完再开始。
  - 新写入者登记之后，以内存会话（`sessions.get(id)`）为准补齐，不要用开始时拍下的长度。
  - 新写入者补写失败时记为已失效，走 `CASE_MOVED`。
  - 补一条"搬迁中发消息"的用例。

**F2【P1｜范围内阻断（机制早就存在，旅程验收挡在这里）】按真服务语义，活会话在新位置打开以后每一轮都被拒，界面没有任何提示**

- **问题**：活会话在内存里的记录头 cwd 仍是旧位置。我方 Agent 插件 `preStep` 用 `agent.session.header.cwd` 调 `/core/task/begin`（`agent/index.ts`）。
  - 真服务按 cwd 找已登记的根（`registry.py` 的 `find_by_root`）。复制后在新位置打开，按案件编号去重只留新根（`registry.py:135-138`），所以旧 cwd 得到 `CASE_NOT_FOUND`，整轮被拒。
  - 输入区只对 `INPUT_CHANGED`、`CASE_MOVED` 给提示（`dock.tsx` 的 `notice`），`CASE_NOT_FOUND` 不显示。
- **影响**：
  - 执行令要的旅程"复制 → 新位置 caseOpen → 立刻续写"在产品里不出回答也不说原因：律师发了消息，没有任何反应。
  - "关软件 → 复制 → 再开（DSH 自动恢复旧会话）→ 打开新位置 → 续写"同样如此，而这是律师挪案件文件夹最常见的做法。
  - 从首页重新打开也没用，只能重启软件。
  - 作者的测试看不到这一点：`live-writer.spec` 没装 Agent 插件；桌面端复测用的开发假服务 `task/begin` 不看 cwd（`fake-service.mjs` 的 `POST /core/task/begin`）。
- **证据**：
  - `zz-rvb23` J1 按真语义：`begin: CASE_NOT_FOUND`，内存 cwd 是旧位置，新处没有回答（`newHasAnswer:0`）；重开新位置再发一条仍是 `CASE_NOT_FOUND`。
  - 对照组 J1（假服务不看 cwd）：回答落新处，重启也看得到。
  - J2（关软件再开）：`notes:["CASE_NOT_FOUND"]`，没有回答。
  - 用真服务代码核对：`service\tests\test_zz_rvb23.py`（TestClient 起真 app）输出 `RVB23 old-cwd begin after copy+open-new: False CASE_NOT_FOUND`，换成新位置的 cwd 才成功。
- **最小修法**：
  - 写入者已搬时，`task/begin` 用会话现在所属的案件根。例如会话存储公开一个"该会话当前根"的方法，Agent 插件优先用它。
  - 输入区对 `CASE_NOT_FOUND` 也给中文说明。
  - `live-writer.spec` 补装 Agent 插件，假服务按 `find_by_root` 的语义写。

**F3【P2｜本次引入】停止后立刻重发：误判"两处分叉"，旧处在打开新位置之后又被写；模型较慢时这一轮的回答哪里都没存**

- **问题**：`relocateOne` 在 idle 事件的监听里同步读 `seq`。DSH 的 `kick` 在发出 idle 之后，同一个 tick 里 `wakeDriver`，`turn/start` 会先追加进去（`agent.ts:257-262`、`turn()`）。搬迁照旧进行，并没有再看一次 Agent 是不是又在跑了。
- **影响**：
  - 重发的那一轮写进旧处，补到新处之后长度对不上拍下的值，于是记为已失效，之后每一轮都给 `CASE_MOVED`。
  - 回答要 800 毫秒时，这一轮的回答新旧两处都没有，重启后也没有，而且这一轮没有 `CASE_MOVED`（`notes:[]`）。
  - 现在被 F2 掩盖（重发的这一轮会是 `CASE_NOT_FOUND`），F2 修好后就会真的发生。
- **证据**：
  - R2：`writerLost:true`，`oldResend:1, newResend:1`，再续写哪里都不写。
  - R3：`oldAns:0, newAns:0`，重启后回答为 false。
- **最小修法**：真正搬之前再看一次 `status`，在跑就继续等；核对长度时用打开之后再读的 `seq`。

**F4【P2｜本次引入的回归】网络盘或 U 盘一时报 `exists:false`：写入者被永久判为已失效，案件其实没动**

- **问题**：`writerStale` 看名单和 `existsSync`。刷新时服务报旧根 `exists:false`（比如睡眠唤醒时映射盘还没连上）就触发搬迁：先关旧句柄，再找新位置，找不到就记已失效。已失效的写入者再也不会重新搬（`staleWriters` 排除了 `lost`）。
- **影响**：
  - 盘恢复后、甚至在原处重新打开案件，本次运行里这个会话每轮都是 `CASE_MOVED`，提示还说"文件夹已不在原来的位置"。
  - 修前：写入暂时失败，留在缓冲里，之后照常写下去。
- **证据**：N1，`lostDuring:true, lostAfter:true, notes:["CASE_MOVED"]`，恢复后在原处没写进去。
- **最小修法**：先找新位置，找到别处的新位置才关旧句柄；新位置还是同一个根或者找不到时，留着旧写入者，下次刷新再判。

**F5【P2｜范围内】`CASE_MOVED` 的说明叫律师"从首页重新打开案件，再在这个对话里继续"，照做没用，律师会反复碰壁**

- **证据**：
  - L1：搬家后被判已失效，从首页打开新位置之后 `lostAfterReopen:true`，第二轮仍是 `CASE_MOVED`，新处没写入。
  - 交付说明 9.5 自己写的是"重新打开也搬不过去，要重启软件"。
- **最小修法**：改文字（例如"请重启软件后在这个对话里继续，或新开一个对话"），或者让重新打开时真的再搬一次。

**F6【P3｜独立后续】搬家发生在一轮进行中或两轮之间：这一轮的内容当时就丢，下一轮才提示，而且提示说的是"这条消息没有发出"**

- `relocateOnce` 关旧句柄时 `.catch(() => undefined)`，把落不进已删目录的缓冲吞掉了。作者的 `live-writer` 第 7 例就是这个现象（`IN-BETWEEN` 新处为 0）。
- 律师屏幕上看到了回答，但它没存下来，提示里也没说上一轮没存。
- 建议：落盘失败（ENOENT）时就提示；或者在 `CASE_MOVED` 的说明里补一句"上一轮的内容可能没有保存"。

**NOTE**
- `%TEMP%` 里有 21 个 `lb-live-*` 目录，建于 17:36–18:26，都早于我 18:53 开始的运行，应是作者跑 `live-writer` 时留下的。我的全量运行没有留下残留。按纪律我没删别人的目录。
- 性能：4803 条事件、1 MB 的会话，复制后 `caseOpen`（含搬迁）用时 180 毫秒。每次刷新名单只遍历写句柄并 `existsSync`，开销可以忽略。

---

### 冻结清单逐条核对

| 项 | 结果 | 依据 |
|---|---|---|
| ① 复制、空闲 → 新位置续写，旧处字节不变，重启看得到 | ✓（存储层） | AG 修前/修后对照、`live-writer` 1、J1 对照组 |
| ① 正在跑一轮 → 落旧处 → idle 后补齐 → 再写新处 | ✓ | `live-writer` 5（全量通过） |
| ① 复制时缓冲里还有未落盘的事件 | ✓ | 关旧句柄会先落盘，再读旧处补齐（代码，`storage.ts` 的 `close`） |
| ① 关旧开新之间来的事件 | **✗** | F1 |
| ① 停止后立刻重发 | **✗** | F3 |
| 分叉 → `CASE_MOVED`；一样长且内容相同不算分叉 | ✓ | 代码 `prefix && equal → same`；`session-store.spec`"相同 → 直接搬" |
| 搬家：旧处不在 → 比内存短 → 已失效 | ✓（但这一轮丢在当时） | `live-writer` 7、F6 |
| 拒绝路径：中文说明、不死循环 | ✓ / 说明有误 | L1 两次拒绝后都回到空闲；F5 |
| 名单没列新位置 → 不搬、`listed:false` 提示 | ✓ | Y2 三种情形 `listed:false` |
| ③ 同一编号只有一个写入者（第二个窗口） | ✓ | Y1 `SessionAlreadyOwnedError`；Y4、Y5 |
| ④ 登记不记两处，重启后归位 | ✓ | Y7 四种，`workspace-attach` W7（全量通过） |
| ⑤ 案件外不能新建 | ✓ | 本轮未改，全量通过 |
| ⑥ 搬迁不打断正在跑的一轮 | ✓ | `live-writer` 5 |
| DSH 启动自动恢复 → 打开新位置 → 续写 | 存储 ✓ / 真语义 **✗** | `live-writer` 4、J2（F2） |
| 全盘特征串 | ✓ | J3：只在新案件目录；`$DSH_HOME`、appData、旧文件夹、新建的 `%TEMP%` 目录都是 0 |
| 第五轮 Y1–Y11、AG、MV 原样跑 | ✓ | 21/21 通过；输出与修前基线比，只有 F1 相关几行按预期变了，其余一致 |
| 第二步 P-9 / P-15 / P-5 | 静态 ✓ | 补丁文件自 `fc0f801` 起未变；在 A 的 dsh 上 `git apply --check -R` 三个都干净；DSH 包测试没跑（缺口） |
| T13 N51 | ✓ | `dock-a19.spec` 在全量里通过 |
| 真实旅程（Host + 真 AgentLoop + Agent 插件） | **✗** | F2 |

### 八项清单

- **契约一致**：✓。没动 `contracts\`；`attachCaseSessions` 的 `listed` 是内部远程方法。
- **边界输入**：✗。F1、F3、F4。
- **错误路径**：✗。F2：`CASE_NOT_FOUND` 不提示；F6：落盘失败被吞掉。
- **日志不含正文**：✓。新增日志只有 index、count、reason、error name。
- **路径闸门未被绕过**：✓。新写入者只在名单上的案件根实例里打开。
- **无外连**：✓。只访问 `127.0.0.1`。
- **测试覆盖新代码**：部分。没有"搬迁中来事件""停止后重发""带 Agent 插件 + 按 cwd 找根"的用例。
- **无机密入库**：✓。

### 实际跑过的命令

- `git rev-parse`、`git status`、`git merge-base --is-ancestor`、`git show`、`git diff --stat`、`git log`。
- `git archive` 导出到 `rv-A23-B-lab`，robocopy node_modules，重建 12 个联接，dsh 联接指向 `D:\lawbench-A\dsh`。
- 全量：`node scripts\test.mjs` → 25 个文件 441 项通过、5 跳过。
- `tsc --noEmit` 退出 0；`check_ui_words.py` 零命中。
- `node scripts\test.mjs tests/zz-rvb23.spec.ts`：J1×2、D1、J2、J3、L1、R1、R2、R3、S1、S2、N1、P1。
- 第五轮三份 spec 原样跑。只把端口改到 19333–19335，并加 `--fileParallelism=false`；不改端口时三份并发会撞端口。
- `pytest service\tests\test_zz_rvb23.py`（venv 用 lawbench-B 的）。
- 在 A 的 dsh 上对 P-9、P-15、P-5 做 `git apply --check -R`（只读）。

我的 spec 和输出（已把用户名换成 `<用户>`）：`C:\Users\<用户>\AppData\Local\Temp\claude\D--lawbench\780b8a59-1849-4c63-905e-c6705fafa3f6\scratchpad\rv-A23-B-specs\`（`zz-rvb23.spec.ts`、`test_zz_rvb23.py`、`rvb22*-out.txt`），以及同一目录下的 `rv-A23-B-full.txt`、`rv-A23-B-y.txt`、`rv-A23-B-zz1..4.txt`。

### 残留审计

- 19331–19339 没有端口在监听。
- 我起的 vitest 和 pytest 进程都已结束，没有常驻进程。
- `%TEMP%` 下没有我的 `lb-rvb23-*` 或 `rvb22*` 目录。
- 先 `rmdir` 掉 13 个联接，再删除 `rv-A23-B-lab`；之后 `D:\lawbench-A\dsh` 的文件和 `dsh-ext\node_modules` 的联接都还在。
- rv-A23 克隆仍干净。
- 没碰别人的进程，也没写 `D:\lawbench*` 和 `D:\lawbench-coord`（只读了附件）。

### 证据缺口

- 没起桌面端复测。F2 的根因在服务语义，开发假服务模拟不出来，桌面端用假服务也看不到它。
- P-9 / P-15 / P-5 的 DSH 包测试没跑，只做了静态核对。
- 没有把真服务和 DSH 串起来端到端跑；F2 是用真 app 的 TestClient 核对服务行为，再用遵循同样语义的假服务跑 DSH 侧。
- F1 的空档只在本机 SSD 上测过；律师在真实界面里撞上空档的概率没有量化。

REJECT
﻿