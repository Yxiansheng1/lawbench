# T17 第二步累计范围 · Reviewer A（改动纪律与可维护性）

- target：`23cbdd94fea498c1deecb0e871e0db219df38085`（line-A）
- 范围：T17 第一步返修 `65946e8` + 第二步源码补丁 `849a670` P-9、`1e0c6ff` P-14、`f529d34` P-15、`4b2b0fa` P-16、`c74b1c0` P-17、`76e4ee1` P-18、`23cbdd9` N41，加用户放行的 `4aaceb4` P-5
- 派发：两名 Opus 5.5 只读复核员同一条消息并发派出，素材相同，互相看不到（前一对因用量上限中断、无结论，本对为重派）
- 复核克隆：scratchpad `rv-A18`；DSH 源码从 `D:\lawbench-A\dsh` 只读克隆钉 `477b4f4` 后按 PATCHES.md 顺序打补丁
- 归档：主编排于 2026-09-30 16:05 (+08:00) 从复核员交回原文抄录，未改内容

## 复核员原文
T17 累计范围复核（Reviewer A：改动纪律与可维护性）

结论：要返修（AMEND），但只有一条阻断，修起来很小。N41 的两份证据里写着本机用户名，违反"证据不写用户名"的规矩，是本轮新引入的。代码本身没有 P0、P1。补丁都能按顺序打上，内容和 PATCHES.md 登记的一致，没有夹带无关改动。第一步冻结的返修项全部关闭，第一步已通过的内容没被后面弄坏。

**要求的行为（一句话）**：在不改 DSH 以外代码的前提下，做到这几件事：
- 桌面端网页层只能连本应用和本机 Host（P-9）；
- 缺了律师工作台组件就不启动（P-14）；
- `/api/file` 只读案件文件夹和附件库（P-15）；
- 对话框里的文件改为导入案件（P-5）；
- 出处做成真按钮（P-16）；
- 回答里的链接一律不打开、只能复制（P-17）；
- 去掉 `@` 占位文字和开发者模式开关（P-18）；
- 按 N41 再成对关 9 行入口；
- 同时关闭第一步冻结的返修项（F2、F3、文档）。

**target 身份**：复核克隆 HEAD 是 `23cbdd94fea498c1deecb0e871e0db219df38085`，工作区干净。范围内的 T17 提交是 `65946e8`、`4aaceb4`（P-5）、`849a670`、`1e0c6ff`、`f529d34`、`4b2b0fa`、`c74b1c0`、`76e4ee1`、`23cbdd9`。

## 一、Findings

**P2-1 N41 证据里有本机用户名**（本次引入，范围内阻断）
- 位置：
  - `docs\plan\evidence\T17\N41\desktop-tests.txt:170` 写着 `"C:\\Users\\<用户>\\AppData\\Local\\Temp\\package-errors-…"`；
  - `docs\plan\evidence\T17\N41\n41-turn.ps1:3` 写着 `$d = 'C:\Users\<用户>\AppData\Local\Temp\claude\D--lawbench-A\…\scratchpad'`。
- 违反的不变量：证据不写本机用户名（brief-common；T13 的 F2 曾按必修处理过同类问题）。同类的 `P-9\desktop-tests.txt:167` 已经打码成 `<用户名>`，说明作者知道这条规矩，N41 这里是漏了。
- 证据：`git grep -n <用户名> 23cbdd9 -- docs/plan/evidence/T17 docs/plan/evidence/T13 dsh-patches dsh-ext` 只命中这两处，另两处命中在历史复核记录里、是描述文字。
- 最小修复：两处换成 `C:\Users\<用户>\…`，单独提交。

