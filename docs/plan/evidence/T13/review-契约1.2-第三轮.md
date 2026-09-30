# T13 契约 1.2 界面侧 · 第三轮独立复核记录（INPUT_CHANGED 返修 + N48）

- 复核员：一名 Opus 5.5 只读复核员（新人，未参与前几轮）
- target：line-A `c30c46f470cc4d50b5743cbb3046ceca61039347`；范围 `8d562e4`、`d746011`、`dadc916`、`eb9d817`、`c30c46f`
- 冻结清单：`review-契约1.2-第二轮.md` 第二部分 + 用户 N48 ①
- 复核克隆：scratchpad `rv-A19`；实验在 `git archive` 副本
- 归档：主编排于 2026-09-30 17:20 (+08:00) 从复核员交回原文抄录，未改内容

## 第一部分 复核员原文

# T13 契约 1.2 界面侧 · 第三轮复核（INPUT_CHANGED 返修 + N48）

- **target**：复核克隆 rv-A19，line-A `c30c46f470cc4d50b5743cbb3046ceca61039347`。开工和结束时 `status --short` 都为空。
- **范围**：`8d562e4`、`d746011`、`dadc916`、`eb9d817`、`c30c46f`。穿插进来的 T17 提交 `eff8d1a` 没有改 `ui\`、`host\`、`agent\`、`shared\`（`git show --stat` 核对过）。它改了 `vitest.config.mjs`，但只加了别名，没有把任何测试排除掉。
- **实验环境**：`git archive` 导出的副本 `scratchpad\rv-A19-T13-lab`，已删除。TEMP、TMP、APPDATA、LOCALAPPDATA 都指到副本里。

**结论先说：**
- 上一轮冻结清单这次都做了，作者的回归用例和变异都站得住。复核员原来那两份 spec 改成断言后，没有被改弱。
- 但 N48（P2-A）只修好了一半：Skill 列表要是比"防抖 0.5 秒 + 写成"回来得还慢，写给服务的参数和参数框显示的仍然不一样（P2）。
- INPUT_CHANGED 提示另外还有三处小问题（P3），其中一处正是这次要查的"成功一轮之后误报"。

---

## Findings

### P2-1｜范围内阻断（N48 修得不完整）：Skill 列表回来得比写入慢时，参数框显示的和服务存的仍然不同

- **问题**：写入 effect 开头是 `if (!stored || stored.saved) return`。加上依赖 `key` 以后，只有 Skill 列表在 500 毫秒防抖到点之前回来才管用。列表要是更慢，事情是这样走的：
  1. 全局默认参数（兜底 128K）先写出去，写成后记为已保存；
  2. 列表回来，参数框改显示这个 Skill 的参数（64K），`key` 变了；
  3. effect 虽然重跑，但 `saved` 已经是 true，直接返回，不再写。
- **影响**：
  - 发送时状态行是绿字"按「合同审查」运行"，参数框显示 64K，这一轮实际按 128K 跑。
  - 一轮结束重读后，参数框悄悄变回 128K。
  - 这和 P2-A 是同一种"显示 ≠ 实际"，同一条路径（首页点胶囊后进案件，软件刚启动），只是慢的时间更长。`dock-z` 的 Z1 只模拟了列表慢 300 毫秒，比 500 毫秒短，所以没测出来。
- **证据**：`rv-a19-skl3.spec.ts` E3（列表慢 1.5 秒）的输出：
  - `参数框={"thinking":"中","window":"64K",...} 服务={"thinking":"中","window":"128K",...} 状态=下一条消息按「合同审查」运行（直到你改掉） saved=true`
  - 发送后：`参数框={...,"window":"128K",...}`
- **最小修复（任选一种）**：
  - 方案一：写入 effect 开头改成 `if (!stored || (stored.saved && (serverKey.current === null || key === serverKey.current))) return`，也就是已保存、但显示的已经不是服务那份时重写。我在副本上试过（Fa）：E3 转绿。
  - 方案二：Skill 列表没回来、参数又是由 Skill 推出来的时候，先不写。
  - 两种修法都要补一条"列表慢 1.5 秒"的用例。
- **归类**：范围内阻断。这是 N48 的剩余路径，按上一轮定的止损线，由主编排决定要不要上候 owner 清单。

### P3-1｜本次引入（`c30c46f`）：挂上时 `turnNotice` 比 `task/current` 晚回来，状态行卡在"正在读取当前选择…"，成果区的选用也不生效

- **问题**：挂上和换会话时，`load()` 和 `notice()` 同时发出去。如果读回先到，`loadedFor` 先设成 S1；随后提示到了，`setLoadedFor(null)` 又把它清掉。
- **影响**：
  - 律师改选 B 并写成以后，`reading` 一直为真，状态行卡在"正在读取当前选择…"，要等下一轮结束或换一次会话才恢复。
  - 取意向的 effect 要等 `loadedFor === sessionId` 才取，所以这期间成果区的"选用 / 取消选用"不会带进来（`意向未取走=true`）。
  - 不会让状态行声称就绪却按别的跑。
- **证据**：E7（`noticeDelay=50`）两种挂载模式的输出都是：`回S1=输入材料已变化，请重新选择 | 改B写成后=正在读取当前选择… | 成果区取消选用后=正在读取当前选择… 意向未取走=true`。
- **最小修复**：挂上时和一轮结束时一样按顺序来：`void notice().then(() => { if (alive) load() })`，去掉单独那个 `load()`。副本试过（Fb），E7 转绿。
- 现实里 `turnNotice` 是 Host 内存读取，通常比走 HTTP 的 `task/current` 快，所以出现的机会不大。

### P3-2｜`eb9d817` 起就有、返修没碰到：被拦下的那一轮前后律师刚改过选择时，红字提示是误报，而且成功几轮都不消失

- **问题**：`inputChanged` 只在写入 effect 开头清一次。可以复现的时序：
  1. 律师改选 B，0.2 秒内发送（和 R11 一样的节奏；或者在那一秒左右的被拦轮次里改选）；
  2. 这一轮按服务那份 A 跑，被拦下；
  3. 一轮结束，`markInputChanged`；
  4. 那次还在防抖里的 B 写成了，服务的输入快照已经是新的，`staleServer` 也清掉了，但 `inputChanged` 没人清。
- **影响**：
  - 状态行一直是红字"输入材料已变化，请重新选择"，可下一条实际按 B 顺利跑完。
  - 成功一轮、两轮之后提示仍在，直到律师再动一次选择。
  - 这正是这次要查的"成功一轮后误报"。不会按错的单子跑。
- **证据**：E8、E8b，两种模式：`写成后状态=输入材料已变化，请重新选择 服务=contract-draft 下一条实际=contract-draft 成功一轮之后状态=输入材料已变化，请重新选择`。
- **最小修复**：写成功时和 `clearStaleServer(sid)` 一起调 `clearInputChanged(sid)`。副本试过（Fc1），E8、E8b 转绿，作者用例不受影响。
- 我还试过另一种写法：成功的一轮结束时（`turnNotice` 为 null）也清提示。这会和作者 `dock.spec` 里写明的"再一轮结束（这次没被拦下）不消掉提示"冲突，所以不推荐。
- 剩一个很窄的空窗：B 的写入比被拦那一轮的 `TURN_ENDED` 先完成时，仍会误报一次，一直到律师下次改动为止。

### P3-3｜`eb9d817` 起就有：取 `turnNotice` 的请求还在途时律师切走，已经取出来的提示被丢掉

- **问题**：`notice()` 里先 `if (!alive) return`，再 `markInputChanged`。Host 那边"取一次即删"已经删了，界面又把结果扔了，这条提示就彻底没了。
- **影响**：回到 S1 时显示绿字"按「合同审查」运行"，实际又被拦下（发送时"显示 ≠ 实际"）。下一轮被拦时会重新出提示，能自己暴露出来。空窗大约是一次 IPC 往返。
- **证据**：E13，两种模式：`回S1状态=下一条消息按「合同审查」运行（直到你改掉） 实际=被拦下 不一致`。
- **最小修复**：提示已经按会话存进 store，不用看 `alive`，改成 `if (r.ok && r.value.code === 'INPUT_CHANGED') { markInputChanged(sid); if (alive) setLoadedFor(null) }`。副本试过（Fd）。
- **四处修法一起试**（Fa+Fb+Fc1+Fd）：dock、dock-review、dock-z、ui-logic 加我的实验，共 145 项全过。试完 `dock.tsx` 按原字节写回，sha256 与原件一致。

### NOTE
- **P3-C ④ 的剩余空窗**：我只读查了 DSH 源码。
  - `agent-loop/src/agent.ts:145-151`：pre-step 在 running 阶段里跑，所以被拦的一轮会先发 `agent/status` running，再发 idle。中间隔着我方 Agent 的两次 `/core` HTTP 请求。
  - 客户端的 `Notifier`（`session-controller/src/client/sessions/notifier.ts`）只把同一个微任务里的变化合并。
  - 所以翻转大概率不会被合并，一轮结束时 `TURN_ENDED` 会发出来。万一被合并：律师一直停在这个会话，就看不到提示，状态行是绿字，但实际会被拦，不会按错的单子跑；下一轮再被拦，或者换一次会话、插槽重挂，就能补回来。返修后没有做桌面端复测（交付说明 17.7 写明随 T17 第三步一起做）。
- **R1 变异活下来**：`staleServer` 写成后不清，作者的 108 项全绿。后果只是这个会话以后"选回同一份"也会真写（多一次 POST，服务会重算快照），不影响显示和实际是否一致。我的 E4 断言了清掉，这个变异会变红。可以考虑把 E4 收进用例。
- **Y7 第一段只断言"不是不一致"**，没有直接断言显示的就是提示文字。A3 变异照样会让它变红，所以不构成缺口；建议加一句 `expect(status()).toBe(INPUT_CHANGED_TEXT)`。
- **截图与记录**：`INPUT_CHANGED-01` 的下拉框是"合同起草"，对话区有两行"用时 1 秒"。这和 `INPUT_CHANGED-desktop.txt` 末尾补记的"截图取自第二次发送"一致。两张 PNG 只有 IHDR、IDAT、IEND 三种块，没有用户名。
- **默认并行跑全量**：vitest 有 5 个 worker 意外退出，看起来是机器负载，不是代码问题。加 `--maxWorkers=2` 后 20 个文件 327 项通过、5 跳过，与作者一致。

---

## 冻结清单逐条核对（第二轮裁决与执行令）

| 编号 | 结论 | 证据 |
|---|---|---|
| N48：依赖加 `key`，补 Z1、Z2 | 部分 ✔ | 已改；A1 变异 → 3 项红（Z1、Z2、Y3b）。但列表慢过写入时仍不一致，见 P2-1 |
| P3-B：按会话记"需重写"，写成才清；Y6a/b/c 真 POST | ✔ | A2 → 6 项红；我的 E4 在两种模式下都是新写入恰好 1 次、快照刷新成 `[1]`、发送时一致；E11（重选同一份写失败 → 重试）一致 |
| P3-C ①：begin 和 context 都成功时清 | ✔ | `agent/index.ts` 在 context 成功后调 `clearBlocked`；R3 → agent.spec 1 项红；R2（Host 去掉 `clearTurnBlocked`）→ turn-notices 1 项红 |
| P3-C ②：挂上、换会话也取一次 | ✔（有 P3-1、P3-3） | A3 → Y7 两种模式红；E6：S1 在后台被拦时，S2 不显示、也不取走 S1 的提示，回 S1 才显示 |
| P3-C ③：提示按会话放进 store | ✔ | A4 → Y8 两种模式红 |
| P3-C ④：撤掉 `updatedAt` 触发，17.6 改准 | ✔ | `turnEnds` 只看 running；`index.tsx` 的类型和 Map 一并删掉；17.6 已加删除线并写明更正。剩余空窗见 NOTE |
| P3-D：`TurnNotices` 单测；Host 接线（去掉 `noteTurnBlocked` 要红） | ✔ | R5（去掉 `noteTurnBlocked`）→ 1 项红；R4（Host 取后不删）→ 1 项红；作者自己的"取了不删、`clear` 不清、远程方法不用那份记录"也红 |
| NOTE：截图与记录一致 | ✔ | 补记了，与截图一致 |
| 成功一轮后不误报 | 部分 ✔ | Y7、E12 通过；E8、E8b 误报，见 P3-2 |
| 复核员实验收为回归用例、没有改弱 | ✔ | 逐行 diff 过原件：只去掉打印；模拟服务的 `run` 加了 `clear`（对应 P3-C ①）；Y6–Y8 改成断言；Z2 加了错误和"重试"的断言。没有删掉或放宽原有断言 |
| 上两轮已过的部分没被弄坏 | ✔ | dock.spec 40 项、ui-logic 18 项全过；R6（P2-1 serverKey）→ dock.spec 2 项红；R7（P3-3 分组）→ 1 项红；R8（胶囊 `new`）→ 1 项红 |

## 八项清单

| 项 | 结论 |
|---|---|
| 契约一致 | ✔ `turnNotice` 不在 `shared\api-routes.ts`，也不在 `contracts\`，只在 `REMOTE_METHODS`；`remote-methods.spec` 核对实现、形参、描述；只返回 `{code}` |
| 边界输入 | ✔ 上限 200 条有单测；`session_id` 不是字符串时返回 null |
| 错误路径 | ✘ P3-1 卡在"正在读取"；P3-3 提示被丢。其余正常：写失败有"重试"（Z2、E2），重选同一份写失败后能重试（E11） |
| 日志不含正文 | ✔ `TurnNotices` 只存错误码；Agent 只记 `{code}`；界面不打日志 |
| 路径闸门未被绕过 | ✔ 界面不碰文件 |
| 无外连 | ✔ `c30c46f` 在 dsh-ext 新增的行里：http(s)、fetch、192.168、10.126 都是 0；`ui\` 里 fetch、XMLHttpRequest、WebSocket、EventSource、sendBeacon、window.open 都是 0。我的实验没有起任何服务，也没有网络请求 |
| 测试覆盖新代码 | 部分 ✔ 作者 8 个变异我抽了 4 个复现，都红；我加的 5 个里 4 个红，只有 R1（`staleServer` 不清）活下来，见 NOTE。缺口：P2-1（列表慢过写入）、P3-1、P3-2、P3-3 没有用例 |
| 无机密入库 | ✔ 五个提交的 diff 里查开发机用户名、`C:\Users`、`sk-`、Bearer、password，都是 0；两张 PNG 没有文本块 |

## 实际跑过的命令
- 复核克隆：
  - `git rev-parse HEAD`、`status --short`、`git fetch origin`；
  - `git show --stat` 看五个提交和 `eff8d1a`；
  - `git show origin/main:.../review-契约1.2-第二轮.md`。
- 读了两份执行令（只读），以及交付说明 17.6、17.7 和红测记录。
- 副本准备：
  - `git archive c30c46f | tar -x`；
  - robocopy 复制 `node_modules`，重建 12 个联接；
  - `dsh\node_modules`、`dsh\packages` 用联接只读指向 `D:\lawbench-A\dsh`。
- 检查：
  - `node scripts\test.mjs --maxWorkers=2`：20 个文件，327 项通过、5 跳过；
  - `tsc --noEmit`：0；
  - `node scripts\build.mjs`：0，纯 ESM 导入检查通过；
  - `check_ui_words.py`：零命中；
  - `contracts\check_examples.py --skills skills`：0。
- 我的实验：
  - `rvh.ts`（夹具）；
  - `rv-a19-skl1/2/3.spec.ts`：E1（列表回来前改参数）、E2（写失败 → 改回 → 列表才回来 → 重试）通过；E3 红，即 P2-1；
  - `rv-a19-ic.spec.ts`：E4、E6、E11、E12 通过；E7、E8、E8b、E13 红，即 P3-1 到 P3-3。
- 变异与修法：
  - `mut.py` 跑了 12 个变异；
  - `fix.py` 试了四处修法；
  - 每次都按原字节写回并用 sha256 核对。结束时 6 个源文件与备份一致。
- 只读查看 DSH 源码：`session-controller`（index.ts、manager.ts、notifier.ts）、`agent-loop/src/agent.ts`。

## 残留审计
- 副本：先用 `[IO.Directory]::Delete` 只拆联接（拆前 14 个、拆后 0 个），再删整个目录。`D:\lawbench-A\dsh\packages`、`dsh\node_modules\vitest`、`dsh-ext\node_modules\ajv` 都还在。
- 没有起任何服务或桌面端；命令行里带 rv-A19 的 node 进程为 0；18931–18939 没有监听。没动别人的进程。
- 真实的 `%LOCALAPPDATA%\lawbench\capsules.json` 不存在；副本里的 appdata、localappdata 也是空的。
- 实验文件留在 `C:\Users\<用户>\AppData\Local\Temp\claude\D--lawbench\780b8a59-…\scratchpad\rv-A19-T13-evidence\`：spec、夹具、`mut.py`、`fix.py` 和各次输出，输出里的用户名已换成 `<用户>`。
- 没写仓库、没 commit、没 stash、没改 git 配置。复核克隆只多了 fetch 下来的远端引用。

## 证据缺口
1. 没有起桌面端。返修后，真实 DSH 里被拦的那一轮会不会发 `TURN_ENDED`，只做了源码推断（见 NOTE），作者也还没复测。
2. 真实 DSH 首次挂上时，`listSkills` 比 `task/current` 加 0.5 秒写入慢多少，没有测过。这决定 P2-1 实际上多常出现。
3. `turnNotice` 和 `task/current` 在真实 IPC 里谁先回来（P3-1、P3-3 的空窗）没有测过。
4. 线 B 真服务的 INPUT_CHANGED 快照语义，只用模拟服务验过。

AMEND

---

## 第二部分 主编排裁决（2026-09-30 17:20 (+08:00)）

**结论：AMEND。** 冻结清单全部落实、变异全红、复核员上一轮的实验收为回归用例且未改弱；但 N48（P2-A）只修了一半：Skill 列表比"防抖 0.5 秒 + 写成"回来得更慢时（Z1 只模拟了 300 毫秒），全局默认参数先写成并标"已保存"，列表回来后 `key` 变了但 `saved` 已真、不再重写——参数框显示 64K、服务存 128K。另有 INPUT_CHANGED 提示的三条 P3（挂上时 `turnNotice` 晚回来卡在"正在读取"；被拦轮次前后刚改过选择时红字误报且成功几轮不消失；取 `turnNotice` 在途切走提示被丢）。

### 止损线的适用

上一轮定的止损线针对"**新**路径"。P2-1 与 P2-A 是同一条路径（首页点胶囊后进案件、Skill 列表慢回来）、同一根因（写入 effect 的判断没把"显示的键 ≠ 服务那份"算进去），这是这一根因的**第二次修**。按双人复核规矩，同根因挺过两次修正才止损；本轮允许返修一次，**下一轮若同一根因再露，不再返修、上候 owner 清单**。

### 返修清单（冻结，线 A 单独一个 `T13:` 提交）

| 编号 | 裁决 |
|---|---|
| P2-1 | 必修。按复核员方案一：写入 effect 开头改成"已保存、且显示的键就是服务那份时才返回"（`if (!stored || (stored.saved && (serverKey.current === null || key === serverKey.current))) return`）；补"列表慢 1.5 秒"用例（E3）。复核员在副本验证 E3 转绿、其余 145 项不受影响 |
| P3-1 | 必修。挂上和换会话时按顺序：先 `notice()` 再 `load()`，去掉并行的那一个 `load()`；补 E7 用例 |
| P3-2 | 必修。写成功时与 `clearStaleServer(sid)` 一起 `clearInputChanged(sid)`；补 E8/E8b 用例；剩余空窗（B 的写入比被拦轮次的 `TURN_ENDED` 先完成）写进已知限制 |
| P3-3 | 必修。`notice()` 不看 `alive` 直接 `markInputChanged(sid)`，只有 `setLoadedFor(null)` 看 `alive`；补 E13 用例 |
| NOTE R1（`staleServer` 写成后不清无测试） | 一并做：把复核员的 E4 收进用例 |
| NOTE Y7 | 一并做：加一句 `expect(status()).toBe(INPUT_CHANGED_TEXT)` |
| NOTE P3-C ④ 剩余空窗 | 记已知限制（翻转被合并时一轮内看不到提示，不会按错单子跑）；桌面端复测随 T17 第三步 |

复核员的四处修法一起试过 145 项全过，实验文件在 scratchpad `rv-A19-T13-evidence\`，可直接复用。

### 下一轮

新复核员核 1.2 界面侧累计范围（`8d562e4` 起），重点跑 E3、E7、E8、E13。通过后 T13 随 T17 一起合并。
