# T17 累计范围（第三轮）· Reviewer A（改动纪律与可维护性）

- target：line-A `a8ffb5a07ba19aa458ea7f9380f762e6ca0e7da9`（已 rebase 到 main 49313b1）
- 范围：T17 第一步、第二步、第二步返修（d870e22）、第三步（995814a、5d685cf、5ae689d）
- 派发：两名 Opus 5.5 只读复核员同一条消息并发派出，素材相同，互相看不到（前一对因用量上限中断、无结论，本对为重派）
- 复核克隆：scratchpad `rv-A20`
- 归档：主编排于 2026-09-30 20:59 (+08:00) 从复核员交回原文抄录，未改内容

## 复核员原文

# T17 累计复核（第一步、第二步、第二步返修、第三步）· Reviewer A：改动纪律与可维护性

**Target**：line-A `a8ffb5a07ba19aa458ea7f9380f762e6ca0e7da9`。克隆 rv-A20 里亲验过 HEAD，`git status` 干净。T17 的提交与交代的清单一致。

**要求的行为（白话）**：
- DSH 的源码改动全部以补丁存在，登记和代码要对得上。
- 第二轮冻结的返修清单逐条关掉。
- 第三步：会话记录按案件存进 `<案件>\工作区\会话`，由我方路由插件顶替原版存储，原版包不改。
- 搬家后旧会话能列出、能打开、能续写。
- 不在案件里的会话不能新建（N46 ②），`$DSH_HOME` 里不留会话原话。

## 一、Findings

**P2-1 关掉会话投影缓存的代价，交付说明写错了**
- 问题：交付说明 5.3 说关掉 `session-projection-cache` 的代价是"列会话时要多重放一遍记录"，侧栏标题变成工作区名"还没查清原因"。实际原因可以确定：DSH 的 `packages/api/session-controller/src/list.ts:282-283`，没打开过的会话，它的标题只从这个缓存取（`cache?.cachedSnapshot(header) ?? cache?.cachedPredecessorTitle(header)`）。缓存关了就没有标题，也不会重放。
- 影响：重启后，同一案件下所有没打开过的会话标题都一样（都是案件名），律师分不清。作者把这条交主编排定，但给的代价说错了，主编排是按错的前提在做决定。
- 证据：上面这段源码；交付说明 5.3、5.8"标题现象"。
- 最小修复：把 5.3 更正为"没打开过的会话在侧栏没有标题，不是多重放"，再由主编排在两条路里选：接受这个代价，或者把标题或投影缓存按案件存放。
- 归类：范围内阻断（第三步引入，属于披露不准）。

**P2-2 PATCHES.md 里 P-9 的登记和补丁不一致**
- 问题：PATCHES.md"T17 第二步返修增补"表 P-9 第④条写"删掉 `file:`"，引用的测试名是"refuses file:, chrome: and chrome-extension:"。实际补丁保留了 `file:`，只放行本应用 `renderer` 目录（`lawbench-request-policy.ts` 的 `appFile`）。测试名实为"file: only for the application renderer files…"和"refuses chrome: and chrome-extension:"。
- 这是对冻结裁决（`file:` 删掉）的偏离，只在交付说明 6.1 请主编排过目，补丁台账反而写成已删。
- 影响：补丁台账是换 DSH 提交时逐条重做的依据，写错会让下一个人以为 `file:` 已经不放行。
- 最小修复：改正第④条和测试名，写明理由（首次配置窗口在 `welcome-window.ts:90` 用 `loadFile` 从 renderer 目录加载），由主编排接受这处偏离。
- 归类：范围内阻断（本次修正引入）。
- 我复核了这处偏离本身，实现是对的：
  - 放行：`file:///…/renderer/x`、大小写不同的写法、`file://localhost/…`。
  - 拒绝：renderer 目录本身、相邻目录 `renderer2`、`..%2f`、`%5c`、`file:////srv/share`、`file://srv/share`、编码过的 UNC。
  - 其余：`filesystem:`、`javascript:`、带账号的 Host 地址都拒绝。
  - 没有找到绕过口，止损线没有触发。

**P3-1 拼写检查只关了主窗口，文档写成"所有窗口"**
- 问题：裁决要求 `setSpellCheckerEnabled(false)`，代码里没有这个调用，只在主窗口的创建处（`main.ts:219`）写了 `spellcheck: false`。首次配置窗口（`welcome-window.ts`，有地址输入框）和 `update-overlay.ts` 的弹窗没设，Electron 默认是开的。
- PATCHES.md 写"③ 所有窗口 `spellcheck: false`"，Spec 3.2 的 P-9 行写 `session.setSpellCheckerEnabled(false)`，两处都和代码不符。回归用例遍历的窗口也只有主窗口。
- 最小修复：在默认会话上加一行 `session.defaultSession.setSpellCheckerEnabled(false)`，或者把文档改准确。
- 归类：范围内（小）。

