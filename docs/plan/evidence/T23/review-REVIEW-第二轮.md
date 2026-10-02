# T23 Word 转 PDF 与案卷归档 · 独立复核记录（第二轮：返修后累计范围 + T15 第二轮六条记录项）

- 复核员：一名 Opus 5.5 只读复核员（换人）
- target：line-C `a0cb9e5`（基座 main 28f7da1）；T23 累计 `10b846f`、`31f4d53`、`fd267eb`、`9d30eb6`、`b13d2e5`；T15 记录项 `a0cb9e5`
- 冻结清单：`review-REVIEW.md` 第二部分；T15 注记 0110 六条
- 复核克隆：scratchpad `rv-C22`
- 归档：主编排于 2026-10-02 09:30 (+08:00) 从复核员交回原文抄录，未改内容（无人值守窗）

## 第一部分 复核员原文
## T23 返修累计范围 + T15 第二轮六条记录项 · 独立复核（rv-C22）

我查的是 line-C `a0cb9e5`，基座 main `28f7da1`。复核克隆 `rv-C22` 的 HEAD 已核对为 `a0cb9e551ad4…`，detached，工作区干净，merge-base 是 `28f7da1`。实验在 `git archive a0cb9e5` 导出的三份副本里做（src、mut、probe），用 Python 的 tarfile 解压：Windows 自带的 tar.exe 会把中文文件名弄乱。导出共 1442 个文件，只比 `ls-files` 少一个子模块 `dsh`。仓库没有任何写入。

### 结论

- **两条 P1 都关闭了，我自己复现过：**
  - 上一轮的端到端探针原样重跑：外链 `.doc` 改名 `.docx`，导入是 failed，放进方案后生成，**监听收到 0 个请求**，假 Word 只转了结案报告。
  - 上一轮的预检矩阵 12 行：11 行判为 True，外部超链接那一行是 False，和设计一致。
- 冻结清单其余各项都做到了，有用例守着。
- 发现的新问题全是 P3 或 NOTE，没有外连，也没有阻断。

---

### 发现的问题

**P3-A 文档里的网页部件坏了，生成接口直接报"内部错误"**
- **问题**：新加的 `convert._altchunk_external` 用 `z.read(n)` 读压缩包里的 `.html` 部件。这个部件校验和不对、或者标成加密时，抛出的是 `BadZipFile` 或 `RuntimeError`。`word_has_external` 只接住 `ParseError` 和 `OSError`，`_lo` 只接住 `ParseError`，所以异常一路抛到接口外面。
- **影响**：
  - 这类文件导入时状态是 `parsed`，保存方案也通过。到生成时整次报 `INTERNAL`（HTTP 500），没有任何提示说是哪份材料出了问题。
  - 好在是"拒绝"这一边：没有交给任何转换程序（假 COM 0 次调用），临时目录清空了，日志里也没有材料名。
- **证据**：
  - `quick.py`：`word_has_external RAISE BadZipFile Bad CRC-32 for file 'word/c.html'`；标成加密的那份是 `RAISE RuntimeError ... is encrypted`。
  - 端到端探针 `test_zz_rv22.py::test_e2e_crc_bad_html_part`：导入 `('docx','parsed')`，保存 ok，生成 `500 {"code":"INTERNAL"}`，`com=[]`，临时目录剩 0 个，`name-in-log False`。
- **最小修复**：`_altchunk_external` 里把读取包起来：`try: data = z.read(n) except Exception: raise ParseError("unchecked")`。这样和 X2"查不了就不放行"同口径，结果是转不了，不是 500。
- **归类**：本次修正引入（P3）。

**P3-B 导入时通过、但生成时转不了的材料，会让整次生成失败，而且错误码让人误会**
- **问题**：下面两类材料导入状态都是 `parsed`，保存方案时没有任何提醒，生成到它时整次失败：
  - 带外链图片的 xlsx：14.3 ②b 不交给 LibreOffice；
  - 带外部地址的 altChunk docx：本次新加的检查。
