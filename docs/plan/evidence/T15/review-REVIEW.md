# T15 导出、确认与修订版 · 独立复核记录（第一轮）

- 复核员：一名 Opus 5.5 只读复核员
- target：line-C `6cd6bd7`（已 rebase 到 main d7eca15）；范围仅此一提交
- 复核克隆：scratchpad `rv-C19`
- 归档：主编排于 2026-10-01 22:58 (+08:00) 从复核员交回原文抄录，未改内容（无人值守窗）

## 第一部分 复核员原文
# T15 复核报告（rv-C19，线 C `6cd6bd7`）

复核对象：克隆 `scratchpad\rv-C19`，HEAD 是 `6cd6bd71b8819d78871e5038b4bc36c1b6f92815`，`git status` 干净，main `d7eca15` 是它的祖先。本次范围只有 `6cd6bd7`（17 个文件，+1452）。实验用的是 `git archive` 导出的副本，导出后已删除。

**结论：AMEND。** 导出、--sandbox、版本号、索引、闸门、日志都没问题，生成的修订件结构正确；但修订版这块有两处 P2 要返修。

## 发现的问题

**P2-1 段落里只要设了自定义制表位，这一段的修改就一律进"需人工修改"，给的原因还不对**
- 影响：合同的签字栏、对齐行常用段落制表位，这类段落永远生成不了修订。系统给的原因是"find 的文字分属不同的段内结构（如内容控件）"，律师会被误导。不会改错字，但这个功能在常见文档上会悄悄失效。
- 证据：`exp_lib.txt` E1。用 python-docx 做一段并加一个制表位（`w:pPr/w:tabs/w:tab`），`_para_chars` 读出来是 `'\t甲方应于…'`（`dx._text` 也一样），`redline._slots` 只数 run 里的字，两边对不上，`_apply` 就返回 R_STRUCTURE。根子在 `tools/edit_list._para_chars`：它往下遍历时进了 `w:pPr`，把制表位的定义也当成了制表符。
- 最小修复：`_para_chars`（最好 `dx._text` 一起）遍历时跳过 `w:pPr`（以及 `w:rPr`）子树，再补一条"带制表位的段落能替换"的用例。
- 归类：范围内阻断（错误逻辑是共用的老代码，但它让 T15 的核心功能失效）。

**P2-2 "原文已有修订就整份拒绝"只查了正文 document.xml**
- 影响：页眉、页脚、脚注里有对方未处理的修订，或者正文里有格式修订（`w:rPrChange`/`w:pPrChange`），都照常生成修订版。律师在 Word 里点"全部接受"，会把对方没处理的改动一起接受掉。这正是 Spec 12.2 要防的情况，Spec 原话是"原文已有修订痕迹的文件：整份不生成"。
- 证据：`exp_lib.txt` E7。往 header1.xml 插一个 `w:ins`，得到 `applied [1]`，没有拒绝；在正文 run 里加 `w:rPrChange`，同样 `applied [1]`。正文里的 `w:moveTo` 和段落标记上的 `w:del` 能正确拒绝。代码位置：`redline.generate` 只对 `word/document.xml` 的根做 `dx._REVISION` 判断。
- 最小修复：遍历压缩包里 `word/` 下所有 `.xml`（页眉、页脚、脚注、尾注、批注），查 ins/del/moveFrom/moveTo 和各类 `*PrChange`，命中就抛 Revised。`edit_list._paragraphs` 用同一个函数，两边口径一致。补一条用例。
- 归类：范围内阻断。

**P3-1 损坏的 docx（document.xml 里带 DOCTYPE）调 /api/redline 返回 HTTP 500 INTERNAL**
- 证据：`exp_api.txt`，接口返回 `带DOCTYPE redline HTTP 500`。原因是 `dx._parse_xml` 抛的 `ParseError` 没被 `outputs.redline` 的 except 接住。伪 docx（CFB 文件头，即加密 docx 的外形）能正确返回 `MATERIAL_NOT_READY`。老的 `save_edit_list` 也有同样问题。
- 修复：except 里加上 `dx.ParseError`，返回 `MATERIAL_NOT_READY`。
- 归类：本次引入（redline 部分）。

**P3-2 修改文字或批注里有 XML 不允许的控制字符（如 `\x0b`）时，lxml 抛 ValueError，接口返回 500**
- 证据：`exp_lib.txt` E5。契约只要求是字符串，不禁这类字符。
- 修复：在 `_apply` 和 `_comment` 前过滤控制字符，或把该条放进"需人工修改"。
- 归类：范围内。

