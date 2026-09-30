# T3 第四轮 / T5 第二轮 · Reviewer A（改动纪律与可维护性）

- target：`695191feddcf461309f38f285617952ea4a45ffd`（line-B，已 rebase 到 `main` `be6aef7`）
- 范围：T3 第三轮返修（S1 补漏、S6）+ T5 第一轮返修（X1–X13、Y1–Y9）+ 契约 1.2 服务侧归 T3/T5 的部分（N21、N26、N28、N35②、contract_version）
- 派发：两名 Opus 5.5 只读复核员同一条消息并发派出，素材相同，互相看不到
- 复核克隆：scratchpad `rv-B9`；未碰 `D:\lawbench-B`
- 归档：主编排于 2026-09-30 13:13 (+08:00) 从复核员交回原文抄录，未改内容

## 复核员原文
## 结论先说

- **T3 可以放行。** S1（服务器地址校验）这次查透了：我自己造了 40 个坏地址，全部被拒；PUT 64 例都拒绝且不写盘；测试连接没有一次出 500。S6 和契约 1.2 里 T3 负责的部分也都已关闭。只剩两条 P3，都不阻断。
- **T5 要返修，原因是一条 P2。** 契约 1.2 要求给 1.2 之前建的 `case.db` 用 `CREATE TABLE IF NOT EXISTS` 补建 `material_ids` 表，服务没有做。结果是：这类旧案件的编号留底完全不生效，`index.json` 重建后，旧编号会被别的材料占用。这正是上一轮 F9 要修的问题，在旧案件上原样复现了。X1–X13、Y1–Y9 其余各条都已关闭，我做的变异全部"改坏即红、复原即绿"。

## 发现（按严重度）

### P2-1（范围内阻断，T5 / N26、X11）旧 `case.db` 不补建 `material_ids` 表，编号仍会被复用
- **问题：** 1.2 之前建的案件，打开和扫描时都不补建 `material_ids` 表。编号留底静默失效，只记一行日志。
- **违反的不变量：** `contracts\case_db.sql` 文件头原文"schema_version 仍为 1……用 CREATE TABLE IF NOT EXISTS 补建即可"；契约 1.2 令 N26；Spec 4.1 "编号同一案件内不复用"。
- **原因：**
  - `service\lawbench\case\registry.py:148-155`：已有 `case.db`、`case_id` 存在、版本为 1 时直接 `return`，不执行建表脚本。
  - `service\lawbench\case\materials.py:766-775`：`_MaterialIds.__init__` 查不到表就把 `con` 置空、记日志，之后 `record`、`reuse`、`next_seq` 全部不起作用。
- **证据（实验副本，已删除）：**
  - 先按 1.2 建案件，再删掉 `material_ids` 表和它的索引，模拟 1.2 之前的 `case.db`；重开案件、扫描后，表名清单里仍然没有 `material_ids`。
  - 同一流程：`a.txt`→M0001、`b.txt`→M0002 → 删 `a.txt` 再扫描 → 删 `index.json` → 新增 `d.txt` 再扫描：
    - 旧库：`{'b.txt': 'M0001', 'd.txt': 'M0002'}`，b 被改号，并占用了已删的 a 的 M0001。
    - 1.2 新库对照：`{'b.txt': 'M0002', 'd.txt': 'M0003'}`，正确。
  - 测试只覆盖新建的 `case.db`：`material_ids` 在 tests 里只出现在 `test_t5_rework.py:607-615`。
- **影响：** 线 A、C 和验收机上已经建过的测试案件，升级后 N26 不生效；引用编号可能指向另一份材料。
- **最小修复：** 在 `_MaterialIds.__init__` 里（或 `registry._init_db` 的"已存在、版本 1"分支里）执行 `case_db.sql`。它全是 `IF NOT EXISTS`，可以重复执行。再补一个"旧库升级后拿回原编号"的测试，并做红测。

### P3（不阻断，建议随返修一起做）
1. **X6 按前缀清残留，匹配过宽（T5）。** `materials.py:424` 用 `startswith(("lo-","unzip-","imp-"))`。律师放在 `工作区\临时` 里、名字恰好以这几个前缀开头的文件会被删掉。
   - 实测：放入 `lo-委托合同.pdf`、`imp-截图.png`、`unzip-说明.txt`、`截图.png`，扫描后只剩 `截图.png`。
   - 返修令原文要求其他文件"不能动"。
   - 修法：改成完全匹配"前缀 + 8 位十六进制"，例如 `^(lo|unzip|imp)-[0-9a-f]{8}$`。
2. **T5 交付说明第 6 节在 HEAD 上与代码矛盾（Y9 没有保持"按现状"）。**
   - 第 122 行"Excel 写的是原始值……本轮不改"，第 123 行"纯扫描件的 Source 行写'文字版'……本轮不改"，而 X13 和 N28 已经改了。
   - 第 14.4 节第 6 条"note 留空"也被 N21 推翻了。
