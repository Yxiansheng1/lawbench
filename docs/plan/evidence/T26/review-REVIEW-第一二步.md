# T26 内置工具与归档的界面 · 第 1、2 步独立复核记录（第一轮：发票整理页 U-13、P-11 委托材料窗口 U-14）

- 复核员：一名 Opus 5.5 只读复核员
- target：line-A `128ee95`（已 rebase 到 main d7eca15）；范围仅此一提交（叠在 T17/T13 之上，未改 T17 代码）
- 复核克隆：scratchpad `rv-A24`
- 归档：主编排于 2026-10-01 23:19 (+08:00) 从复核员交回原文抄录，未改内容（无人值守窗）

## 第一部分 复核员原文
## T26 第 1、2 步复核（发票整理页 U-13、P-11 委托材料窗口 U-14）——复核员 rv-A24

范围：只看 `128ee95`。亲验 HEAD 为 `128ee95dc1bf54caf00305f5d41c2580894b81f9`，工作区干净，`d7eca15` 是它的祖先。这次提交没有碰 `dsh-ext/host/`、`session-store/`、`agent/`、`credentials/`、`cordis.patch.yml`，T17 的会话存储和路由代码一行没改。

### 发现

**P1-1 "人工核验"按钮在真服务上永远做不完**
- 问题：界面把 `review` 当成两步走，先发 `confirm:false` 当预览，预览成功才弹确认框、再发 `confirm:true`。但真引擎对没带 `--confirm` 的 review 不做预览，直接报错。
- 影响：律师每次点"人工核验"都只看到红色"引擎报告没有完成"，确认框永远不出现。U-13 的核验动作在真服务上整条走不通。
- 证据（已逐处核对）：
  - 界面：`dsh-ext/ui/invoice-logic.ts` 的 `TWO_STEP.review`（`preview:'self'`）；`invoice.tsx` 的 `run()` 里 `if (!v || v.failed) return`。
  - 真服务：`origin/line-C:service/lawbench/invoice/runner.py:205-208`，只在 `confirm` 为真时才加 `--confirm`。
  - 引擎第一步：`engines/invoice-ledger/scripts/workflow.py:155`，原文 `if not a.confirm ...: raise ValueError('逐张核对原票后，填写reviewer并加--confirm')`。
  - 引擎第二步：`workflow.py:178` 把这个异常打印成 `[BLOCKED]`、退出码 2。
  - 服务最后一步：`runner.py:88-91` 看到 `[BLOCKED]` 置 `failed:true`。
- 作者为什么没发现：开发假服务 `dsh-ext/dev/fake-tools.mjs:25,58` 自己造了一个"review_preview"成功体，和真服务行为不一致。`invoice.spec.ts` 也没有 review 的用例。交付说明 3.3 已写"候线 C 确认"，但引擎代码就在仓库里，答案是确定的。
- 最小修复：
  1. `review` 从 `TWO_STEP` 去掉，改成和 `exclude` 一样：先弹确认框（写明"逐张核对原票后确认，写入台账"），确认后只发一次 `confirm:true`。
  2. 假服务的 `review_preview` 改成回 `[BLOCKED]` 失败体，和真服务一致。
  3. 补一条页面用例：点人工核验后只发 1 次请求且 `confirm:true`，不确认则 0 次。
- 归类：范围内阻断。

**P2-1 "路由超时 35 分钟"实际在 5 分钟就断**
- 问题：Host 调服务用的是 Node 自带 `fetch`（`dsh-ext/host/index.ts:148-149`）。它只靠 `AbortSignal.timeout(route.timeoutMs)` 控时，底层 undici 默认"等响应头"上限是 300 秒。DSH 装的全局分发器也是默认参数构造的 `undici.Agent`（`packages/util/http-proxy/src/install.ts:145-157,196`）。服务要等引擎跑完才回头部。
- 我的实测：本机 Node v24.21.0，在 127.0.0.1:19341 起一个 320 秒后才回的服务，用 `AbortSignal.timeout(35 分钟)` 去请求。结果 `FAIL after 304.025 s TypeError UND_ERR_HEADERS_TIMEOUT HeadersTimeoutError`。
- 影响：
  - 超过 5 分钟的发票动作（大批量 `run`、首次 `env_check --deep --ocr` 等）界面会显示"工作台服务不可用"，引擎在服务端其实照跑。按钮恢复后律师再点只会拿到 `ENGINE_BUSY`，跑完的结果和 `files` 在界面上丢了。
  - "与 Spec 13.3 的 30 分钟对齐"这一说法不成立，T25 交付说明"不要给请求设短超时"实际仍被违反（等于隐藏了一个 5 分钟超时）。
  - 已有的 10 分钟 `LONG` 路由（归档、导入等）也有同样问题。这部分不是本次引入，可另列后续。