**P3-3 修改清单里 id 重复时，表格里的那条也会被改**
- 证据：E6，同 id 两条（表格内一条、正常一条），得到 `applied [1, 1]`，表格里出现了 `w:ins`/`w:del`。原因是 `reasons` 按 id 建字典，后一条覆盖了前一条。
- 正常流程走不到：`save_edit_list` 会拒绝重复 id。
- 修复：redline 遇到重复 id 返回 `INVALID_ARGUMENT`。
- 归类：独立后续。

**P3-4 去工作区链接漏了三种写法**
- 证据：`exp_api.txt`。三种写法都原样留在成果 md 里：
  - 尖括号目标里带空格：`[x](<工作区/材料/文本/M 1.md>)`
  - 原始 HTML：`<a href="工作区/…">`
  - 图片外面再套链接：`[![img](工作区/a.png)](工作区/b.md)`，处理完剩下 `[img](工作区/b.md)`，因为只替换一遍
- 修复：行内替换循环到结果不再变化；尖括号目标允许空格；`href="…工作区…"` 一并处理。
- 归类：范围内（小）。

**P3-5 有几处新代码没有测试把关（变异后测试仍全绿）**
- 修订作者改成取本机用户名、日期改成本地时间不带 Z、日志里记标题、去掉案件锁、写索引失败不回滚、去掉"按 run 数出的原文与判范围原文一致"的检查。
- 我亲手验证过：作者是固定值、日期是 UTC 带 Z、日志干净、并发 4 次得到 v1–v4。所以现在的行为没问题，缺的是防回归。
- 修复：至少加两条断言，`R.AUTHOR == "AI审查（待律师确认）"`，日期匹配 `\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ`。
- 归类：范围内（测试）。

**NOTE-1 pandoc 会把草稿里的 ```` ```{=openxml} ```` 原样写进 docx**
- 实测加 --sandbox 后，带 `w:dirty="true"` 的 `INCLUDEPICTURE "http://127.0.0.1:…"` 域仍被写进了输出件。Word 打开时一般会先弹窗问是否更新域，所以没有实证能联网。
- 加固办法：改成 `-f markdown-raw_attribute-raw_html-raw_tex`。
- 归类：臆测，独立后续。

**NOTE-2 在整段超链接文字后面 insert_after，插入的文字会进到超链接里面**（E9），成了链接文字的一部分。归类：独立后续。

**NOTE-3 python-docx 是 `test_redline.py` 的依赖，但 `pyproject` 的 test 依赖里没写**
- B 的 venv 没装它，`test_redline` 在收集阶段就报错，我改用 C 的 venv 才跑起来。
- 修复：在 test 依赖里补 `python-docx`。

**NOTE-4 改动文件超出"api\ui.py 只加路由"**：还改了 `app.py`（1 行，实例化 Exporter）、`pyproject` 加了 package-data，另新增 `scripts\make_export_templates.py`。三处都是必需的，模板来源写清了，没有无关改动。

## 冻结清单逐条核对

| 项 | 结果 |
|---|---|
| 每次调 pandoc 都带 --sandbox；变异去掉后用例变红 | 通过（作者变异 1 我复现为红） |
| 自己复现监听：草稿放指向 127.0.0.1 的远程图片，导出后收到 0 个请求 | 通过。我测了 md 图片、引用式图片、`<img>`、`\includegraphics`、iframe、link、`file:///`、`../`，监听收到 `[]`。同一份草稿不带 sandbox 时收到 `/md.png`、`/ref.png`，证明监听有效。正常路径和深路径都测了 |
| pandoc 路径不写死用户名 | 通过（diff 里搜 `<用户名>`、`Users\` 没有命中） |
| 找不到 pandoc 时报可读错误 | 有 `INTERNAL`（pandoc_not_found），技术意见见下 |
| 两个模板干净 | 通过。都是 pandoc 3.11 自带 reference.docx 只改了字体；没有宏、OLE、customXml；没有律所信息或用户名；重跑脚本生成的文件逐字节相同 |
| 替换、插入、删除各 3 条；修订和批注、关系、内容类型都对 | 通过 |
| LibreOffice 转 PDF | 通过。证据件和我重生成的件都转出 `%PDF-1.7`；读进再存回 docx，6 处插入、6 处删除和作者都还在。我重生成的件与证据件只差日期 |
| 原文其余部分不变 | 通过。没有一条生效时 document.xml 逐字节等于原件；9 条生效时，按规范化 XML 逐段比对，只有目标段 16、17、21、23、24、27、31、32、42 不同；把目标段清空后其余字节一致；其他部件逐字节不变；python-docx 能读回 |
| 范围外 5 条进"需人工修改" | 通过 |
| 原文已有修订整份拒绝 | 正文通过；页眉、页脚、脚注和格式修订没拦住（P2-2） |
| 变异：出现多次改成改第一处 → 红；去掉已有修订检查 → 红 | 两项都红 |
| 跨 run（三种格式）、跨 w:br/w:tab、fldSimple 内和跨出 | 通过。fldSimple 里面照改，跨出去进需人工 |
| 全角/半角、空白 | 不做归一，找不到就进需人工，不猜。这样合理 |
| 空 text、超长 find、超长 text | 通过 |
| 同段两条修改 | 通过 |
| 控制字符 | 返回 500（P3-2） |
| 修改清单不合契约 | 返回 `INVALID_ARGUMENT` |
| 伪 docx 与 DOCTYPE | 伪 docx 返回 `MATERIAL_NOT_READY`；DOCTYPE 返回 500（P3-1） |
| 修订作者和日期 | 作者固定为"AI审查（待律师确认）"（批注缩写 AI），日期是 UTC 带 Z；不写用户名 |
| 版本递增与并发 | 并发 4 次确认得到 v1–v4，不撞号；`索引.json` 过契约 |
| 标题里的非法字符 | `/ \ : * ? " < > |` 在保存草稿时就被拒；结尾空格会被去掉；结尾点保留（`尾点.-v1.md`）；超长被拒；`CON`、`NUL` 生成的是 `CON-v1.md`，不是保留名，可以 |
| Markdown 去链接与保留出处 | 通过，变异后变红；三种漏网写法见 P3-4 |
| 只读与闸门 | 通过。原件区哈希不变；写入只经 `gate.write_bytes`；修订版落在 `草稿/采购合同-修订版-v1.docx`；深路径（案件根 131 字符，含中文）整套跑过 |
| 日志 | 通过。真服务跑了确认和修订版各一次，`service.log` 只有 module/op/status/case_id/ms 和 reason，标题、正文、修改内容、批注、材料名、"修订版"、"成果/"都搜不到 |
| 接口契约 | 通过。返回体逐字段过契约；缺字段、`formats:[]`、`template:"公文"` 都返回 `INVALID_ARGUMENT`；错误码都在 Spec 20.1 表里 |

