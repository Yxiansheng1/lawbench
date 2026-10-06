# T13/T20 律师反馈第一批 · 独立复核记录（AMEND）

- 复核时刻：2026-10-06 21:30–22:05 (+08:00)；复核员：一名 Opus 只读复核员（克隆 `D:\lawbench-rv\rv-A47`，实验目录 `rv-A47-exp`）
- target：line-A `b61a69b`、`60eb0c2`、`8e2410e`、`23f5573`；基座 main `3b8e755`；27 文件 +783/-84
- 裁决（主编排）：**AMEND**。P1（补丁链 CRLF 断链）+ 三条 P2 必修；P3 三条与估算份数上限一起做；令 `致A-ORCH-执行令-律师反馈第一批复核AMEND-<HHMM>.md`。

## 复核员报告（原文，路径已去用户名）

**Verdict：AMEND。** 一个 P1：补丁链断了（线 A 自报 154/0 不成立）；其余 P2/P3 属安全加固与小缺陷。

### 1. 目标与 hunk 归类
HEAD `23f5573`，`3b8e755..HEAD` 正好 4 提交，27 文件 +783/-84。必需实现：Host `desk-actions.ts`、`desk-node.ts`、`index.ts`（4 新方法、`desk` 注入、`dailyCase` 改 userProfile）、`remote-methods.ts`、`daily-case.ts`；UI `cases.ts`（offerLocalFolder）、`dock.tsx`（confirmScope）、`estimate.ts`、`folder-actions.ts`、`home-page.tsx`（ToolsRow）、`materials.tsx`、`results.tsx`；P-4（installer.nsh、strings.nsh、directory-picker.ts、isolation 加 `LAWBENCH_PACKAGED`）；PRD/Spec md+html 各一句。必需验证：4 spec、PATCHES.md、交付说明、4 截图。无关：P-4 里 `lawbench-isolation.ts` 整节换成 CRLF（P1）。

### 2. Findings
**P1 · 引入的回归：补丁链在 P-22 断开**：新 P-4 把 `apps/desktop/src/lawbench-isolation.ts` 整节 50 行写成 CRLF（blob 50 个 `\r`，基座 0），P-22 上下文是 LF → `git apply` 失败 `patch failed: apps/desktop/src/lawbench-isolation.ts:8`。影响：干净 dsh 按 PATCHES.md 重建断在 P-22（T28 Mac 打包依赖此链）；"154/0"只有 `--ignore-whitespace` 才成立且文件变混合行尾。证据：基座 17 补丁 153/0；HEAD `FAIL P-22-macos` 152；`git ls-files --eol` `i/mixed dsh-patches/P-4-brand.patch`；blob 1560–1609 行 `\r`。修复：重生成该节为 LF，不加 `--ignore-whitespace` 重跑整条链 154/0。

**P2 · 安全面：`openFolder` 不核对案件根**：`root` 直接取自渲染层；`rel===''` 时跳过 `plainAbsolute` → 可开任意目录；UNC 根 + `rel:''` 时 `statSync` 先发起 SMB 外连；子文件夹为联接时 `insideCase` 不 realpath，可开到案件外（实验 `rel:'jn'` → real=`…\fs\outside`）。修复：照 `materialRemove` 用 `caseRecent` 核对并改用 `known.root`；`rel===''` 也走 `plainAbsolute`；打开前 realpath 核仍在根内。

**P2 · `materialRemove` 只禁用按钮，Host 方法仍可调**：`MATERIAL_REMOVE_ENABLED=false` 只控 `disabled`；方法仍在 `REMOTE_METHODS`，调用即 `rm` 永久删（不进回收站）并重扫。核心校验到位（case_id/root 对服务登记、lstat 普通文件、realpath 在根内；联接、`..`、目录均拒）。修复：开关打开前从 `REMOTE_METHODS` 拿掉，或 Host 直接返回 `NOT_AVAILABLE`。

**P2 · 流程回归：案件名含同步关键字时"本机建文件夹"反复建空文件夹**：SEC-14 按任一级目录名子串匹配；案件名如"Dropbox公司诉某某案"→ 本机新建仍被拒 → `offerLocalFolder → openCase → offerLocalFolder` 递归，每确认一次多一个 `(n)` 空目录，文案也不对。修复：第二次被拒只提示不再 offer（递归标志），或建本机文件夹时替换名字里的同步关键字。

**P3 · `safeFolderName`**：先 trim 再 `slice(0,80)` 截断后可能尾随空格/点（Windows 建目录会去掉，与返回路径不一致）；`con.txt` 类带扩展名保留名未拦。修复：先 slice 再 trim；保留名正则 `^(con|…)(\..*)?$`。
**P3 · `toolExe` 用 `name in TOOLS`**：原型名可过（`toString`、`__proto__`），因 exists 检查不过而失败，不可利用。修复 `Object.hasOwn`。
**P3 · 卸载可能留开始菜单项**：按卸载时语言删 `$(LAWBENCH_TOOL_*)`，安装/卸载语言不同时留 .lnk。

**NOTE 1 · 估算常量**：`READ_BUDGET_PAGES` 一处；代码无"份数上限"，要"100 页或 11 份先到"须加 `READ_BUDGET_FILES`、`estimateCoverage` 的 `fit` 到上限即停、`over = pages > budget || total > files`。可"仍然开始"、有 `ESTIMATE_OFF`、不改契约、无平台分支。
**NOTE 2 · 核过无问题**：`openTool` 只认两个名、路径拼自 installDir、渲染层传不进路径/参数、Mac 返回 null、开发期 `NOT_AVAILABLE`；`localCaseFolder` 取 `USERPROFILE ?? homedir()`、`..` 变"新案件"、同名 `(n)`；日常事务已建过的靠 marker 与 `office.dir` 不动；选目录对话框只在装好的包且文件夹已存在时用默认位置；4 新方法在 `REMOTE_METHODS` 不在 `API_ROUTES`，表测试覆盖；日志只记 tool/kind；PRD/Spec 各一句，`build_docs` 重跑哈希一致；截图无用户名。

### 3. 检查
dsh-ext vitest 655 通过 / 1 失败（brand.spec 环境）/ 6 跳过，与自报 656/6 一致；tsc 0；`check_ui_words` 零命中；补丁链 HEAD 152（P-22 失败）、基座 153/0。

### 4. 跑过的命令（摘要）
`git rev-parse/log/diff --stat`；`git clone --no-checkout --shared D:\lawbench-A\dsh rv-A47-exp\{dsh,dsh-base,dsh-head}` + read-tree + 按序 apply --cached（基座/HEAD 各一遍，`--ignore-whitespace` 复试定位 CR）；`node --experimental-strip-types rv-A47-exp\exp.mts`（insideCase/removableMaterial/safeFolderName/toolExe 路径逃逸实验，含临时 junction 已删）；`rv-A47-exp\docsbuild` 跑 `build_docs.py` 比对哈希；robocopy node_modules + 12 联接；借用联接跑 `node scripts/test.mjs`、`tsc --noEmit`、`check_ui_words.py`；借用联接已拆，克隆 `git status` 干净。约 35 分钟。