- 最小修复：长路由在 Host 的 `fetch` 里传 `dispatcher: new Agent({ headersTimeout: route.timeoutMs, bodyTimeout: route.timeoutMs })`（用 dsh 依赖里的 undici）。补一条用例：本机服务延迟超过 300 秒时仍能拿到回答（可用小超时参数缩短）。
- 归类：范围内（35 分钟是本次的交付点）；对 LONG 路由的影响属独立后续。

**P3-1 取消批次的"先看报表再确认"，报表里看不到要取消的批次**
- 问题：`report` 调的是 `invoice_db.py report`（`cmd_report`，`invoice_db.py:993` 起），给的是全台账统计，契约 1.3 的 `report` 也没有 batch 参数。确认框却写"上面是台账报表，请核对批次"X"的内容"。真服务上律师看不到打印批次的成员和文件夹。
- 安全上没问题：不会发出 `apply:false` 的 cancel；只有点确认（框里带批次名）之后才发 `cancel apply:true`；变异 M2 验证过。
- 最小修复（二选一）：
  - 改确认框措辞，不再说"核对批次内容"；
  - 或按 Spec 13.3 回写③ 允许的 `reprint` 做预览：它只读批次记录，能列出成员和文件夹。但 `reprint` 会让服务另存一份购买方副本；如果预览失败也应允许继续确认取消。
- 开发假服务的 `report` 输出写着"批次 {batch}：待报销 3 张"，和真引擎不符，宜一并改掉。
- 归类：范围内小项。

**P3-2 委托材料窗口的预加载脚本没有用例守着**
- 问题：`preload-retainer.ts` 删掉 `showDirectoryPicker`、`showSaveFilePicker`，两样都没有自动化用例。
- 我的变异 M8：去掉删 `showSaveFilePicker`，`lawbench-retainer.spec.ts` 9 项全绿。连 `showDirectoryPicker` 也只靠桌面端手工实测守着。
- 最小修复：加一条用例，用假的 `contextBridge.executeInMainWorld` 取出 `func`，在一个带这两个属性的假 window 上执行，断言执行后两者都是 `undefined` 或已不存在。
- 归类：测试覆盖缺口。

**P3-3 证件识别起不来时的提示借用了发票的文案**
- 问题：真服务驱动模型损坏时回 `ENGINE_FAILED`，它的中文是"发票整理未完成，请查看下方的输出信息"（`origin/line-C:service/lawbench/errors.py:29`）。`retainer.ts` 原样经 `errorText` 显示，律师会看到"证件识别没有启动：发票整理未完成……"。T25 交付说明"给 T26 的配合"第 2 条已提醒按接口区分文案。
- 最小修复：`openRetainer` 对 `started.error.code === 'ENGINE_FAILED'` 用自己的话，例如"本机识别引擎文件缺失或损坏，请联系技术支持"。
- 归类：范围内小项。

**P3-4 打包后仍会读环境变量 `LAWBENCH_ENGINES_DIR`**
- 问题：`enginesDirectory()` 打包后也接受这个环境变量，只要求是绝对路径，可以把委托材料网页和白名单里的 `file:` 根指到程序目录以外。
- 两条回退路径没问题：打包后是 `dirname(execPath)\engines`，开发期是仓库 `engines`，都不含用户名，也不越出程序目录。
- 最小修复：打包后忽略这个环境变量（与 PATCHES.md 待办里 `LAWBENCH_SKILLS_DIR` 的 T20 条目同理），并在 PATCHES.md "待办"表加一行 T20。现在只写在交付说明 3.1。
- 归类：独立后续（T20）。

**P3-5 `buildInvoiceRequest('cancel', form)` 默认就生成 `apply:false` 的 cancel，测试第 55 行还把它固定下来**
- 问题：服务对 cancel 一律带 `--apply`，这个默认值等于"真取消"。眼下界面只经两步路径调用，不会发出去；但这是个潜在陷阱。
- 最小修复：cancel 分支固定 `apply:true`，只经两步路径调用；或在函数注释里写明，并删掉测试第 55 行对 cancel 的那条断言。
- 归类：臆测级的维护风险。