## 对作者两条偏离的技术意见

**1. 原文含修订时返回 `INVALID_ARGUMENT`**
- 现有码里没有合适的：`MATERIAL_NOT_READY` 的提示是"待识别或处理失败"，`INPUT_CHANGED` 的提示是"材料被修改"，都会误导律师。
- 律师在界面上点"生成修订版"时，拿不到 AI 那边 `out_of_scope` 的原因，只会看到"请求参数有误"。
- 建议：同意作者的提议，在契约 1.4 加一个专用码（如 `ORIGINAL_HAS_REVISIONS`，提示用 Spec 原句）。1.4 之前维持 `INVALID_ARGUMENT` 作为过渡可以接受。同时按 P2-2 把检查范围补全。

**2. 找不到 pandoc 返回 `INTERNAL`**
- 合理。`CONVERTER_UNAVAILABLE` 的提示专指转 PDF；`TEMPLATE_MISSING` 名不副实；pandoc 随安装包分发，缺了就是安装坏了，"联系技术支持"是对的处置。业务错误照常返回 HTTP 200。
- 不建议为此加码。可选：把 pandoc 是否就位放进 `/health` 或启动自检（T20）。

另外 13 条偏离里其余各条，代码与作者自述一致。

## 八项清单
- 契约一致：通过
- 边界输入：不通过（P2-1、P3-2、P3-3、P3-4）
- 错误路径：部分通过（P3-1、P3-2 会出 500）
- 日志不含正文：通过
- 路径闸门未被绕过：通过
- 无外连：通过（raw openxml 那条见 NOTE-1）
- 测试覆盖新代码：部分通过（P3-5，变异 22 个里 6 个仍绿）
- 无机密入库：通过

## 实际跑过的命令
- `test_export.py` + `test_redline.py`：33 passed（C 的 venv 加 `-B`，环境变量指到临时短路径，`LAWBENCH_PANDOC` 指本机 pandoc）。
- 全量（短路径副本）：1086 passed / 6 skipped / 1 failed。失败的是 `test_tokenizer_json_ignored_by_git`，原因是导出副本不是 git 仓库（报 `fatal: not a git repository`）；在 rv-C19 克隆里单跑这一条通过。折算后与作者报的 1087 passed / 6 skipped 一致。
- 变异 22 个（单条超时 1800 秒，Start-Process + WaitForExit 兜底）：
  - 作者 4 个复现，全红：去掉 --sandbox、原文有修订照做、不去工作区链接、不判范围。
  - 我自做 18 个，其中 12 个红：出现多次改第一处、版本号只看索引不看成果目录、不登记批注内容类型、Word 草稿也允许要 md、引用式链接不处理、删除时 `w:t` 不改 `w:delText`。另 6 个仍绿，见 P3-5。
  - 每次都逐字节复原，65 个源文件哈希与变异前一致。
