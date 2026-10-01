# T26 第 1、2 步 · 独立复核记录（第二轮：返修后累计范围）

- 复核员：一名 Opus 5.5 只读复核员（换人）
- target：line-A `7940d3e`；累计 `128ee95` + `7940d3e`（叠在 T17/T13 之上，未改 T17 代码）
- 冻结清单：`review-REVIEW-第一二步.md` 第二部分
- 复核克隆：scratchpad `rv-A25`
- 归档：主编排于 2026-10-02 00:16 (+08:00) 从复核员交回原文抄录，未改内容（无人值守窗）

## 第一部分 复核员原文
## T26 第 1、2 步返修后累计复核（rv-A25，第二轮，换人）

范围：`128ee95` + `7940d3e`。我亲自核对过：HEAD 是 `7940d3ec1fa5643a35df4e1821bfdc9255363b33`，`git status` 干净。
两个提交都没碰 T17 的会话存储和路由代码：`host/session-store`、`attach-sessions.ts`、`supervisor.ts`、`agent/`、`credentials/`、`cordis.patch.yml` 一行没改。`host/` 下只改了 `index.ts` 的 `callApi` 一段加一行 import，另新增 `http-json.ts`。`engines/`、`contracts/` 都没动。

### 发现

**P3-1（本次引入，测试缺口）新请求函数有两条行为没有用例守着**
- 问题：`http-json.ts` 的"3xx 当失败"和"超时后 `r.destroy()` 断开请求"，删掉哪一条测试都全绿。我的变异 MF（3xx 判断改成 `if (false)`）和 MG（去掉 `r.destroy()`）都是 `host-api.spec` 26 项全过。
- 影响：现在的行为是对的，我在 Node 和 Electron 44 下都实测过。
  - 302 立即拒绝，Host 报"服务不可用"。
  - 超时 1 秒时，服务端约 0.3 秒内就看到连接关闭。
  - 风险只在以后有人改这个文件时没有用例拦着。
- 最小修复：`host-api.spec` 加两例。一例是服务回 302 时 `callApi` 得 `SERVICE_UNAVAILABLE`；另一例是超时后服务端的 `req` 收到 `close`。
- 归类：独立后续，不阻断。

**NOTE（不需要改）**
- N1 请求体传输方式变了：从带 `content-length` 变成分块传输（`transfer-encoding: chunked`）。我在本机起了真工作台服务（uvicorn 0.54），用新写法发 `caseOpen`（中文路径），服务照常收下。`caseRecent`、`materialsScan`、`materialsList`、`search`、`getCapsules`、`tasksList` 新旧两种写法的返回逐字相同。没有影响。
- N2 说法不准：交付说明说"Host 调 `/api/*` 全部走 `requestJson`"。实际 `api()`（读写设置、测试连接）仍用 `fetch`，时限 30 秒，远低于 300 秒，无害。
- N3 长连接竞态没有出现：真服务空闲 5 秒关连接，Node 自带 `globalAgent` 的空闲套接字时限也是 5 秒。我用与真服务同参数的 uvicorn，在空闲 4.90–5.10 秒之间复用连接试了 42 次，新写法 0 次失败，旧 `fetch` 也是 0 次。
- N4 新写法不再经过 DSH 装的全局 undici 分发器（代理设置）。连 127.0.0.1 不走代理，只会更稳。
- N5 `PATCHES.md` P-11 行"共 131 项通过"没改成 135；实际加了预加载 4 例，我跑出来是 5 个文件 135 项。只是文字。
- N6 开发假服务里 review 不带 confirm 回 `[BLOCKED]` 的改动没有用例守（变异 ML 全绿）。只影响开发期，不影响产品。

**此前既有**
- 界面经 DSH 远程调用到 Host 这一段有没有逐次超时，我只粗查了 `packages/api/gateway` 和 `packages/client/connection`：只见握手超时，没见逐次调用超时。桌面端上"超过 5 分钟的动作界面能等到结果"没有端到端实测（见证据缺口）。

**无关新发现**
- `D:\lawbench-A\dsh` 工作区有 T20 P-4 还没提交的品牌名改动（时间在 23:36，晚于本提交），涉及 `main.ts`、`electron-builder-config.mjs`、`main-startup.spec.ts`。所以补丁链打完后，这 3 个文件与工作区不一致，差的正是这几行。归 T20，不归本卡。

### P2-1 偏离判定：接受作者用 `node:http` 代替执行令写的 undici `Agent`
1. 没有隐藏的头部超时：客户端 `http.request` 没有头部时限。`globalAgent` 的 5 秒时限只销毁空闲连接，管不到正在等回答的请求。
   - 头部晚到 8 秒：Node 24.21 和 Electron 44（Node 24.18，Host 的真实运行环境）都在 8.0 秒拿到回答。
   - 头部晚到 320 秒，在 Electron 44 下对照：`fetch` 在 304.3 秒报 `UND_ERR_HEADERS_TIMEOUT`，`requestJson` 在 320.0 秒拿到回答。
