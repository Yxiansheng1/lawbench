# T15 导出、确认与修订版 · 独立复核记录（第二轮：返修后累计范围）

- 复核员：一名 Opus 5.5 只读复核员（换人）
- target：line-C `9d30eb6`（基座 main 28f7da1）；T15 累计 `540d116` + `45743ea`
- 冻结清单：`review-REVIEW.md` 第二部分
- 复核克隆：scratchpad `rv-C20`
- 归档：主编排于 2026-10-02 01:10 (+08:00) 从复核员交回原文抄录，未改内容（无人值守窗）

## 第一部分 复核员原文
# T15 返修累计范围复核（rv-C20，线 C `9d30eb6`，T15 = `540d116` + `45743ea`）

**结论：PASS。** 冻结清单全部关闭，每一项我都自己复现过。返修没有引入 P0/P1/P2 回归。下面 4 条 P3 和几条 NOTE 建议记作后续，都不挡合并。

复核对象：克隆 `rv-C20` 已 detach 到 `9d30eb6`，`git status` 干净，`28f7da1` 是它的合并基点。实验用的是 `git archive` 导出到短路径的副本（`f` 跑全量和读型实验，`m` 做变异），用完已删除。

## 发现的问题

**P3-1 NOTE-2 的修法只挡住了最简单的一种写法**（归类：本次修正不完整，独立后续）
- 问题：只有"链接的最后一个 run 后面什么都没有"这一种情况会进"需人工修改"。只要链接末尾还跟着别的元素，插入的文字照样进到链接里。
- 证据（`exp_lib2-new.txt` 第 7 节）：
  - 链接里最后一个 run 后面跟 `w:bookmarkEnd` 或 `w:proofErr`（Word 常见写法）：insert_after 得到 `applied [1]`，`ins inside hyperlink: True`。
  - `w:fldSimple HYPERLINK` 形式的链接同样插进去了。
- 原因：`redline._apply` 里的判断是 `parent.tag == _HYPERLINK and runs[-1].getnext() is None`。
- 最小修复：改成"`runs[-1]` 之后的兄弟元素里没有 `w:r`"，并把 fldSimple/复杂域形式的 HYPERLINK 一并算上。

**P3-2 "修改清单和修订版查修订用同一个函数"没有用例把关**（归类：测试覆盖，范围内但小）
- 现状：行为是对的。我实测页眉插入、rPrChange 等 12 种情况，`_paragraphs` 都判为有修订；接口 `case_save_edit_list` 返回 out_of_scope，原因是"原文件含未处理的修订…"。
- 问题：把 `edit_list._paragraphs` 改回只查正文 document.xml（变异 M05），用例仍然全绿（94 passed）。现有用例只测了 `has_revisions` 函数本身，没测保存修改清单这条路。
- 最小修复：在 `test_revisions_anywhere_rejected` 里加一句，经 `case_save_edit_list` 断言页眉有修订时返回 out_of_scope。

**P3-3 材料文本格式版本升到 3 理由不准，重扫范围也比交付说明写的大**（归类：本次修正引入，交主编排定）
- 交付说明写"带制表位的 Word 段落开头原来多一个 `\t`"。但 T5 解析对每段都做 `.strip()`，开头的 `\t` 本来就被去掉了。
- 新旧两棵树对比：8 个 docx 夹具、10 种段内结构解析结果逐字相同。唯一变化是**文本框里**带制表位的段落：旧 `'外层 \t\t框内'`，新 `'外层 框内'`。
- 但版本号是全局的。实测 v2 案件（以及没有版本行、算 v1 的旧案件）下次扫描时，**docx、pdf、jpg、xlsx 全部重新解析**，txt 不动。不是只重扫 docx/doc/wps；doc/wps 还会各走一次 LibreOffice。
- 其余几点都没问题：
  - 只重扫一次，第二次扫描没有重写。
  - 旧案件打开不崩：版本行写成乱码、状态文件乱码、状态文件缺失，三种都扫描正常。
  - T5 相关用例全过。
  - 迁移写法与 T5 X13 已有的版本机制一致，只改了两行。
