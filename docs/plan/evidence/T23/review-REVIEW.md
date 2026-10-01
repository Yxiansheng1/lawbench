# T23 Word 转 PDF 与案卷归档 · 独立复核记录（第一轮）

- 复核员：一名 Opus 5.5 只读复核员
- target：line-C `9d30eb6`（基座 main 28f7da1）；范围 `10b846f`、`31f4d53`、`fd267eb`、`9d30eb6`
- 复核克隆：scratchpad `rv-C21`
- 归档：主编排于 2026-10-02 00:53 (+08:00) 从复核员交回原文抄录，未改内容（无人值守窗）

## 第一部分 复核员原文
## T23 复核报告（Word 转 PDF 与案卷归档，line-C `9d30eb6`，基座 `28f7da1`）

复核克隆 `rv-C21` 的 HEAD 已核对：`9d30eb6128c2…`，detached，工作区干净；merge-base 是 `28f7da1`。复核范围是 `10b846f`、`31f4d53`、`fd267eb`、`9d30eb6` 四个提交，`45743ea` 不在范围内。所有实验都在 `git archive` 导出的副本里做（`scratchpad\rv-C21-T23-lab\`），仓库本身没有写入。

---

### 发现的问题

**P1-1 被导入环节拒掉的外链文档，归档生成时照样被转换，实测发出 2 个请求**
- **问题**：导入时因为"有外链图片"被标成 `failed` 的材料，放进归档方案后照样会被转换。原因有两层：
  - `check_plan` 对 `failed` 只给一条提示（"生成卷宗时转不了"），`build._build` 不拦。
  - `convert._lo` 只看扩展名是不是 `.doc`/`.wps` 才查外链。所以一份旧版 `.doc` 改名成 `.docx`，就不经检查直接交给 LibreOffice。
- **影响**：Spec 14.3 和 N17（"查到外链就拒绝"）在归档这条路上失效。对方埋的链接会把本机地址和时间发出去。另外，交付说明第 11 条写的"读不了的材料跳过并写明"，和代码实际行为不一致。
- **证据**：探针 `probe\service\tests\test_zz_probe2.py::test_e2e`。样本是 LibreOffice 生成的带外链图片的 `.doc`，改名为 `对方证据甲.docx`。导入结果是 `status=failed`，原因 external_link，导入时 0 个请求。把它放进方案保存，保存成功，只给了一条提示。然后调 `/api/archive/build`（设置 auto，Word 用假子进程）：返回 `ok=True`，**127.0.0.1 监听收到 2 个请求**。直接调用的对照结果：`ole-as-docx auto converter libreoffice hits 2`；同一份文件扩展名为 `.doc` 时报 `CONVERTER_UNAVAILABLE`，0 个请求。
- **最小修复**：
  - `build._build` 取原件前加：`if by_name[name]["status"] in am._UNREADABLE: skipped.append(name); continue`。也可以改成在 `check_plan`（生成时调用）直接拒绝。
  - `convert._lo` 改成按 `detect.content_kind` 分流：OLE 一律先查加密和 `has_external_picture`；`other`（RTF、HTML 冒充 Word 文档）一律不转。
  - 补一条带监听的用例。
- **归类**：范围内阻断。

**P1-2 改个扩展名就能绕过"交给 Word 前查外链"**
- **问题**：`word_has_external` 也是按扩展名分流。docx 内容、扩展名写成 `.doc`/`.wps` 的文件，会走二进制检查，结果返回 False，于是交给 Word。这类文件导入时状态是 `parsed`，没有任何提示。
- **影响**：作者自己在 `printer.txt` 里实测过，Word 关了 UpdateLinksAtOpen 也会按 `r:link` 取图（8 个请求）。默认设置 auto 加上律所电脑装着 Word，交付说明第 1 条的修复就被改名轻易绕过。
- **证据**：
  - 预检矩阵（`test_zz_probe.py::test_precheck_matrix`）：同一份外链 docx，扩展名 `.docx` 返回 True，`.doc` 返回 **False**，`.wps` 返回 **False**。RTF 或 HTML 内容配 `.doc` 扩展名也都返回 False。
  - 端到端：`对方证据乙.doc`（docx 内容）导入状态 `parsed`；生成时假 COM 日志是 `['Word.Application','Word.Application']`，一次是这份材料，一次是结案报告。也就是说，这份材料确实交给了 Word。
  - 按指令没有用真 Word 打开它，请求数没有亲测。
- **最小修复**：`word_has_external` 开头改成按文件头分流：
  ```python
  kind = detect.content_kind(path)
  if kind == "ole": return detect.ole_encrypted(path) or links.has_external_picture(path)
  if kind != "zip": return True   # RTF/HTML/其他：不交 Word/WPS
  # 以下照旧查 OOXML
  ```
  补一条用例：外链 docx 改名 `.doc`，在 auto 下断言假 Word 没有被调用、监听 0 个请求。
- **归类**：范围内阻断。

**P3-1 卷宗页码在部分扫描件上看不见**
- **问题**：页码层按 MediaBox 定位，没有用 CropBox。CropBox 比纸面小的扫描件，"第x页"会画在可见区域外面。
- **证据**：`test_zz_probe.py::test_cropbox` 里 CropBox 下边设在 100，页码画在 y=25。
- **影响**：这类页面上看不到页码。
- **最小修复**：`number_pages` 里 `box = page.cropbox`。
- **归类**：独立后续。

**P3-2 `.md` 材料让整次生成失败**
- **问题**：`.md` 是合法的材料类型，保存方案时也收；但生成时才报 `INVALID_ARGUMENT not_convertible`，而且是在前面的材料都转完之后才失败。
- **证据**：探针 e2e 里 md 那一组：保存 `ok`，生成返回 `ok=False INVALID_ARGUMENT`。
- **最小修复**：在 `LO_ONLY` 里加 `.md`；或者让 `check_plan` 拒绝不能转换的类型，并给出提示。
- **归类**：独立后续。

**P3-3 `com_worker` 没有用例守**
- **问题**：
  - 变异 M14（`AddToRecentFiles=True`）没被抓住，`test_convert` 加 `test_archive` 共 31 passed。
  - 变异 M15（`ReadOnly=False`）也没被抓住。
  - 我用假 win32com 模块核过当前的调用，都是对的：`DispatchEx`、`Visible=False`、`DisplayAlerts=0`、`AutomationSecurity=3`、`UpdateLinksAtOpen` 先关后恢复为原值、`Open(src, False, True, False)`、`ExportAsFixedFormat(out, 17)`、`Close(0)`、`Quit(0)`，没有调用 PrintOut。
- **最小修复**：把探针 `test_com_worker_fake` 的写法收进 `test_convert`，断言上面这些参数。
- **归类**：独立后续，测试补强。

**P3-4 整项材料都读不了时，申请书和归档目录还把它当已归档**
- **问题**：方案里某一项的材料全都跳过了，这一项在立卷申请书和归档目录里仍然列为"已归档"，只是页码为空。必交项因此不算缺失，也就不会生成缺失情况说明。
- **最小修复**：没有 `ranges` 的项从申请书里去掉；如果是必交项，计入 `missing`。
- **归类**：独立后续。P1-1 修好后，这种情况会少很多。

**NOTE-1 收尾可能误杀别人的 Word**
- `_reap` 会结束"转换期间新出现、父进程是 svchost"的所有 Word/WPS 进程。生成接口没有串行锁，两次生成同时跑，或者其他软件在这段时间里用自动化方式启动了 Word，都可能被误杀。
- 建议：在 `OfficeConverter._com` 外面加一把模块级锁，让 COM 转换一次只做一个。
- 归类：臆测，没有实测。

**NOTE-2 预检查不到的几种写法**
- 探针结果都是 False：
  - 二进制 `.doc` 里的附加模板路径；
  - RTF 的 `\*\template`；
  - docx 的 altChunk（内嵌 HTML 里 `img src=http`）；
  - Word 常见的拆组写法 `fldinst`：`.rtf` 分支的正则漏判，不过 `.rtf` 不是材料类型，暂时碰不到。
- Word 会不会对这些写法联网，没有实测。docx 的附加模板外部关系、页眉 rels 外部图片都能拦住，外部超链接按设计放行，也都核过了。
- 建议写进候 owner 的残留风险清单。

**NOTE-3 `.xls` 外壳的检查也是按扩展名**
- 扩展名 `.xls`、内容是带外链图片的 xlsx，`_lo` 不查外链（同样按扩展名分流）。实测导出 PDF 时 0 个请求，没有发现外连。
- 建议随 P1 一起改成按文件头分流，和 T5 X1 的口径保持一致。

**NOTE-4** STSong-Light 不嵌入字体，交付说明第 13 条已写明、候定，和代码一致。

---

### 重点逐条核对

| 项 | 结果 |
|---|---|
| 转换顺序 Word → WPS → LibreOffice；指定程序时只用它 | 符合（M1 红） |
| 120 秒超时，杀子进程树（`procs.kill_tree`），收尾结束 COM 启动的进程 | 符合（M2、M12 红） |
| 只打开 `工作区\临时\` 下的副本；AddToRecentFiles=False；返回实际用的程序 | 符合（假 COM 核过）；但没有用例守，见 P3-3 |
| 外链预检的覆盖面 | 部分：OOXML 各部件的外部关系都覆盖了；按扩展名分流可以绕过（P1-1、P1-2） |
| 开发机情况 | 有 Word，没有 WPS（`printer.txt`）；复核期间没有用真 Word |
| `CONVERTER_UNAVAILABLE` | 用的是现有码（`common.schema.json`、`errors.py`） |
| 匹配四条规则 | 符合 Spec 12.4，也和原版第三步"最具体优先"一致（M4、M5 红） |
| closed-01 匹配结果 | 和卡上一致：三份证据按文件夹归到 7；`~$起诉状.docx` 和微信图片都在 `ignored` |
| 归档目录 | 4 个卷类目录都通过 `archive_catalog` 校验；`check_examples --skills skills` 全对 |
| 归档方案 | 契约校验、写入路径、缺失必交项（M6 红）、`MATERIAL_NOT_FOUND` 都符合 |
| result 为 null | 返回 `PLAN_NOT_CONFIRMED`，不建文件夹（M9 红） |
| 卷宗页码 | 证据里的卷宗共 10 页 = 1+1+1+1+3+2+1；每页都有"第i页 共10页"；立卷申请书的 p1…p10 和 `page_ranges` 逐项一致（M7、M13 红） |
| 同名文件夹 | 加 `-v2`，旧的不动（M8 红） |
| 索引写入 | 只有 `outputs.index_update` 一个写入口，没有第二份 |
| 原件与临时目录 | 原件 sha256 不变（M10 红）；`工作区\临时` 用完为空（M11 红） |
| 闸门与日志 | 写入都经过 gate；日志只有元数据（转换失败原因都是码，不含材料名） |
| 证据 | `closed-01-output` 是虚构内容，没有用户名，没有 Key |
| 改动纪律 | 最小：ui.py +4 行、app.py +2 行、tools 注册 +2 行，outputs.py 是按令抽出公共函数 |

交付说明"需要主编排知道的"13 条，和代码对照：第 1 条有可绕过的口子（P1-2）；第 11 条和实际行为不一致（P1-1）；其余 11 条和代码一致。

### 八项清单
1. **契约一致**：通过。
2. **边界输入**：不通过（改名文件、`.md` 材料、CropBox）。
3. **错误路径**：基本通过（P3-4 除外）。
4. **日志不含正文**：通过。
5. **路径闸门未被绕过**：通过。
6. **无外连**：**不通过**，实测 2 个请求（P1-1）。
7. **测试覆盖新代码**：部分通过（`com_worker` 没有用例，P3-3）。
8. **无机密入库**：通过。

### 实际跑过的命令
- `git rev-parse`、`git status`、`git merge-base`、逐提交 `git show --stat`；用 `git archive 9d30eb6` 导出到 lab。
- `test_convert.py` + `test_archive.py`：31 passed / 1 skipped（跳过的是真 Word 那条）。
- 全量（短路径，1800 秒兜底）：**1133 passed / 1 failed / 7 skipped**。唯一的失败是 `test_tokenizer_json_ignored_by_git`，原因是导出副本不是 git 仓库；在复核克隆里单跑这一条是 1 passed，所以和作者的 1134 passed / 7 skipped 等价。
- 探针 `test_zz_probe.py`、`test_zz_probe2.py`、`test_zz_probe3.py`：外链只指向 127.0.0.1；Word 一律用假子进程或假模块，没有启动真 Word/WPS。
- 变异 16 条（`mutate.py`，结果在 `mutations-result.txt`）：14 条变红，2 条没被抓住（M14、M15，都在 `com_worker`）。每条改完都逐字节复原，sha256 核对一致。
- `contracts\check_examples.py --skills skills`：全对。

### 残留审计
- M2 变异留下的假孙进程（PID 45500 及其子进程 9060），已核对是本次复核 `com.pids` 里记的 PID，按 PID 结束。
- 我起的 python 和 soffice 进程都已结束。机器上剩下的 soffice 10028、42468（9-29 的）和 35472/33516（另一名复核员 `rvC20s` 的）都没动。
- 我没有起监听端口；探针里的监听都在用例内关闭了。
- 短路径临时目录 `rvC21s` 已删除。lab 目录按要求保留。

### 证据缺口
- 没有用真 Word 验证 P1-2 的请求数（按指令不做），用的是作者 `printer.txt` 的实测加上假 COM 调用链。
- WPS、打印机弹窗、`find_leaks` 都是候真机，和作者写的一致。
- NOTE-2 那几种写法 Word 是否会联网，没有实测。

AMEND

报告里提到的路径：
- 实验目录：`C:\Users\<用户>\AppData\Local\Temp\claude\D--lawbench\780b8a59-1849-4c63-905e-c6705fafa3f6\scratchpad\rv-C21-T23-lab\`
- 被评代码：`service\lawbench\office\convert.py`、`service\lawbench\office\com_worker.py`、`service\lawbench\archive\build.py`、`service\lawbench\archive\match.py`
- 探针：`rv-C21-T23-lab\probe\service\tests\test_zz_probe*.py`
- 探针结果：`rv-C21-T23-lab\probe-out.txt`（每跑一个探针会覆盖一次，以上面写的输出为准）
- 变异结果：`rv-C21-T23-lab\mutations-result.txt`

AMEND
﻿
---

## 第二部分 主编排裁决（2026-10-02 00:53 (+08:00)，无人值守窗）

**结论：AMEND，返修一轮，清单冻结。** 匹配四条规则、归档方案、生成第 1–8 步（10 页卷宗页码与申请书逐项一致）、`-v2`、索引单一写入口、原件哈希不变、临时目录清空、闸门、日志、证据无机密全部通过；转换顺序/超时杀树/收尾符合。

| 编号 | 裁决 |
|---|---|
| P1-1 导入时因外链被拒的材料，归档生成照样转换（实测 2 个请求）；`_lo` 按扩展名分流，`.doc` 改名 `.docx` 就不查 | 必修：`build._build` 对 `status in _UNREADABLE` 的材料跳过并写明（与交付说明第 11 条一致）；`convert._lo` 按 `detect.content_kind` 分流：OLE 一律查加密与 `has_external_picture`，`other`（RTF/HTML 冒充）一律不转；带监听用例 |
| P1-2 `word_has_external` 也按扩展名分流，docx 内容改名 `.doc`/`.wps` 就交给 Word | 必修：按文件头分流（`zip` 查 OOXML、`ole` 查加密与外链图、其余不交 Word/WPS）；用例"外链 docx 改名 .doc 在 auto 下假 Word 未被调用、监听 0 请求" |
| NOTE-3 `.xls` 外壳同样按扩展名 | 一并做：随 P1 改成按文件头，与 T5 X1 口径一致 |
| P3-1 页码按 MediaBox 不按 CropBox | 一并做：`number_pages` 用 `cropbox` |
| P3-2 `.md` 材料整次失败 | 一并做：`check_plan` 拒绝不可转换类型并提示（主编排选这条，不把 md 塞进 LO_ONLY） |
| P3-3 `com_worker` 无用例守 | 一并做：收探针 `test_com_worker_fake` 断言全部 COM 参数 |
| P3-4 整项材料都读不了仍列"已归档" | 一并做：无 `ranges` 的项从申请书去掉，必交项计 `missing` |
| NOTE-1 `_reap` 可能误杀别人的 Word | 一并做：`OfficeConverter._com` 模块级锁，一次只做一个 |
| NOTE-2 预检查不到的写法（.doc 附加模板、RTF template、altChunk、fldinst 拆组） | 残留风险记候 owner 知悉项 N57；T22 真机验收加一条 |
| NOTE-4 STSong-Light 不嵌入 | 与第 13 条一致，候定 |

交付说明 13 条：第 1 条有可绕过的口子（P1-2）、第 11 条与实际不一致（P1-1），其余与代码一致。Spec 14.3 ③"真 Word 关 UpdateLinksAtOpen 仍按链接取图"由主编排回写（合并时）。