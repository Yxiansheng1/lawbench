# T14 第二次实跑派修 A 侧三件（T13 `c7d8348` 首页重试、`e01397e` 任务单失败拦发送；T7 `e428ba8` 换 Key 入口）· 复核记录（单人，八项清单）

- target：line-A `c7d8348`…`e428ba8`（父 `ad25901`）；复核克隆 `D:\lawbench-rv\rv-A35`
- 派发：Opus 5.5 只读复核员，2026-10-03 18:0x
- 归档：主编排于 2026-10-03 18:21 (+08:00) 从复核员交回原文抄录，未改内容

## 复核员原文## 结论先说
三处都做到了要求，测试也真能抓到问题：三条作者变异我各重跑了一遍，全部变红。复核里没有发现阻断问题，只有 4 条 P3 和 NOTE。
- **首页**：启动时服务还没起来，就每 2 秒重读一次，最多试到第 30 秒；读成功就停；30 秒还不行，显示错误和"重试"按钮。
- **任务单**：写任务单明确失败后，这个会话的下一次发送会被整轮拦下，不会拿服务那边上一张任务单发出去。
- **换 Key**：设置页可以更换 Key。新 Key 覆盖旧 Key，接着测两台服务器并显示结果；测试不通过也不退回旧 Key。

身份已核：`D:\lawbench-rv\rv-A35` 的 HEAD 是 `e428ba8`，工作区干净。`ad25901..e428ba8` 共 3 个提交，18 个文件 +398/−38，和复核包一致。

## Findings
1. **P3：拦发送的逻辑抄了一份，没有复用 `rejectMoved`。**
   - 问题：`agent/index.ts` 第 79–84 行和第 65–70 行的 `rejectMoved` 是同样四步：记日志、`noteBlocked`、`tasks.delete`、`reject`。拒绝逻辑现在有两处。
   - 影响：今后改拒绝流程时，容易只改一处。
   - 最小修复：抽成 `reject(sessionId, code, event)` 共用。
   - 归类：独立后续。

2. **P3：`changeKey` 不排队，没进首次配置测试连接用的那条队列。**
   - 问题：`trialConnection` 在 `trialQueue` 里排队；`changeKey`（`host/index.ts` 第 420 行）不排。
   - 影响：如果首次配置页的"测试连接"测试失败、正在恢复旧 Key，同一时刻又在设置页换了 Key，新 Key 可能被恢复动作盖掉，界面却显示"已换成新 Key"。正常使用时这两个页面不会同时开着，所以只是理论上的风险。
   - 最小修复：`changeKey` 也进 `trialQueue`。
   - 归类：独立后续。

3. **P3：Host 端这两处只核了代码，没有测试覆盖。**
   - Host 的 `sheetHold(request)` 怎么解析参数、`lawbenchCore.sheetHeld` 怎么接线，没有用例测。`dock.spec` 用的是界面侧的假 Host，`turn-notices.spec` 只测 `TurnNotices`。
   - 我静态核过：界面发的是 `{session_id, hold}`，Host 按这两个字段读；Host 里用的 `notices` 和 apply 里的是同一个实例（第 129、511、519、528 行）。
   - 影响：以后改参数名时，现有测试抓不到。
   - 归类：独立后续。

4. **NOTE：两个边缘情况，都只会多拦，不会漏拦。**
   - 写入后来成功了却多拦一次：
     - X1 用例：写入超时，但服务其实已经建好了 B，这次发送照样被拦。律师点"重试"就行。我认为这样改口径合理：超时时界面没法确认服务那边是哪一张，拦下比按不确定的那张发出去安全。
     - 选回原来那一项时，界面马上清掉 hold；如果之前一次写入正在进行、后来失败，又会把 hold 记上，结果也是多拦一次。
   - 凭据写入超时但其实已经写成：界面会显示"没有换成"，Key 实际已经换了，律师再换一次即可。
   - 两种情况都不需要改。

5. **NOTE：全量跑时 `supervisor.spec` 挂了一例（"等待超时"）。**
   本轮没改这个文件；单独重跑 11/11 通过。判断是机器负载高时的偶发超时，不是本次引入的回归。

