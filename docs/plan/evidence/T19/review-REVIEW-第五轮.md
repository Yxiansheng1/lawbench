# T19 复核记录（第五轮：第四轮返修 + 第五步 N24）

- 复核员：一名 Opus 5.5 只读复核员（新人）
- target：`aaad8c18c2640326106a150b4c3ca57bb02f4f74`（line-C）；范围 `9e32a12..aaad8c1` 中 T19 的三个提交
- 复核克隆：scratchpad `rv-C7`；未碰 `D:\lawbench-C`
- 归档：主编排于 2026-09-30 13:13 (+08:00) 从复核员交回原文抄录，未改内容

## 第一部分 复核员原文
# T19 第四轮返修 + 第五步 独立复核（只读）

target 已亲自核对：复核克隆 `rv-C7` 的 `HEAD` 是 `aaad8c18c2640326106a150b4c3ca57bb02f4f74`，`git status --short` 为空。`9e32a12..HEAD` 共 5 个提交，范围内是 `05035ce`、`49904c8`、`aaad8c1`；`a288279`、`36b662d` 只改了 `prep395/deploy/README.md`（T11），不在范围。

**结论：F1、F3 和第五步都关闭了，没有 P0、P1、P2。** F1 这回关干净了，不用上报止损。剩下 4 条 P3 和 2 条备注，都不影响合并。

## 一、冻结清单与第五步核对表

| 编号 | 要求 | 结论 | 我怎么验的 |
|---|---|---|---|
| F1 | 配置目录删不掉，同时转换失败、超时或出意外异常时，失败原因里也带"转换程序的临时目录没能删除，下次启动时会再清理" | **关闭** | 没有用 monkeypatch 假装删不掉，而是在配置目录里**真的占住** `registrymodifications.xcu` 的句柄（Python 打开文件时不允许别人删），走 `convert_many`，共 5 种情况：<br>① 成功：提示在提示列表里<br>② 坏 docx，真 LibreOffice 报 `ConvertError`：原因是"转换失败…（另：转换程序的临时目录没能删除…）"<br>③ 卡住的假 soffice，超时设 3 秒："转换超时…（另：…）"<br>④ `_run` 抛出 RuntimeError："处理失败（程序内部错误）…（另：…）"，没有漏出异常内容<br>⑤ 我另加的：LibreOffice 成功之后 `shutil.move` 抛 OSError，同样带提示<br>红测：运行时把 `core.with_notes` 换成原样返回，②到⑤全部丢了提示，①不受影响。作者的 3 个 F1 用例同样变红（3 failed、2 passed），和作者的 `red-test-round4.txt` 一致 |
| F3 | 全部会调用 LibreOffice 的测试都不写真实的 `%LOCALAPPDATA%` | **关闭** | `conftest.py` 里的 fixture 是会话级、自动生效，替换的是 `core.profile_root`。grep 确认产品里没有地方用 `from .core import profile_root` 绕开它，界面测试也被覆盖。<br>两次全量验证：<br>① `LOCALAPPDATA` 指到一个拒绝写入的目录（icacls deny W,D,DC）：54 passed、9 skipped（8 个因为找不到 pandoc，1 个是 Tk 偶发），没有一条因为写不进去而失败<br>② 用真实的 `LOCALAPPDATA`：63 passed。跑之前和跑之后，`%LOCALAPPDATA%\lawbench` 递归的文件列表和修改时间完全一致。`logs\` 已排除，那是别的会话在写 |
| 第五步 | 按文件头判断旧版文件，用令里的提示原话，不启动转换程序，批量只跳过不中断，`.xls` 照常，小工具不再调用 `extlinks`，README 写明，测试四种输入加批量加红测 | **关闭**（有 P3 小瑕疵，见 F-2、F-4） | 用仓库现有的 `engines\…\format-corpus\license-old.doc`（文件头 `D0CF11E0A1B11AE1`）和 `license.docx`，只复制、改扩展名，走 `convert_many`：<br>- `.doc`、`.wps` 用 doc2docx 和 word2pdf，改名成 `.docx` 的 doc 用 word2pdf 和 docx2md：全部给出原话提示"暂不支持旧版 Word / WPS 文件。请用 Word 或 WPS 打开后另存为 .docx，再来转换。"，拦截到的 Popen 调用为 0，原文件哈希不变<br>- 混合批量 [正常1.docx, 旧版.doc, 其实是doc.docx, 正常2.docx]：第 1、4 个转换成功，第 2、3 个跳过并提示，Popen 调用恰好 2 次<br>- 改名成 `.doc`、`.wps` 的 docx：照常转换，同名文件得到"(2)"<br>- `.xls`（LibreOffice 从 xlsx 转出，文件头是 OLE）转 `.xlsx`：成功<br>- `git grep extlinks -- tools`：只剩注释、README 和 4 个直接测 `extlinks` 的留档用例，产品代码里没有 import 也没有调用<br>- `49904c8` 的开关常量 `LEGACY_WORD_ENABLED` 已经完全去掉，只剩一套判断（"不是 zip 就拒"）<br>- 红测：运行时把 `is_zip` 换成恒真，10 个相关用例变红，和作者的 `red-test-step5.txt` 一致 |

## 二、findings

**F-1（P3，本次引入，可维护性）：`is_zip` 的字面量里嵌着看不见的控制字符**
- 问题：`core.py:51` 源码看上去是 `f.read(4) == b"PK"`。按字节查，引号里其实是 `50 4B 03 04`，是直接写进文件的控制字符。
- 影响：现在能正常工作。但人读起来像是"4 个字节和 2 个字节比较、永远为假"的 bug。编辑器或格式化工具一旦把控制字符删掉，所有 docx 的 Word 类转换都会被拒。
- 证据：对 `core.py` 做十六进制检查，`b"` 后面是 `50 4B 03 04`。
- 最小修复：改写成转义形式 `b"PK\x03\x04"`。

