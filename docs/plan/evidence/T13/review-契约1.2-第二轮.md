# T13 契约 1.2 界面侧 · 第二轮独立复核记录

- 复核员：一名 Opus 5.5 只读复核员（新人，未参与前几轮）
- target：`23cbdd94fea498c1deecb0e871e0db219df38085`（line-A）；范围 `8d562e4`、`d746011`、`dadc916`、`eb9d817`（含 Agent 插件与 Host `turnNotice`）；对照 line-B `4bb0e40`
- 复核克隆：scratchpad `rv-A18`；实验在 `git archive` 副本；未碰 `D:\lawbench-A`
- 归档：主编排于 2026-09-30 15:49 (+08:00) 从复核员交回原文抄录，未改内容

## 第一部分 复核员原文
# T13 契约 1.2 界面侧累计范围（第二轮）独立复核

- target：复核克隆 rv-A18，line-A `23cbdd94fea498c1deecb0e871e0db219df38085`。开工和结束时 `status --short` 都为空，没有任何写入。
- 范围：`8d562e4`、`d746011`、`dadc916`、`eb9d817`，外加 `eb9d817` 改到的 Agent 插件和 Host（`turnNotice`）。其后的 T17 提交没有改 `ui\`、`host\`、`agent\`、`shared\`，已用 diff 确认。
- 对照：线 B `origin/line-B`（`4bb0e40`）的 `task.py` 和 `ui.py`。

**结论先说：**
- 冻结清单逐条做到了，每条都有测试守着，变异会变红。上一轮的 X 系列我在"重挂"和"不重挂"两种模式下各跑一遍，全部一致。
- 但我找到一条上一轮没有的"显示 ≠ 实际"路径：输入区刚挂上时，写给服务的参数和参数框里显示的不同（P2）。它从 `8d562e4` 起就有，返修没碰到。
- INPUT_CHANGED 提示另有几处小毛病（P3）。
- 按止损线，这条 P2 应由主编排决定是否直接上候 owner 清单。

---

## Findings

### P2-A｜范围内阻断（新的"显示 ≠ 实际"路径，`8d562e4` 起就有）：输入区刚挂上时写给服务的参数，和参数框显示的不一样

- **问题**：`dock.tsx` 写入那个 effect 的依赖只有 `[stored, sync]`，500 毫秒防抖到点时写出去的是**安排写入那一次渲染**里的 `ui`。输入区刚挂上的第一次渲染，Skill 列表还没回来（`skills=[]`），参数就取成设置里的全局默认值（或兜底的 128K）。等 Skill 列表回来，参数框改显示这个 Skill 的预设或自带参数，可 effect 不会重跑，定时器照旧把旧参数写出去。
- **影响**：
  - 状态行显示"按「合同审查」运行"，胶囊和 Skill 都对。但参数框显示"中/64K"，服务存下、实际执行用的是 `{"thinking":"中","window":"128K"}`。
  - 这一轮结束重读后，参数框会悄悄变成 128K。律师给这个 Skill 设的个人预设在这条路径上被忽略。
  - 附带问题：如果这次写入失败，错误里记的键和此刻显示的键对不上，错误被过滤掉。状态行一直停在"正在保存选择…"，也没有"重试"按钮。
- **哪些情况会出**：
  1. 软件刚启动，首页点胶囊后进案件，而 Skill 列表比 `task/current` 回来得慢（Z1）；
  2. 插槽重挂时本会话还有没写成的改动：X5、X6 的重挂版本，改完 0.5 秒内离开再回来（Z2、Y3b 重挂版）。
- **证据**：
  - `rv-t13r2-z.spec.ts` 的 Z1 输出：`Z1 状态=下一条消息按「合同审查」运行（直到你改掉） 参数框显示=中/64K 服务存的参数={"thinking":"中","window":"128K","max_tokens":16384}`。
  - Z2：`失败后 状态=正在保存选择… 有重试按钮=false`；恢复后同样写成 128K，而参数框是 64K。
  - `rv-t13r2.spec.ts`：Y3b（重挂）失败，原因是 `no button 重试`。
  - 作者的 X5、X6 重挂用例只断言了 `entry`，没有看参数。
- **最小修复**：写入 effect 的依赖加上 `key`，即 `[stored, sync, key]`。我在副本里试过：
  - Z1、Z2、Y3b 都转绿；
  - 作者 `dock.spec.ts` 41 项、我的 X/Y 系列都不受影响；
  - 同时修上 P3-B 后三个文件共 107 项全过。
- **归类**：范围内阻断（1.2 输入区重做时引入；对"输入区显示的选择 = 下一条实际会用的任务单"这条不变量，是一条新路径）。

### P3-B｜本次引入（`eb9d817`）：收到 INPUT_CHANGED 后，律师"重新选"成和原来同一份时不会真写，提示消失、变绿字，下一条照样被拦下

- **问题**：
  - 被拦下后，重读会把 `serverKey` 设成服务那份（旧的 sha256 快照）。
  - 律师随后的改动只要最后得到同一个键，写入 effect 就走 `key === serverKey.current` 分支：直接记为已保存，不 POST，同时清掉提示。例如：0.5 秒内切到 B 再切回 A；参数本来就是默认值时点"恢复默认"；在成果区快速取消再选用。
  - 服务那边的快照没有更新（线 B `input_refs` 只在 create 时算 sha256）。
- **影响**：状态行显示绿字"下一条消息按「合同审查」运行"，实际下一轮再次被 INPUT_CHANGED 拦下，红字重新出现。不会按错的单子跑，但绿字是假的。
- **证据**：Y6a、Y6b、Y6c 在重挂和不重挂下都是 `新写入=0`，`重选后发|…按「合同审查」…|实际=被拦下|不一致`。作者的内存服务改写后要手动 `inputChanged=false`，没有模拟"重写才刷新快照"。
- **最小修复**：收到 INPUT_CHANGED 后，把服务那份记为"需重写"（一个按会话的 `stale` ref），写成功才清掉；在这之前去重不生效。我在副本里试过：Y6a、Y6b、Y6c 转绿，其余全过。

### P3-C｜本次引入（`eb9d817`）：INPUT_CHANGED 提示的生命周期有漏洞

1. 被拦下的那一轮结束时，如果律师正看着别的会话，`TURN_ENDED` 没人接，提示丢了。回到该会话时显示绿字，下一条又被拦（Y7 第一行）。
2. `inputChanged` 只有一个槽（`string | null`）。S1 被拦后去 S2，S2 也被拦下，回到 S1 时提示没了（Y8 不重挂版）。插槽重挂时组件状态清空，提示也没了（Y8 重挂版）。
3. Host 的 `TurnNotices` 在成功的一轮后不清。漏取的那条会在之后某一轮**成功**结束时被取到，显示假的"输入材料已变化，请重新选择"（Y7：改参数写出新快照，这一轮按 A 跑成功，结束后状态行仍是红字提示，判为误报）。
4. 补充：我只读查了 DSH 源码。`updatedAt` 只在用户消息写入时变：`session-controller/src/index.ts:196` 只对 `user/message` 发 `api-session/activity`，`list.ts:327` 取 `lastPromptAt`。所以"空闲会话 updatedAt 变了"实际标记的是**一轮开始**，不是结束。
   - 它只有在 `running` 翻转被合并、而且快照在拒绝之后才送到时，才正好落在"被拦下之后"。
   - 否则多出来的是一轮开始时的一次重读，外加一次提前的 `turnNotice` 取走，可能把第 3 条里的陈旧提示带出来。
   - 多出来的重读本身无害：有没写成的改动时不覆盖，也不会让重读的结果不对。
- 以上都会自己暴露（下一轮被拦就重新提示），不会按错的单子跑。
- **最小修复**：
  - Agent 在 begin 和 context 都成功时清掉该会话的记录；
  - 输入区在挂上或换会话时也取一次 `turnNotice`；
  - 提示按会话放进 store，不放组件状态。
- 归类：本次引入，P3。

### P3-D｜测试覆盖缺口（新代码）
- `TurnNotices.take` 改成不删，相关 4 个文件 79 项全绿（变异 M11 活下来）。"取一次即删"只有作者自己内存服务里的假实现守着。
- Host 的 `apply` 里去掉 `noteTurnBlocked` 那一行，全部 225 项全绿（M12 活下来）。接线只靠桌面端实测证明。
- `outputsList` 路径改成 `/api/output`，全部测试全绿（M21 活下来）。我已静态核对：`/api/outputs`、`/api/task/current` 与契约 title、线 B `ui.py:123/124` 一致。缺的是一条通用的"路由与契约 title 一致"测试，属独立后续。
- 最小修复：给 `TurnNotices` 补单测；Host `apply` 补一条接线测试。

### NOTE
- **M4（错误不按会话过滤）、M5b（意向不等读回就取）、M10（INPUT_CHANGED 不退回读取中）变异后仍全绿**：这三处是多余的保险。换会话时读取那个 effect 会先 `setError(null)`；读回不覆盖没写成的改动；提示优先于"读取中"。按实际行为不构成缺口。
- **Y4**：首页点胶囊后，S1 还没读回律师就切到 S2，意向由 S2 取走（S2 = A，S1 没被写入）。显示和实际一致，属"由当前会话取走"的设计。首页和会话视图同时挂着时由谁取走，要桌面端才能看。
- **材料刚变之后的第一条消息**：必然是绿字、实际被拦。这是 1.2 语义的自然结果，界面事先无从知道，不算界面缺陷。
- **截图 `INPUT_CHANGED-01`**：下拉框是"合同起草"加红字提示，而 `INPUT_CHANGED-desktop.txt` 写的是选"合同审查"后被拦下，像是另一次运行截的。截图对话区里有 T17 局域网探针的地址 `192.168.8.191`，不是机密。两张图没有用户名，也没有 PNG 文本块。

---

## 冻结清单逐条核对

| 编号 | 结论 | 证据 |
|---|---|---|
| P2-1 写失败后 `serverKey=null` | ✔ | X1b、X2 两种模式都一致；变异 M6 → 2 项红 |
| P2-2 `selections[sessionId]` | ✔ | M8（读取改回按案件存）→ 37 项红 |
| P2-2 `intents[caseId]`，由当前会话取走一次 | ✔ | M9 → 2 红；M2（取走不删）→ 2 红；Y4b 通过 |
| P2-2 换会话重置 `serverKey` | ✔ | M1 → 1 红（"读回前就选了和 S1 一样的 A"） |
| P2-2 读回前说"正在读取" | ✔ | M5 → 2 红；X4 两种模式都一致 |
| P2-2 错误按会话显示 | ✔（行为） | X6 通过；M4 不红，原因见 NOTE |
| P2-2 写结果在发起时定下会话 | ✔ | M3（here=true）→ 1 红；M3b（记到此刻显示的会话）→ 1 红 |
| P2-2 用不重挂的 mount 补 X4、X5、X6 | ✔ | `dock.spec` 默认 `key:'dock'`，重挂的另测 |
| P3-1 读错误总显示 | ✔ | M7 → 2 红；X3 显示读错误，不再显示绿字 A |
| P3-2 文档 | ✔ | 16.4 的 R12b–d、R10 两行已改准；16.2 旧注已删；`P5-desktop.txt` 第 14 行 0x07 出现 0 次，文字是 `DSH_HOME\attachments` |
| P3-3 显示胶囊带出隐藏分组 | ✔ | M19 → 1 红 |
| 小项①（1.1 残留断言） | ✔ | `fixtures.spec.ts` 第 64 行改为注释；ajv 43 项全过；M22（假数据多一个字段）→ 1 红 |
| 小项②（0 份材料） | ✔ | "本任务没有列入材料"，有测试 |
| 小项③（错误不拼两句） | ✔ | M23 → 1 红 |
| X7、X9 记为已知限制 | ✔ | 交付说明 17.4；我实测两种模式都是"本窗口一轮前不一致，一轮后一致" |
| INPUT_CHANGED（注记 1318） | 部分 ✔ | 提示、重读、改选后消失、只在该会话显示都做了（作者 5 个变异红）；漏洞见 P3-B、P3-C |
| `turnNotice` 不是 `/api` 接口 | ✔ | 不在 `api-routes.ts`；在 `REMOTE_METHODS`；`remote-methods.spec` 的界面调用扫描守着它（M13 → 1 红）。只返回 `{code}`，Agent 日志只记 code |

**R、X、Y 系列逐行结果**（线 B 语义的模拟服务，加上 sha256 快照语义；Host 端用真实的 `TurnNotices`；真实 `dock.tsx`、假时钟）：
- 下面各行在重挂和不重挂两种模式下，发送时都是"一致"，或状态行没有声称就绪：R1–R11、X1、X1b、X2、X3、X4、X5、X6、X8、Y1（S2 读回前律师改了 B）、Y2（同案两会话在防抖内交替改）、Y3（写入在途时切走又切回）、Y4、Y4b、Y5 和 Y5b（写失败 → 改回 → 再改 → 服务恢复）。
- X7、X9：已知限制行，表现与上一轮一致。
- 不一致：只有 Y6a/b/c（P3-B）、Y7 和 Y8（P3-C）、Z1 和 Z2（P2-A）。

## 八项清单

| 项 | 结论 |
|---|---|
| 契约一致 | ✔ 路由、字段与契约 1.2 和线 B 一致；假数据 ajv 全过 |
| 边界输入 | ✔ coverage 为 null 或 total=0、citation_check 为 null、胶囊缺 `new`，都有测试 |
| 错误路径 | ✘ P2-A 的附带问题：新挂上后写失败，状态行卡在"正在保存"、没有重试；其余错误路径通过 |
| 日志不含正文 | ✔ `TurnNotices` 只存错误码；Agent 只记 `{code}`；界面不打日志 |
| 路径闸门未被绕过 | ✔ 界面不碰文件；inputs 由服务的 `input_refs` 校验 |
| 无外连 | ✔ `ui\` 和构建产物 `lib\client.js` 里：fetch、XMLHttpRequest、WebSocket、EventSource、innerHTML、`href=`、`http(s)://`、sendBeacon、window.open 全部为 0。`ic-check.mjs` 只连 `127.0.0.1:9222` 调试端口，是证据目录里的开发脚本 |
| 测试覆盖新代码 | 部分 ✔：dock 41 项加变异，覆盖面不错；缺口见 P3-D，参数一致性见 P2-A |
| 无机密入库 | ✔ 四个提交的 diff 里查开发机用户名、`C:\Users\…`、`sk-`、Bearer、password，都是 0；8 张 PNG 只有 IHDR、IDAT、IEND 三种块 |