2. 总时限在两个阶段都生效：
   - 等头部阶段：头部晚到 3 秒、时限 1 秒，1.02 秒报 TimeoutError。
   - 读正文阶段：正文 3 秒才完、时限 1.5 秒，1.51 秒超时；正文卡住不结束，同样 1.51 秒超时。
3. 3xx：302 立即拒绝，不跟随。
4. 错误映射与原 `fetch` 版一致：
   - 端口没人听（ECONNREFUSED）、回头部前断连、正文中途断连（ECONNRESET）、非 JSON，都报"服务不可用"。
   - 超时报 TIMEOUT。
   - 500、422 带失败体照样解析返回。
5. 目标主机：主机名写死为字面 `'127.0.0.1'`，端口来自 Supervisor 自己选的端口。路径参数经 `encodeURIComponent`，查询串经 `URLSearchParams`，用户输入改不了目标主机。P-9/P-15 只管渲染进程和会话层，本来就不管 Host 的 Node 请求（P-9 登记里写明 Host 外连归 P-7），这次没有改变这一点。
6. 小参数复现见第 2 条；320 秒那一组是我自己跑的长实验。
7. 27 个 `/api` 方法：我在本机起假服务（`--fixtures`，端口段内的副本），新写法与 `128ee95` 的旧 `fetch` 写法逐个对照。
   - 27 个返回里 26 个逐字相同；`taskCreate` 不同只因为服务每次随机生成任务编号。
   - 有 25 个方法我构造了合法请求，经网络走通且回答通过契约；另 2 个是我构造的请求没过契约，两种写法都在发出前拒绝。
   - 回声服务比对：服务端看到的方法、路径、鉴权头、content-type、正文、Host 头，25/25 一致。
   - 另对真服务对照见 N1。

### 冻结清单（第一轮记录第二部分）逐条核对
| 编号 | 结果 |
|---|---|
| P1-1 人工核验 | 通过。`TWO_STEP` 只剩 reimburse 和 cancel；`buildInvoiceRequest('review')` 一律 `confirm:true`；`run()` 先弹确认框（含"逐张核对原票"和核验人），确认后只发一次；假服务不带 confirm 回 `[BLOCKED]`、`failed:true`；与引擎 `workflow.py:155-156`、`:178` 一致。我的变异全红：放回两步预览、第一次发 `confirm:false`、确认后发两次 |
| P2-1 长路由超时 | 通过（偏离接受，见上）。发票、归档、导入、扫描、成果确认、修订都走同一处；我把 Host 改回 `fetch` 的变异 MD 和作者的"没有总时限"变异都红 |
| P3-1 取消批次措辞、假服务全台账统计 | 通过（措辞变异红） |
| P3-2 预加载 4 例 | 通过。作者变异（只删一个选择器）和我的变异 MK（不删原型上的）都红；P-11 补丁里新增的就是这一个测试文件 |
| P3-3 `ENGINE_FAILED` 文案 | 通过（变异红） |
| P3-4 `PATCHES.md` 待办加 T20 | 通过 |
| P3-5 cancel 固定 `apply:true` | 通过。原把 `apply:false` 固定下来的断言已改；变异（改发 `apply:false`）红 |
| N1、N3 | 接受，无需改 |
| N4 | 交付说明第 2 节已按复核员措辞改 |
| N6 | 交付说明第 4 节已记为已知限制 |
| 第一轮通过项 | 没弄坏。dsh-ext 和 DSH 全部用例照过；抽了 3 个变异都红：exclude 不带 `confirm:true`、分区权限放行、IPC 不核 `senderFrame`；第一轮 N2 白名单探针 17 拒 8 放，0 处与预期不符 |
| 补丁链 | 12 个补丁按 `PATCHES.md` 顺序 `apply --check` 全部无错并打上。74 个改动路径里：67 个与 `D:\lawbench-A\dsh` 逐字节一致；3 个只差 T20 P-4 在途改动；4 个是我的克隆因 Windows 路径过长没检出的文件，与补丁无关 |

### 八项清单
1. 契约一致：通过。27 个方法新旧对照见上。
2. 边界输入：通过。我实测了 3xx、断连、非 JSON、正文卡住、超长等待。
3. 错误路径：通过。映射与旧版一致。
4. 日志不含正文：通过。`callApi` 日志字段没变。
5. 路径闸门未被绕过：通过。目标主机写死为 127.0.0.1。
6. 无外连：通过。我的实验只用 127.0.0.1 的 19351–19359；真服务的 6000D/395 地址设成本机没人听的 19358/19359，启动后读回设置核对过，没有调测试连接。
7. 测试覆盖新代码：大体覆盖，缺口见 P3-1。
8. 无机密入库：通过。diff 里没有 Key、令牌、本机用户名。