- 返回的错误码是 `CONVERTER_UNAVAILABLE`，提示文字是"无法把文件转成 PDF，请在 Word 或 WPS 中另存为 PDF"。律师看不出是哪一份，也看不出是因为外链。
- **证据**：`test_e2e_parsed_but_unconvertible`：
  - `xlsx 外链（parsed）`：保存 True，没有相关提醒；生成 `ok=False CONVERTER_UNAVAILABLE`，0 个请求。
  - `docx altChunk 外链（parsed）`：结果同上。
- **最小修复**：按 P1-1 的口径，转换时拒绝的材料也当作"跳过并写明"，记进 `skipped`。或者在 `check_plan` 里先跑一遍同样的预检并给提醒。
- **归类**：
  - xlsx 那种是此前既有。第一轮已有这个行为，这次 `.xls` 外壳也变成这样，是 NOTE-3 的预期结果。
  - altChunk 那种是本次引入的新触发面。
  - 两种都只是失败方式的问题，不是安全问题。

**P3-C altChunk 补检只覆盖了最直白的一种写法**
- **问题**：下面 6 种写法 `word_has_external` 都判为 False，也就是会交给 Word。只调了预检，按指令没有用真 Word 打开：
  - 部件扩展名写成 `.bin`、内容类型是 `text/html`；
  - `style="background-image:url(http…)"`；
  - MHT 的 quoted-printable 写法 `src=3D"http…"`；
  - 实体编码 `&#104;ttp`；
  - 无协议的 `//host`；
  - altChunk 指向 RTF 部件、里面写 INCLUDEPICTURE。
- **影响**：Word 对这些写法会不会联网，没有实测。交付说明说"补了 altChunk"，但"残留风险"一节没列这些写法。
- **证据**：`rv22-out.txt` 的 `altchunk ...` 七行，只有第一种是 True。
- **最小修复**（二选一）：
  - 压缩包里只要有 `aFChunk` 关系，就一律不交 Word/WPS，只走 LibreOffice。这是确定性的，比正则可靠，LibreOffice 走这条路实测 0 个请求。
  - 或者把这 6 种写进残留风险，候 owner 知悉（N57）。
- **归类**：独立后续。主编排的令只要求"能低成本补的补"，作者已按令做了最低一档。

**P3-D 两处"查加密"没有用例守**
- **问题**：下面两处删掉"查加密"后，`test_convert` 加 `test_archive` 仍是 45 passed：
  - R3：交 Word 前，OLE 分支不查加密；
  - R5：交 LibreOffice 前，表格类 OLE 分支不查加密。
- **影响**：实际风险低。加密材料导入时就是 failed，生成时 P1-1 会跳过。但如果以后有人删掉这两行，不会有用例变红。
- **最小修复**：用 `fakes.minimal_ole(p, {"EncryptionInfo": b"x"})` 做 `.doc` 和 `.xls` 各一份，断言不交 Word，也不交 LibreOffice。
- **归类**：独立后续（测试补强）。

**P3-E T15 记录项 5 只修了一半：没有 `>` 的 `<a href` 仍是平方增长**
- **问题**：新的 `_HTML_TAG = <(/?)(a|…)\b([^>]*)>` 在每个 `<a` 处都要扫到下一个 `>`。如果全文都没有 `>`，每次都扫到文末。
- **证据**：`'<a href="https://example.com/x" ' * n`（不含 `>`）：
  - n=4000 时 3.6 秒，n=8000 时 14.5 秒，n=20000 时 91 秒；
  - 有 `>` 的版本，n=20000 只要 0.16 秒。
- **影响**：只会让导出这一个请求变慢，不会出错。实际要 AI 输出几十万字符的畸形 HTML 才会碰到，概率低。
- **最小修复**：`[^>]*` 改成 `[^<>]{0,2000}`，同时限制属性长度。
- **归类**：此前既有，本次没修全。旧正则同样是平方增长。

**NOTE-1 T15 记录项 1 的残余**
- 在复杂域 HYPERLINK 里，如果链接文字后面先跟一个空 run（`<w:r><w:rPr><w:b/></w:rPr></w:r>`），再到域结束，`insert_after` 仍会被应用（`applied=[1]`），插入的文字会成为链接显示文字的一部分。
- 原因：`_ends_link` 只看下一个 `w:r` 是不是域结束。
- 修法：改成"往后找第一个含 `w:t` 或 `fldChar` 的 run"。
- 归类：臆测级，Word 很少这样写。