- 现在还没发布，没有真实旧案件，所以实际代价接近 0。另外把版本撤回 2（变异 M02）用例仍全绿，说明这次升级没有用例把关。
- 建议主编排二选一：撤回版本升级；或者保留，但把交付说明改成实情（"只影响文本框内段落；所有可重解析类型都会重扫一次"）。

**P3-4 修改文字或批注里有孤立的 Unicode 代理字符时仍返回 500**（归类：此前既有，与 P3-2 相邻，独立后续）
- 修改清单文件里写 `"\ud800"` 或 `"\udfff"`，`/api/redline` 返回 HTTP 500 INTERNAL（`exp_api2.txt`）。库层报的是 UnicodeEncodeError。
- 原因：`_BAD_XML` 没有覆盖 `\ud800-\udfff`。
- 最小修复：把 `\ud800-\udfff` 加进 `_BAD_XML`。

**NOTE**
- **N1（本次新代码）`_HTML_A` 遇到不闭合的 `<a href>` 时耗时按平方增长**：1000 个不闭合标签（16KB）用 1.2 秒，4000 个（64KB）用 18 秒。草稿正文没有长度上限。AI 草稿里出现大量不闭合 `<a>` 的可能性很小；修法是限制向后搜索的长度，或改成不依赖 `.*?` 回溯的写法。
- **N2** `<iframe src="工作区/…"></iframe>` 处理后剩下 `</iframe>`，`<object>` 同样。不外连，只是成果里会多出一段字面文字。
- **N3** `word/styles.xml` 等非正文部件 XML 损坏时，修订版返回 `MATERIAL_NOT_READY`，提示是"待识别或处理失败"。但 T5 不读这些部件，材料状态仍显示 parsed，提示略不贴切。概率很低。
- **N4** `test_doctype_docx_not_ready` 对修订版接口的断言接受 `MATERIAL_NOT_READY` 或 `INVALID_ARGUMENT` 两种码，偏宽。好在变异 M06、M07 都变红，实际有效。
- **N5** pyproject 里 pywin32 补上界 `<313` 是给 T23 用例收尾，不在 T15 冻结清单里。交付说明写明了，改动只有一行，可接受。
- **接缝**：T23 把索引写入抽成 `index_update`，确认保存和归档共用。去掉案件锁（M20）、写索引失败不回滚（M21）这两个变异都变红；并发确认 4 次得到 v1–v4（正常路径和深路径都测了）。

## 冻结清单逐条核对

| 项 | 结果 |
|---|---|
| P2-1 制表位 | 关闭。`docx._SKIP` 加了 pPr/rPr；原 E1 样例 `applied [1]`；制表位段落的替换、删除、插入、跨制表符都生成修订。<br>`_text` 对 instrText、delText、sym、嵌套 smartTag、行内 sdt、链接内嵌 smartTag、段落标记删除、br/cr，新旧结果逐字相同。<br>撤回（M01）变红。<br>格式版本升级：见 P3-3 |
| P2-2 全部件查修订 | 关闭。以下全部拒绝：页眉 ins、页脚 ins、rPrChange、sectPrChange、tblPrChange、cellIns、行删除、styles rPrChange、numbering pPrChange、moveTo、glossary 里的 ins。<br>只有 settings 里的 `trackRevisions`、或 word/ 以外的 customXml 部件，不误拒。<br>与 `_paragraphs` 用同一个函数；M03、M04 变红，M05 不红（见 P3-2） |
| P3-1 DOCTYPE | 关闭。接口返回 `MATERIAL_NOT_READY`，保存修改清单同样，正常路径和深路径都测了；M06、M07 变红 |
| P3-2 控制字符 | 关闭。`\x00`、`\x01`、`\x0b`、`\ufffe` 进"需人工修改"；`\x7f`、`\x85`、`\t\n\r` 照常生成。孤立代理字符见 P3-4。M08 变红 |
| P3-3 重复 id | 关闭。库层抛 ValueError，接口返回 `INVALID_ARGUMENT`（真服务也验了）；M09、M10 变红 |
| P3-4 去链接三种写法 | 关闭。另测 17 种写法：无引号、大写、属性在前的 href，链接嵌链接，双层图片套链接，百分号编码，`a(1).md` 等都去掉了；外链保留不动。M11、M12、M13、M14 变红 |
| P3-5 六处断言 | 关闭。六处变异（M17–M21 加 run 原文一致检查）全红 |
| NOTE-1 | 关闭。`--sandbox` 仍带（去掉它的 M22 变红）；`-f markdown-raw_attribute-raw_html-raw_tex` 已生效。<br>openxml 块和行内块不再成为域：输出件里没有 instrText/fldChar，INCLUDEPICTURE 只作为普通文字出现。<br>raw html、latex 块，以及 md 图片、`<img>`、`\includegraphics` 指向自建监听，收到 0 个请求。<br>原八种外链写法正常路径、深路径都 0 请求（对照组不带 sandbox 时收到 2 个）。M15 变红 |
| NOTE-2 | 作者选"进需人工修改"，最简单情况成立；M16 变红；有漏网写法，见 P3-1 |
| NOTE-3 | 关闭。test 依赖里有 python-docx |
| 偏离① 原文含修订 | 维持 `INVALID_ARGUMENT`（reason `original_has_revisions`），代码注释和交付说明都写明是 1.4 前的过渡。页眉有修订时实测返回这个码 |
| 偏离② 找不到 pandoc | 返回 `INTERNAL`、HTTP 200，成果目录里不留半成品文件 |

