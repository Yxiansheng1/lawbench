# T25 发票整理与委托材料（服务端）· Reviewer A（改动纪律与可维护性）

- target：line-C `36e8f2d`；范围 T25 提交 `2785eee`、`b346b7f`、`535be9e`、`145f225`、`6ed730c`、`36e8f2d`
- 派发：两名 Opus 5.5 只读复核员同一条消息并发派出，素材相同，互相看不到（高风险卡：发票引擎白名单动作）
- 复核克隆：scratchpad `rv-C13`
- 归档：主编排于 2026-10-01 12:37 (+08:00) 从复核员交回原文抄录，未改内容

## 复核员原文

# T25 复核 · Reviewer A（改动纪律与可维护性）· line-C 36e8f2d

**结论：AMEND。** 白名单、清空环境、返回语义这三处核心都做对了，而且我用变异实验确认测试能抓住这些地方出错。但有四处要修，修法都很小：
- `run` 动作没有另存购买方清单，正常路径下返回的还是写死律所名的原清单（实测）；
- 驱动的 `close()` 没有接到服务退出流程上，服务一停驱动就成孤儿进程；
- 日志不含发票内容的那条断言是空转的（变异实验存活）；
- `--engine rapidocr` 这条防线没有测试守着（变异实验存活）。

## 亲验前提
- `rev-parse HEAD` = 36e8f2df…，`status --short` 为空，已 detach。T25 共 6 个提交，`ac2495c` 不在 `6cf499e..36e8f2d` 范围里。
- `git diff 6cf499e 36e8f2d --stat -- engines` 输出为空，`engines\` 一字未改。
- 改动共 13 个文件、+1547 行。逐个 hunk 归类：
  - runner.py、driver.py、ui.py 两条路由、app.py 两个对象、pyproject 的 `[retainer]` 组：都是"必需实现"。
  - 两份测试和 T25 证据：都是"必需验证"。
  - 没有"无关" hunk。
- b346b7f 的提交信息写了"两处 /health 断言改读 contracts/VERSION"，但最终 diff 里没有这处改动。交付说明偏离第 6 条已解释（rebase 时取了 main 的写法），只是提交信息不准，记为 NOTE。

## Findings

**P2-1 `run` 动作没有另存购买方清单，返回的是写死律所名的原清单**（范围内阻断）
- 问题：引擎的 `run` 内部第三步就是 `prepare`，同样会生成 `贴票清单.html`。但 runner.py:86 只在 `prepare`/`reprint` 时调 `_with_buyer_copy`。
- 影响：界面"导入并生成贴票包"按钮在正常路径下，`files` 里给的是写死"广东连越（深圳）律师事务所"的原清单，没有副本。这与 Spec 13.3 ⑧"引擎生成清单后另存一份；界面只给新文件"不符。
- 证据：在副本上，只放发票 02、03，跑 plan → run，`run` 退出码 0：
  - `files` 里有 `贴票清单.html`，内容含写死串（`HARDCODED_IN_FILE=True`）；
  - 磁盘上 `贴票清单（*）` 副本数为 `[]`。
- 一期证据里 `run` 因为有重复票在 import 处就停了（退出码 2），所以作者没走到这条路径。
- 2023 补充令字面写的是"prepare（及 reprint）"，作者照字面做了。所以这是令和 Spec 之间的缝，需主编排确认。
- 最小修复：判断条件改成 `action in ("prepare", "reprint", "run")`（run 的批次名同样用 `scoped_batch`）。补一条 run 走到 prepare 的用例，可用只含 02、03 的夹具。

**P2-2 服务退出时不停驱动，驱动成孤儿，之后再也停不掉**（范围内，作者已部分披露）
- 问题：`RetainerDriver.close()` 只在测试夹具里调用。app.py 没有 shutdown/lifespan 钩子去调它。
- 影响：服务一退出（正常停止或崩溃），驱动继续占着 17801，而且它的跨域设置允许任何来源。服务重启后 `start` 会走"复用"分支，而 `stop` 按设计"不是自己起的不停"，于是这个驱动一直跑到关机。Spec 13.5 接受残余风险的前提是"只在委托材料窗口打开期间运行"，这个前提被打破了。
- 交付说明"遗留"只写了"服务崩溃时驱动会留着、下次复用"，没写"复用后 stop 永远停不掉"。
- 最小修复：服务关闭时调 `st.retainer.close()`（Starlette `on_shutdown`/lifespan）。或者在复用时把它记为"可停"。

**P2-3 日志不含发票内容的断言空转**（测试覆盖缺口）
- 问题：`test_logs_have_no_invoice_details` 只跑了 `report`。report 的输出里金额是 `1,366.50`（带千分位逗号），没有票号，所以 SECRETS 里一项都不会出现。
- 证据：变异 M6，在 runner 里加一行 `logs.event("invoice", action, error=output)`，把引擎整段输出写进日志，这条用例仍是 **1 passed**（存活）。
- 影响：工单验收"日志中不出现发票号、金额、购买方名称（测试断言）"实际没有被守住。代码本身目前没有把输出写进日志。
- 最小修复：让 period 夹具在 `logs.setup` 之后跑，覆盖 run/analyze/prepare 全程，再查日志；或者断言日志行只含 `t`/`module`/`op`/`status`/`ms`/`error` 这几个固定字段。

**P3-1 `--engine rapidocr` 没有测试守着**
- 证据：变异 M9 去掉这个参数，`test_start_ocr_status_stop` 仍通过（存活）。原因是 /health 的 engine 在默认情况下本来就是 rapidocr。
- 这条参数是防止退到 PaddleOCR 联网下模型的关键。
- 最小修复：加一条断言拼出的 cmd 里含 `--engine rapidocr` 的单测。

**P3-2 `exclude`/`review` 的自由文本以 `-` 开头时被误判为"须看明细"**（错误路径）
- 问题：契约对 `reason`/`reviewer` 只限长度。值以 `-` 开头时，引擎 argparse 报 "expected one argument" 并退出 2，服务把它归成 `attention:true, failed:false`。
- 证据：真引擎上 reason 取 `-x` 和 `--confirm` 各跑一次，两次都是 `exit 2 attention True failed False`。
- 不构成参数注入：argparse 直接报错，我在副本上实测过。
- 最小修复：拼成 `--reason=<值>`、`--reviewer=<值>` 的形式，或者服务端拒绝以 `-` 开头的值。

**P3-3 清理子进程的写法有三份重复**（可维护性）
- runner `_kill_tree`、driver `_terminate`、T5/T19 已有的 `ingest/libreoffice.kill_tree` 是同一套 `taskkill /T /F`。
- 最小修复：抽成一个公共函数复用（runner 需要 `communicate` 排空管道，可加一个参数）。

**P3-4 另存副本出错时静默跳过**
- 问题：`_with_buyer_copy` 遇到 `(OSError, ValueError, KeyError)` 直接返回原列表，界面会拿到原清单却没有任何提示。另外 `dst.write_text` 失败没有被捕获，会在引擎已经成功之后整个请求变成 INTERNAL。
- 最小修复：失败时记一条不含内容的 `logs.event(... error="buyer_copy")`；返回值要不要加提示交主编排定。

**NOTE**
- `run.src` 接受 UNC 路径，引擎会访问 SMB。这与全项目对路径的立场一致，不算本卡引入，记为独立后续。
- 拼 eml 渠道的参数时，如果只给了 start、没给 end，会传 `--end ""`。服务端已经挡住了 eml 缺日期的情况；local 渠道只给一端时怎么处理，归 Reviewer B。
- 交付说明"偏离之处"列了 6 条（不是 4 条）。逐条看都如实、必要、最小。

## 冻结清单逐条核对

| 项 | 结果 |
|---|---|
| 1 白名单拼命令 | 通过。脚本名和子命令都写死在代码里，`assert_allowed` 再断言一次；invoke.py 路径 = 常量 `ENGINE_DIR`，不可控；`collect`/`attach`/`import --img`/`build_env_zip.py`/`--download-links` 都拼不出来（M3 变异被杀）。 |
| 2 环境 | 通过。只传名单内 8 个变量（INVOICE_BUYER 只在设置有值时传）；`LB_CANARY` 真子进程用例有效（M1 被杀，2 failed）。 |
| 3 返回语义 | 通过。`[BLOCKED]` 或退出码非 0/2 → `failed`；退出码 2 → `attention`；超时、起不来 → ENGINE_FAILED；output 不进日志（M2 被杀）。另见 P3-2。 |
| 4 N50 另存一份 | prepare/reprint 通过：原文件不动，副本 HTML 转义，文件名去掉非法字符，购买方为空不生成，`HARDCODED_BUYER` 常量单独一处，交付说明写了换引擎要重核（M5 被杀）。**run 缺失（P2-1）。** |
| 5 exclude | 通过。一律带 `--confirm`；台账逐字节不变的断言真的在起作用（M7 去掉 --confirm 后 2 failed）。 |
| 6 驱动 | `--engine rapidocr` 已固定，但没有测试守着（P3-1）。模型哈希从 default_models.yaml 读、模型损坏不启动（M8 被杀）。端口被占时探 /health 再复用，stop 会等端口放开。依赖 `[retainer]` 组与实测版本清单一致、不含 pywin32（与 D:\lawbench-C\.venv 的 pip list 逐项对过）。退出不停驱动（P2-2）。 |
| 7 偏离 | 如实。三份重复见 P3-3。没有为测试暴露的生产接口（`python`/`engine_dir`/`timeout_s` 是构造参数）。 |

## 八项清单
- 契约一致：通过（请求、返回都过 schema，`failed` 字段与契约 1.3 一致）。
- 边界输入：P3-2。
- 错误路径：P3-4、P2-2。
- 日志不含正文：代码层面通过；测试没有守住（P2-3）。
- 路径闸门未被绕过：office 目录走 `check_office_dir`；src 接受 UNC 见 NOTE。
- 无外连：通过。驱动与 /health 探测只连 127.0.0.1，`trust_env=False`。
- 测试覆盖新代码：有缺口（P2-1、P2-3、P3-1）。
- 无机密入库：通过（证据和测试里没有用户名、真 Key）。

## 实际跑过的命令
- 副本：`git archive 36e8f2d` 导出到 `%TEMP%\claude\rvC13a`；TEMP/TMP/LOCALAPPDATA/APPDATA 都指到这个目录下。副本里把测试端口改成 19201–19209（只改副本）。
- `D:\lawbench-B\...\python -m pytest test_invoice.py test_retainer_driver.py`：65 passed，2 failed。失败的两条是驱动用例，原因是这个 venv 没装 `[retainer]` 依赖（`No module named 'onnxruntime'`），属于环境问题，不是代码问题。
- 换 `D:\lawbench-C\.venv`（只读使用，设了 `PYTHONDONTWRITEBYTECODE=1`）跑 test_retainer_driver.py：8 passed。
- 变异 11 个：
  - 被杀 7 个：M1 env 全继承、M2 failed 只看 [BLOCKED]、M3 去掉禁用参数循环、M4 超时不连子进程杀、M5 清单原地改写、M7 去掉 --confirm、M8 模型校验恒真。
  - 存活 4 个：M6 输出写进日志、M9 去掉 --engine、M10/M11 驱动去掉 /T 杀树、不等端口放开。M10/M11 存活可能是 Windows venv 启动器的作业对象会连带结束子进程，对风险影响小，未单列 finding。
  - 每个变异做完都按 sha256 逐字节复原，并用 `git hash-object` 与 36e8f2d 比对一致。
- 4 个红测复现：取自变异 M1、M2、M3、M4 —— `test_child_process_sees_only_whitelisted_env`/`test_env_only_whitelisted`、`test_exit_code_mapping`、`test_refused_commands`、`test_timeout_kills_engine_tree` 在对应变异下都变红。
- 两个自写实验：一个验证 run 路径返回的清单（P2-1），一个验证以 `-` 开头的参数值（P3-2）。

## 残留审计
- 19201–19209、17801 端口无监听；命令行含 rvC13a 的进程数为 0。
- 实验目录已删除（`Test-Path` 返回 False）；scratchpad 里的临时工单副本也已删除。
- 复核克隆 `status` 干净；没有动别人的进程。

## 证据缺口
- 第一次跑测试用的 D:\lawbench-B venv 没有设 `PYTHONDONTWRITEBYTECODE`，可能往它的 site-packages 写了 pyc（只是缓存）。
- 没有做连接抓取复测，`connections.txt` 沿用作者的。
- 驱动测试只能借 D:\lawbench-C\.venv 跑，因为指定解释器缺依赖。

AMEND