### 改动纪律
返修 diff 逐块对得上清单：
- P1-1：`invoice-logic`、`invoice.tsx`、`fake-tools`、`invoice.spec`。
- P2-1：`http-json.ts`（新增 42 行，够小）、`index.ts`（7 行）、`host-api.spec`、证据两件。
- P3-1：`invoice-logic` 和 `fake-tools` 的 report。
- P3-2：P-11 补丁、`PATCHES.md`。
- P3-3：`retainer.ts`、`retainer.spec`。
- P3-4：`PATCHES.md`。
- P3-5：`invoice-logic`、`invoice.spec`。
- 文档：交付说明第 5 节、`mutate.py`、`red-tests.txt`。

没有无关改动。

### 实际跑过的命令
- 在 `git archive` 导出的副本里（依赖用 robocopy 复制，加上指向复制件或 A 的只读联接）：
  - `node scripts\test.mjs`：27 个文件 474 项通过、5 跳过，与作者一致。
  - `tsc -p tsconfig.json --noEmit`：退出 0。
  - `node scripts\build.mjs`：退出 0。
  - `check_ui_words.py`：零命中。
  - `check_examples.py --skills skills`：退出 0。
- DSH：从 `D:\lawbench-A\dsh` clone，切到 `477b4f4`，按顺序打 12 个补丁；跑 `main-startup`、`lawbench-request-policy`、`welcome-window`、`lawbench-retainer`、`lawbench-retainer-preload` 五个文件，135 项通过，与作者一致。
- 变异 15 处，每处按 sha256 逐字节复原：
  - 13 处红：MA、MB、MC、MD、ME、MH、MI、MJ、MK、MM、MN、MO、MP。
  - 3 处绿：MF、MG（见 P3-1）、ML（见 N6）。
  - 作者的 31 处里复现了 6 处，全红：review 发 `confirm:false`、没有总时限、措辞改回、`ENGINE_FAILED` 文案、预加载只删一个选择器、cancel 发 `apply:false`。
- 实验：
  - `requestJson` 11 种情形，Node 24 和 Electron 44 各跑一遍。
  - 320 秒头部延迟，`fetch` 与 `requestJson` 对照（Electron 44）。
  - uvicorn 长连接竞态 42 次。
  - 假服务下 27 个方法新旧对照，加回声服务比对线上请求。
  - 本机真服务下新旧对照。
  - 第一轮 N2 白名单探针。

### 残留审计
- 我起的进程全部按 PID 结束或已自行退出：假服务、真服务、uvicorn、Electron 和 node 客户端。19351–19359 没有在监听；没有命令行含实验目录的进程。
- 实验目录 `rv-A25-lab` 已删：先把 370 个联接逐个解开（不碰目标），再删其余内容。
- A 那边前后一致：`dsh\node_modules` 条目数前后都是 40，`dsh-ext\node_modules` 都是 9，`D:\lawbench-A\dsh` 的 status 都是 99 条。
- 复核克隆 `rv-A25` 干净，HEAD 仍是 `7940d3e`。
- 没有动别人的进程（`soffice` 10028、42468 都还在）；没有写 `D:\lawbench*` 和协调目录。

### 证据缺口
- 桌面端没有起：发票页在桌面里走一遍、界面经远程调用等超过 5 分钟拿到结果，都没有端到端实测。Host 层已用真实运行环境 Electron 44 证明。
- 真服务上没有 T25 的发票和驱动接口（本基座的 service 还没合入），所以对真服务只核了传输层和 7 个已有接口；P1-1 仍靠引擎源码静态核对。
- 真抓包（G-11）不在本轮。

PASS
﻿
---

## 第二部分 主编排裁决（2026-10-02 00:16 (+08:00)，无人值守窗）

**结论：PASS，T26 第 1、2 步任务门=过。** 冻结清单全部关闭并各有复核员自证；P2-1 偏离（`node:http` 代替 undici `Agent`）复核员七项核实后接受（Electron 44 下 320 秒头部延迟拿到回答、两阶段总时限、3xx 拒、错误映射一致、目标主机写死 127.0.0.1、27 个方法新旧对照 26 逐字相同 + 1 随机编号）；第一轮通过项未弄坏；补丁链一致。

记录项（不阻断，随后续小项做）：P3-1 `http-json.ts` 的"3xx 当失败""超时 destroy"补两例；N5 PATCHES.md 131→135 文字；N6 假服务 review `[BLOCKED]` 无用例。主编排以注记交线 A 随 T20 一并做。

合流：随 T13/T17 合并（候 N55）。第 3 步归档面板等 T23。