# T14 派修 A 侧（T13 `bfd16ad` 首次配置白名单 / 预算到顶显示草稿 / Host 缺失日志；T20 `a2629a9` 品牌字样）· 复核记录（单人，八项清单）

- target：line-A `bfd16ad` + `a2629a9`（父 `c5d704e` = main）；复核克隆 `D:\lawbench-rv\rv-A34`
- 派发：Opus 5.5 只读复核员，2026-10-03 17:0x
- 归档：主编排于 2026-10-03 17:30 (+08:00) 从复核员交回原文抄录，未改内容

## 复核员原文## 复核结论（line-A `bfd16ad` T13 + `a2629a9` T20，父 `c5d704e`）

先说结论：T20 通过。T13 要返修（AMEND），只需补测试。问题出在"草稿是链接就不读"这道闸门：它的测试在这台机器上其实没跑，把闸门整个删掉，测试照样全绿。代码本身我用探针核过，是对的。

一句白话说清三处要求：
1. 首次配置窗口不再空白：只多放行 `lib\welcome\` 这一个目录，`lib\` 其余照拦。
2. 预算到顶时，对话区显示"已用完本次运行的模型调用次数（8/8），结果已保存到成果"，下面按回答样式显示刚存的草稿，出处可以点；成果页能跳回那个对话。
3. 律师看得见的四处中文原版字样改成我方品牌，侧栏显示我方产品名和版本。

身份已核：`D:\lawbench-rv\rv-A34` 的 HEAD 是 `a2629a9`，工作区干净；增量 34 个文件，+1118/−56，与复核包一致。

## findings

**F1 P2：链接闸门的测试在本机空转**
- 问题：`tests/answer.spec.ts:70` 建文件符号链接失败时直接 `return`。这台机器建符号链接报 EPERM，所以这一例实际没测，却算"通过"。
- 影响：交付说明写"链接"已覆盖，其实 `task-answer.ts` 读草稿的两道防线（逐级查链接、核实际位置在案件根里）没有任何测试守着。
- 证据：
  - 只删其中一道：13/13 绿（两道互为备份）。
  - 两道一起删：`answer.spec` 仍 13/13 绿。
  - 同一份改坏的代码，我的联接探针读出了案外文件（`READ OUTSIDE-SECRET`、`READ OUTSIDE-Y`）。
  - 原样代码对两种联接都拒读：草稿目录是联接时 `draft=null`；任务目录是联接时 `TASK_NOT_FOUND`。
- 最小修复：草稿目录、任务目录两种情况改用 `'junction'` 建链接（不需要特权）各加一例；文件符号链接那例改成显式 `it.skipIf`，不要静默 return。只改测试。
- 归类：范围内阻断（路径闸门测试覆盖）。

**F2 P2（推断，未复现）：提示句可能和服务写结果抢先后**
- 问题：`answerNotice` 靠 `result.json` 里的 `status === 'budget_stopped'` 决定第一句。这个状态由 Agent 在 `turn/end` 时异步调 `/core/task/end` 写入，服务还要先算读取覆盖情况才落盘。界面那边是"一轮结束 → turnNotice → 显示 → taskAnswer"，两边没有先后保证，面板也不会重读。
- 影响：如果界面读得早，status 还是 `running`，第一句会变成"本次运行已结束，结果已保存到成果"，不是执行令要的"已用完……（8/8）"。草稿和出处照常显示。
- 证据：
  - `ui/dock.tsx:136`、`ui/answer.tsx`（`answerNotice`、`TaskAnswerPanel` 只读一次）
  - `agent/index.ts:166-174`
  - `service/lawbench/case/task.py` 的 `_end`
  - 探针：result.json 为 running 时，`readTaskAnswer` 原样返回 `running`。
- 最小修复：二选一。由 BUDGET_STOPPED 打开时，第一句按"到顶"处理；或者 status 为 running 时隔几百毫秒重读几次。
- 归类：范围内；是推断，建议主编排在第二次实跑截图里核这句话。

**P3 / NOTE**
- **F3 P3**：提示句的测试只用 8/8，把"已用/上限"写反的变异测不出来（我的变异 F 存活）。实际影响很小。
- **F4 NOTE**：`taskAnswer` 的 root 只要求是绝对路径，`\\主机\共享` 也算，Host 会先去访问 SMB。这和已收的 `archivePlan` 是同一写法，要渲染进程先被攻破才能利用。建议两个方法一起学 P-15 拒绝 `\\`、`//` 开头。归类：独立后续。
- **F5 NOTE**：`check_ui_words.py` 默认扫 `<仓库>\dsh`。没检出子模块的克隆会报 3 条"文件不在"并返回非零，这是作者有意的设计；复核或 CI 要带 `--dsh` 或 `--no-dsh`。
- **F6 NOTE**：全量第一次跑 `supervisor.spec` 挂了 1 例（"15 秒内自动重启"，实际用了 16.2 秒，机器负载高）。单独重跑 11/11 通过，本次改动没碰它。稳定时总数 544 过、5 跳过，与作者一致。
- **F7 NOTE**：`shared/product.ts` 的版本写死 `0.1.0`，与 `service\pyproject.toml` 靠手工同步。作者已标"候主编排定"。
- **F8 NOTE**：`session_store.host_missing` 的 30 秒计时器在插件卸载时不清（已 unref），只可能多记一条日志。