**P3-1 P-5 落地后，拖入守卫在产品里已经不会触发，注释也过时了**（此前既有，这次变成死代码；独立后续）
- 产品里 `conversationFileIntake` 总在，`intakeActive` 恒为真。`dsh-ext\ui\drop-guard.ts` 的拖入、粘贴两支（连同 `65946e8` 新补的"文字重新派发"）都不会执行。
- 注释仍写"候 N36"（`drop-guard.ts` 文件头）和"P-5 落地前的过渡做法"（`ui\index.tsx:99` 附近）。
- 删掉它，只有它自己的 10 项测试会变红。
- 第一步裁决拒绝 B-F1 守卫的理由是"要拆掉的代码"，同一个理由现在也适用于这个守卫。
- 最小修复：请主编排二选一：
  - 删掉（`drop-guard.ts`、`tests\drop-guard.spec.ts`、`index.tsx` 一行接线）；
  - 或者留作"P-5 补丁没打上时"的兜底，并改掉过时注释。

**P3-2 P-17 补丁在注释里写进了字面的 `\n`**（本次引入）
- 位置：`packages/client/ui-primitives/src/markdown/render.tsx:7`，内容是 `…protocol allowlist (lawbench\n * P-17: allowlisted links…`，脚本生成时把换行写成了两个字符。
- 最小修复：改成真换行，重新生成 `P-17-links-never-open.patch`。

**P3-3 P-9 放行的协议比执行令多，没写逐项理由**（本次引入）
- 执行令只列了 `dsh-app:`、`data:`、`blob:`、`devtools:`。`lawbench-request-policy.ts` 另外放行了 `file:`、`chrome:`、`chrome-extension:`、`about:`。
- `file://主机/共享` 在 Windows 上会走 SMB，理论上是一条外连途径。主窗口 `webSecurity: true`，从 `dsh-app:` 页面加载 `file:` 子资源会被 Chromium 拦住，所以现实风险低。
- 最小修复：在 PATCHES.md 的 P-9 行写明每个多放的协议谁要用；用不上的删掉。

**P3-4 Spec 里 P-9 的"关拼写检查"没做，也没写明**（此前既有的范围差）
- Spec 3.2 的 P-9 写着"主窗口关闭拼写检查"，工单 T17 第 3 步也写了。
- `apps/desktop/src` 里没有 `setSpellCheckerEnabled`。PATCHES.md 的 P-9 行把"Spec 3.2 P-9"作为依据，读起来像已经整条做完。
- 执行令 1034 只要求了 webRequest，所以不算违令。
- 最小修复：在 PATCHES.md 和交付说明 4.1 加一句"拼写检查未改"及原因，或交主编排定要不要补。

**P3-5 交付说明两处说法过时**（本次引入）
- 第 3 节 B-F1 行写"P-5 已于 `7bf8f89` 落地"。`7bf8f89` 是 rebase 前的 SHA，不是 HEAD 的祖先；与 `4aaceb4` 的 patch-id 相同，应改成 `4aaceb4`。
- 第 4.1 节"注意"一行写"改了主进程要重新 bundle"，和 PATCHES.md 已改正的"要 build（先 `tsc -b`）"对不上。P-9 当时实际跑的是 `tsc -b` 加 bundle，证据成立，只是说法要改。

**P3-6 P-15 依赖本机附件存储实现里的 `root` 字段，改名时会悄悄失效**（本次引入，独立后续）
- `media-references.ts` 用 `(ctx.attachments as unknown as { root?: unknown }).root` 取附件库根目录。这个字段在 `attachment-local/src/index.ts:163` 的实现类上，不在服务接口里。
- 测试用的是假的 `root`。换 DSH 提交后如果这个字段没了，附件库里的图片会一律 403，不报错，也没有测试会变红。
- 最小修复：把它加进 PATCHES.md 的"换 DSH 提交时的核对清单"；或者补一例用真实附件插件取 `root` 的测试。

**P3-7 出处按钮的"登记"这一行没有测试守着**（本次引入，独立后续）
- 在副本上删掉 `ui\index.tsx` 的 `ctx.inject(['chatInlineMarks'], registerCitationMarks)`，dsh-ext 全部 225 项仍然通过，只有桌面端实测能发现。
- 纯函数 `citationMark`、`citationItemRanges` 有测试：我把〔推断〕判断去掉后变红。
- 最小修复：可选，补一个 jsdom 用例断言 apply 后登记了一次。

