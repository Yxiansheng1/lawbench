# T25 返修累计（第二轮）· Reviewer A（改动纪律与可维护性）

- target：line-C `a0c40a9`；范围 T25 累计 `2785eee`…`36e8f2d` + 返修 `f1c0275`、`a0c40a9`（同分支 T12 提交不在范围）
- 冻结清单：`review-综合裁决.md` 第 3 节
- 派发：两名 Opus 5.5 只读复核员同一条消息并发派出，素材相同，互相看不到；首次派出被用量上限中途杀停，本记录为重派后的完整报告
- 复核克隆：scratchpad `rv-C15`
- 归档：主编排于 2026-10-01 17:07 (+08:00) 从复核员交回原文抄录，未改内容

## 复核员原文
## Reviewer A（改动纪律与可维护性）· T25 返修后累计复核 · target line-C `a0c40a9`

**结论：PASS。** 冻结清单 A-P2-1、B-P2-1、B-P2-2、A-P2-2、A-P2-3，以及"一并做"的六条，全部关闭。B-P2-1（排队执行不可逆动作）和 N50 副本两处同根因都没有再出现。下面四条都是 P3 或 NOTE，不阻断。

已核实：克隆 HEAD = `a0c40a9`，`git status` 干净。`git diff 36e8f2d..a0c40a9 -- engines` 和 `2785eee~1..a0c40a9 -- engines` 都是空的，`engines\` 一字未改。

### Findings

**P3-1 · A-P2-2 要求的"服务退出关驱动"没有用例（本次修正引入的测试缺口）**
- 问题：把 `app.py` lifespan 里的 `st.retainer.close()` 换成 `pass`，没有任何用例变红。
- 影响：以后有人删掉这一行，测试发现不了。
- 证据：我做的变异 M7，跑 `test_retainer_driver` + `test_t3_rework` + `test_t3_rework2` + `test_invoice`，结果 158 passed。"复用驱动 stop 真停"这一半有用例（M15 变红），只缺退出钩子这一半。
- 最小修复：用 TestClient 进出一次 lifespan，把 `st.retainer.close` 换成计数桩，断言被调了一次。
- 归类：独立后续。

**P3-2 · 交付说明有两处还是返修前的说法（本次引入，只涉及文档）**
- 问题：
  - 文件表 driver 行仍写"是驱动就复用（不归我们停）"；
  - "遗留"节仍写"服务退出时没有主动停驱动……服务崩溃时驱动进程会留着"。
- 影响：这两句和返修后的行为以及返修节自相矛盾，T26/T20 读到会被误导。
- 最小修复：改这两句，指向返修节。
- 归类：独立后续。

**P3-3 · `stop` 的提示文字在一种情况下说错（本次引入）**
- 问题：`driver.py` 的 `stop()` 里，确认是本产品的驱动、已经 `kill_tree`，但 5 秒内端口没放开时，也返回 `MSG_NOT_OURS`（"不是本程序启动的，未关闭"）。
- 影响：`running:true` 是真实状态，但给律师看的原因说错了。
- 最小修复：这种情况另给一句"关闭未完成，请稍后再试"。
- 归类：独立后续。

**NOTE（记录，不要求动作）**
- 以下几点都是"判不了就不停、如实返回 `running:true`"，失败方向是安全的：
  - 判断"是不是本产品的驱动"靠 `netstat -ano` 的 `127.0.0.1:<port> LISTENING`，再用 powershell `Get-CimInstance` 取命令行，和 `driver_dir.resolve()` 比对；
  - 律所机器若禁用 PowerShell，或路径经过 junction / 8.3 短名，比对会失败；
  - 退出时只要端口上有驱动，`close()` 会在锁内最多多花约 25 秒（netstat 10 秒 + powershell 15 秒）。
- 变异 M14（去掉命令行核对）时，长得像驱动的假服务就在 pytest 自己的进程里，结果 `taskkill /T` 把 pytest 进程本身杀掉了。这反过来说明这道核对是必要的。

### 冻结清单逐条核对

| 编号 | 结论 | 怎么验证的 |
|---|---|---|
| A-P2-1 `run` 另存副本 | 关闭 | 条件改为 `("prepare","reprint","run")`，批次名用 `scoped_batch`。真引擎 02/03 夹具用例 `test_run_also_writes_buyer_copy` 通过；变异 M3（去掉 run）变红 |
| B-P2-1 等锁 2 秒 → `ENGINE_BUSY`、第二个动作不启动 | 关闭 | `acquire(timeout=2.0)`，在 try/finally 里释放。计数桩用例断言 `started == ["report"]`、等待 1.8–5 秒；HTTP 用例 `test_api_busy_contract` 通过；变异 M2（改回无限等）变红 |
| B-P2-2 副本写失败照常返回原清单并记 `buyer_copy` | 关闭 | 写副本包进 `try/except OSError`。用例让同名目录占住副本位置；变异 M4 变红 |
| A-P2-2 服务关闭调 `close()`、复用驱动 `stop` 可停且如实返回 | 关闭（退出钩子缺用例，见 P3-1） | 复用 → stop → 端口放开（ORT 解释器上通过）；假驱动不停、返回 `running:true`；变异 M15 变红、M14 变红（见 NOTE）；M7 不红 |
| A-P2-3 日志用例看全程 | 关闭 | 一期全程（plan…report + `-x` 重印）每行只允许 7 个固定字段，并检查票号、金额、购买方、文件名、原因文字都不出现。我自己复现了变异"把输出写进日志"（M1）→ 变红 |
| `--engine rapidocr` 断言 | 关闭 | `test_driver_command_has_engine_rapidocr` |
| `--参数=值` | 关闭 | `batch`/`reason`/`reviewer` 都改了；真引擎 `-x` 批次得 `failed` 而不是 usage 报错；变异 M5（batch）、M5b（reason）变红。顺带：批次名 `--download-links` 这类值现在被包在 `--batch=` 里，比原来更安全 |
| `invoke.py` 缺失 → `ENGINE_FAILED spawn` | 关闭 | 变异 M6 变红 |
| `procs.kill_tree` 合并三处 | 关闭 | 三处调用方都改了（runner 带 `drain=True`、driver、libreoffice）。新文件 `procs.py` 30 行，范围最小 |
| 驱动用例缺依赖时跳过 | 关闭 | B 解释器上 2 skipped，原因写明；C 解释器（有 ORT）10 passed |
| 交付说明配合段 | 关闭（另有过时句子，见 P3-2） | 等锁 2 秒的后果、复用驱动 stop、缓存路径约 110 字符，三点都写了 |

### 公共函数与 T5 的接缝
- `libreoffice.kill_tree` 只在 `proc.wait` 超时后调用，那时进程一定活着，新加的 `poll()` 前置判断不改变行为。新旧写法都是 `/F /T`、等待 10 秒。
- `test_t5_convert_safety`（含 LO 超时路径）、`test_t5_lo_placement`、`test_ingest` 共 89 passed。
- T12 没有调用 `procs`。

### 契约与 Spec
- `errors.py` 的 `ENGINE_BUSY` 中文提示"发票整理正在进行中，请等它完成再操作"，与 Spec 20.1 表逐字一致。
- `common.schema.json` 已有 `ENGINE_BUSY`。
- 走 HTTP 时按失败体返回，过了契约校验（`test_api_busy_contract`）。

### 第一轮已通过的核心没被弄坏（作者红测 4 个 + 自做变异 15 个，全部按预期红/不红）
| 变异 | 红了的用例 |
|---|---|
| M8 环境多传一个代理变量 | `test_env_only_whitelisted`、`test_child_process_sees_only_whitelisted_env` |
| M9 `[BLOCKED]` 语义（failed 只看退出码） | 4 条 |
| M10 禁用参数检查失效 | `test_refused_commands` |
| M11 exclude 去掉 `--confirm` | exclude 台账、一期报销、副本共 3 条 |
| M12 跳过模型哈希核对 | 驱动用例 |
| M13 `kill_tree` 去掉 `/T` | `test_timeout_kills_engine_tree` |

每个变异做完都逐字节复原，并与 git blob 比对确认一致。

### 八项清单
- 契约一致：通过
- 边界输入（`-` 开头的值、同名目录占位、入口缺失、锁超时）：通过
- 错误路径（spawn / timeout / busy / buyer_copy 各归其位）：通过
- 日志不含正文：通过（全程用例 + 变异）
- 路径闸门未被绕过：通过（`_ledger_dir` 云同步目录再挡一次，未改动）
- 无外连：通过（驱动 `trust_env=False`、只连 127.0.0.1；新增的 netstat / powershell 都是本机查询）
- 测试覆盖新代码：基本通过，lifespan 钩子除外（P3-1）
- 无机密入库：通过（diff 中没有 Key 或令牌）

### 实际跑过的命令
- `git rev-parse` / `status` / `show` / `diff`（在复核克隆上只读）。
- `git archive a0c40a9` 后用 Python tarfile 解到实验目录。Windows tar 解不了中文文件名，所以换了 Python。
- B venv：`pytest tests\test_invoice.py tests\test_retainer_driver.py` → 74 passed, 2 skipped（172 秒）。
- C venv（`-B`，有 onnxruntime）：`test_retainer_driver.py` → 10 passed。
- B venv：`test_t5_convert_safety` + `test_t5_lo_placement` + `test_ingest` → 89 passed。
- 变异脚本 `mut.py` / `mut2.py` 共 15 个变异，含 M7 跑 158 条。
- 环境：`PYTHONPATH`、TEMP、TMP、LOCALAPPDATA、APPDATA 都指向实验目录，`INVOICE_RUNTIME_CACHE` 由此落在短路径下。

### 残留审计
- 开工前清空了上一名复核员留在 `C:\Users\<用户>\AppData\Local\Temp\claude\rvC15a\` 的残留；结束时整个目录已删除。
- 没有命令行含 `rvC15a` 的进程留下（M13 留下的 sleep 子进程已自行结束）。
- 17800–17999、19401–19409 端口没有在监听。
- 没有动别人的进程，没有写任何仓库、协调目录或克隆。

### 证据缺口
- 全量回归没跑（不要求）。
- 真驱动的复用 → stop 只在 C venv 上跑过一次。
- `netstat` / `powershell` 在律所受限机器上的表现没有验证（见 NOTE）。

PASS