**F-2（P3，本次引入，死代码）：`core.is_ole()` 在产品里没人调用**
- 问题：`is_ole()` 只被测试 `test_xls_still_converts_with_ole_header` 用到，实际的判断是 `not is_zip`。
- 影响：看代码的人会以为存在两套判断。
- 最小修复：把它挪进测试里，或者删掉。

**F-3（P3，本次引入，比令收得更紧，已披露）：非 zip、非 OLE 的文件也一律拒绝**
- 问题：执行令写的是"按文件头判断是 OLE 容器"就拒。实现是"不是 zip 就拒"，所以改了扩展名的 RTF、网页也会被拒，给的也是"旧版 Word / WPS"那句提示。
- 影响：方向更安全，只是提示对 RTF 不完全准确。
- 证据：交付说明 7.6 已写明这一点。
- 这属于偏离执行令，请主编排确认接受。我倾向于接受。

**F-4（P3，本次引入，界面文字）：界面和报错里还有"支持 doc/wps"的意思**
- 问题：下拉框里还有"doc / wps → docx"这一项；Word → PDF 的选择文件对话框仍然筛选 `*.doc *.wps`；扩展名不对时的提示是"不是这种转换能处理的格式（.docx、.doc、.wps）"。
- 影响：和"去掉支持 doc/wps 转换的说法"有点矛盾。选中这一项时下方会显示"暂不支持…"，律师不会被误导到转换出结果，只是多绕一步。
- 证据：我的实验输出 `reg.txt` 里 `[tail]` 那两行；`core.py:106`、`108`。
- 最小修复：doc2docx 这一项改名或隐藏；报错里不再把 `.doc`、`.wps` 列为能处理的格式。

**N-1（备注，本次引入的副作用，无害）：扫描页提示也会并进失败原因**
- PDF 转 Word 如果 pandoc 失败，"第 n 页是扫描页"这条提示也会以"（另：…）"的形式并进失败原因。读着有点怪，但没有危害。

**N-2（备注，此前既有）：界面测试偶发跳过**
- 第一次全量时 `test_gui_notes_and_close_guard` 因为 Tk 偶发问题跳过了（"没有图形界面环境"），第二次通过。作者在 7.5 节已经记过。

## 三、回归抽样（真实 LibreOffice，走 `convert_many`）

- 盘符路径总长 240：成功，第二次转出"材料(2).pdf"，原文件不变。
- `\\127.0.0.1\c$\…` 网络共享路径总长 240：成功，同名得到"(2)"，原文件不变。作者的 3 个网络共享用例在我第二次全量里也通过了。
- 文件名末尾带空格、带点：用中文拒绝，同一批里的正常文件照常转换。
- 系统临时目录下没有残留的 `lawbench-convert-*`，配置目录的上级也是空的。

## 四、全量测试

- 作者 `pytest.txt`：63 passed。
- 我的：
  - 用真实 `LOCALAPPDATA`：**63 passed，1 warning**（Pillow 的图片过大警告，此前就有），236.7 秒。
  - 用只读 `LOCALAPPDATA`：54 passed、9 skipped（8 个找不到 pandoc，1 个 Tk 偶发）。