**P3-2 路由的几处关键路径没有测试守着**
- 我做的变异里有 3 个没变红：
  - `flush` 只刷默认根。案件实例的持久化屏障没有任何用例。
  - 重复编号不跳过。
  - `locate` 不查编号表（这一条只影响性能）。
- DSH 的存储契约整套只在"开关打开、全部落默认根"下跑，没经过案件实例和 cwd 替换用的 Proxy 句柄。
- 最小修复：契约整套再跑一遍，会话 cwd 放在已登记的案件根里（外加一遍搬家后的根）；补一条"案件实例的 flush 被调用"用例。
- 归类：独立后续（测试缺口）。

**P3-3 N46 ② 只拦了新建，已有的案件外会话还能续写**
- 问题：路由只在 `create` 时拒绝。`$DSH_HOME\sessions` 里已有的案件外会话，`open(id,'write')` 照常放行，续写的内容仍落在 `$DSH_HOME`。执行令原话是"已有的照常可读"。
- 影响：只影响升级前就有记录的机器（开发机）。第一版还没部署，影响小。
- 最小修复：默认根的 `open(…,'write')` 拒绝并给同一句中文说明；或者由主编排明确"续写可以"。
- 归类：范围内，待主编排定。

**P3-4 证据文件和文档有几处过期或笔误**
- `docs\plan\evidence\T17\plugin-tree.txt:1483` 仍是 `allowOutsideCase: true`，是 N46 提交之前导出的静态树。`check_plugin_tree.py` 也不核 `legal-session-store` 的配置，N46 的配置值只靠插件默认值和桌面端实测守着。
- 交付说明 5.1 的表里仍写 `allowOutsideCase: true`。
- 交付说明 5.8 的"见 `第三步ed-tests.txt` 末节"：路径里的 `\r` 被吞掉了，应为 `第三步\red-tests.txt`。
- 最小修复：重新导出静态树；检查脚本加一行核 `allowOutsideCase: false`；两处文字改正。
- 归类：本次引入（文档）。

**P3-5 案件根名单缓存出错时不留痕，列会话还会等服务**
- `session-store\case-roots.ts` 的 `load()` 和 `save()` 出错时既不报错也不写日志。缓存坏了就当空名单；在 N46 ② 下，服务起来之前所有新建都会被拒，日志里却查不到原因。
- `router.list()` 每次都 `await` 一次服务刷新（5 秒节流、超时 3 秒），服务慢时侧栏列表会跟着慢。
- 最小修复：两处各记一条元数据日志（只写错误码）；列表里的刷新改为不等待。
- 归类：独立后续。

**P3-6 P-5 补丁里问钩子的循环写了两遍**
- `ui-conversation/src/client/apply.ts` 里，`intakeFirst` 和 `addFiles` 各自遍历一遍钩子。钩子都不接手时会被问两次。
- `addFiles` 只有 `InputBar.intakeFiles` 一处调用。我方钩子从不返回 `undefined`，所以目前没有实际影响。
- 最小修复：抽成一个小函数共用。
- 归类：独立后续（可维护性）。

**NOTE-1 "不需要改原版包、不做 P-19"这个说法成立，而且是必然的，不是碰巧**
- 原版的身份核对（`session-persistence-jsonl/src/index.ts` 1514-1541 行的 `assertStoredIdentity`）用"本实例的根 + 记录头里旧 cwd + 编号"算出应在的位置。
- 按编号找文件时（`findLog`，1486 行）是扫这个根下面的全部项目目录。
- 续写也按内部那份旧 cwd 的记录头写。
- 每个案件一个实例、根跟着案件目录一起搬，所以 `--<旧cwd>--\<编号>` 这段相对路径不变，核对自然通过。
- 我核过 `D:\lawbench-A` 已构建的 `lib/index.js`，身份核对与源码一致，没有 cwd 覆盖的试验残留。
- 用原版包的搬家用例我跑过，能列、能开、能续写，而且 `sessions` 目录里没有新东西。
- 例外只有"只搬了一部分"或手工改了目录名，作者已写明。

**NOTE-2 路由对子目录 cwd 的处理**：`header()` 会把 cwd 在案件根子目录里的会话也改报为案件根。DSH 的会话 cwd 就是工作区根，目前没有影响。

**NOTE-3 无关新发现**：`docs\plan\evidence\T13\review-REVIEW-第三轮.md:232` 把本机用户名那串数字当作扫描关键词写了出来。这不是 T17 作者的文件，请主编排自行决定要不要打码。