3. **格式版本号触发重扫的 PDF、图片分支没有测试。** `REFORMAT_TYPES` 里的 `pdf`、`image` 删掉后不会有任何测试变红；`test_x13_format_version_triggers_reparse` 只测了 xlsx 和 txt。
   - 另一个隐患：重扫时 `is_ocr` 会被写回 `"none"`（`materials.py:333`）。现在还没有识别功能，所以无害；T9 上线后若再升格式版本，会冲掉识别状态。这条算独立后续。
4. **`test_t5_contract12.py:41、63`** 在普通字符串里写了 `'\('`，全量运行时报 SyntaxWarning。以后的 Python 版本会把它当语法错误，应改成原始字符串。
5. **`dcc05ac` 提交时 `test_xls_no_request` 是红的**，由后一个提交 `81b24b2` 改断言才转绿，中间提交不干净。断言本身改得对：契约 1.2 N21 要求写这个 note，原来断言"为空"已经过时。我的全量已经覆盖了"只补跑 2 个测试"的缺口。
6. **`_scan` 里一次无功能变化的顺手重构（T5，`dcc05ac`）。** 把几个计数局部变量换成 `counts` 字典，最后再赋回局部变量，不影响行为。
7. **T3 测试会真的去连所内地址。** `test_t3_rework3.py:88`（`test_s1_put_f10_url_rejected_not_written`）在没有设置文件时调测试连接，会用默认的 192.168.8.77、192.168.8.124 真实发起 TCP 连接。归独立后续：测试应改用假的传输层。
8. **NOTE：** `server_url_ok` 接受超过 63 字符的标签和 `[::ffff:127.0.0.1]` 这类写法。实测 probe 按"不通"处理、接口不出 500，不算 S1 的漏洞。新证据 `T5\pytest-返修第一轮.txt` 第 15 行含本机用户名路径，不算机密，只提一句。

## T3 冻结清单

