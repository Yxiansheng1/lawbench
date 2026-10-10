# T13 左栏移除案件后首页/下拉/弹框同步（第七版待办 23，本机记录过渡）· 独立复核记录（PASS）

- 复核时刻：2026-10-10 21:46–22:08 (+08:00)；复核员：一名 Opus 只读复核员（克隆 `D:\lawbench-rv\rv-A60`，实验目录 `rv-A60-exp`）
- target：line-A `1341afc`；基座 main `0784d29`；16 文件 +479/-10（新 `host\hidden-cases.ts`、`ui\hidden-cases.ts`、`tests\hidden-cases.spec.ts` 16 项）
- 裁决（主编排）：**PASS**，cherry-pick 进 main，发重打第七版令（第六次）。P3-1（弹框过滤无用例）记第八版小项；NOTE 1–3 不改。契约 1.4 `case_forget`（候项 17）落地后替换本机记录。

## 复核员报告（原文摘要，路径已去用户名）

**Verdict：PASS。**

### 误隐藏风险：未找到可触发路径
- "读全了"判据 `watchRemovedCases` 只认 `state === 'idle'|undefined`；DSH `ClientWorkspaceModel` 初始 `loading`，只有 `replaceBaseline`（整份基线一次装入，`model.ts:271`）置 `idle`；断线 `handleCarrierFailure` 进 `loading` 保留旧表；不可重试失败进 `error`。不认的列表既不比也不当基准。基线完整不分页；`ctx.workspaces.list` 即该 model 带 `state`。
- 实验 `rv-A60-exp\model.spec.ts`（DSH 真 model 副本换 3 个桩）："加载中先插一项→基线→断线→基线→出错→基线"均不误记；移除"日常事务"不记；真移除才记；2 passed。
- 会删左栏项的地方：DSH `WorkspaceBrowser.tsx:1198`（律师点"移除"）；dsh-ext `forgetIfGone`（删前登记"程序自己撤的"，`index.tsx:168`）；Host `create` 同位置直接返回不先删后建。
- 1612 P3 否掉的"登记 vs 左栏"推断未回来：只比左栏前后两次。同位置不同写法（大小写、斜杠、尾反斜杠）按同一位置。

### Findings
- **P3-1 "先选择案件"弹框过滤无用例守**（独立后续）：变异 M4 `dialogs.tsx` `visibleCases`→`all` 仍 16 passed。修：加一例渲染 `CasePickDialog` 断言已移除不出现。
- **NOTE-1**（臆测）联接别名：左栏同案两项时移除其一，界面 `samePath` 字面比报给 Host，Host `sameFolder` realpath 对上登记即记隐藏，左栏剩一项而首页/下拉不列；再打开即恢复。
- **NOTE-2**（独立后续）`writeFileSync` 非原子，断电损坏按空处理，只往"多列"方向坏。
- **NOTE-3**（臆测）服务未起时 `caseHide` 读不到登记则本次漏记，不误藏。

### 其余核对
`caseHide` 按登记找 id、未登记忽略；`case_open` 成功后清记录（`host\index.ts:721`，按 id 或同位置）；拖入/左栏添加/"打开案件…"/日常事务均经 `cases.ts:95 caseOpen`；记录损坏按空；Host 读改写同步段不交错；日志仅 `case.hide {hidden,total}`、`case.unhide {dropped}`；"日常事务"只在位置等于 `dailyRoot` 时跳过；替换点注释齐。变异 M1（去过滤）2 红、M2（判据恒真）"断开重连"例红、M3（去"同位置仍有项"）1 红。dsh-ext 759/1/6（brand.spec 环境缺 `dsh\apps`，计入即 760/0/6）；tsc 0；check_ui_words 产品零命中；4 截图无用户名（无弹框截图，与 P3-1 同源）。

### 跑过的命令
`git diff 0784d29 1341afc`；三只读联接；vitest 全量/单跑/M1–M4（克隆内改后 `git checkout --` 还原）；`model.spec.ts` 实验；tsc；check_ui_words。联接已 rmdir，A 目录 `.vite`/`.vite-temp` 时间戳不变，克隆干净。
