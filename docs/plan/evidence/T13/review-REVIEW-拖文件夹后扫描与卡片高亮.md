# T13 拖文件夹建成后扫描 + 卡片高亮抖动 · 独立复核记录（PASS）

- 复核时刻：2026-10-10 17:09–17:22 (+08:00)；复核员：一名 Opus 只读复核员（克隆 `D:\lawbench-rv\rv-A57`，实验目录 `rv-A57-exp`）
- target：line-A `b7e64c3`；对比 `28f898d`（第七版第一包证据）；9 文件 +112/-15
- 裁决（主编排）：**PASS**，cherry-pick `28f898d`、`b7e64c3` 进 main，发重打第七版令。P3（材料页"重新扫描"无界面用例）记第八版小项；NOTE"材料有变化需复核"一句对新案件多余，第八版顺手改。

## 复核员报告（原文摘要）

**结论：PASS。** 无阻断、无回归。

- `scanMaterials`（`cases.ts:182`）与旧 `rescan` 等价：同调 `materialsScan {case_id}`、失败提示同、成功句逐字同；刷新改发 `lawbench:materials-changed` 事件（材料页与 wiki 卡都收，导入路径同款，无害超集）；无其他调用方；`call` 不抛，扫描失败不影响 `openCase`。
- 顺序：`onOpened` async（recordKind → await scanMaterials），`cases.ts:105` `await hooks.onOpened` 在 `openCaseWorkspace` 前；用例断言 `dropInfo → caseOpen → materialsScan` 与 `['scan','enter']`；失败照样建成并提示；取消/云同步不同意/已登记或 has_case 不扫；云同步复制路 `onOpened` 只 recordKind，序列 `[dropInfo, caseOpen, localCaseFolder, caseOpen, materialsImport]` 无重复扫。
- 高亮：`!e.currentTarget.contains(e.relatedTarget)`，null 时为 false 会关，不卡死；stopPropagation 仍在；drop 时 `setOver(false)`。
- 变异：去 `await scanMaterials` 3 红；去 relatedTarget 判断 1 红；`await`→`void` 2 红；`relatedTarget && …` 1 红；原样 drop-case.spec 16/16。
- **P3（独立后续）**：材料页"重新扫描"按钮无直接界面用例。**NOTE**：新案件扫描句多"材料有变化，案件 wiki 和已有成果需要复核。"；卡片高亮无超时兜底（臆测，未复现）。
- 检查：vitest 732/1/6（唯一失败 brand.spec 读 `dsh\apps` 环境缺件，计入即 733/0/6 与自报一致）；tsc 0；check_ui_words 产品零命中；截图 07/08 与测试记录无用户名。
- 命令：`git diff 28f898d b7e64c3`；三只读联接；vitest 包装配置 cacheDir 指实验目录；robocopy 副本四处变异；tsc；check_ui_words。6 联接已 rmdir；A 目录无 17:09 后写入；克隆干净。