| 编号 | 结论 | 依据 |
|---|---|---|
| S1 补漏 | 关闭 | `net.py:55-94` 的 `server_url_ok`，`check_servers` 第 151 行调用，probe 第 185-187 行接住所有异常。<br>我自造 40 个坏地址全部被拒：`user@`、`\`、`%2e`、十进制 IP、`0x7f.1`、`0x7f000001`、`0177.0.0.1`、尾点、首尾空格、零宽字符、全角端口、`。` 句号、NBSP、`[fe80::1%eth0]`、`[v1.fe]`、`:+80`、`:-1`、双端口、`http:\\`、无协议头、CRLF 注入等。<br>16 个地址 × 4 个字段 = 64 例 PUT：都是 `INVALID_ARGUMENT`，没写 `settings.json`。<br>坏地址进了内存后测试连接 18 例：都是 200。<br>变异：去掉控制字符和非 ASCII 检查 → 红 2 个，复原 → 绿；去掉 probe 的兜底 → 红 4 个，复原 → 绿 |
| S6 | 关闭 | 第 5 行现在是 `b8fa6b2`（rebase 后），注明了 rebase 前 `e58454b` 和误写的 `5864fc1`；第 11 节有 24 行对照表 |
| 1.2：N35② 胶囊 `new` | 关闭 | `capsules.py` 只给新补进来的胶囊标 `new`，测试覆盖了"PUT 后清掉" |
| 1.2：`contract_version` | 关闭 | `/health` 读 `contracts\VERSION`，得 1.2；两处测试已改 |

## T5 冻结清单

| 编号 | 结论 | 依据 |
|---|---|---|
| X1 | 关闭 | `_parse` 按 `detect.content_kind` 分流（`materials.py:217-258`）。<br>变异"按扩展名分流"→ 红 2 个；变异"重算不查外链"→ `test_xls_no_request`、`test_n21_external_note` 监听都收到 **2 次请求**（对照组）；现版本全量里都是 0 次 |
| X2 | 关闭 | 关系文件带 DOCTYPE、加密判断出错、Data 流读不了，都报 `unchecked`，并且会查完所有 `*.rels`。<br>变异 DOCTYPE 放行 → 红；加密判断出错放行 → 红 2 个 |
| X3 | 关闭 | `materials.py:538-540` 和 `587` 行。变异 → 红 |
| X4 | 关闭 | `links.open_zip` 看解压后大小；xlsx 用 `ws._cells` 只遍历实有单元格。<br>我的变异"改成看压缩后大小"→ 红 |
| X5 | 关闭 | `gate.copy_original` 先写 `工作区\临时\imp-*` 再改名移过去；带强杀子进程的测试。<br>我的变异"改名改成 `os.replace`（会覆盖）"→ 红 2 个 |
| X6 | 关闭，另有一条 P3 | 在锁内按前缀清理、不碰链接。前缀匹配过宽见 P3-1 |
| X7 | 关闭 | 我的变异"`工作区` 下任何文件都接受导入"→ 红 |
| X8 | 关闭 | 用长路径前缀遍历；读不了的登记为失败；读不了的文件夹里的旧条目不标"原件已删除"；另有 3 个测试 |
| X9 | 关闭 | `RETRY_REASONS` 分类已写进交付说明 14.3 节；另有测试 |
| X10 | 关闭 | 按临时裁决加 `_2`、`_3`；5 个测试 |
| X11 → 改按 1.2 做 | **未关闭** | 新建的库上正确，变异"不拿回原编号"→ 红；**1.2 之前的旧库不生效，见 P2-1** |
| X12 | 关闭 | 导入目录和 ZIP 都跳过任何层级的点开头项；另有测试 |
| X13 | 关闭，另有一条 P3 | `numfmt.py` 套显示值；格式版本号写在 `_处理状态.md`，没加契约字段。<br>变异"写原始值"→ 红；"版本号不触发重扫"→ 红。PDF、图片重扫没有测试，见 P3-3 |
| Y1–Y8 | 关闭 | `default_lo_base` 和 `LB_SOFFICE` 已删；`gate.py` 文件头如实；`remove_reported`；文本框只出现一次、DOCTYPE 部件按失败；UTF-16；Y7 退回写公式；Y8 换了样本并配对照测试 |
| Y9 | **部分关闭** | 交付说明第 6 节在 HEAD 上已过时，见 P3-2 |
| N21 | 关闭 | 只在有外链、没重算、并且确有公式没缓存值时才写 note；值在契约枚举里。变异 → 红 |
| N28 | 关闭 | Source 行只在四个取值里取"待识别"。变异 → 红 |
| `material_ids` 表、`meta.next_material_seq` | 服务侧写入正确，旧库不补建 | 服务不自带表定义，直接执行 `contracts\case_db.sql`，列名、类型、约束与契约逐字一致；`schema_version` 仍为 1。**已有旧库不会补建，见 P2-1** |

## 文件归类
- **必需实现：** `net.py`、`capsules.py`（T3）；`materials.py`、`gate.py`、`ingest\*`（含新文件 `numfmt.py`）（T5）。
- **必需验证：** `test_t3_rework3.py`、`test_api_case.py`、`test_main.py`、`test_t5_rework.py`、`test_t5_contract12.py`、`test_t5_convert_safety.py`、`test_t5_lo_placement.py`、`test_ingest.py`、`conftest.py`、`fakes.py`，以及 `evidence\T3\`、`T5\` 两个目录。
- **无关：** 没有，只有 P3-6 那一处顺手重构。
- T5 返修没有碰 T8 的文件（`63b551c..9d9d4e0` 在 `context.py`、`task.py`、`tools\`、T8 测试上的 diff 为空）。

## rebase 核对
- HEAD = `695191f`，工作区干净，与 `origin/main` 的合并基点 = `be6aef7`。
- `git range-diff`：24 个提交全部是 "="（内容不变），与 T3 交付说明第 11 节的对照表逐行一致。
- `git diff 7407914 d45b79f -- service` 为空（两边只差 `main` 上的复核文档）。所以 `7407914..HEAD` 在 `service\` 下的改动只来自 `a74051e`、`dcc05ac`、`1897478`（T8）、`81b24b2` 这 4 个提交，rebase 没有带进多余改动。

## 八项清单
| 项 | T3 | T5 |
|---|---|---|
| 契约一致 | 通过 | 旧库不补建表，未通过（P2-1）；其余通过 |
| 边界输入 | 通过 | 通过；前缀匹配过宽（P3-1） |
| 错误路径 | 通过 | 通过；旧库时静默降级正是 P2-1 的成因 |
| 日志不含正文 | 通过 | 通过（只记异常类名和原因代号） |
| 路径闸门未被绕过 | 通过 | 通过（临时文件、删除都经闸门） |
| 无外连 | 通过；测试会连所内地址（P3-7） | 实测 0 次请求，关掉检查的对照组 2 次 |
| 测试覆盖新代码 | 通过 | 缺旧库升级和 PDF、图片重扫的测试 |
| 无机密入库 | 通过 | 通过（只有本机用户名路径，NOTE） |

## 我实际跑过的命令
- `git rev-parse`、`status`、`merge-base`、`log`、`show --stat`、`range-diff`、`diff`、`grep`。
- 全量：克隆里，TEMP、LOCALAPPDATA、APPDATA 和 basetemp 都放在 `C:\Users\<用户>\AppData\Local\Temp\claude\rvB9a\`。先确认 `lawbench.__file__` 指向克隆，结果 **662 passed、3 skipped**（11 分 18 秒），与作者"改断言后"的合计一致。
- 实验副本（用 `git archive HEAD` 导出）上的实验：
  - S1 地址 133 例全部通过；
  - N26 旧库两个实验，都复现了问题；
  - X6 前缀实验，复现了问题；
  - 变异 15 类，全部改坏即红、复原即绿，源码逐字节复原。

## 残留审计
- 实验副本和短路径目录都已删除（用带长路径前缀的 `shutil.rmtree`）。克隆仍是 HEAD `695191f`，工作区干净。
- 没有我留下的 python 或 soffice 进程；18811–18819 端口没有监听。你说不是我的那两个 `soffice.bin`（10028、42468）没有动。

## 证据缺口
- 深路径全量没有复跑，只跑了短路径全量。
- 符号链接相关的 3 个用例仍然跳过（按用户决定留到验收机补跑）。
- T8 不在我的范围内，没有审。

T3: PASS
T5: AMEND