## 三处核对表

| 要求 | 结果 | 依据 |
|---|---|---|
| 1 首次配置白名单（P-9） | 通过 | 见下方"P-9 白名单核对" |
| 2 预算到顶显示草稿 | 实现正确，测试缺口见 F1、F2 | 见下方"预算到顶核对" |
| 3 品牌文案（P-4 + T20） | 通过 | 见下方"品牌文案核对" |
| 4 Host 没起来 | 按执行令做了"记日志、界面提示转独立后续" | `HOST_WAIT_S=30`，日志只有秒数；作者说的实测截图 24 不在本增量里 |

**P-9 白名单核对**
- `lawbenchAppFileRoots` 只返回 `renderer` 和 `lib\welcome` 两个目录；判断方式是"规范化后的路径以 目录+分隔符 开头"。
- 我在开发树和安装后的 `app.asar` 两种布局下各跑了 16 个探针，全部符合预期：
  - 放行：`lib\welcome\welcome.js`、`welcome.css`、`renderer\welcome.html`；
  - 拒绝：`lib\host\x.js`、`lib\main.js`、`lib/welcome/../host/x.js`（原样、`%2e%2e` 编码、`%5c` 编码、反斜杠四种写法）、`lib\welcomeX`、`lib\welcome-evil`、`lib\welcome` 目录本身、`file://evil/share`、四斜杠 UNC、`package.json`。
- 打包配置的 files 含 `lib/welcome/**/*`。`brand-font.css` 引的字体都是 `./*.woff2`，在同一目录里。
- DSH 的 6 例测试全过。变异结果：
  - 放行整个 `lib`：测试和探针都红；
  - 前缀不带分隔符：测试和探针都红；
  - 拿掉 `lib/welcome`：测试和探针都红；
  - 去掉 `resolve`：存活，但这是等价变异，URL 解析已经规范化了 `..`，探针仍 0 错。

**预算到顶核对**
- 草稿来源：Host 只读本任务的 `task.json`、`result.json` 和最新一版草稿，路径只认本任务 `草稿/` 下一层的 `.md`。字段名与 `contracts\files\result.schema.json`、`task.schema.json` 一致，正斜杠写法与服务一致。不写任何文件。
- 出处按钮：`citationInlineMarks` 与 ui-chat 的 `buildInlineMarks` 是同一算法（出处范围本来就有序、不重叠，省掉排序等价），点击走既有的 `citationMark → openCitation → resolveCitation`。
- 没有 innerHTML / dangerouslySetInnerHTML；DSH 的 `MarkdownText` 把按钮画成 React 文本按钮。
- 非到顶的回合：只有码为 `BUDGET_STOPPED` 且带任务编号时才显示，既有用例全过。
- 日志只有 ok、错误码和"有无草稿"。

**品牌文案核对**
- 补丁后 DSH 三个中文词条表零命中；补丁前同样三表命中 6 处，与作者记录一致。
- 线 A 构建产物（16:25 构建的 ui-chat、ui-conversation、locale、ui-sidebar 的 `lib\client.js`）里中英文旧字样都不再出现。唯一剩下的"深度求索"在 `lib\types\client\locale.js` 第 63 行，是保留下来的代码注释，界面看不到。
- 造一个含五个禁词的文件，`check_ui_words.py` 报出 5 处，返回 1。
- 侧栏版本标来自 `dsh-ext\shared\product.ts`（0.1.0），经 `sidebar.brand.name` 插槽整块替换原版的名字和 DSH 构建号；官方品牌插件在我方配置里是 `disabled`，不会抢这个插槽。
- 空标签 `''` 在 DSH 的取词逻辑里不会回退显示成键名，"预览版"标确实不画。