**NOTE（不需要改，供主编排判断）**
- **N1 ENGINE_BUSY 后停用 15 秒，可以接受。** 服务等锁最多 2 秒就回 BUSY，不排队。15 秒后律师再点，只会再拿到一次 BUSY，或者锁正好空出来就执行（他已经确认过）。没有误执行风险。界面自己的动作本来就串行，BUSY 只会来自别处。提示卡 15 秒后消失，但输出区的 ENGINE_BUSY 中文说明一直留到下一个动作。
- **N2 白名单函数的调用参数核对无误。** `lawbenchRequestAllowed(url, 'http://127.0.0.1:17801', <engines>\retainer)`。我把 P-11 打好后的 `lawbench-request-policy.ts` 拿出来直接测：
  - 拒绝：6000D 两组（`192.168.8.77:8000`、`10.126.126.1:8000`）、395 两组（`192.168.8.124:9000`、`10.126.126.3:9000`）、`https`/`wss` 到 17801、`localhost:17801`、`[::1]:17801`、`127.0.0.1:17801@evil.test`、`127.0.0.1:17801.evil.test`、`127.0.0.1:80`、引擎目录外的 `file:`、`retainer2` 前缀、`%2F..` 编码、`file://主机/共享`。
  - 放行：`http`/`ws` 到 `127.0.0.1:17801`（`127.1`、`0x7f.0.0.1`、`2130706433` 这些写法 URL 解析后都是同一个本机地址）、本页目录内的 `file:`（不分大小写）、`data:`、`blob:`、`about:`。
  - 列表里还有 `dsh-app:`，但这个协议只在默认会话注册了 `protocol.handle`（`main.ts:562`），委托材料分区到不了，无害。
- **N3 `persist:retainer` 的落点与 Spec 3.3 一致，不用回写 Spec。** Spec 3.3 数据落点表本来就写着"委托材料窗口的浏览器存储 → Electron `userData/Partitions/retainer`"，交付说明 3.6 与之一致。
- **N4 `retainer-capture.txt` 的证据等级：间接证据，不等于抓包。**
  - 本机探针加关掉网页 CSP 后重试，能证明"拦下请求的是 P-11 的分区白名单"，是有力的功能证据。
  - 外网地址"失败"那几条单独看不足以作证（测试机可能本来就连不上 192.168.8.77）。
  - 连接表只是 22:11:19 一个时刻的采样，盯了 15 个进程。
  - 结论：可作为"白名单起作用"的证据，不能替代 G-11 的全程抓包（作者自己也这么写）。
- **N5 `leaks.txt` 自洽。** 本次扫描 100199 个加沿用 10 个，正好 100209；0 命中。范围是测试目录（DSH_HOME、LOCALAPPDATA、APPDATA 都指在这里）、开发期 Electron 用户数据、%TEMP%。排除的是案件目录、retainer 分区（Spec 允许）和 `%TEMP%\claude`（原因已说明）。另有 25 个文件读不了。
- **N6 停驱动由渲染进程做，不是主进程。** Spec 3.2 P-11 写的是"关闭窗口时通知工作台服务停止"。现在是关窗后界面调 `stop`；主窗口重载时会漏，作者已列入遗留，兜底是服务退出时关驱动。
- **N7 改动分量。**
  - 实现约 760 行：dsh-ext 界面约 494、P-11 主进程与预加载约 260、开发假服务约 121。
  - 用例约 582 行：invoice 232、retainer 130、P-11 单测 220。
  - 文档与证据约 388 行，另有 5 张截图。
  - 新抽象（`invoice-logic.ts` 纯逻辑、`fake-tools.mjs`）规模相称；`fake-service.mjs` 只是改成异步的缩进。没有无关改动，界面文字检查零命中。证据里没有用户名、没有 Key，5 张截图我逐张看过。

