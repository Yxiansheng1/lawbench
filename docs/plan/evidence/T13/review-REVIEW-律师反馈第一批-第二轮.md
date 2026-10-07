# T13/T20 律师反馈第一批 AMEND 关闭 · 独立复核记录（第二轮，PASS）

- 复核时刻：2026-10-07 09:06–09:31 (+08:00)；复核员：一名 Opus 只读复核员（克隆 `D:\lawbench-rv\rv-A48`，实验目录 `rv-A48-exp`）
- target：line-A `ae8fe02`（T13 AMEND 修法 + 估算阈值）、`7f3c777`（T20 P-4 LF 重生成、卸载快捷方式）；累计 main `3b8e755..7f3c777` 6 提交 30 文件 +900/-36
- 裁决（主编排）：**PASS**，line-A 整条合并进 main。P3/NOTE 四条记下轮小修（随第五版前 T20 小修一批，令 0905 顺带）。

## 复核员报告（原文，路径已去用户名）

**结论：PASS。** 上一轮冻结清单 P1、P2×3、P3×3、估算 NOTE 全部关闭；本轮无新阻断或回归，剩 4 条 P3/NOTE。

### 冻结清单逐条关闭
- **P1 补丁链 CRLF：关闭。** `rv-A48-exp\dsh` 共享克隆，基座 `477b4f4205…`，`read-tree`，`core.autocrlf=false`，按 PATCHES.md 顺序不带任何空白选项 `git apply --cached` 17 个：ok=17 fail=0 零警告；`--shortstat` 154 files；17 个补丁 blob `\r` 全 0；`.gitattributes` 含 `*.patch -text`，`check-attr text` = unset。
- **P2 openFolder：关闭。** `knownCase` 用 case_id 查 caseRecent 并比对根（忽略大小写、尾随分隔符）后只用登记根；`openableFolder` 走真文件系统：`plainAbsolute → insideCase → realpath 仍在根内 → 须为文件夹`。`rv-A48-exp\of-exp.mts` 直接 import 产品 `desk-actions.ts`、给 realFn/isDir 计数、真联接：UNC 四种写法全 INVALID_ARGUMENT 且 0 次文件系统访问；`..`、绝对 rel 拒且 0 次；联接指向根外/同前缀兄弟 `Case-evil` 拒；联接回根本身放行；全大写根放行；尾随点/空格、`C:x`、`::$DATA` → NOT_FOUND。未登记根与 case_id 不符由 spec 覆盖（真 mkdtemp、真 junction）。服务 `recent()` 无条数上限。
- **P2 materialRemove：关闭。** 第一行判 `!MATERIAL_REMOVE_ENABLED` 回 NOT_AVAILABLE；spec 断言开关 false、返回码、`calls` 为空。
- **P2 递归：关闭。** 名字含同步词直接说明不提议；本机建好仍被拒走 `openCaseNoOffer` 只说明；spec 断言 `made` 为空 / 只一条、confirm 只 1 个。UI `SYNC_NAME_WORDS` 与服务 `gate.py SYNC_NAME_MARKERS` 九项相同。
- **估算 NOTE：关闭。** `READ_BUDGET_PAGES=100`、`READ_BUDGET_FILES=11` 先到者触发；`fit >= maxFiles` 封顶 11；文案含"按案件全部材料估"。变异（去 `|| sizes.length > maxFiles`、去 `fit >= maxFiles ||`）estimate.spec 各失败 1 例，已还原。
- **P3 三条：关闭。** `toolExe` 对 toString/`__proto__`/constructor/hasOwnProperty 全 ok=false；`safeFolderName` 先截再去首尾空格与点，`con.txt`/`aux.tar.gz`/`COM1 ` → "新案件"；卸载按中英文名各删 2 个 .lnk，`!define` 在 strings.nsh 经 `customHeader` 引入先于卸载段展开，test-windows-installer 语言过滤保留 `!define`（本地未跑 makensis，线 A 自报编译通过）。

### 回归检查
openFolder 界面唯一调用处 `ui\folder-actions.ts` 两次 call 均带 `case_id`，feedback-buttons 断言；`shared/feature-flags.ts` 无 import，UI 从 `../shared/` 引用为既有写法，不带 Node 依赖进渲染层；NSIS `Delete "$SMPROGRAMS\${…}.lnk"` 语法正确。

### 测试
dsh-ext tsc exit 0；vitest 52 files 659 passed / 6 skipped（与自报一致，supervisor.spec 本次无偶发）；`check_ui_words` 零命中。

### Findings（不阻断）
1. **P3 臆测**：界面 `CaseRef.root` 为律师选的原始路径，服务登记的是 realpath；上级为联接、subst 盘、映射盘（Python realpath 转 UNC）时对不上，"打开所在文件夹"报"请求参数有误"（安全方向）。修复：caseOpen 返回登记根供界面用，或 knownCase 比对前 realpath。
2. **P3 独立后续**：`safeFolderName` 保留名比服务 `DEVICE_NAMES` 窄（`com0/lpt0`、`com¹²³`、`conin$/conout$`；`CON .txt` 漏）。修复：对齐服务列表，比对前去扩展名前空格。
3. **NOTE**：`noOffer` 为模块级全局，并发 openCase 可能被吞提议。修复：参数传递。
4. **NOTE 证据**：开关为 true 的正向用例被删，将来开开关要补回；严格核对脚本未入库（复核员独立复现 154/0）。

### 跑过的命令（摘要）
`git log/diff --stat 3b8e755..7f3c777`、`git diff 7f3c777~2 7f3c777`；共享克隆 + `log -1`（只读）+ `autocrlf false` + `read-tree` + 17 次 `apply --cached` + `--shortstat`；`ls-tree`/`cat-file` 统计 CR；`check-attr`；`node rv-A48-exp\of-exp.mts`；robocopy node_modules `/E /SJ /SL` + `rv-A48\dsh` 联接；`tsc --noEmit`；`node scripts\test.mjs`；estimate.spec 两次变异；`check_ui_words.py`。借用全部拆除并核线 A 目录完好。约 25 分钟。
