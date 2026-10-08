# T13/T20 聊天流成果卡片 + 运行前待识别提示 + 小项 · 独立复核记录（AMEND）

- 复核时刻：2026-10-08 14:30–15:15 (+08:00)；复核员：一名 Opus 只读复核员（克隆 `D:\lawbench-rv\rv-A52`，实验目录 `rv-A52-exp`）
- target：line-A `02707cb`（运行前待识别提示、总述分开、注记 0934 四小项）、`c60f5ae`（首配页 getSetup catch、100 次断言、冒烟清单）、`fd7bf35`（聊天流草稿/成果卡片、右栏去成果默认收起、概览卡已确认成果、Host `openFile`）；基座 main `722b872`；37 文件 +1197/-253
- 裁决（主编排）：**AMEND**。P1 按 a）不改契约修（界面按会话记"草稿路径 → confirm 返回的 outputs"，历史卡片唯一对上才切换；假服务成果版本与真服务一致；补"草稿 v2 → 成果 v1"用例）；b）记契约 1.4 候项（outputs 加 `draft` 来源路径）。P3 四条一并修；NOTE 记后续。令 `致A-ORCH-执行令-聊天流卡片复核AMEND-<HHMM>.md`。

## 复核员报告（原文，路径已去用户名）

**结论：AMEND。** 一个范围内阻断：草稿与成果对应关系判错。Host `openFile` 未发现能逃出案件根的路径，只有几处加固。

### Findings
**P1 · 草稿和成果按版本号对应，但服务端两个版本号各算各的**（范围内阻断）：`result-cards.tsx outputOfDraft` 要求成果与草稿"同任务、同标题、同版本"；真服务草稿版本按任务从 v1 起（`tools\drafts.py:52-56`），成果版本按案件同标题最大 +1（`export\outputs.py:129-131,146-154`）；假服务把成果版本写成草稿版本（`dev\fake-service.mjs:209`），真机截图看不出；用例按版本相等写（`result-cards.spec.ts:62-63`）。影响：同一任务改到 v2 再确认生成成果 v1 → 上一轮 v1 卡片错标"已保存到成果"、v2 仍是草稿可再点多出成果 v2；同案件第二个任务同名草稿 v1 确认得成果 v2，卡片永不切换。修复 a）不改契约：确认成功后按会话记"草稿路径 → confirm 返回的 outputs"，历史卡片唯一对上才切换；b）契约：outputs 加 `draft` 来源路径。两者都要改假服务版本口径 + "草稿 v2 → 成果 v1"去掉即红用例。

**P3-1 openFile 放行 NTFS 备用数据流**：`rel="成果/evil.exe:s.docx"` 过 `openableFile`（扩展名取 `.docx`，lstat 读到流）；服务 `gate.py _BAD_CHARS` 拒 `:`，两端不一致。修：rel 含 `:` 拒。
**P3-2 sameFolder 先对界面给的根 realpath**：`knownCase` 字面比不上时直接 `realpathSync.native`，在 `plainAbsolute` 前 → `\\host\share` 先发 SMB；不放宽范围。修：先 `plainAbsolute(b)`。
**P3-3 正在识别的材料也算"还没识别"**：`pendingOcr` 只看 `pages_need_ocr`/`needs_ocr`，服务识别中仍保留 `pages_need_ocr`（`ocr\merge.py:157-159`，`ocr_running`）→ 识别跑着仍弹、"去识别"再弹提交框。修：排除 `status==='ocr_running'`。
**P3-4 旧会话留下打不开的"成果"标签**：DSH 对未登记标签种类保留标题"成果"、内容区显示"这类内容还没有可用的查看方式"（`ui-sidebar-right/.../SidebarRight.tsx:227-248`、`locales.ts:44`）；seeder 记在本机不重开，律师一直看到死标签。修：保留隐藏 `lawbench-results` 登记显示一句"成果已移到聊天卡片和案件概览"，或启动时关掉已开过会话的该标签。
**NOTE**：`explorer.exe <文件>` 文件名含逗号时 explorer 按逗号拆参数可能开错位置（不构成注入；openFolder 同）；指向案件外的硬链接可打开（同 removableMaterial 口径，风险低）；`OCR_PENDING_REASON=/^还没识别/` 靠服务 `task.py:404` 字面文案无共享常量，建议加一例读源码对照。

### 逐项核对结论
openFile 逃逸实验（真目录/联接/硬链接）：`ok.docx`、`OK2.DOCX`、`sp ace.docx`、`a,b.docx` OK；`x.docx.exe`、`x.lnk`、`x.docx.lnk`、`../outside`、`成果/../../outside`、经联接 `成果/jout/secret.docx`、文件夹、末尾点/空格、`::$DATA`、`\\?\` 均 INVALID_ARGUMENT；例外备用数据流与硬链接。sameFolder 字面比/联接别名 true、案件外/子目录/不存在 false，返回登记根。四小项：`isDeviceName` 与 `gate.py:48-50,239-242` 同套（13 名实测）；`noOffer` 改 `openCase` 参数 `offerLocal`；`materialRemove` 正向用例 `vi.mock` 开、真跑、开关仍关。聊天卡片：DSH `assembler.ts:957` 要求 key==kind，现同取 `TURN_DATA_KEY` 并有用例；同轮同名取版本最大/后出现；路径来自 drafts.py 同一 `rel` 不会对不上；自由对话无任务不出卡片；渲染层只有案件内相对路径。右栏：`seedTabsCollapsed` 只在开前收起时收回、每会话一次，用户展开后不再收；出处走 `openTab` 自动展开。运行前提示：数据来自 `/api/materials`，无材料/全已识别不弹；先待识别后篇幅；"去识别"带 `ocr=pending&at=<时间>` 打开材料页，同请求只弹一次（无渲染用例/真机截图）。首配页：catch 放开表单显示 `SETUP_READ_FAILED` 中文；100 次读满前后断言；desktop 用例未在本机跑。截图无用户名。

### 检查
dsh-ext vitest 54 files 687/0/6；tsc 0；`check_ui_words` 零命中；补丁链 `477b4f4205` 起 `--whitespace=error-all` 18 个全成功零输出 158 文件、`--check` 0（未比对线 A 工作树——禁区）。

### 跑过的命令（摘要）
`git rev-parse/diff --stat/diff 722b872..HEAD`；共享克隆补丁链；robocopy node_modules（排除 `.vite*`，ajv/ajv-formats/yaml 改联接指克隆内 `.pnpm`）、`rv-A52\dsh` 三联接（node_modules/packages 只读借用，apps 指实验克隆）；`node scripts\test.mjs`、`tsc --noEmit`、`check_ui_words.py`；`node rv-A52-exp\exp1.mjs` 逃逸实验；借用目录 `.vite*` 无新写入；借用已拆，`git status` 干净。