### 冻结清单逐条核对
| 项 | 结果 |
|---|---|
| 只发白名单 14 个动作、字段只用契约 1.3 | 通过。逐动作过契约的用例我独立复跑；变异 M3（report 改成 attach）变红 |
| `--apply` 类先预览再确认 | reimburse 通过；review 有 **P1-1**；cancel 用报表代替预览，见 P3-1 |
| cancel 从不发 `apply:false` | 通过（变异 M2 变红）；潜在默认值见 P3-5 |
| exclude 一律 `confirm:true`、带 reviewer/reason、先确认 | 通过（变异 M1 变红） |
| `failed:true` 标红显示 output；退出码 2 标黄 | 通过 |
| ENGINE_BUSY 停用全部动作并提示 | 通过（变异 M4 变红）；15 秒合理，见 N1 |
| 重印 `files` 为空时提示看输出 | 通过 |
| 路由超时 35 分钟对齐 13.3 | **不成立**，见 P2-1 |
| 未设日常办公文件夹或购买方时引导去设置 | 通过 |
| P-11 IPC 只认主窗口顶层 | 通过（`sender`、`senderFrame`、`assertDesktopSender` 三重核对；有用例） |
| 分区白名单拒 6000D、395 和外网 | 通过（N2；变异 M6 变红） |
| 权限一律拒 | 通过（变异 M7 变红） |
| 禁跳转、重定向、新窗口、webview；关拼写检查 | 通过（单测加作者变异） |
| 预加载删两个选择器 | 代码正确；**没有用例守**，见 P3-2 |
| 下载只落 `工作区\临时\委托材料\<时间>\`、同名改名、去掉目录 | 通过。案件根要求是真实文件夹且有"工作区"，不认联接；`临时` 这一层没核联接，NOTE 级 |
| 关窗后 stop，`running:true` 如实显示 | 通过（变异 M5 变红） |
| 导入 01委托手续，有 ZIP 时 `unzip:true` | 通过 |
| 没有案件时说明文件在哪 | 通过 |
| 补丁链 `apply --check`、与工作区逐字节一致、PATCHES.md 登记 | 通过。12 个补丁按顺序全部 `apply --check` 无错并打上；69 个改动路径与 `D:\lawbench-A\dsh` 逐字节一致（4 个是两边都已删除的文件）；PATCHES.md 已登记 |
| `LAWBENCH_ENGINES_DIR` 回退路径 | 回退路径通过；打包后仍读环境变量，见 P3-4 |
| 没改 T17 代码 | 通过 |

### 八项清单
1. 契约一致：请求、回答都过契约；review 的语义与真服务不符（P1-1）。
2. 边界输入：批次名、号码、日期、64 位编号、下载文件名（`..`、保留名、非法字符）都有校验和用例。
3. 错误路径：预览失败就停；开窗失败会停驱动；stop 停不下来如实显示。缺口是 P2-1（5 分钟头部超时）和 P3-3（文案）。
4. 日志不含正文：界面和主进程都不记引擎输出；Host 只记方法名、错误码、耗时。
5. 路径闸门：下载目录只落经核验的案件根或应用数据目录；导入走服务的 `/api/materials/import`。
6. 无外连：分区白名单核实（N2）；我的实验只用了 127.0.0.1:19341。
7. 测试覆盖新代码：大部分覆盖；review 流程和预加载脚本没有用例（P1-1、P3-2）。
8. 无机密入库：证据和代码里没有 Key、令牌、本机用户名。

### 实际跑过的命令
- `git rev-parse HEAD` / `status` / `show --stat` / `merge-base --is-ancestor d7eca15 HEAD`。
- 在 `git archive` 导出的副本上：`node scripts\test.mjs` → **27 个文件 468 项通过、5 跳过**（与作者一致）；`tsc -p tsconfig.json --noEmit` 退出 0；`node scripts\build.mjs` 退出 0；`check_ui_words.py` 零命中；`check_examples.py --skills skills` 退出 0。
- `check_plugin_tree.py`：要运行中的桌面端导出清单，我只能用 T17 的证据文件跑，结论"通过"。本次没改任何插件配置，这个结论只能算静态核对。
- DSH：`git clone --no-hardlinks D:\lawbench-A\dsh`，切到 `477b4f4`，按 PATCHES.md 顺序 `apply --check` 并打上 12 个补丁；逐字节比对；`vitest run` 跑 main-startup、lawbench-request-policy、welcome-window、lawbench-retainer 四个文件 → **4 个文件 131 项通过**（与作者一致）。依赖用联接指向 A 的 node_modules，只读，因为 `pnpm install --offline` 缺包装不上。
- 变异（我自己挑的 8 处，每处用完按 sha256 逐字节复原）：M1 exclude 去掉 `confirm`、M2 cancel 发 `apply:false`、M3 动作名改成白名单外、M4 BUSY 不停用按钮、M5 关窗不停驱动、M6 白名单换成 6000D 地址、M7 权限放行，**全部变红**；M8 不删 `showSaveFilePicker` **保持全绿**（P3-2）。
- 白名单探针（N2）、undici 头部超时实测（P2-1）。
- 直接跑真引擎 `workflow.py review` 没成功：引擎自己展开运行环境时进程报错退出。P1-1 的结论只依据代码静态核对，没有真跑。

### 残留审计
- 我起的进程（头部超时探针 node、两次引擎 python）都已自行结束；19341–19349 没有在监听；没有命令行含我实验目录的进程。
- 实验目录 `rv-A24-lab` 已删：先把 109 个联接逐个用 RemoveDirectory 解开（不碰目标），再删其余内容。A 的 `node_modules` 条目数前后都是 40，`D:\lawbench-A\dsh` 的 status 前后都是 69 条。
- 复核克隆 `rv-A24` 保持干净，HEAD 仍是 `128ee95`。没有动别人的进程，也没有写 `D:\lawbench*` 和协调目录。

### 证据缺口
- 桌面端没有起来复现：要在隔离目录完整构建桌面端主进程（tsc -b 会连带构建工作区各包）、Host 和组合包，还要起假服务和驱动，代价过大。发票页走完一期、委托材料窗口识别引擎已就绪、下载回退为 ZIP，这几条只采信作者的截图和记录。
- P1-1 没有在真服务和真引擎上实跑（引擎运行环境在我的实验目录里展开失败），只靠三处源码的静态链条。
- 界面到 Host 之间 DSH 远程调用有没有自己的超时，没核。
- 真抓包（G-11）不在本轮。

AMEND
﻿
---

## 第二部分 主编排裁决（2026-10-01 23:19 (+08:00)，无人值守窗）

**结论：AMEND，返修一轮，清单冻结。** 白名单动作、exclude/cancel 安全、BUSY 停用、P-11 分区白名单（6000D/395/外网全拒）、IPC 三重核对、权限拒、补丁链逐字节一致、泄漏 0 命中、无机密全部通过。

| 编号 | 裁决 |
|---|---|
| P1-1 "人工核验"在真服务上永远做不完 | 必修。`review` 从两步预览改成与 `exclude` 同款：先弹确认框（"逐张核对原票后确认，写入台账"），确认后只发一次 `confirm:true`；假服务 `review_preview` 改成回 `[BLOCKED]` 失败体与真服务一致；页面用例"点人工核验只发 1 次且 confirm:true，不确认 0 次"。**主编排补一条**：线 C 交付说明已写 review 不带 --confirm 只报错，作者 3.3 的"候线 C 确认"答案在仓库里 |
| P2-1 "35 分钟超时"实际 5 分钟断（undici headersTimeout 300 秒） | 必修。长路由 `fetch` 传 `dispatcher: new Agent({headersTimeout, bodyTimeout})`（dsh 依赖里的 undici）；用例用小参数复现"延迟超过头部超时仍拿到回答"。LONG 10 分钟路由同样受影响——一并改（同一处代码），记入交付说明 |
| P3-1 取消批次"先看报表"看不到批次成员 | 一并做：确认框措辞改成不说"核对批次内容"（主编排选措辞方案，不用 `reprint` 预览——它会另存副本）；假服务 `report` 输出改成与真引擎一致的全台账统计 |
| P3-2 预加载删两个选择器无用例 | 一并做：假 window 执行 `func` 断言两者消失 |
| P3-3 `ENGINE_FAILED` 借用发票文案 | 一并做：`openRetainer` 自己的话"本机识别引擎文件缺失或损坏，请联系技术支持" |
| P3-4 打包后仍读 `LAWBENCH_ENGINES_DIR` | 独立后续归 T20（PATCHES.md 待办表加一行） |
| P3-5 `buildInvoiceRequest('cancel')` 默认 `apply:false` | 一并做：cancel 分支固定 `apply:true` 并只经两步路径调用；删测试第 55 行那条断言 |
| N1 BUSY 15 秒 | 接受 |
| N3 `persist:retainer` 落点与 Spec 3.3 一致 | 不回写 |
| N4 `retainer-capture.txt` 是间接证据 | 交付说明按复核员措辞写明"白名单起作用的功能证据，不替代 G-11 抓包" |
| N6 关窗停驱动在渲染进程、主窗口重载会漏 | 已知限制（兜底服务退出关驱动） |

作者第 3 节六条：①引擎目录归 T20；②15 秒接受；③review 口径见 P1-1；④粘贴路径接受；⑤删 `showSaveFilePicker` 接受；⑥落点一致。