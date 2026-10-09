# T13 新建案件子文件夹可选 + 案件 wiki 合卡 · 独立复核记录（PASS）

- 复核时刻：2026-10-09 11:50–12:30 (+08:00)；复核员：一名 Opus 只读复核员（克隆 `D:\lawbench-rv\rv-A54`，实验目录 `rv-A54-exp`）
- target：line-A `1e2a0ad`；基座 `b0d29bf`；23 文件 +1032/-39
- 裁决（主编排）：**PASS**，cherry-pick 进 main。NOTE-1 契约绕行记 1.4 候项 12；NOTE-2 模板名含 `/` 已令线 B 改（服务、契约 formats.md 1.1、`shared\case-folders.ts`、用例；`engines\retainer\data\config.json` 为数据项同步改并记 engines CHANGELOG）；P3 竞态同 gate.py 结构，单用户可接受。
- 复核员越界记录：vitest 结果缓存经联接写进 `D:\lawbench-A\dsh-ext\node_modules\.vite\vitest\…\results.json`（仅测试缓存，无损）；下次复核令写明 cacheDir 指克隆内。

## 复核员报告（原文，路径已去用户名）

**Verdict：PASS。**

### Host `caseFolders` 安全面
`knownCase(case_id, root)` 按服务登记核对；`chosenFolders` 双核：种类只认 civil/criminal、勾选项须在该类标准目录内、自填名过 `customFolderProblem`（拒 `/`、`\`、`:` 等非法字符、空名、首尾空格点、设备名、>80 字、`工作区`/`成果`）、最多 20 项；渲染层传不进任意路径段。与 `gate.py mkdir_original` 等价：路上任一级链接/联接/同名文件整条跳过；已有目录不动不覆盖；每建一级前核上级实际位置仍在案件根；`RESERVED_TOPS` 挡 `工作区/`、`成果/`。逃逸实验 `rv-A54-exp\t.ts`（真目录 + 联接）：`03一审` 为指向 `outside\` 的联接 → 全部 false、`outside\` 仍空；`01委托手续` 同名文件 → false；`05执行` 与 3 个二级正常建；`../x`、`a/b`、`a\b`、`C:x`、`工作区`、`成果`、`.. `、`CON`、81 字、tops `../evil` 全 INVALID_ARGUMENT；`mkdirInCase(root,'工作区/../../outside2')` false。日志只记 asked/created 计数。

### 弹框
默认全不勾；全选/全不选；自填非法名当场拒（截图 02）；日常事务与打开已有案件 template null 不弹；取消 = 整件取消不登记案件（`askFolders` 返回 null 时 `openCase` 在 `caseOpen` 前返回），确认按钮"新建案件（不建子文件夹）"为"建案件不建子目录"，表述合理；云同步被拒改本机后沿用已勾名单不再问。

### Host `caseWiki`
只读固定路径经 `readInCase`（链接拒、实际位置在根内、大小上限）：`工作区/wiki/case.json`、`工作区/wiki/案件/` 五篇 md、`工作区/材料/index.json`；回渲染层只有正文、parties/issues/key_facts、计数、指纹、相对 rel，无绝对路径，`materials_at_generation` 不外传；出处打开"原文查看"；打开文件/文件夹经 openCaseFile/openFolder 限根内；"核对完成"记 localStorage `lawbench.wikiChecked.<case_id>`；指纹 sha256(生成时间 + 按 material_id 排序的 id:sha 列表)，顺序变化不误判，新增/变化/移除/重生成都重显待复核，律师改文章不触发（设计）。

### 偏离
合卡放材料页顶部（"生成/更新 wiki"按钮区）合理；案件卡片只列当事人/争议焦点/关键事实及出处，不含路径（截图 05）。

### 模板名 `08执行（财产刑/民事赔偿）`
服务 `registry.py:60`、`engines\retainer\data\config.json`、`generate.py:1053`、`contracts\formats.md` 1.1 同名，均建成两级；Host 按 `/` 切开逐级核对无安全问题；`folders_created` 只报一条、弹框显示一项实际两级；T3 review-B N1 早已记。改名须服务、引擎、契约、`shared\case-folders.ts`、`case-folders.spec.ts:116` 一起改，引擎改动走主编排并记 CHANGELOG。

### Findings
NOTE-1 契约绕行（template=null + Host 补建），候 1.4；NOTE-2 模板名；P3（臆测）`mkdirInCase` lstat→realpath→mkdir 竞态窗口，与 gate.py 同结构，单用户可接受。

### 测试与检查
dsh-ext vitest 709/1/6（brand.spec 环境缺件，计入即 710 与自报一致）；tsc 0；`check_ui_words` 零命中；截图 01–06 无用户名。

### 越界
vitest 结果缓存经联接写进 A 的 `dsh-ext\node_modules\.vite\vitest\…\results.json`（12:28:57）；仅缓存，顶层无变化。

### 跑过的命令
`git rev-parse/diff --stat/diff b0d29bf 1e2a0ad`；五个 `mklink /J`（三只读借用 + 实验联接）；`node --experimental-strip-types rv-A54-exp\t.ts`；`node scripts/test.mjs`；`tsc --noEmit`；`check_ui_words.py`；联接已全部 `rmdir`。