## 第一轮通过项回归抽查
- **其余字节不变**：零条生效时 document.xml 逐字节等于原件；9 条生效时只有目标段 16、17、21、23、24、27、31、32、42 不同，清空目标段后其余一致；其他部件逐字节不变；python-docx 能读回。
- **范围外 5 条**仍进"需人工修改"；修订作者和批注作者都是固定值，日期是 UTC 带 Z。
- **LibreOffice**：`test_libreoffice_opens_and_keeps_revisions` 通过。
- **模板**：本次没有改模板文件。
- **索引与并发**：并发 4 次得到 v1–v4，索引过契约。
- **标题边缘**：结果与第一轮相同。
- **原件哈希**不变。
- **日志**：真服务（端口 19492/19493；6000D、395 两组地址都设成 127.0.0.1:19498/19499 死端口，没调测试连接）跑了确认、修订版、控制字符、重复 id 各一次。14 个敏感词（标题、正文、修改内容、批注、材料名、"修订版"、"成果/"、Users 等）在 `service.log` 里都搜不到。

## 返修 diff 逐 hunk 归类
13 个文件，没有无关改动。
- `docx._SKIP` → P2-1
- `materials.py` 两行 → P2-1 连带的格式版本升级（见 P3-3）
- `edit_list` 里的 `REVISION_TAGS`、`has_revisions`、`_paragraphs` → P2-2；接住 ParseError → P3-1
- `outputs.py`：接口查重复 id → P3-3；接住 ParseError → P3-1；过渡注释 → 偏离①
- `redline.py`：`_BAD_XML` → P3-2；`R_IN_LINK` → NOTE-2；库层查重复 id → P3-3；改调 `has_revisions` → P2-2
- `pandoc.py`：几条正则加循环替换 → P3-4；`-f` 参数 → NOTE-1
- `pyproject`：python-docx → NOTE-3；pywin32 上界 → N5
- `test_ocr_queue.py`：随版本号改为读常量
- 测试文件、证据、交付说明

## 八项清单
- 契约一致：通过
- 边界输入：基本通过（有 P3-1、P3-4、N1）
- 错误路径：通过（孤立代理字符仍会 500，见 P3-4）
- 日志不含正文：通过
- 路径闸门未被绕过：通过（原件哈希不变，写入仍只经 gate）
- 无外连：通过
- 测试覆盖新代码：基本通过（22 个变异里 20 个红，M02、M05 仍绿）
- 无机密入库：通过