**NOTE-1 P-16 不再认"出处被加粗切成两半"**：作者在交付说明 4.4 里摘了原文、交主编排定，处理方式正确。和 T13 已接受的"跨加粗可认"相比是行为倒退，请主编排裁。

**NOTE-2 两处防御判断在别处已被兜住，删掉也不变红**：
- P-9 的 `if (hostUrl === undefined) return false`：删掉后 `new URL(undefined)` 抛错，照样返回 false，3 项全过。把它改成 `return true` 则 2 项变红，说明"Host 地址未知一律不放"的行为有测试守着。
- P-16 在 `render.tsx` 里的 `context.streaming` 判断：删掉后测试全过，因为流式时 `MarkdownText` 本来就不传 `inlineMarks`。
- 两处都不掩盖错误，可以留。

**NOTE-3 P-16 的写法和执行令说的"仿 `chatFileMentions`"不同**：`inline-marks.ts` 用的是模块级全局登记表加 `useSyncExternalStore`，不是按上下文注入。另有"多种标记重叠时先登记的优先"的通用逻辑，比现在只有一种标记的需要多约 10 行。99 行里多是注释，可以接受。

**NOTE-4 覆盖率**：DSH 自己的 CI 对每个文件要求 100% 覆盖率。实测 `inline-marks.ts` 分支 90%，`lawbench-request-policy.ts` 语句 93%。只有跑 DSH 自己的覆盖率流水线时才会报。

**NOTE-5 Spec 3.2 要主编排回写**：main 和 target 上的 Spec 3.2 都还没有 P-14 到 P-18 这几行。P-5 的位置还写着 `input/editor/apply.ts`，实际是 `src/client/apply.ts`。

**NOTE-6 执行令里的一处误读，作者纠正对了**：执行令 1034 说 `onBeforeSendHeaders` 要"并进来"。它和 `onBeforeRequest` 是两种事件，各挂一个互不冲突，作者分开挂并在 PATCHES.md 写明了。

**NOTE-7 P-15 的两处小风险，属 Reviewer B 的边缘情况范围**：
- 先做路径核对、再读文件，中间有极短的时间窗；
- 不存在的文件回 404、存在但越界的回 403，能借此探出某个路径是否存在。
- 请求方只有已鉴权的界面，结果到不了模型，风险可以忽略。

## 二、冻结清单逐条核对

| 编号 | 状态 | 依据 |
|---|---|---|
| B-F2（文字加文件的粘贴只拦文件） | 关闭 | 新用例在；我把 `target.dispatchEvent(textOnly)` 去掉后变红（1 failed） |
| B-F3 / A-P3-2（粘贴时 P-5 让路） | 关闭 | 我把 onPaste 里的 `\|\| deps.intakeActive()` 去掉后变红（1 failed） |
| B-F1（不加守卫，写进交付说明） | 关闭 | 交付说明第 3 节有；SHA 过时见 P3-5 |
| A-P3-1、A-P3-4、B-F7（第 1 节过时说法） | 关闭 | 第 1 节 21/22 行、70/71 行、17 个文件、超时措辞都已加注改正 |
| A-P3-3（名单只写一份） | 关闭 | `T17_STEP1` 只写一份，并入 `MUST_OFF` 并有条数守卫；N41 同样写法（`T17_N41`，守卫 9） |
| A-P3-6（过时注释） | 关闭 | "48 行"已改 |
| A-P3-5、A-P3-7（落点记录、请求命令） | 关闭 | `drop-points.txt` 在；`api-probe-product.txt` 补了命令 |
| B-F5（workspace-changes） | 关闭 | N41 已关 |
| `/export` 回车 | 关闭 | 截图 12，写入交付说明第 3 节 |
| 第一步已通过的内容 | 未被破坏 | 1c 节只改了一行注释；我重跑反向检查，输出与作者提交的 `plugin-tree-check.txt` 逐字一致（80 行必须关、101 个启用行、0 个启用但没激活、2d 两批都写着 disabled）；变异 22 例全部符合 |