## 实际跑过的命令
- 准备：
  - 从复核克隆 `git archive 23cbdd9` 导出到 `scratchpad\rv-A18-T13-lab\r`；
  - robocopy 复制 `node_modules`（跳过联接），在副本里重建 12 个联接；
  - `dsh\node_modules`、`dsh\packages` 用联接只读指向 `D:\lawbench-A\dsh`；
  - TEMP、TMP 指到实验目录。
- 复核克隆里 `git fetch` 了 `origin/line-B` 和 `origin/main`。
- `node scripts\test.mjs`：16 个文件，225 项通过、5 跳过（与作者一致）。
- `tsc -p tsconfig.json --noEmit`：退出码 0。
- `node scripts\build.mjs`：通过，含纯 ESM 导入检查。
- `check_ui_words.py`：零命中。
- `contracts\check_examples.py --skills skills`：退出码 0。
- 我的实验：
  - `tests\rv-t13r2.spec.ts`：66 项，R、X、Y 系列，两种挂载模式。它是由上一轮的 `rv-extra.spec.ts` 改写来的：`mount` 改为默认不重挂，加了 `forgetDockSyncs`，加了 sha256 快照和 `turnNotice`。
  - `tests\rv-t13r2-z.spec.ts`：Z1、Z2，Skill 列表延迟返回、按 50 毫秒逐步推进假时钟。
