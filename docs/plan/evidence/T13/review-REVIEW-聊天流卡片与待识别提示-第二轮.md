# T13 聊天流卡片 AMEND 关闭 · 独立复核记录（第二轮，PASS）

- 复核时刻：2026-10-08 15:55–16:25 (+08:00)；复核员：一名 Opus 只读复核员（克隆 `D:\lawbench-rv\rv-A53`，实验目录 `rv-A53-exp`）
- target：line-A `d9efe11`；基座 `fd7bf35`；19 文件 +229/-51
- 裁决（主编排）：**PASS**，cherry-pick `02707cb`、`c60f5ae`、`fd7bf35`、`d9efe11` 进 main。NOTE 六条记后续（1 随契约 1.4 候项 10；2/4 补用例；5 打包时设 `LAWBENCH_BUILD_STAMP`；6 候定）。

## 复核员报告（原文，路径已去用户名）

**Verdict：PASS。** 上轮冻结 P1 与四条 P3 已关闭，无范围内阻断或引入回归。

### 逐项
**P1 关闭**：`recordConfirmed` 把"草稿路径 → {version, files}"写进界面 localStorage（键 `lawbench.confirmed.<case_id>`，应用数据，不在案件文件夹），值只含相对路径；`outputOfDraft` 先看记录，无记录时须"任务里同标题草稿唯一且成果里该任务同标题唯一"才切换，不再按版本对。用例：存 v1、v2 确认 v2 生成成果 v1——无记录两张不切、有记录只切 v2；服务回 v3 按记录切、localStorage 断言。变异 1（去草稿唯一性）用例变红。假服务成果版本=已确认 + fixture 同标题（小写比较）最大 +1，与 `outputs.py _next_version`（casefold，另数成果文件夹）口径一致。
**P3 四条关闭**：`insideCase` 正则 `[\u0000-\u001f<>:"|?*]` 与 `gate.py:57 _BAD_CHARS` 逐字一致，0x0000–0xFFFF 逐字符对照"gate 拒而 insideCase 放行"为 0；openFile 逃逸集复跑 + `ok.docx:evil`（真建备用数据流）、`:evil:$DATA`、`C:成果/…`、控制字符、`x.docx.EXE`、`X.DOCX.LNK`——放行仅 `ok.docx`、`OK2.DOCX`、`a,b.docx`、`sp ace.docx`、硬链接 `hl.docx`（已知接受），其余全拒；`sameFolder` 对五种网络写法 realpath 0 次，联接同根仍认；`pendingOcr`/`ocrTargets` 排除 `ocr_running` 有用例；`lawbench-results` 登记 `guide: []`（DSH `tab-registry.ts` 据此不入"开始"列表），内容 `OLD_RESULTS_TEXT` 指路不空白。
**注记项**：`DailyBody` 加 `OutputsLine`，用例断言材料读 0 次、成果读 1 次；构建号经 esbuild `define __LAWBENCH_BUILD__` 写进 bundle，`LAWBENCH_BUILD_STAMP` 优先（字符校验）否则本机时间，测试/未构建为空只显示 `0.1.0`；侧栏品牌位与设置显示 `0.1.0+<戳>`（截图 05 `0.1.0+202610081538`）；`dsh-ext/package.json` version 未改理由成立（runtime-lock 4 处钉 `lawbench-dsh-0.0.0.tgz`）；DSH"当前版本"仍 0.1.0 记后续。
**检查**：vitest 690/0/6（brand.spec 环境缺文件，拷入后 6/6）；tsc 0；`check_ui_words` 零命中；截图 05 无用户名。

### Findings（均 NOTE）
1. 确认记录在应用 localStorage：换机/重装/清存储后退回"唯一才切"（保守，不会错标，可能多一版）；成果标题可能留在案件文件夹外。修复：契约候项 b 落地后不需本机记录。
2. "成果里该任务同标题唯一"无用例守（变异 2 仍绿）；影响低；补"同一草稿确认两次不切换"用例。
3. `sameFolder` 对登记根 `a` 仍可能 realpath（可信，无需改）。
4. P3-4 未真机核成（DSH 加载覆盖本机存储）；可补 `OldResultsTab` 渲染用例。
5. 构建号每次取当前时间，打包脚本未设 `LAWBENCH_BUILD_STAMP`；DSH"当前版本"不带构建号。
6. explorer 打开含逗号文件名失败（线 A 自报，候定）。

### 跑过的命令（摘要）
`git rev-parse/diff --stat/diff fd7bf35 d9efe11`；借用联接（dsh node_modules/packages 只读；dsh-ext node_modules 真目录内 `.pnpm`/ajv/ajv-formats/yaml 联接，`.vite` 落克隆）；`node scripts\test.mjs`（+brand 单跑）；`tsc --noEmit`；`check_ui_words.py`；`node exp1.mjs`（逃逸集、realpath 计数、`_BAD_CHARS` 全字符对照）；robocopy dsh-ext 到 exp 做两次变异并还原。借用已拆，A 目标完好。