**NOTE-4 B-F7、B-F5 的后续记在哪里**：裁决里"记 T20 输入"（`app-update.yml`、`dshMandatoryUpdatePolicy`）和"B-F5 记 T3/T14 后续"，在交付说明里没找到。如果本来就由主编排记，可以忽略。

**NOTE-5 改动清点**
- 第二步返修的 DSH 增量：我对"旧补丁链"和"新补丁链"打好后的文件逐个比较，只有 16 个文件有变化，每一处都能对上冻结清单或 1516 令的小项，没有夹带。
- 第三步：产品代码 365 行（新文件 3 个）加配置 21 行，都属于必需实现。`vitest.config.mjs`、检查脚本属于必需验证。
- 没有无关改动。

## 二、冻结清单逐条核对（第二轮综合裁决第 2 节）

| 编号 | 状态 | 证据 |
|---|---|---|
| B-F1 超上限的批次先交导入钩子 | 关闭 | `InputBar.tsx` 先调 `intakeFirst`；新用例覆盖 21 张、单张超大、钩子不接、钩子拒绝四种；变异"跳过 intakeFirst"变红 |
| A-P2-1 用户名打码 | 关闭 | `N41\desktop-tests.txt:170`、`n41-turn.ps1:3` 已是 `<用户>`；T17 证据全目录扫本机用户名和 Key，0 命中 |
| 1516 小项① 两处 openExternal | 关闭 | `platform-view.ts`、`mandatory-update-window.ts` 都不再调；桌面端和 Host 源码里 `openExternal` 为 0 处；两个用例改写后通过 |
| 1516 小项② "@ 打开引用菜单" | 关闭 | 快捷键表里 `fixed.mention` 一行已删；留下一个没人用的文案键 `shortcut.mention`，无害 |
| 1516 小项③ 配置写死权限模式 | 关闭 | `sandbox-policy` 的 `mode: workspace-write`（`workspaceRoot` 与原版一致）、`approval` 的 `policy: ask`；反向检查第 3 项一致；变异"policy 改成 never"被报出 |
| B-F7 侧栏浏览器通道 | 关闭 | `webviewTag: false`；`browserAcquire` 和 `browserRelease` 不注册；变异"重新注册"变红 |
| A-P3-3 / B-F6 协议白名单 | 关闭，但有偏离 | `chrome:`、`chrome-extension:` 已删；`file:` 改为只放行 renderer 目录（见 P2-2，台账要改正） |
| A-P3-4 拼写检查 | 部分关闭 | 只关了主窗口，没用 `setSpellCheckerEnabled`（见 P3-1）；变异"主窗口打开拼写检查"变红 |
| A-P3-1 删拖入守卫 | 关闭 | `drop-guard.ts`、它的测试、`index.tsx` 接线、`intakeActive` 在代码、测试、脚本里 0 处残留；兜底用例 `intake.spec.ts`（两个服务各登记一次）通过。交付说明第 2 节保留了历史叙述，第 6.2 节记了删除 |
| B-F2 Excel 粘贴带位图 | 关闭 | `intake.ts` 在捕获阶段记下粘贴是否带文字，1 秒内带文字的位图不导入；三条用例通过 |
| B-F3 / B-F4 `/api/file` 加固 | 关闭 | 先拒 `\\`、`//` 开头的路径；越界和不存在都回 403；读取改用核对过的规范路径；变异"不拒前缀""读请求里的写法"都变红 |
| B-F9 中文网址重复显示 | 关闭 | 比较前两边都解码后再比 |
| A-P3-2 注释里的字面 `\n` | 关闭 | `render.tsx` 文件头已是真换行 |
| A-P3-5 交付说明两处 | 关闭 | 第 3 节提交号、4.1"要 build"都已改 |
| A-P3-6 私有字段写进核对清单 | 关闭 | PATCHES.md 核对清单已有 `attachments.root` 一行 |
| 补丁重新生成、与工作区一致 | 关闭 | 11 个补丁对 `477b4f4` 按顺序 `git apply --check` 全过；打好后与 `D:\lawbench-A\dsh` 状态相同、62 项逐字节 0 差异；P-3、P-10、P-12、P-13、P-14、P-16 与上一轮逐字节相同 |

## 三、八项检查