## 五、实际跑过的命令（环境统一如下）

统一环境：`PYTHONDONTWRITEBYTECODE=1`；`TEMP`、`TMP` 指到 `C:\Users\<用户>\AppData\Local\Temp\claude\rvC7s\t`；解释器 `D:\lawbench-C\.venv\Scripts\python.exe`；已确认导入的 `convert` 来自 `rv-C7\tools`；没有设置 `LAWBENCH_*`。

1. `git rev-parse HEAD`、`git status --short`、`git log 9e32a12..HEAD`、`git diff 9e32a12 aaad8c1 -- tools docs/plan/evidence/T19`；对 `core.py` 做十六进制检查；各处 `git grep`。
2. `pytest -p no:cacheprovider --basetemp rvC7s\bt1 -rA -q tests`，`LOCALAPPDATA` 指到只读目录。
3. 同样的全量，`--basetemp rvC7s\bt2`，用真实 `LOCALAPPDATA`，前后各做一次快照（`snap1.txt`、`snap2.txt`），比对结果无差异。
4. `f1_lab.py`（占住句柄的 5 种情况）绿测一遍、红测一遍，输出在 `f1-green.txt`、`f1-red.txt`。
5. `pytest -p redplug -k "left_behind or profile_left"`：3 failed、2 passed。
6. `s5_lab.py`（四种输入、混合批量、改名 docx、xls），输出在 `s5-green.txt`。
7. `pytest -p redplug5 -k "legacy or each_conversion or refused or batch_with"`：10 failed、6 passed、4 skipped。
8. `reg_lab.py`（240 字符路径、网络共享、末尾空格或点、同名、残留），输出在 `reg.txt`。

实验脚本和输出都在 `C:\Users\<用户>\AppData\Local\Temp\claude\D--lawbench\780b8a59-1849-4c63-905e-c6705fafa3f6\scratchpad\rv-C7-lab\`。

## 六、残留审计

- 只剩 2026-09-29 的两个 `soffice.bin`（10028、42468），我没动；另外几个 `python.exe`（`e_s1.py`、`-m lawbench --port 18831`）是线 B 的，不是我起的。我起的进程都已退出。
- 真实 `%TEMP%` 下没有 `lawbench-convert-*`、`lbp-*`、`lbt-*`。
- 真实 `%LOCALAPPDATA%\lawbench`（不含 `logs`）和跑之前的快照一致。
- 只读目录的 deny 规则已撤掉，`rvC7s` 整个删了。
- 克隆工作区干净。没有写入任何受保护目录，没有新建或改写 `.doc`、`.wps`（只复制、改名仓库现有样本；作者测试自己在临时目录里生成的 `.doc` 除外）。

## 七、证据缺口

- 用 tasklist 按进程名监控 soffice 不可靠：复核期间别的会话也在起 soffice，只拦旧版文件的那一批里就冒出了 2 个新 PID（21164、37440），但我这边拦截到的调用是 0 次。所以"不启动转换程序"的证据依据的是拦截 `subprocess.Popen`（`core` 只通过它启动转换程序）加上作者用例里对 `_libreoffice` 的拦截，没有做按父进程过滤的进程级监控。
- 映射成盘符的网络驱动器仍然没有实测（按约定不做 `net use`）。
- 只读 `LOCALAPPDATA` 那一轮里，pandoc 相关的 8 个用例因为找不到 pandoc 而跳过；这部分由真实 `LOCALAPPDATA` 那一轮的快照比对补上了。

PASS（本结论不含外链检查的健壮性）

---

## 第二部分 主编排裁决（2026-09-30 13:13 (+08:00)）

**通过，合并 `main`。** 无 P0/P1/P2；F1 用真实占住句柄的方式验证了五种情况，F3 用只读 LOCALAPPDATA 和前后快照两种方式验证，第五步四种输入、混合批量、`.xls` 照常都有实测；红测与作者一致。

- **F-3（"非 zip 一律拒"比令收得更紧）**：接受。方向更安全，交付说明 7.6 已披露；提示文字对 RTF 不完全准确，归 F-4 一起改。
- **F-1、F-2、F-4**：作为小项交线 C，单独一个提交，不算返修轮次，随下一张卡一起复核。
- **N-1、N-2**：记录，不动。
- 证据缺口（映射网络驱动器未实测）写进台账已知限制。
- 合流门见 `docs\plan\evidence\T19\merge.txt`。