**NOTE-2 跳过材料的提示写错了原因**
- 跳过的材料一律提示"读不了（加密或损坏）"（`build.py` 第 256 行）。因为有外链被拒的材料，也显示成"加密或损坏"。保存方案时的提醒是对的（"加密、读不了或有外链"）。
- 建议两处说法统一。

**NOTE-3 P3-2 的拒绝信息太泛**
- `.md` 材料被拒时，返回的是 `INVALID_ARGUMENT`，提示"请求参数有误"，`not_convertible` 只写进日志。模型和律师都不知道是哪一份、为什么。
- 主编排要的是"拒绝并提示"，这里提示偏弱。

**NOTE-4 文档字符串过时**
- `convert.py` 文件头第 9–10 行还写着".doc / .wps、xlsx 交给它之前按 ②a、②b 查外链"，没跟上按文件头分流的改动。`_lo` 函数自己的说明是对的。

**另外核过、没有问题的：**
- 文件头边界：空文件、截断的压缩包、OLE 文件头后面是垃圾、PDF 文件头配 `.docx`、2 字节的 `.wps`，全部返回 `CONVERTER_UNAVAILABLE`，没有崩溃。
- txt/csv 冒充网页（`<body background>`、`<!DOCTYPE><td background>`、UTF-16 编码的 html、4KB 之后才出现的 html、`<meta refresh>`）经 LibreOffice 转换：**0 个请求**。
- 带外链图片的 docx 在 auto 下走 LibreOffice：0 个请求。
- xlsx 内容改名 `.docx`，以及 xlsx 叠一份 `word/document.xml` 的复合文件：都走 LibreOffice，0 个请求。

---

### 冻结清单逐条核对（review-REVIEW.md 第二部分）

| 编号 | 结果 | 我怎么核的 |
|---|---|---|
| P1-1 build 跳过 `_UNREADABLE` 材料；`_lo` 按文件头分流 | **关闭** | 上一轮 e2e 原样重跑：甲 failed，生成 ok，hits=0，com 只有结案报告；`ole-as-docx` 直接调用报 `CONVERTER_UNAVAILABLE`、hits 0（上一轮是 libreoffice、hits 2）；我的变异 R1、R4 红 |
| P1-2 `word_has_external` 按文件头 | **关闭** | 预检矩阵：外链 docx 配 `.docx/.doc/.wps` 都是 True；RTF、HTML 配 `.doc` 都是 True（不交 Word）；乙（docx 内容配 `.doc`）生成时 com 只有 1 次（结案报告），hits 0；我的变异 R2、R16 红 |
| NOTE-3 `.xls` 外壳 | **关闭** | 上一轮 probe3 现在是 `CONVERTER_UNAVAILABLE`、hits 0；变异 R7 红（失败方式见 P3-B） |
| P3-1 CropBox | **关闭** | 上一轮探针页码 y=125（裁切框下边 100 加 25）；变异 R11 红 |
| P3-2 `check_plan` 拒不能转换的类型 | **关闭** | md 保存时被拒、生成时被拒、0 次转换；变异 R10 红（提示偏弱，见 NOTE-3） |
| P3-3 `com_worker` 全参数断言 | **关闭** | 上一轮 M14、M15 现在变红；我的 R14、R15 也红；上一轮假 COM 的调用序列和用例断言逐项一致 |
| P3-4 空项去掉、必交项计缺失 | **关闭** | 变异 R8、R9 红；e2e"全部材料都跳过"：ranges 只剩 15，生成了缺失情况说明 |
| NOTE-1 `_com` 模块级锁 | **关闭** | 锁包住整个 `_run_worker` 和 `_reap`；变异 R12 红 |
| NOTE-2 altChunk 与残留风险 | **部分** | 补了 html/htm/mht 部件里的 src/href/data/background 一种写法（R13 红）；另外 6 种写法漏判，也没写进残留风险（P3-C） |
| 交付说明第 1、11 条改成事实 | **符合** | 和代码对照一致（第 11 条的提示措辞见 NOTE-2） |

### T15 六条记录项