## 实际跑过的命令
- 用 C 线 venv（`-B`），TEMP、TMP、LOCALAPPDATA、APPDATA 都指到 `C:\Users\<用户>\AppData\Local\Temp\claude\rvC20s`；每条都用 Start-Process + WaitForExit 兜底超时。
- **相关用例**：test_export、test_redline、test_ingest、test_t5_rework/2/3、test_tools、test_checks、test_ocr_queue、test_materials_api、test_t5_contract12，**407 passed**。
- **全量（短路径）**：1132 passed / 7 skipped / 2 failed。两条失败重跑都通过：
  - `test_tokenizer_json_ignored_by_git`：导出副本不是 git 仓库，在克隆里单跑通过。
  - T23 的 `test_hang_times_out_kills_and_falls_through`：单跑 test_convert 13 passed，判为机器负载或进程号复用引起的偶发失败，不归本卡。
  - 折算后与作者报的 1134 passed / 7 skipped 一致。
- **变异 22 个**（单条超时 1800 秒）：
  - 20 个红：撤回 P2-1、P2-2 两处、P3-1 两处、P3-2、P3-3 两处、P3-4 四处、NOTE-1、NOTE-2，P3-5 五处，去掉 --sandbox。
  - 2 个绿：M02 撤回格式版本升级、M05 `_paragraphs` 改回只查正文。
  - 每次都逐字节复原，71 个源文件哈希与变异前一致。
- **实验脚本**：
  - 我写的：`exp_lib2.py`（新旧两棵树对比）、`exp_strip.py`、`exp_api2.py`、`test_zz_rv_format.py`（只放在副本里）、`exp_live.py`（改了端口）。
  - 复用第一轮的：`exp_api.py`、`exp_lib.py`（只读复用）。

## 残留审计
- 我起的进程都已结束：各次 pytest、真服务 36608；中途卡住的实验 41556/16592 是按 PID 杀的进程树。
- 端口 19491–19499 都没有在监听。
- `rvC20s` 已删除；克隆 `rv-C20` 状态干净，HEAD 仍是 `9d30eb6`。
- 没动 `soffice.bin` 10028、42468，没写任何仓库，也没碰协调目录。
- 实验脚本和输出留在 `C:\Users\<用户>\AppData\Local\Temp\claude\D--lawbench\780b8a59-…\scratchpad\rv-C20-T15-lab\`，主要有 `mutate.txt`、`mutate2.txt`、`full.txt`、`exp_lib2-*.txt`、`exp_api*.txt`、`exp_live.txt`、`exp_format.txt`、`strip-*.txt`。

## 证据缺口
- 没在 Word 或 WPS 里实测（按工单放在 T22）。
- doc/wps 重新解析没有实跑 LibreOffice，是按代码路径推断的。
- 页脚注、尾注、批注部件里的修订：夹具里没有这几个部件，是用 glossary 部件和代码路径覆盖的。
- 孤立代理字符经 `case_save_edit_list` 那条路没测到：测试客户端发不出这种字符。

PASS
﻿
---

## 第二部分 主编排裁决（2026-10-02 01:10 (+08:00)，无人值守窗）

**结论：PASS，T15 任务门=过。** 冻结清单全部关闭并各有复核员自证（22 变异 20 红；全部件查修订 12 种情形全拒；八种外链 + raw 块 0 请求；其余字节不变；日志 0 泄漏）。

记录项（不阻断，注记交线 C 随 T23 返修一并做）：P3-1 链接末尾跟 bookmarkEnd/proofErr 或 fldSimple HYPERLINK 时 insert_after 仍进链接（判断改"runs[-1] 之后无 w:r"并算上 fldSimple）；P3-2 `case_save_edit_list` 经页眉修订返回 out_of_scope 的断言；**P3-3 格式版本升 3 的理由与范围——主编排定：保留升级（未发布、代价≈0），交付说明改成实情（只影响文本框内段落；所有可重解析类型都重扫一次）并补一条用例守版本号**；P3-4 `_BAD_XML` 加 `\ud800-\udfff`；N1 `_HTML_A` 不闭合标签平方耗时限长；N2 `</iframe>` 残留。

合流：T15 两提交与 T12（候 N56）、T23（返修中）同在 line-C，且 `45743ea` 改了 `test_ocr_queue.py`（T12 文件），不单独 cherry-pick；随 line-C 一起合并。