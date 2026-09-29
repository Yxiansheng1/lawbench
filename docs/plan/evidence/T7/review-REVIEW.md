# T7 第一次交回复核记录（插件侧，对假服务验收）与主编排裁决

- 复核员：主编排派出的子代理，Opus 5.5 · high，只读。停摆前（00:2x）派出的那一名因用量上限中断、没有留下结论，本份是 01:3x 重新派出的另一名
- target：head `f0e3dda2928fd99b1d9831c2696a0647f5c35892`（line-A），base `f57f309`；范围 `dsh-ext\`、`dsh-patches\`、`docs\plan\evidence\T7\`
- 复核位置：主编排临时目录里的克隆和实验目录；没有联网，没有碰凭据管理器，没有启动桌面端
- 时间：2026-09-30 01:33 起，约 15 分钟（无人值守窗内）
- 第一部分是复核员最终报告的原文，未作删改；第二部分是主编排的裁决

---

## 第一部分 复核员报告
# T7 第一次交回 独立复核（线 A 插件侧，对本机假服务验收）

**先说结论：AMEND。** 功能主体是对的。11 个 `case_*` 工具的参数逐字来自契约；看护逻辑有上限，不会无限重启；Key 确实只经标准输入输出传给 PowerShell；日志只记元数据；插件自己不读写案件文件，也没有外连。要返修的是两处测试缺口（两条 P2）：
- `/core/*` 的返回契约校验没有任何测试兜住。我把这段校验删掉，测试照样全绿。
- P-3 整个删掉了 DSH 里测首次配置窗口安全属性的测试。被测的代码还在，只是换了 IPC 通道名，应当改写而不是删除。

另有 7 条 P3、若干 NOTE，都不阻断。

复核对象：`line-A` head `f0e3dda2928fd99b1d9831c2696a0647f5c35892`，merge-base `f57f309`，克隆工作区始终干净（已亲验）。

## 这张卡要求什么（一句白话）
在 DSH 里装三个我方插件：
- **Host 插件**：拉起并看护工作台服务。
- **Agent 插件**：按契约注册 11 个 `case_*` 工具，管取任务、上下文、预算、进度和结束。
- **凭据插件**：Key 放进 Windows 凭据管理器，不落盘。

同时把 DSH 的欢迎窗口换成"首次配置"页。在工作台服务合并之前，先对本机假服务把整条链路跑通。

## Findings（按严重度）

**P2-1 `/core/*` 返回的契约校验没有测试（范围内阻断）**
- 问题：工单第 3 步要求请求和返回都校验。代码做了（`dsh-ext\shared\core-client.ts:64-70`），但没有一个测试让服务返回不合契约的内容。
- 影响：这段校验被误删或改坏，测试发现不了。交付说明第 3 节说"测试覆盖通过、拒绝"，实际只覆盖了"请求被拒"。
- 证据：变异 M4 把 `validate(id, 'response', payload)` 换成空数组。`core-client.spec`、`contracts.spec`、`agent.spec` 共 20 项仍全绿（rc=0）。
- 最小修复：给 `dev\fake-service.mjs` 加一个开关（比如 `--bad-response`），让它返回缺字段的响应。在 `tests\core-client.spec.ts` 断言得到 `INTERNAL`，并且记了一条 `core.response_contract`。`executeTool` 对工具结果的校验也补一个同类用例。

**P2-2 P-3 删掉了仍然有效的安全测试（引入的回归）**
- 问题：`P-3-first-run-page.patch` 整个删除了 `apps/desktop/tests/welcome-window.spec.ts`（补丁第 1979–2172 行）。这个文件测的是：
  - 窗口的 sandbox、contextIsolation 配置；
  - 禁止跳转、`setWindowOpenHandler` 拒绝；
  - 拒绝非本窗口主框架发来的 IPC（"unowned frame"）；
  - 窗口关闭时移除 IPC 处理器。

  这些代码在 `welcome-window.ts` 里原样保留，只换了 IPC 通道名。
- 同时删掉的 `welcome-host.spec.ts` 有两类测试，新的 `welcome-backend.ts` 没有对应测试：
  - "诊断信息不外泄"：新代码 `safe()` 只放行含中文的错误信息，这个逻辑没测；
  - "未认证就拒绝"。
- 新增的 `lawbench-first-run.spec.ts` 只测了三个输入校验函数。
- 影响：首次配置窗口是 Key 的输入入口，它的框架隔离和错误信息过滤现在没有回归保护。
- 最小修复：
  - 把 `welcome-window.spec.ts` 恢复，只把通道和 operations 的 mock 换成 `getSetup / testConnection / save`；
  - 给 `connectDesktopWelcome` 补两个用例：远端错误信息不含中文时换成通用文案；认证失败时抛错。

**P3-1 "退出码 2 不计入重启次数"的测试没有区分力（范围内）**
- 证据：变异 M5 把退出码 2 的分支整个关掉，`supervisor.spec` 6 项仍全绿。原因是测试只让进程退出 2 次，就算计入重启次数也不到 3 次上限。
- 修复：`simDeps([2,2,2,2,undefined])`，断言最终 `running`、不是 `failed`。

**P3-2 看护的两处小竞争（独立后续）**
- 位置：`host\supervisor.ts:90-93`。`launch` 在 `await pickPort()` 之后没有再检查 `stopping` 和 `generation`。
  - 如果恰好在挑端口的几毫秒内调了 `stop()`，仍会拉起一个没人管的服务进程。桌面端用 Windows job 收容子进程，Host 退出时会一并结束，所以影响有限。
- 位置：`onExit` 第 153、164 行用 `void this.launch(...)` 调用，没有接住异常。
  - `pickPort` 抛错时（例如开发期端口范围全被占），会变成未处理的 Promise 拒绝，状态卡在 `starting`。
- 修复：await 之后加 `if (this.stopping || gen !== this.generation) return`；两处 `launch` 调用加 `.catch`，里面记日志并把状态设为 `failed`。

**P3-3 凭据的 PowerShell 子进程没有超时（独立后续）**
- 位置：`credentials\credman.ts:42-58`。PowerShell 一旦挂住，`setupState`、`resolve` 会一直等下去：首次配置页卡在加载中，模型请求也会卡住。
- 修复：`run()` 加 15 秒超时，到时结束子进程并报错。

**P3-4 默认测试命令会写真凭据管理器，还留下临时目录（独立后续）**
- `node scripts/test.mjs` 会跑 `credman.spec.ts`，每次在真凭据管理器里写再删一条 `lawbench/T7-TEST-xxxx`。
- 假服务每次在 `%TEMP%` 留一个 `lb-fake-*` 目录，从不清理。本机现在已有 40 多个 `lb-fake-*` 和 12 个 `lb-agent-calls-*.jsonl`，是作者之前的运行留下的，我没有动。
- 修复：`credman.spec` 改为只在设了环境变量（如 `LB_TEST_CREDMAN=1`）时才跑；`startFake().stop()` 里顺手删掉自己的临时目录。

**P3-5 "测试连接"会先保存地址和 Key（交主编排定）**
- 交付说明第 5 节已把这点列为"线 A 实现选择"。Spec 3.2 P-3 原文只说"'测试连接'调 `/api/connection/test`"。
- 实际后果有两个：
  - 只点"测试连接"、不点"保存并进入"就关窗口，下次启动也算已配置，会跳过首次配置页；
  - 测试时输错的 Key 会直接覆盖之前存好的正确 Key。`first-run.png` 里测试后 Key 栏显示"已保存"，就是这个行为。
- 是否接受由主编排定。

**P3-6 进度和结束两类调用可能乱序到达服务（臆测，等 T8 真服务核实）**
- `agent\index.ts:188-190` 对每个 `session/event` 都是发出去就不管。
- 前一条 `/core/progress` 还在路上时，`/core/task/end` 可能先到。服务如果按 Spec 9.2 在结束时把 `进行中.md` 改名，这份文件可能又被迟到的进度重新写出来。
- 修复：按会话把 `core.call` 串成一条队列，前一个完成再发下一个。

**P3-7 凭据插件不发更新事件（独立后续）**
- DSH 的基类 `CredentialProvider` 在 set、unset、modifyRecord 后会发 `credentials/reference-updated` 和 `record-updated`。界面的 `ui-model-selection`（`service.ts:55-56`）靠这两个事件刷新模型目录。
- 我方插件没有继承基类，也不发这两个事件。以后在设置页换 Key，模型目录可能要重开才刷新。首次配置页保存后直接进工作区，现在不受影响。

**NOTE**
- 退出码 3（被信号停止）现在按普通退出处理：重启，并计入次数。代码注释写的是"Host 主动停止时不重启"，执行令只说"认退出码 3"。二者不矛盾但不明确，交主编排定。
- 转发端口 18765 被占时服务也以退出码 2 退出，Host 会白白换 5 次服务端口。最坏约 24 次拉起后停在 failed，有上限。
- 工具白名单用的是正则 `^case_[a-z_]+$`，不是 11 个注册名的集合。这符合 Spec 1.2 的写法；收紧成集合也可以。
- 服务启动命令目前从环境变量 `LAWBENCH_SERVICE_CMD` 读，仅开发期。`PATCHES.md` 已记入 T20 待办。
- `check_plugin_tree.py` 只检查"必须关"的行，没有"必须开"的清单：`legal-credentials` 或 `legal-host` 被关掉它不会报。缺了凭据插件时拿不到 Key、模型请求失败，不会泄露，所以只算提醒。
- **P-6 没做（主编排未裁决），我的看法**：同意延后到 T13。
  - T7 的所有验收项都不依赖它：首次配置页在 Electron 主进程里经 Host 的 `/api/lawbench/*` 调用，`first-run.png` 显示能用；
  - P-6 只有界面插件用 `ctx.remote.lawbench` 时才需要；
  - 建议主编排在 T13 工单的"输入"里明写 P-6。

## 八项清单

| 项 | 结论 | 依据 |
|---|---|---|
| ①契约一致 | 通过；返回侧缺测试（P2-1） | 自写脚本逐个比对：11 个工具参数与契约 `$defs/args` 逐字相同，`case_suggest_wiki` 展开 `$ref` 后字段集合一致，无残留 `$ref`，11 个工具都有 `result` 定义。`/core/*` 请求和返回都校验，工具结果另按工具契约校验。没有私自增减字段 |
| ②边界输入 | 通过 | Key 只接受 8–512 位可见 ASCII，渲染进程和主进程两层都查；地址只接受 `http://`，拒绝多余字段；`putSettings` 按契约校验；`testConnection` 只接受 `llm` 和 `prep` |
| ③错误路径 | 基本通过；见 P3-1、P3-2、P3-3 | 服务连不上、401、没有端点：都报 SERVICE_UNAVAILABLE（有测试）。返回不合契约：报 INTERNAL（无测试）。取不到任务：拒绝整轮（有测试）。重启超限：failed（有测试，变异 M2 能抓到）。端口被占 / 退出码 2：换端口（测试没有区分力）。退出码 3：见 NOTE |
| ④日志不含正文 | 通过 | 日志只记事件名、命令、状态码、耗时、错误码、端口、次数、工具名、记录名。契约里没有以用户数据作键的对象（没有 patternProperties，也没有对象形式的 additionalProperties），校验错误的路径不会带出材料名；令牌、Key 不进日志 |
| ⑤路径闸门未被绕过 | 通过 | 插件只写 `<应用数据>\logs`、只查 `settings.json` 是否存在；`cwd` 原样交给服务；没有读写案件文件的途径 |
| ⑥无外连 | 通过 | 插件代码、假服务里的 fetch 都指向 127.0.0.1，并设了 `redirect: 'error'`。P-3 删掉了 `shell.openExternal`、复制登录链接、账号监听；页面上没有外部链接和登录入口。diff 里的外部地址只出现在补丁删除的旧测试行中 |
| ⑦测试覆盖新代码 | **不通过**（P2-1、P2-2、P3-1） | `host\index.ts`（LawbenchRemote、passThroughEnv、freePort）和 `agent\index.ts` 里 `apply()` 的挂接没有单测，只有端到端证据 |
| ⑧无机密入库 | 通过 | 扫 diff 新增行：没有真 Key 和令牌，只有测试用的假值 `sk-12345678`。地址只有 127.0.0.1、192.168.8.77、192.168.8.124、10.126.126.1。证据文件里没有 `Authorization` 值、没有真实案卷内容，用户名已打码 |

## 活性地图（看护与相关等待点）

| 资源 | 持有者 | 等待点 | 有没有上限 |
|---|---|---|---|
| 服务子进程 | `Supervisor.child` | `child.exited` | 有：terminate 后 graceMs 3000 强制结束，另有 Windows job 收容 |
| 启动探测循环 | `launch` | 每次 probe（2 秒超时）加 500 毫秒间隔 | 有：30 秒到期就 kill，计一次重启 |
| 5 秒探测定时器 | `schedulePing` | 上一次 probe 结束后再排下一次 | 有：3 次没响应就 kill；stop 或 generation 变化即停 |
| 重启计数 | `restarts[]`（滚动 60 秒） | — | 有：1 分钟内第 4 次退出就停在 `failed`，不再恢复；每条链最多换 5 次端口；最坏约 24 次拉起 |
| 挑端口 | `freePort` | 本机绑定 | 快，但抛错时没人接（P3-2） |
| `/core` 调用 | CoreClient | fetch | 有：60 秒 |
| Host 转 `/api` | LawbenchRemote | fetch | 有：30 秒 |
| 凭据读写 | credman | PowerShell 子进程 | **没有**（P3-3） |
| 任务状态 | `LegalAgent.tasks` | turn/end | 按会话；turn/end 没来时由下一轮第一步覆盖 |

探测和重启之间的竞争由 generation 挡住：版本不符、stop、新一轮启动都会让旧的回调失效。只剩 stop 恰好落在挑端口那一刻的窗口（P3-2）。

## 预算与"立即收尾"（Agent 插件）
- 工具预算：只数 `case_*`，`case_save_draft` 不计入也不受限。第 25 次被拒，有测试；变异 M1 能抓到。
- 模型调用预算：第 8 次调用前只注入一次"立即收尾"，第 9 次拒绝，有测试。
- 时长：45 分钟时拒绝，40 分钟时注入收尾。
- 白名单外的工具：发给模型的工具集合恰好是 13 个（`request-tools.json`），执行前的挂载点还会再拒一次（变异 M3 能抓到）。
- 缺口：真 DSH 里"立即收尾"注入和预算拒绝的效果，只有单元测试，没有端到端证据。

## 凭据插件
- Key 只经标准输入写入、标准输出（base64）读回；命令行里只有 `-EncodedCommand` 加脚本，脚本里只有目标名和用户名这两个常量。这一点属实。
- 授权记录白名单只有 `client-connection/browser-session`，只放内存；其他记录名一律拒绝，日志只记记录名。
- 核对了 DSH 的 `credentials` 远程接口（`settings-controller/src/credentials.ts`）：对界面只开放 describe、set、unset，不开放 `resolve`，界面读不到 Key。

## 配置补丁与反向检查
- 49 行"必须关"的行在运行时插件清单里全部是关闭状态，其中含原 `credentials` 行。
- `legal-host`、`legal-credentials` 已启用；preset 里只挂了 7 个允许的插件。
- 我独立重跑了 `check_plugin_tree.py`（通过）和 `mutate_check.py`（8 种篡改全部报出，基线通过），检查脚本有区分力。

## P-3 补丁（2172 行：新增 302 行，删除 1603 行）
- 改动只落在首次配置流程涉及的文件上，没有顺手改别的。
- 删掉 DeepSeek 账号相关的测试是合理的。但 `welcome-window.spec.ts` 和 `welcome-host.spec.ts` 里的安全用例不该删，见 P2-2。

## 文件归类
- **必需实现**：`dsh-ext\agent\*`、`host\*`、`credentials\*`、`shared\*`、`persona.md`、`cordis.patch.yml`、`package.json`、`pnpm-lock.yaml`、`tsconfig.json`、`vitest.config.mjs`、`scripts\*`、`.gitignore`；删除 `agent-ping\`；`dsh-patches\P-3-first-run-page.patch`、`PATCHES.md`；删除 `P-03a`。
- **必需验证**：`dsh-ext\tests\*`、`dev\fake-service.mjs`、`dev\check-keyring.mjs`、`dev\build-one.mjs`、`docs\plan\evidence\T7\*`。
- **无关**：无。

## 我实际跑过的命令（都在克隆和实验目录里，没有联网）
- `git rev-parse HEAD`、`git status --short`、`git merge-base`、`git diff --stat f57f309 HEAD`，以及对 diff 新增行的机密、网址、IP、用户路径扫描。
- 实验目录的搭法：
  - `git archive` 取出 `dsh-ext`、`contracts`、证据目录和 `dsh-patches`；
  - 用 robocopy 复制 `D:\lawbench-A\dsh-ext\node_modules`，再在实验目录内重新做 ajv 的 junction；
  - `dsh\node_modules` 用 junction 只读指向 `D:\lawbench-A\dsh\node_modules`。
- `node scripts/build.mjs`：通过。`tsc -p tsconfig.json --noEmit`：退出码 0。
- `node scripts/test.mjs --exclude tests/credman.spec.ts`：6 个文件 44 项全过。另外 5 项在 `credman.spec`，会写真凭据管理器，所以没跑。
- 自写脚本逐个比对 11 个工具参数与契约：0 处不符。
- 变异（都是改坏→跑测试→复原→再跑，复原后全绿）：

  | 变异 | 改了什么 | 改坏后 |
  |---|---|---|
  | M1 | `case_save_draft` 不再豁免工具预算 | 红 |
  | M2 | 1 分钟 3 次上限失效 | 红 |
  | M3 | 白名单放行一切工具 | 红 |
  | M4 | 去掉 `/core` 返回的契约校验 | **仍绿** |
  | M5 | 退出码 2 也计入重启次数 | **仍绿** |

- `python check_plugin_tree.py` 和 `python mutate_check.py`：通过；8 种篡改全部报出。

## 残留审计
- 18700–18900 端口没有监听；我起的 node 和假服务进程都已结束（只剩两个我复核前就在的 Codex node 进程）。
- 实验目录已删除：先拆 junction，确认 `D:\lawbench-A\dsh\node_modules` 完好，再删。
- 我那次测试在 `%TEMP%` 留下的 3 个 `lb-fake-*` 和 1 个 jsonl 已删除；作者之前留下的没有动。
- 复核克隆 `git status` 干净，HEAD 没变；`D:\lawbench-A` 的 `git status` 干净。
- 没有碰凭据管理器，没有启动桌面端。

## 证据缺口
- 没有跑 `credman.spec`（会碰真凭据管理器），也没有独立验证 keyring 互通，都采信作者的 `credentials-check.txt`。
- Spec 8.1 验收"换一个 Windows 账号登录读不到"：没有证据，作者也没测。
- 没有启动 DSH，所以下面几项只有作者的证据：
  - 桌面端里"立即收尾"注入、预算拒绝的真实效果；
  - `tools/pre-execute` 的 prepend 顺序；
  - P-3 的真实界面流程；
  - DSH 网关对 `lawbench` 远程接口的"运行时回退"：`gateway/src/index.ts:743-830` 我没有逐行核实。
- `credential-manager.png` 用 cmdkey 输出代替，要不要补截图交主编排定。
- 所有联调对的都是假服务；真服务复测留在第二次交回。

AMEND

---

## 第二部分 主编排裁决（2026-09-30 01:49 (+08:00)）

**T7 第一次交回不合并，返修。** 功能主体成立，要返修的是测试缺口。

### 返修清单（冻结）

| 编号 | 裁决 |
|---|---|
| P2-1 | 必修。假服务加一个"返回不合契约"的开关；`core-client` 断言得到 `INTERNAL` 并记一条日志；`executeTool` 对工具结果的校验补同类用例。红测：去掉返回校验后这些用例变红 |
| P2-2 | 必修。恢复 `welcome-window.spec.ts`，只把通道和 mock 换成现在的三个操作；给 `connectDesktopWelcome` 补两个用例（远端错误信息不含中文时换成通用文案；认证失败时抛错） |
| P3-1 | 必修。退出码 2 的测试改成有区分力的（连续多次退出码 2 后仍是 running、不是 failed）。红测：关掉退出码 2 的分支后变红 |
| P3-5 | 必修，按下面的裁决改 |

### P3-5 的裁决："测试连接"先保存

契约里 `/api/connection/test` 不带地址和 Key 参数，服务按已保存的设置测。让它接受候选值是改契约，不做。在契约之内这样定：

- "测试连接"仍然先保存再测；**测试失败时恢复成测试之前的地址和 Key**（之前没有的就删掉），测试成功的保留。
- "是否已配置过"的判断不变。测试成功后直接关窗口、下次不再显示首次配置页，可以接受：这时存下的配置是测通过的。
- 恢复 Key 时旧值只在进程内存里过一下，不写日志、不落盘。

### 放到第二次交回（对真服务复测）时一并做

| 编号 | 做什么 |
|---|---|
| P3-2 | `launch` 在挑完端口之后再检查一次是否已停止或已换代；两处 `launch` 调用接住异常，记日志并把状态设为 failed |
| P3-3 | 凭据的 PowerShell 子进程加 15 秒超时 |
| P3-4 | `credman.spec` 只在设了环境变量时才跑（默认测试命令不碰真的凭据管理器）；假服务停止时删掉自己的临时目录。线 A 之前在系统临时目录留下的 `lb-fake-*`、`lb-agent-calls-*.jsonl` 由线 A 自己清掉 |
| P3-6 | 进度和结束两类调用按会话排队，前一个完成再发下一个；对真服务核实 `进行中.md` 不会在结束后又被写出来 |
| NOTE 转发端口 | 转发端口被占时服务同样以退出码 2 退出，Host 换服务端口无济于事。对真服务实测后给出做法，交主编排定 |

### 不在本卡做

| 项 | 去向 |
|---|---|
| P3-7 凭据插件不发更新事件 | 转 T13（设置页换 Key 时要用） |
| P-6 没做 | 同意延后。工单 T13 第 1 步本来就写着 P-6；主编排执行令 Q3 里"P-6 提前到 T7"那句撤回 |
| 退出码 3 | 维持现在的做法：Host 自己发起的停止不重启；不是 Host 发起的退出码 3 照常重启并计入次数。代码注释改准确 |
| 工具白名单用正则 | 维持，符合 Spec 1.2 |
| 反向检查脚本没有"必须开"的清单 | 记为提醒，不要求 |
| `credential-manager.png`、"换一个 Windows 账号登录读不到" | 留到验收机，由用户截图和实测（候 owner 清单 N30） |

### 下一轮复核

换新的复核员，审完整累计范围，逐条核对 P2-1、P2-2、P3-1、P3-5 是否关闭。