- 变异脚本 `mut.py` 跑了 23 个变异，每次改完都按原字节写回，并用 sha256 核对。
- `fix.py` 试了两处修法（F1：依赖加 `key`；F2b：收到 INPUT_CHANGED 后标记需重写），试完复原。
- 只读查看了：
  - 线 B 的 `task.py` 和 `ui.py`；
  - `D:\lawbench-A\dsh` 的 `session-controller` 源码（grep 和读）；
  - 三份执行令和注记；
  - 交付说明第 16、17 节，红测记录，INPUT_CHANGED 桌面记录，两张截图。

## 残留审计
- 实验目录：先用 `Directory.Delete` 只拆联接（拆之前 14 个、之后 0 个），再删整个目录。`D:\lawbench-A\dsh\packages`、`dsh-ext\node_modules\ajv` 都还在。
- 没有起任何服务或桌面端；18891–18899 没有监听；没有命令行里带我实验目录的 node 进程。没动别人的进程，包括 soffice 10028、42468。
- `%LOCALAPPDATA%\lawbench\capsules.json` 不存在。
- 实验文件留在 `C:\Users\<用户>\AppData\Local\Temp\claude\D--lawbench\780b8a59-…\scratchpad\rv-A18-T13-evidence\`：两个 spec、`mut.py`、`fix.py`、各次输出，可以复现上面的结果。
- 上一名复核员的半成品：我不能确定是哪个目录。`rv-A18-lab`、`rv-A18-B-lab` 可能是 T17 两名复核员正在用的，没有删。
- 没写仓库、没 commit、没 stash、没改 git 配置、没联网、没碰凭据管理器。

## 证据缺口（没有启动桌面端）
1. 真实 DSH 换会话时插槽重挂还是只换属性。这决定 P2-A 的第 2 种触发、P3-C 的第 2 条在实际中多常见。
2. 首次挂上时 `listSkills` 和 `task/current` 谁先回来（P2-A 第 1 种触发）。我只用假时钟模拟了"Skill 列表慢 300 毫秒"。
3. 被拦下的一轮里 `running` 翻转有没有被合并、`activity` 和 `status` 的先后。作者桌面实测没有区分触发来源；DSH 源码显示 `updatedAt` 只在用户消息时变，结论见 P3-C 第 4 条。
4. 两窗口同会话、首页和会话视图是否同时挂着（关系到 Y4 意向由谁取走）。
5. 真服务：线 B 的 INPUT_CHANGED、`coverage`、`citation_check`、`/api/outputs`、胶囊 `new` 都只对模拟或假服务验过。

AMEND

---

## 第二部分 主编排裁决（2026-09-30 15:49 (+08:00)）

**结论：AMEND。** 冻结清单十五条全部关闭、每条有测试守着且变异变红；R/X/Y 系列在重挂、不重挂两种模式下全部一致。新发现一条 P2-A（输入区刚挂上时写给服务的参数与参数框显示的不同，`8d562e4` 起就有，返修没碰到）和 INPUT_CHANGED 的三条 P3（本次引入）。

### 止损线触发：P2-A 上候 owner 清单

上一轮裁决写明"这一轮之后若再查出'显示 ≠ 实际'的新路径，不再返修，上候 owner 清单"。P2-A 正是新路径，主编排照办：**不发 P2-A 的返修令，记 N48**。给用户的推荐：修法是把写入 effect 的依赖从 `[stored, sync]` 改成 `[stored, sync, key]`（一处），复核员已在副本验证 Z1、Z2、Y3b 转绿、其余 107 项不受影响；推荐允许随 P3 一并修，由下一名复核员一起核。

### 本次引入的 P3（不受止损线约束，发返修令）

| 编号 | 裁决 |
|---|---|
| P3-B | 必修。收到 INPUT_CHANGED 后把服务那份记为"需重写"（按会话的 stale 标记），写成功才清；在此之前去重不生效。补 Y6a/b/c 用例 |
| P3-C | 必修。①Agent 在 begin 和 context 都成功时清掉该会话的记录；②输入区挂上或换会话时也取一次 `turnNotice`；③提示按会话放进 store 而不是组件状态；④"空闲会话 updatedAt 变了"实际标记的是一轮开始（DSH `session-controller/src/index.ts:196` 只对 `user/message` 发 activity）——去掉这条判断，或改成只用来"提前取一次 turnNotice"而不触发重读；交付说明 17.6 改准确。补 Y7、Y8 用例 |
| P3-D | 必修。`TurnNotices` 补单测（取一次即删）；Host `apply` 补接线测试（去掉 `noteTurnBlocked` 那一行要变红）。"路由与契约 title 一致"的通用测试记独立后续 |
| NOTE 截图 `INPUT_CHANGED-01` 与文本记录不是同一次运行 | 一并做：重截或把记录改成与截图一致 |
| NOTE M4/M5b/M10 多余保险 | 记录，不动 |

### 下一轮

线 A 单独一个 `T13:` 提交（P2-A 若用户放行则并入）。新复核员核 1.2 界面侧累计范围，重点跑复核员留下的 `rv-A18-T13-evidence`（两个 spec 直接复用）。T13 仍随 T17 一起合并。