## 三、逐文件归类

- **必需实现**：
  - 7 个补丁文件，改动文件与 PATCHES.md 登记的一一对应；
  - `dsh-ext\ui\drop-guard.ts`、`citation.ts`、`index.tsx`；
  - 删除 `citation-click.ts`（执行令要求撤掉）；
  - `cordis.patch.yml`：N41 的 9 行，加一行注释更新。
- **必需验证**：
  - 各补丁目录下的证据；
  - `check_plugin_tree.py`、`mutate_check.py`；
  - `dev\fake-service.mjs --llm-reply`（假模型网关只监听 127.0.0.1，交付说明第 4 节已披露）；
  - 各测试文件和 DOM 固定样例。12 个样例里 6 组的定稿版和流式版改动逐行相同，都只是 `<a>` 和图标换成了文字。
- **无关：0 个。**
  - P-5 删掉的 `onToggleCommandMenu`、P-17 删掉的 `shell` 导入、P-18 删掉的 import，都是因为改动后没人用了，属必需。
- **9 行关得对**：
  - 这 9 行都能在 DSH 原版的 base / web-app 补丁里找到；
  - 我方补丁里写 `disabled: true`、被关掉的行和"必须关"名单一一对应，两边都没有多出来的；
  - 补丁里没有重复的行 id；
  - Host 行和界面行按执行令成对：`permission` + `ui-permission`；`goal`、`goal-round-driver`、`agent-preset-registry` 按令保留。
- **新增文件是否必要**：
  - `lawbench-request-policy.ts`（27 行）：删了单测失败；工单第 4 步要求白名单写成可复用函数给 T26 用。
  - `lawbench-bundle-guard.ts`（25 行）：删了单测失败。
  - `inline-marks.ts`：删了 P-16 两个包的新测试失败。
  - 三者都成比例。

## 四、八项清单