- 实验脚本：`exp_lib.py`（库层边缘）、`exp_api.py`（接口、并发、标题、链接、坏 docx、深路径、自建监听）、`exp_live.py`（真服务，端口 19471/19472；6000D、395 两组地址都设成 127.0.0.1:19478/19479 死端口，没调测试连接）、`exp_tpl.py`（模板与成品）、`exp_lo.py`（LibreOffice 转换）、手动跑了一次 pandoc 验 raw openxml。

## 残留审计
- 我起的进程（真服务 36852、各次 pytest、各个实验脚本）都已退出。机器上现存的 python 进程属于别的会话（线 C 的 42280/46032 等）。
- `soffice.bin` 10028、42468 没动过。
- 端口 19471–19479 都没有在监听。
- 临时短路径 `C:\Users\<用户>\AppData\Local\Temp\claude\rvC19s` 已删除（深路径部分用 `\\?\` 前缀才删掉）；实验目录里的导出源码副本 `src` 已删除。
- 实验脚本和输出留在 `C:\Users\<用户>\AppData\Local\Temp\claude\D--lawbench\780b8a59-…\scratchpad\rv-C19-T15-lab\`，主要文件有 `exp_lib.txt`、`exp_api.txt`、`exp_live.txt`、`exp_tpl.txt`、`exp_lo.txt`、`mutate.txt`、`mutate2.txt`、`full.txt`。
- 没有写入任何仓库，也没碰协调目录。

## 证据缺口
- 没有在 Word 或 WPS 里实测（G-10 按工单放在 T22）。
- NOTE-1 没在 Word 里验证是否会真的联网。
- 加密 docx 用的是伪造的 CFB 文件头，不是真加密文件。

AMEND
﻿
---

## 第二部分 主编排裁决（2026-10-01 22:58 (+08:00)，无人值守窗）

**结论：AMEND，返修一轮，清单冻结。** 导出、`--sandbox`（八种外链写法 0 请求）、模板干净、版本并发、索引契约、闸门、日志 0 泄漏、修订件结构与"其余字节不变"全部通过。

| 编号 | 裁决 |
|---|---|
| P2-1 带制表位的段落一律进"需人工修改"且原因错 | 必修：`tools/edit_list._para_chars`（与 `dx._text`）遍历跳过 `w:pPr`/`w:rPr` 子树；用例"带制表位段落能替换" |
| P2-2 已有修订只查 document.xml | 必修：遍历 `word/` 下所有部件（页眉/页脚/脚注/尾注/批注）查 ins/del/moveFrom/moveTo 与各类 `*PrChange`；`edit_list._paragraphs` 用同一函数；用例 |
| P3-1 DOCTYPE 损坏 docx → 500 | 一并做：接住 `dx.ParseError` → `MATERIAL_NOT_READY`（`save_edit_list` 同） |
| P3-2 控制字符 → 500 | 一并做：过滤或进"需人工修改" |
| P3-3 重复 id | 一并做：redline 遇重复 id → `INVALID_ARGUMENT` |
| P3-4 去工作区链接三种漏网 | 一并做：循环到不变、尖括号目标允许空格、`href` 一并 |
| P3-5 六处变异不红 | 一并做：作者常量、日期格式、日志无标题、案件锁、索引失败回滚、原文一致检查各补断言 |
| NOTE-1 `{=openxml}` 原样写入 | 一并做（一行）：`-f markdown-raw_attribute-raw_html-raw_tex` |
| NOTE-3 python-docx 不在 test 依赖 | 一并做 |
| NOTE-2 超链接后 insert_after 进入链接 | 独立后续或进"需人工修改"——线 C 选一写明 |

偏离两条（主编排定）：①原文含修订 → 1.4 加专用码 `ORIGINAL_HAS_REVISIONS`（随 N45 一起），1.4 前维持 `INVALID_ARGUMENT`、交付说明写明；②找不到 pandoc 用 `INTERNAL`——接受，pandoc 就位检查记 T20 启动自检。其余 11 条按交付说明默认做法。