| 项 | 结果 | 证据 |
|---|---|---|
| ① 链接末尾判断含 bookmarkEnd、proofErr 与 HYPERLINK 域 | 符合，有残余 | 三种情形的用例；作者变异"按 getnext"我复现为红（T1）；空 run 的残余见 NOTE-1 |
| ② 页眉修订 → 视为含修订 | 符合 | 用例直接查 `_paragraphs`；从 `case_save_edit_list` 到 out_of_scope 这条调用路径，已有用例 `test_edit_list_revised_and_errors` 和 `test_revised_original_rejected_whole` 守着 |
| ③ 格式版本 3 说明改成实情，加守护用例 | 符合 | `docx.py:148` 确实先 strip；说明和 `REFORMAT_TYPES` 一致；撤回到 2 变红（T3 复现） |
| ④ `_BAD_XML` 加孤立代理字符 | 符合 | 修改文字和批注里的孤立代理字符都进需人工；变异 T4 红 |
| ⑤ 不闭合 `<a>` 的耗时 | 部分 | 有 `>` 的 4000 个 0.03 秒；没有 `>` 的仍是平方增长（P3-E） |
| ⑥ `</iframe>`、`<object>` 残留 | 符合 | 大写、不带引号的写法也能去掉；变异 T6 红 |

作者的 6 个变异抽 4 个复现（T1、T3、T4、T6），都变红。

### 八项清单
1. **契约一致**：通过。没有增减字段。错误码 `CONVERTER_UNAVAILABLE` 和 `INVALID_ARGUMENT` 都是现有的。
2. **边界输入**：基本通过。文件头边界都不崩；html 部件损坏会报 500（P3-A）；没有 `>` 的 HTML 平方增长（P3-E）。
3. **错误路径**：基本通过（P3-A、P3-B）。
4. **日志不含正文**：通过。500 那条路径的日志里没有材料名，也没有部件名。
5. **路径闸门未被绕过**：通过。新写入都经过 gate，临时目录清空。
6. **无外连**：通过。所有实验监听都是 0 个请求。没有用真 Word。
7. **测试覆盖新代码**：基本通过。两处查加密没有用例（P3-D）。
8. **无机密入库**：通过。两个提交里没有 Key，也没有本机用户名，pytest 证据里的路径是 `D:\lawbench-C`。

### 改动纪律
逐个改动片段分了类，没有无关改动：
- **`b13d2e5`**：
  - build.py：CropBox / P1-1 / P3-4；
  - match.py：P3-2 / 提醒文字；
  - convert.py：import、锁、P1-2、altChunk、`_lo` 分流。`_lo` 里多做了文本类的文件头检查，超出了令的字面要求，但属于"other 不转"的同一意图，可以接受。顺带删掉了 `_RTF_LINK`：RTF 现在一律不交 Word，删了是合理的。
  - 测试 2 个文件、证据 3 个文件。
- **`a0cb9e5`**：pandoc.py（记录项 5、6）、redline.py（记录项 1、4）、测试 2 个文件、证据 3 个文件。

### 实际跑过的命令
- `git fetch`、`checkout --detach a0cb9e5`、`rev-parse`、`status`、`merge-base`；两个提交的 `show --stat` 和 `show`；用 `git archive` 导出，再用 tarfile 解压到 src、mut、probe 三份。
- `test_convert` + `test_archive` + `test_export` + `test_redline`：**101 passed / 1 skipped**（跳过的是真 Word 那条），250 秒。
- 全量（短路径，Start-Process + WaitForExit 1800 秒兜底）：**1154 passed / 1 failed / 7 skipped**，1165 秒。
  - 唯一的失败是 `test_tokens.py`：tokenizer.json 应被 gitignore 忽略。原因是导出副本不是 git 仓库。在复核克隆里单跑 `test_tokens.py`，7 passed。所以和作者报的 1155 passed / 7 skipped 等价。
