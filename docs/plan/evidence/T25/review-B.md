# T25 发票整理与委托材料（服务端）· Reviewer B（影响半径、边缘情况与回归安全）

- target：line-C `36e8f2d`；范围 T25 提交 `2785eee`、`b346b7f`、`535be9e`、`145f225`、`6ed730c`、`36e8f2d`
- 派发：两名 Opus 5.5 只读复核员同一条消息并发派出，素材相同，互相看不到（高风险卡：发票引擎白名单动作）
- 复核克隆：scratchpad `rv-C13`
- 归档：主编排于 2026-10-01 12:37 (+08:00) 从复核员交回原文抄录，未改内容

## 复核员原文

# Reviewer B 复核：T25 发票整理与委托材料（line-C `36e8f2d`）

我核对了复核克隆：HEAD 是 `36e8f2df…`，工作区干净。T25 的 6 个提交在 `6cf499e..36e8f2d` 里，属于 T12 的 `ac2495c` 不在这个范围内。diffstat 显示 13 个文件、+1547 行，`engines\` 一处没改。所有实验都在 `git archive` 导出的副本上做，副本放在 `C:\Users\<用户>\AppData\Local\Temp\claude\rvC13b\`，结束后已删除。

## Findings

**P2-1：排队的动作在律师放弃等待后仍会执行，包括不可逆的动作**
- **问题**：`InvoiceRunner.run` 用一把没有等待时限的 `threading.Lock` 排队。客户端断开以后，后台线程仍在等锁，拿到锁就照常执行。
- **影响**：`cancel`（服务一律带 `--apply`）、`reimburse --apply`、`exclude --confirm` 都可能出现"界面显示超时，台账其实已经改了"。排队也没有上限：每个排队请求在等锁期间都占着一个线程池线程（anyio 默认 40 个），极端情况下会拖住其他接口。
- **证据**：用真 uvicorn 在 127.0.0.1:19216 做实验。第一个 `report` 用假引擎睡 4 秒；第二个 `cancel` 的客户端 1.5 秒后放弃。引擎标记显示 `start workflow.py cancel` / `end workflow.py cancel` 照样执行了。
- **最小修复**：二选一，交主编排定。
  - 忙时直接拒绝：要在契约里加一个"忙"错误码。
  - 保留排队：给等锁加时限（例如 `acquire(timeout=…)`，超时返回失败体）；同时在交付说明里写清楚 T26 必须在动作进行中禁用按钮、不能给请求设短超时。
- **归类**：范围内，需要主编排拍板。作者的偏离第 5 条只说了"排队"，没说这个后果。

**P2-2：N50 副本写入失败时，一次成功的 prepare / reprint 会变成 500**
- **问题**：`_with_buyer_copy` 里的 `dst.write_text(...)` 不在 try 里面。
- **影响**：引擎已经建好批次并记了哈希，律师却看到失败。律师可能重做 prepare，然后被引擎以"批次已存在"挡住，或者带 `--replace` 重建。这不符合工单"副本写入失败时原流程不受影响"的要求。
- **证据**：先在目标文件名处建一个同名目录，再用假引擎（退出码 0）跑 prepare，`run()` 抛出 `PermissionError`。从 HTTP 层看，同一类未捕获异常返回的是 500 INTERNAL（见 P3-3 里 OSError 的复现）。
- **最小修复**：捕获 `OSError`，`files` 原样返回原清单。再加一条有界回归用例：目标被占用时 run 返回成功体，`files` 里是原文件。
- **归类**：范围内阻断。这是工单点名要验的 N50 边界。

**P3-1：契约放行、以 `-` 开头的参数值会被引擎当成用法错误，界面标成"须看明细"**
- **问题**：`reason`、`reviewer` 和批次名可以以 `-` 开头（例如 `--download`、`-x`、`--apply`）。引擎的命令行解析会报"expected one argument"并以退出码 2 退出。服务把它判成 `attention:true, failed:false`，而不是失败。
- **证据**：真引擎上 `exclude dash reason`、`exclude dash reviewer`、`reprint dash batch` 三条都是 `exit=2 att=True failed=False`，最后一行是 usage error。没有越权：`--download-links` 这类禁用参数仍被 `assert_allowed` 挡下，返回 INVALID_ARGUMENT。
- **最小修复**：自由文本参数改用 `--reason=<值>` 的写法拼接，或在服务端挡掉以 `-` 开头的值。加一条用例。
- **归类**：范围内（小）。

**P3-2：引擎入口 `invoke.py` 缺失时报"须看明细"，不是 `ENGINE_FAILED`**
- **问题**：只有引擎目录不存在、或解释器不存在（OSError）时才判 spawn。目录在、`invoke.py` 不在的情况，Python 会报 "can't open file" 并以退出码 2 退出，结果被判成 `attention:true`。
- **影响**：与 Spec 的"引擎起不来 → ENGINE_FAILED"不符。代码注释写的是"解释器或入口缺失"，入口缺失这一半实际没有覆盖。
- **最小修复**：起进程前检查 `(engine_dir/"scripts"/"invoke.py").is_file()`，不在就返回 `ENGINE_FAILED spawn`。加一条用例。
- **归类**：范围内（小）。

**P3-3：结尾带换行的值能通过契约**
- **问题**：Python 正则里的 `$` 会匹配到末尾换行之前。
- **影响**：
  - `period:"2026-09\n"` 在 `job()` 里调 `mkdir` 时触发 OSError，HTTP 返回 500 INTERNAL。
  - `batch:"ab\n"` 会一路送到引擎（实验里引擎确实被启动了）。
  - 这违反"非法请求一律 INVALID_ARGUMENT 且不启动引擎"。
- **证据**：`contracts.errors(... {'action':'reprint','batch':'ab\n'})` 返回 `[]`。
- **最小修复**：契约 pattern 改用 `\Z` 结尾，或在校验层统一做全串匹配。
- **归类**：独立后续，是全契约共有的问题，T25 只是又踩到一次。

**P3-4：服务退出或崩溃后遗留的识别驱动停不掉，`stop` 还报"已关闭"**
- **证据**：
  - d1 启动驱动后模拟服务退出（`close()` 在全仓没有任何调用方）。
  - 新实例 d2 的 `start` 返回"沿用已在运行的驱动"。
  - d2 的 `stop` 返回 `running:false`、"证件识别已关闭"，但紧接着的 `status` 返回 `running:true`，端口仍在监听。
- **最小修复**：
  - 沿用的驱动在 `stop` 时如实返回 `running:true` 并给出说明，或者也允许 stop 它（它确实是本产品起的驱动）。
  - 服务关闭时调用 `RetainerDriver.close()`。
- **归类**：独立后续。交付说明"遗留"一节写了孤儿驱动，但没提"已关闭"的假消息。

**NOTE**
- **引擎缓存路径的实际上限远低于 259 字符**：本机 `LongPathsEnabled=0`。`INVOICE_RUNTIME_CACHE` 长 124 字符时，引擎就以退出码 1 失败，报 `ModuleNotFoundError: openpyxl.compat.numbers`；长 204 字符时报 `WinError 206`。原因是解压时引擎内部还会再加约 135 字符（`win-amd64\.build-xxxx\` 加上包内最深 104 字符的路径）。T20 安装检查的阈值应定在"应用数据路径不超过约 110 字符"。服务这一侧的表现是对的：`failed:true`，原因在 output 里。
- **超时的实际耗时**：最长约为 30 分钟加 10 秒（`_kill_tree` 里 `communicate(timeout=10)`），有上限。
  - 实验中超时设 5 秒，实际 15.6 秒返回。
  - 中间层还活着的孙进程被 `taskkill /T` 结束了。
  - 中间层先退出后留下的孤儿进程能存活。现行引擎全部用 `subprocess.run` 同步等待，不会出现这种结构，所以属于臆测。
- **`[BLOCKED]` 的判法**：代码按"任一行以 `[BLOCKED]` 开头"判，契约描述写的是"输出以它开头"。代码比契约更严、更稳妥，交付说明已写明。建议主编排顺手把契约描述对齐。
- **驱动对模型文件的检查偏严**：模型目录里多一个 `.onnx` 时 `models_ok` 返回 False，也会报 `ENGINE_FAILED`。偏严但安全。
- **驱动测试在 B 线解释器上会失败**：`test_retainer_driver.py` 在 B 线 `.venv` 上有 2 条失败，因为缺少 onnxruntime 等依赖，用例没有在缺依赖时跳过。换成装了 `[retainer]` 依赖的解释器后 8 条全过。

## 冻结清单逐条核对

| 项 | 结论 |
|---|---|
| ① 只能以白名单动作、写死参数、净化后的环境调用引擎 | 成立。非法请求共 39 种，其中 37 种返回 INVALID_ARGUMENT 且没有启动引擎；两种结尾带换行的见 P3-3。禁用参数作为参数值时也被拒。子进程和孙进程的环境变量名都只有 8 个：`INVOICE_BUYER`、`INVOICE_RUNTIME_CACHE`、`LOCALAPPDATA`、`PYTHONUTF8`、`SYSTEMROOT`、`TEMP`、`TMP`、`USERPROFILE`。我塞进去的 `INVOICE_IMAP_HOST`、`HTTP(S)_PROXY`、`PYTHONPATH`、`PYTHONHOME`、`LB_CANARY`、`INVOICE_LEDGER_DIR` 等都看不到 |
| ② 引擎和驱动进程 0 条对外连接 | 成立（采样取证）。真引擎走一期时，进程树共 79 个进程（python 59、conhost 20）。采到的 102 条 TCP 记录全部属于测试和服务进程本身，都是 127.0.0.1 自连的 socketpair；引擎子进程 0 条 TCP、0 条 UDP。驱动只监听 127.0.0.1 |
| ③ 台账目录只被引擎写 | 成立。服务只建 `_任务\<期>`、写历史票号 JSON，以及写 N50 副本（Spec 允许的唯一后处理）。副本不进批次记录（`artifacts` 只有原 `贴票清单.html`）。副本生成后，`reprint` 和两次 `reimburse --apply` 都照常 |
| ④ exclude 只改任务目录 | 成立。排除前后台账 42 个文件逐字节不变，`_原票` 也不变。不存在的 item 返回 `failed:true`（KeyError）；重复排除同一项退出码 0，是幂等的。交付说明写明了"不可逆" |
| ⑤ 失败原因给律师看，不进日志 | 成立。service.log 共 40 行，没有票号、金额、购买方、批次名、`[BLOCKED]`、核验人。假引擎输出里的 SECRET 字样也没有进日志 |

## 影响地图

| 维度 | 状态 |
|---|---|
| 调用方（T26） | 受影响：要配合 P2-1（按钮禁用、不设短超时）、P3-4，并且只给副本的打开入口 |
| 契约兼容 | 已排除风险：经 HTTP 走一期，返回也做了契约校验，全部通过。结尾换行问题见 P3-3 |
| 持久化 | 已排除风险：台账、`_原票` 不变，副本不进批次记录。引擎缓存只写到应用数据下的 `ivc` |
| 授权与隔离 | 已排除风险：环境变量、白名单、`collect`/`attach` 都已核实 |
| 并发 | 受影响：P2-1 |
| 超时 | 有上限，见 NOTE |
| 配置 | 已排除风险：购买方名称为空、含非法字符或很长时，副本文件名都处理正确。云同步目录会再按规则挡一次 |
| 依赖与供应链 | 已排除风险：模型改一个字节就拒绝启动，返回 ENGINE_FAILED |
| 性能 | 每次调用都要遍历 `_打印包`、`_报销批次`，规模小，可接受 |
| 可观测性 | 已排除风险：日志只记动作、状态、耗时、错误码 |

## 八项清单

| 项 | 结论 |
|---|---|
| 契约一致 | 基本通过。P3-3；`[BLOCKED]` 描述的措辞差异见 NOTE |
| 边界输入 | 两处没过：P3-1、P3-3 |
| 错误路径 | 三处没过：P2-2、P3-2、P3-4 |
| 日志不含正文 | 通过 |
| 路径闸门未被绕过 | 通过（批次名不允许 `.`、`/`、`\`；`src` 必须是存在的绝对路径） |
| 无外连 | 通过（采样取证） |
| 测试覆盖新代码 | 作者 59 条发票用例本地全过，8 条驱动用例用 C 线解释器全过。没有覆盖 P2-1、P2-2、P3-1、P3-2、P3-4 |
| 无机密入库 | 通过（diff 里没有 Key，fixtures 都是虚构材料） |

## 实际跑过的命令

- `git rev-parse`、`git status`、`git log 6cf499e..36e8f2d`、`git diff --stat`。
- 用 `git archive` 导出副本，再用 Python 的 tarfile 解压。Windows 自带的 tar 处理不了中文文件名，第一次解压失败后重来。
- 在副本里用 B 线 `.venv` 跑 `pytest tests\test_invoice.py tests\test_retainer_driver.py`：65 passed、2 failed，失败是因为该解释器缺驱动依赖。
- 用 `D:\lawbench-C\.venv` 跑 `test_retainer_driver.py`：8 passed。只读使用，带 `-B` 和 `PYTHONDONTWRITEBYTECODE`，不写字节码缓存。
- 自写的实验脚本：
  - `exp_req.py`：请求边界，用计数桩代替 Popen，确认非法请求不启动引擎。
  - `exp_fake.py`：环境变量、失败语义、并发、N50、日志。
  - `exp_timeout.py`：超时与进程树。
  - `exp_period.py`：真引擎经 HTTP 走一期，同时用 `sampler.ps1` 按进程树采 `Get-NetTCPConnection` 和 `Get-NetUDPEndpoint`。
  - `exp_longcache.py`：引擎缓存超长路径。
  - `exp_driver.py`：驱动实验，端口用 19215。
  - `exp_queue.py`：真 uvicorn，端口 19216。
- 起服务前，两组服务器地址都设成 127.0.0.1:19211–19214 这几个没人监听的端口；LOCALAPPDATA、APPDATA、TEMP、TMP 和应用数据目录都指到实验目录。全程没有测连接、没有用 Key、没有外连。

## 残留审计

- 采样器（PID 34108）已自行退出。
- 命令行带 `rvC13b` 的 python 和 powershell 进程：0 个。
- 17801、19211–19219 端口都没有在监听。
- 驱动孤儿实验留下的进程已按 PID 清理，复查确认存活 0 个。
- 超时实验留下的孤儿进程已按 PID 清理。
- 实验目录 `rvC13b` 已删除（`Test-Path` 返回 False）。
- 复核克隆 `git status` 干净。
- 没有碰别人的进程，也没有写任何线的目录或协调目录。

## 证据缺口

- 连接取证是约 300 毫秒一次的采样，存活时间更短的连接可能漏采；走系统 DNS 服务的域名查询不归属到引擎进程，这种方法看不到。
- 线程池被大量排队请求占满的情况只做了推理，没有压测。
- T26 界面本身不在这次复核范围内。

AMEND