| 项 | 结论 |
|---|---|
| 契约一致 | 通过。路由只实现 DSH 基类的 5 个抽象方法，DSH 里用这个服务的地方只调 open、list、stat；存储契约整套对默认根通过（P3-2：没覆盖案件根） |
| 边界输入 | P-9 的 16 种地址写法、P-15 前缀各写法、按 cwd 选实例（子目录、大小写、斜杠）都有覆盖；子目录 cwd 被改报为根（NOTE-2） |
| 错误路径 | 单个案件根失败只跳过、默认根失败照原样报，变异验证过；缓存读写出错不留痕（P3-5） |
| 日志不含正文 | 路由日志只有序号和错误码；刷新失败只记错误名；`/api/file` 不带路径 |
| 路径闸门未被绕过 | P-15 通过；P-9 的 `file:` 只到 renderer 目录，未发现绕过 |
| 无外连 | 构建出的 `session-store.js` 只连 `http://127.0.0.1:${port}/api/case/recent`；桌面端再没有 `openExternal` |
| 测试覆盖新代码 | 基本覆盖；case 实例的 flush、重复编号、契约走案件根三处缺口（P3-2） |
| 无机密入库 | Key 和令牌 0 命中；T17 证据里没有本机用户名 |

## 四、实际跑过的命令

- **补丁链**：从 `D:\lawbench-A\dsh` 克隆一份，检出 `477b4f4`，按 PATCHES.md 顺序对 11 个补丁 `git apply --check` 后再 apply。结果全 OK，状态与 line-A 相同，逐字节比较 0 差异。
- **新旧补丁链对比**：另用 `23cbdd9` 的补丁打一份旧链，与新链比较，列出 16 个变化文件并逐个看了 diff。
- **dsh-ext 测试**：`node scripts\test.mjs`，21 个文件，340 项通过、5 项跳过。
- **dsh-ext 其余检查**：
  - `tsc -p tsconfig.json --noEmit` 退出码 0；
  - `node scripts\build.mjs` 通过，含纯 ESM 导入检查；
  - `check_ui_words.py` 零命中；
  - `check_examples.py --skills skills` 通过。
- **反向检查**：
  - `check_plugin_tree.py … --inventory-overlay` 结论"通过"，与作者存的 `plugin-tree-check.txt` 只差一个 BOM；
  - `mutate_check.py` 全部变异被报出、基线通过。
- **DSH 桌面端相关测试**（P-9、P-14、P-15 等，8 个文件）：203 项通过、1 项跳过。
- **DSH 其余受影响的包**：`ui-conversation`、`ui-primitives`、`ui-chat`、`desktop-host` 全部通过。其余失败都属于环境问题：
  - `session-controller` 的 8 个客户端测试文件载入即失败（`window is not defined`，是测试环境问题，与作者记录的同一类）；
  - `session-persistence-jsonl` 并发跑时有超时，降为 3 个并发重跑后 771 项通过，只剩 1 项因为本机没有建符号链接的权限而失败。
- **变异 18 个**：
  - DSH 侧 7 个全部变红：`file:` 一律放行、`browserAcquire` 重新注册、主窗口打开拼写检查、跳过 `intakeFirst`、不拒前缀、读请求里的写法；
  - 会话存储侧 8 个做在路由和插件入口上，变红 5 个：不换 cwd、案件根失败整体失败、默认值改回允许、新建不问服务，以及一个用于核对的变异；
  - 没变红 3 个：flush 只刷默认根、重复编号不跳过、不查编号表（见 P3-2）。
  - 每次做完都用 sha1 核对原文件已复原。
- **P-9 策略**：用 node 直接调 `lawbenchRequestAllowed` 试了 16 个边缘地址。

## 五、残留审计

- 我没有起桌面端或服务，没有占用 18951–18959 端口，进程表里没有指向我实验目录的进程。
- 我的实验目录 `rv-A20-A2` 已删除；前一名复核员的半成品 `rv-A20-lab` 按吩咐一并删除。删之前先逐个断开目录联接、不跟进联接，删完核对 `D:\lawbench-A\dsh` 状态仍是 62 项、依赖目录完好，`D:\lawbench-A` 只有原有的 ` m dsh` 和 `.tmp-demo/`。
- 没写过 `D:\lawbench*` 和协调目录，没读 `.env.local` 和凭据管理器。

## 六、证据缺口

- 桌面端没有亲自实测：N46 的拒绝弹框、首页和新建草稿时"先打开或新建一个案件"提示会不会出现、侧栏标题现象、全盘搜特征串，这几条都只看了作者的证据。
- 另外还有一个没测过的推测：启动时案件列表读回来之前，输入区可能会短暂闪一下红字提示。
- 被 N46 拒绝的那条消息，文字会不会落到草稿或待发队列里，作者和我都没搜。
- 运行时插件清单沿用作者的导出，没有独立重新导出。
- DSH 测试依赖借的是 `D:\lawbench-A\dsh` 的依赖目录（通过联接只读引用）；`session-controller` 的客户端测试文件载入不了。

AMEND