- 第一轮探针 `test_zz_probe.py`、`test_zz_probe2.py`、`test_zz_probe3.py` 原样重跑（只改了输出路径）：8 passed。
- 我自己的探针 `test_zz_rv22.py`（A–I 九组）、`quick.py`。
- 变异共 36 条，全部逐字节复原，sha256 核对一致，事后 mut 目录整体哈希比对 0 差异：
  - 我的 20 条（`mutations22-result.txt`）：18 红，R3、R5 绿；
  - 第一轮 `mutate.py` 16 条原样重跑：16 条全红（含原来绿的 M14、M15）。
- 没有起真服务，没有用真 Word/WPS。监听只在 127.0.0.1 上：`CountingListener` 用随机端口；19511 只出现在我构造的样本地址里，没有实际监听。

### 残留审计
- 我起的 python 和 soffice 进程都已结束（按命令行里 `rvC22s`、`rv-C22-lab` 核过，0 个）。
- 机器上剩下的只有 9-29 的 soffice 10028、42468，没动。
- 端口 19511–19519 上没有监听。
- 短路径临时目录 `C:\Users\<用户>\AppData\Local\Temp\claude\rvC22s` 已删除：里面有一个超长路径的残留，用 `rd /s /q` 删掉了。系统临时目录里近 3 小时没有新的 `lblo-*` 残留。
- 复核克隆工作区干净。
- 实验目录按要求保留：`C:\Users\<用户>\AppData\Local\Temp\claude\D--lawbench\780b8a59-1849-4c63-905e-c6705fafa3f6\scratchpad\rv-C22-lab\`。
  - 探针输出：`probe-out.txt`、`rv22-out.txt`；
  - 变异结果：`mutations22-result.txt`、`mutations-result.txt`；
  - 全量结果：`full.txt`。

### 证据缺口
- P3-C 那 6 种 altChunk 写法，Word 是否真的会联网，没有实测（按令不用真 Word 打开含外链的样本）。
- WPS 本机没有，未测。
- 打印机弹窗、真 Word 那条用例，候真机验收（T22）。

PASS
﻿
---

## 第二部分 主编排裁决（2026-10-02 09:30 (+08:00)，无人值守窗）

**结论：PASS，T23 任务门=过；T15 六条记录项收货。** 两条 P1 独立复现关闭（上轮 e2e 探针 0 请求、预检矩阵 11/12 True、改名 .doc 不再交 Word）；冻结清单其余全关，上轮 16 条变异全红（含原绿的 M14/M15）；文件头边界与 txt/csv 冒充网页经 LibreOffice 0 请求。

记录项（不阻断，注记交线 C 一个小提交，主编排亲核）：
| 编号 | 裁决 |
|---|---|
| P3-A html 部件 CRC 坏/加密 → 500 | `_altchunk_external` 读取包 try → `ParseError("unchecked")`，与 X2"查不了就不放行"同口径 |
| P3-B 导入 parsed 但生成时转不了 → 整次 `CONVERTER_UNAVAILABLE` | 按 P1-1 口径：转换时拒绝的材料也"跳过并写明"进 `skipped`；`check_plan` 先跑同样预检给提醒 |
| P3-C altChunk 六种写法漏判 | **主编排定**：压缩包里只要有 `aFChunk` 关系，一律不交 Word/WPS、只走 LibreOffice（确定性；LibreOffice 路径实测 0 请求）；六种写法写进交付说明残留风险，随 N57 |
| P3-D 两处"查加密"无用例 | `minimal_ole` 加 EncryptionInfo 的 .doc/.xls 各一例，断言不交 Word 也不交 LibreOffice |
| P3-E `_HTML_TAG` 无 `>` 时平方增长 | `[^>]*` → `[^<>]{0,2000}` 并限属性长度 |
| NOTE-1 复杂域 HYPERLINK 后空 run | `_ends_link` 改"往后找第一个含 w:t 或 fldChar 的 run" |
| NOTE-2 跳过原因文字 | 与保存方案提醒统一（"加密、读不了或有外链"） |
| NOTE-3 `.md` 拒绝提示太泛 | 返回体 `message` 写明哪份材料、为何不可转换（错误码不变） |
| NOTE-4 `convert.py` 文件头文档字符串过时 | 改 |

合流：随 line-C 整体（T12 候 N56）。Spec 14.3 ③（真 Word 关 UpdateLinksAtOpen 仍按链接取图；外链预检按文件头分流）由主编排合并时回写。