- **契约一致**：未改 `contracts\`；出处正则仍由 `citation.spec` 守着和契约逐字一致（通过）。
- **边界输入**：
  - P-9：Host 地址未知时、别的端口、`https` 到 Host、`localhost` 别名、带账号密码的地址都拒绝，有测试；
  - P-15：`..`、目录联接、前缀但不是整段、Windows 大小写都有测试；
  - P-16：〔推断〕、链接文字、流式时都不成按钮。
- **错误路径**：
  - P-14 抛中文错误，经 `main().catch` 发 `fatal` 给主进程，截图可见中文正文；
  - P-15 越界回 403，正文是 `outside the allowed folders`，不带路径（测试断言正文里没有那个路径）；不存在回 404。
- **日志不含正文**：新代码不打日志。
- **路径闸门未被绕过**：P-15 收紧了 `/api/file`，我方界面读写案件仍经工作台服务。
- **无外连**：
  - 我全程只在本机跑测试，没起任何服务；
  - 假网关只听 127.0.0.1；
  - 未决事项已上交主编排：主进程另两处 `openExternal`、`DSH_PERMISSION_MODE` 要不要锁死。
- **测试覆盖新代码**：
  - 抽测 13 个变异（P-9、P-14、P-15、P-16、P-17、drop-guard、citation），逐个复现作者说的红测，都变红；
  - 另有 3 个删掉后测试仍全绿：两个是 NOTE-2 说的已被兜住的判断，一个是 P3-7 说的出处按钮登记行。
- **无机密入库**：没有 Key 或令牌；用户名见 P2-1。

## 五、实际跑过的命令

- 复核克隆：`git rev-parse HEAD`；`git status`；`git show` 各提交；`git grep <用户名>`；`git patch-id`（`7bf8f89` 对 `4aaceb4`）。
- 实验副本（我自己的目录，取自 target 的完整导出）：
  - DSH 从 `D:\lawbench-A\dsh` 只读克隆，detach 到 `477b4f4`，按 PATCHES.md 的顺序逐个 `git apply --check` 再 `apply`：**11 个全部通过**；
  - 打好补丁后涉及的文件，与 `D:\lawbench-A\dsh` 工作区逐字节比对 0 处差异。
- dsh-ext：
  - `node scripts\test.mjs` → 16 个文件 225 项通过、5 项跳过（跳过的是 `credman` 真实凭据管理器的用例）；
  - `tsc -p tsconfig.json --noEmit` → 0；
  - `node scripts\build.mjs` → 0，纯 ESM 导入检查通过。
- 仓库检查：
  - `check_ui_words.py` → 零命中；
  - `contracts\check_examples.py --skills skills` → 0；
  - `check_plugin_tree.py --inventory-overlay` → 0，输出与作者提交的逐字一致；
  - `mutate_check.py` → 22 例全部符合。
- DSH（vitest 加 `--no-cache`）：
  - desktop 两个文件、desktop-host 的 bundle-guard、media-references → 4 个文件 135 项通过、1 项跳过（FIFO）；
  - `ui-primitives` 加 `ui-chat` → 104 个文件 1917 项通过；
  - `ui-conversation` 加 `ui-settings-general` → 45 个文件 586 项通过，2 个文件载入失败（环境问题，同作者）。
- 变异结果：
  - M1（Host 地址未知时放行）：2 项红；
  - M2（去掉账号密码检查）：1 项红；
  - M3（去掉"有组合包被跳过"的判断）：1 项红；
  - M4（去掉 realpath）：1 项红；
  - M6（显示文字等于网址时也补网址）：9 项红；
  - drop-guard D1、D2：各 1 项红；
  - citation 去掉〔推断〕判断：1 项红；
  - 删掉后仍全绿的 3 个：M1b（删掉 Host 地址未知那一行）、M5（去掉流式判断）、删掉出处按钮登记行。
  - 所有被改的文件都已逐字节复原并核对。
- 覆盖率只量了新文件，见 NOTE-4。

## 六、残留审计

- 没起任何服务或桌面端，127.0.0.1 上 18871–18879 没有监听。
- 实验目录已删：先按个拆掉 336 个目录联接，只拆联接不删目标，再删目录。
- 上一名复核员的半成品 `rv-A18-lab` 同样先拆联接再删。
- 复核克隆里我临时 fetch 的 `refs/rv/main` 已删掉，克隆仍在 `23cbdd9`、工作区干净。
- `D:\lawbench-A\dsh` 里，排除线 A 自己开发机的 `.desktop-build`，我开工以来没有任何新写入。
- 没动别人的进程。

## 七、证据缺口

- DSH 各包的 tsc 我没能独立验证：我的克隆里没有构建过的依赖类型，只报环境错误。沿用作者"`tsc -b apps/desktop` 通过"的说法；vitest 能载入和转译补丁代码。
- `ui-settings-general` 的 `apply`、`shell` 两个测试文件载入即失败（我这边的报错是 `client/modules manifest … reading 'load'`，和作者报的不同，都是环境问题）。所以 P-18 改的"通用设置只剩版本号一行"的断言没人跑到过，只有作者的桌面截图。
- 桌面端实测没复现（不是必需）。N41 前后对照、P-9 和 P-17 探针 0 次、P-14 弹框，都以作者证据为准。32 张截图我看了 3 张，没看到用户名。
- 没跑 DSH 自己的全量测试和覆盖率流水线。

## 返修清单（最小）

1. P2-1 两处用户名打码。
2. 顺手做（不阻断）：
   - P3-2 改真换行并重新生成补丁；
   - P3-5 SHA 和 build 说法改正；
   - P3-3 P-9 多放的协议写理由或删掉；
   - P3-4 写明拼写检查没改。
3. 交主编排定：P3-1（拖入守卫删还是留）、NOTE-1（跨加粗）、NOTE-5（Spec 回写）。

AMEND