## 三处核对表
| 要求 | 核对 | 结果 |
| --- | --- | --- |
| **首页重试** | `useRetryLoad`（kit.tsx）：第 0、2、…、30 秒共读 16 次后才给出失败；读成功就 return，不再读；卸载或点"重试"时 seq 加 1，上一轮自己作废。不会无限轮询，最多留一个 2 秒的 timer，到点后自己 return。用例断言：30 秒内读 16 次，之后 10 秒不再读。"最近案件"改为首页读成功后才显示，原来那条错误行去掉了，这是合理的随改。 | 通过 |
| **拦发送：怎么记** | 记在 Host 进程内存里，按会话（`TurnNotices.holds`，一个 Set，有上限）。软件重启就清空；重启后输入区挂上时会从服务重读当前选择，界面和服务一致，不会出错。 | 通过 |
| **拦发送：拒绝路径** | 第 1 步就整轮拒绝，记 `TASK_SHEET_FAILED`，界面经 `turnNotice` 弹"这条消息没有发出"。用的是和 `rejectMoved` 同一套机制，但代码抄了一份（见 F1）。 | 通过（P3） |
| **拦发送：写成后去掉** | 写成后调 `sheetHold(hold:false)`；选回服务那一张时也会去掉。 | 通过 |
| **N51 已知限制** | 半秒空窗、恰好不可用这两种情况的行为没有改动。 | 通过 |
| **X1 用例改口径** | 写入超时就拦下发送。合理，理由见 NOTE 4。 | 合理 |
| **换 Key：Key 去了哪里** | 只在三处出现：界面里 React 的输入状态 → 参数 → `cred.set`。日志只记 `credentials.key_changed {}`；返回值只有 llm、prep、error，用例断言返回值里不含 Key；`lb()` 和 `call` 都不打日志。密码框在点"保存并测试"后第一步就 `setKey('')`，"取消"时也清空。 | 通过 |
| **换 Key：方法登记** | 已在 `REMOTE_METHODS` 登记：`changeKey ['key']`、`sheetHold ['request']`。`remote-methods.spec` 核对形参名通过。 | 通过 |
| **换 Key：同一个写凭据函数** | 和首次配置一样调 `cred.set('LAWFIRM_KEY', …)`，没有另写一套；格式校验用的正则和 `trialOnce` 一样。 | 通过 |
| **换 Key：会不会把律师锁在门外** | 新 Key 错了，"更换 Key"按钮还在，可以再换；`setupState` 仍判定为已配置，不会被赶回首次配置页。不会锁死。这里"不退回旧 Key"是偏离点，按执行令"旧 Key 覆盖"办，T7 交付说明里已写明。 | 通过 |

逐 hunk 归类：
- 必需实现：home.tsx、kit.tsx、dock.tsx、agent/index.ts、host/index.ts、remote-methods.ts、turn-notices.ts、settings.tsx、state.ts。
- 必需验证：7 个 spec 文件，以及两份交付说明。
- 无关改动：没有。

## 八项清单
1. **契约一致**：通过。新增 Host 方法不是 /api 契约接口，已在 `REMOTE_METHODS` 登记；`ConnectionResult` 和 connection_test 契约字段一致。
2. **边界输入**：通过。Key 格式两侧都校验（8–512 位可见 ASCII），格式不对不写凭据；`sheetHold` 参数类型不对时什么都不改。
3. **错误路径**：通过。服务没起来时 Key 照换，并返回中文说明；写凭据失败显示"没有换成"。
4. **日志不含正文**：通过。只记 `agent.sheet_held {}` 和 `credentials.key_changed {}`。
5. **路径闸门未被绕过**：不涉及。
6. **无外连**：通过。没有新地址。
7. **测试覆盖新代码**：基本通过。缺口见 F3。
8. **无机密入库**：通过。测试用的 Key 都是虚构的 `sk-*-12345678`。

## 实际跑过的命令
所有命令都在从 `e428ba8` `git archive` 导出的副本 `D:\lawbench-rv\x35` 里跑。
- `node scripts\test.mjs`（dsh-ext 全量）：35 个文件，554 通过、1 失败、6 跳过。失败的是 `supervisor.spec` 那例超时，单独重跑 11/11 通过（见 NOTE 5），所以全量实际 555 通过。
- 相关 spec 8 个：home-retry、dock、dock-z、agent、turn-notices、trial-connection、settings-key、remote-methods，90/90 通过。
- tsc：用 dsh 依赖环境里的 typescript 6.0.3，`-p tsconfig.json --noEmit`，退出码 0。
- `check_ui_words.py`：零命中。
- 三条变异，每条做完都逐字节复原（文件哈希一致）：
  - kit.tsx 改成不重读 → home-retry 2 例红。
  - dock.tsx 去掉记 hold → dock.spec 2 例红（写失败、X1）。
  - host 的 `changeKey` 去掉写凭据 → trial-connection 2 例红。

## 残留审计
- 收尾时我第一次写的清理命令有误：用 `dir /AL /S` 枚举目录联接，会顺着指向 `D:\lawbench-A\dsh` 的联接往里走，有误删那边联接的风险。
  - 我在它还没删任何东西之前停掉了它：输出文件是空的，连第一行计数都没打出来；我自己建的 14 个联接停掉后逐个核过，全部还在。
  - 随后只按路径删了我自己建的这 14 个，再删实验目录。
  - 删完核过 `D:\lawbench-A\dsh\packages`、`D:\lawbench-A\dsh-ext\node_modules\ajv` 都还在。
- `D:\lawbench-rv\x35` 已删除；`rv-A35` 工作区干净。
- 19360–19369 端口没有监听；我没起过服务进程，也没动别人的进程。
- 没写本机凭据管理器，没碰 `D:\lawbench-A`，只读引用过它的 `node_modules` 和 `dsh`。

## 证据缺口
- 没在桌面端实际跑。三处行为都是靠 jsdom 环境的用例、假服务和代码核对得出的。
- Host 端 `sheetHold` 的接线没有直接测过（见 F3）。
- 真实凭据管理器上的覆盖写入没有跑：按约束不写本机凭据管理器。

T13: PASS
T7: PASS