**逐段归类（包括 P-4 +335）**
- **T13 必需实现**：`agent/index.ts`、`host/index.ts`、`host/task-answer.ts`、`shared/turn-notices.ts`、`shared/remote-methods.ts`、`ui/answer.tsx`、`dock.tsx`、`results.tsx`、`state.ts`、`kit.tsx`、`index.tsx` 的 openSession 部分、`dsh-shims.d.ts`、`session-store/index.ts`、P-9 补丁。
- **T13 小重构**：`ui/citation-deps.ts` 是从 `index.tsx` 原样搬出 `citationDeps`，行为不变。
- **T13 必需验证**：`answer.spec`、`agent.spec`、`session-store.spec`、`turn-notices.spec` 等的增量、P-9 新例。
- **重导带来的无关变化**：P-11、P-17 只是 index 行和导入行上下文。我在干净 DSH 克隆上按 PATCHES.md 顺序打完 13 个补丁，得到 114 个改动路径，与线 A 的 `dsh\` 工作区逐字节一致（0 处不同）。
- **P-4 +335**：原有部分只变了一处 `main.ts` 的 index 行。新增 9 个文件段：
  - 三个词条表的文案替换；
  - `EmptyHero.tsx` 空串时不画标（2 行）；
  - 5 个测试和快照的字样跟着改。
  - 没有夹带别的改动。
- **T20 其余**：`product.ts`、`brand.tsx`、`index.tsx` 的品牌插槽那一行、`check_ui_words.py`、两份证据文档。

## 八项清单

| 项 | 结果 |
|---|---|
| 契约一致 | 通过：字段与 files 契约一致，新远程方法登记在方法表，`build.mjs` 的形参名核对通过 |
| 边界输入 | 基本通过：任务编号格式、绝对路径、512 KB 截断、BOM 都有处理；UNC 根见 F4 |
| 错误路径 | 通过：读不到给中文提示且不转会话；`openSession` 出错有 try 兜住 |
| 日志不含正文 | 通过：`task.answer_read` 只有 ok、错误码和有无草稿；`host_missing` 只有秒数 |
| 路径闸门未被绕过 | 代码通过（探针证实），测试不守（F1） |
| 无外连 | 通过：没有新增网络目标；P-9 只多放行一个本地目录 |
| 测试覆盖新代码 | 有缺口：F1、F3 |
| 无机密入库 | 通过：扫增量没有 Key、令牌、外部网址、本机用户名 |

## 跑过的命令（实验都在 `D:\lawbench-rv\rv-A34-x`）
- `git clone --no-hardlinks D:\lawbench-A\dsh` → checkout `477b4f4` → 按顺序对 13 个补丁做 `git apply --check` 再 apply：全过，得到 114 个路径；与线 A 工作区逐文件比哈希：0 处不同。
- `node scripts\test.mjs`（dsh-ext 全量）：第一次 1 例失败（F6），单独重跑 `supervisor.spec` 11/11 通过。
- 相关三个测试文件基线 30/30 通过。
- `tsc -p tsconfig.json --noEmit`：退出码 0。
- `node scripts\build.mjs`：退出码 0。
- `check_ui_words.py --dsh <补丁后>`：零命中；对补丁前三表：命中 6 处；禁词探针：命中 5 处。
- 我自己的变异（作者记录 dsh-ext 8 条 + P-9 1 条全红）：
  - dsh-ext 7 条：A 不记 BUDGET_STOPPED 红；D 草稿路径放宽红；E 输入区不显示红；G 出处按钮点了不核对红；B、C 各自存活（两道防线互为备份），B+C 一起删仍存活 → F1；F 次数写反存活 → F3。
  - P-9 4 条：3 条红，1 条是等价变异。
  - 每次变异后逐字节复原，`git status` 干净。
- 探针：`probe-p9.mts`（32 个判断，0 错）、`probe-answer.mts`（联接和 running 两种情况）。

## 残留审计
- 我建的 331 个目录联接（DSH 各包 316 个、dsh-ext 依赖 12 个、dsh 根和两个依赖联接 3 个）都是逐个按联接删掉的，删之前没有进到联接里面。之后整棵目录扫一遍：联接 0 个，再删除整个实验目录。确认 `D:\lawbench-rv\rv-A34-x` 已不存在。
- 线 A 抽查完好：`D:\lawbench-A\dsh\apps\desktop\node_modules\electron` 仍是联接，vitest、ajv、ui-chat 源码都在。
- 中途一次清理用了 `cmd dir /s`，它会走进联接里，我发现后在列表阶段就按 PID（32276、29952）停掉了，rmdir 一次都没执行。
- 19350–19359 端口没有在监听；没有残留的 rv-A34 进程。我没起任何服务，没动别人的进程。
- 需要说明一处：收尾时我在 `D:\lawbench-A` 跑过一次只读的 `git status`（看到 27 处改动，都是线 A 自己正在做的事），这个命令可能刷新它的 `.git\index` 状态缓存。除此之外，对线 A 只有读文件。

## 证据缺口
- DSH 侧 P-4 改过的四个测试文件（chat-view、skeleton、sidebar-root、sidebar 快照）我没跑：在复核目录里跑需要接线 A 的 node_modules，vitest 可能往线 A 目录写缓存，我放弃了。只做了静态核对：源码和测试一一对应替换。
- 桌面端没有实测：首次配置窗口是否真不空白、到顶时界面实际显示什么（F2）都没看；依赖第二次实跑。
- 交付说明提到的截图 `T14\steps\24-…png` 不在本增量里。

T13: AMEND
T20: PASS

