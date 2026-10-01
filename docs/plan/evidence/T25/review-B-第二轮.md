# T25 返修累计（第二轮）· Reviewer B（影响半径、边缘情况与回归安全）

- target：line-C `a0c40a9`；范围 T25 累计 `2785eee`…`36e8f2d` + 返修 `f1c0275`、`a0c40a9`（同分支 T12 提交不在范围）
- 冻结清单：`review-综合裁决.md` 第 3 节
- 派发：两名 Opus 5.5 只读复核员同一条消息并发派出，素材相同，互相看不到；首次派出被用量上限中途杀停，本记录为重派后的完整报告
- 复核克隆：scratchpad `rv-C15`
- 归档：主编排于 2026-10-01 17:07 (+08:00) 从复核员交回原文抄录，未改内容

## 复核员原文
# Reviewer B 复核：T25 返修后累计范围（line-C `a0c40a9`）

**简短结论：** 两个止损项都已关闭。B-P2-1（律师放弃后排队的动作仍执行）真修好了；N50 第一轮的病根（写副本失败把成功变成 500、`run` 漏了副本）也修好了。剩下两处小问题：一处是这次返修新引入的，另一处是冻结清单要求的用例没补齐。

**复核对象核对：** 克隆 `rv-C15` 的 HEAD 是 `a0c40a99…`，工作区干净。返修源码改动在 `f1c0275` 里，涉及 `runner.py`、`driver.py`、`procs.py`、`app.py`、`errors.py`、`libreoffice.py`。`git diff --stat 2785eee~1 a0c40a9 -- engines` 为空，`engines\` 没有改动。所有实验都在 `git archive` 导出的副本里做（`C:\Users\<用户>\AppData\Local\Temp\claude\rvC15b\`）。上一名复核员留下的残留已先清空；19411–19419 开工时没有进程在监听。

## Findings

**P3-1：在已有同名批次的报销月里重跑 `run`，如果停在"须看明细"，会把旧批次的贴票清单副本当成这次的产出返回**
- **问题**：返修把 `run` 加进了生成副本的条件 `action in ("prepare","reprint","run")`。判断只看 `not failed`，没看这次 `run` 有没有真的走到 prepare。
- **触发路径**：引擎 `workflow.py:72` 在 import 返回 2 时直接退出，不跑 prepare；`collection_job.py:124` 在处理未完成时返回 2，而且不打 `[BLOCKED]`。这种情况下服务仍按 `<期>_<批次>` 去找批次记录。引擎规定"同一任务不能改变批次名"，所以同一个月重跑一定会找到旧批次。
- **影响**：
  - 律师补交迟到发票、重跑 `run`、结果是"须看明细"时，`files` 第一项是**已报销旧批次**的 `贴票清单（购买方）.html`。界面只给副本的打开/打印入口，律师容易误以为这是这次的清单。
  - 服务还会往已报销批次的文件夹里重写一次副本。内容和以前一样，不影响批次哈希。
- **证据**：
  - 真引擎：一期走完、`2026-09_九月` 状态为 paid 后，用只含发票01的目录重跑 `run`，结果是 `exit 2 att True failed False`，`files` 为 `['_打印包\2026-09\2026-09_九月\v001\贴票清单（某某虚构律师事务所）.html', '_任务\2026-09\收集对账表.csv']`。
  - 假引擎（返回 2、没有 `[BLOCKED]`）复现相同结果。
- **最小修复**：只有 `run` 退出码为 0 时才生成副本；或者只有批次 json 出现在本次 `_changed()` 列表里时才生成。补一条"run 停在须看明细 + 已有同名批次 → `files` 里没有副本"的用例。
- **归类**：本次引入的回归（小）。它不是 N50 第一轮的同一病根：那次是写副本失败没兜住、`run` 漏做副本，这次是挑错了批次。

**P3-2：冻结清单 A-P2-2 要求的"服务退出时停驱动"没有用例守护**
- **问题**：变异实验把 `app.py` lifespan 里的 `st.retainer.close()` 换成 `pass`，`test_retainer_driver.py` 和 `test_main.py` 仍是 14 passed。
- **影响**：功能本身我实测是对的（见 D1、D3）。但以后有人删掉这一行，不会有用例变红。
- **最小修复**：用 `TestClient` 的 with 块，或者给 `st.retainer.close` 打桩，断言退出 lifespan 时 close 被调用。
- **归类**：范围内。冻结清单写了"补用例"，只补了复用/停止的用例，lifespan 这一半没补。

**NOTE**
- **重印时副本写不了，`files` 是空的**：真引擎在副本位置放同名目录后 `reprint`，返回成功体、`files=[]`，日志里有一条 `error:"buyer_copy"`。原因是重印不改动任何文件，原清单本来就不在 `files` 里；设置里购买方为空时重印也一直是空列表。不算回归，T26 要从 `output` 或批次记录里取打印包位置。
- **交付说明有两处没随返修更新**：文件表里驱动一行仍写"复用（不归我们停）"；"遗留"一节仍写"服务退出时没有主动停驱动"。
- **改了设置里的购买方，旧批次就重印不了**：购买方改成空串、非法字符、"..."、300 字长名后，`reprint` 都得到 `failed:true`（"原票、抬头或分类核验缺失"）。原因是 `INVOICE_BUYER` 传给了引擎做抬头核验。这是第一轮就有的引擎语义，不是返修引入的，建议在 T26 文案里提醒。
- **服务退出变慢**：有驱动时服务退出约 8–9 秒，复用驱动的 `stop` 约 9 秒。原因之一是 Windows 上连本机关闭的端口每次约 2 秒。都有上限，最坏情况由几个超时相加，约 55 秒。另外 CTRL_BREAK 退出码是 3。
- **驱动 `stop` 没停掉时日志仍记 ok**：`stop` 返回 `running:true`（"不是本程序启动的"）时，日志 status 仍是 `ok`。只影响排查。
- **`_listener_pid` 依赖 netstat 英文状态名**：它按 `LISTENING` 匹配。本机 netstat 输出是英文；如果某些语言版系统把状态名本地化，找不到监听进程，结果是驱动不停、返回 `running:true`，属于安全的失败方向。

## 冻结清单逐条核对

| 编号 | 结论 |
|---|---|
| A-P2-1 `run` 也另存 | 成立。用例 `test_run_also_writes_buyer_copy` 通过。但条件过宽，见 P3-1 |
| B-P2-1 等锁限时 | **关闭**，在 `run()` 里直接测（真子进程假引擎）：<br>• S1：A 跑 4 秒，B 1 秒后到 → 2.015 秒后得 `ENGINE_BUSY`，B 的 cancel 没有启动<br>• S2：B 在 A 结束前约 0.1 秒到 → 拿到锁照常执行<br>• S3：cancel、reimburse --apply、exclude 三个等待者同时到 → 全部 `ENGINE_BUSY`，标记文件里只有 report 的起止<br>• S4：A 超时被杀树（2.34 秒）→ 锁释放，B 照常执行，A 的孙进程已结束<br>• S5：持锁段内抛异常 → 锁释放<br>• S6：边界：持锁方 1.9 秒放锁 → B 成功；2.15 秒放锁 → `ENGINE_BUSY`<br>• S7：经 HTTP，失败体过契约，提示文字与 Spec 20.1 第 1390 行一致 |
| B-P2-2 写副本失败 | 成立。真引擎在副本位置放同名目录后 `reprint` → 成功体、日志有 `buyer_copy`、日志不含内容；目录删掉后再 `reprint`，副本恢复；之后 `reimburse --apply` 照常 |
| A-P2-2 驱动随服务停、复用驱动可停 | 行为成立：<br>• D1：真服务 CTRL_BREAK 退出 → 驱动进程结束、17801 放开<br>• D2：强杀服务留下驱动 → 新实例 `start` 得"沿用" → `stop` 得 running:false → `status` 为 false，进程和端口都没了<br>• D3：复用驱动后正常退出服务 → 驱动被停<br>• D4：17801 被别的 HTTP 程序占 → `start` 得 running:false 加说明，`stop` 不动别人的程序<br>缺 lifespan 的用例，见 P3-2 |
| A-P2-3 日志用例 | 成立。变异"把引擎输出写进日志"后用例变红（`'26999000000000410002' not in …`）；源文件已从归档复原，哈希一致 |
| A-P3-1 `--engine rapidocr` | 成立。真驱动的命令行含 `--engine rapidocr` 和 `--host 127.0.0.1` |
| A-P3-2 `--参数=值` | 成立，真引擎实测：<br>• `reprint`、`reimburse`、`cancel` 的批次名分别取 `--confirm`、`--download-links`、`-x`、`--apply`、`--replace`：都报"批次文件不存在"，failed:true，没有用法错误<br>• `exclude` 的理由取 `--confirm`、核验人取 `--download-links`：按字面值处理<br>• `review` 的核验人取 `--confirm`：得"须 --confirm"<br>• `run` 的批次名取 `--download-links`：引擎内部加了期前缀，报"同一任务不能改变批次名"<br>• 前后台账逐字节不变 |
| B-P3-2 入口缺失 | 成立（用例通过） |
| A-P3-3 `kill_tree` 合并 | 成立。T5 用例（convert_safety、lo_placement、rework、main）106 passed，包括超时杀树；逐行比对与旧写法等价 |
| B-NOTE 缺依赖跳过 | 成立。B 线解释器上 2 skipped，C 线解释器上 10 passed |

## 影响地图

| 维度 | 状态 |
|---|---|
| T26 调用方 | 交付说明已写：收到 `ENGINE_BUSY` 时禁用按钮、不设短超时。另需知道 P3-1 和重印时 `files` 为空 |
| 契约兼容 | 无风险：`ENGINE_BUSY` 已在 common 里，失败体过契约 |
| 持久化 | 副本不进 `artifacts`；原清单哈希等于批次记录。P3-1 会往旧批次文件夹写一次副本 |
| 并发 | 已排除，见 S1–S7 |
| 进程 | 已排除，见 D1–D4、S4、T5 用例 |
| 配置 | 购买方为 None、空串、空格时不生成副本；含非法字符的变成 `_`；"..." 变成"购买方"；长名截到 60 字；`&<>` 做了转义 |
| 可观测性 | 已排除风险，日志只有固定字段，见 NOTE |

## 八项清单

| 项 | 结论 |
|---|---|
| 契约一致 | 通过 |
| 边界输入 | 通过。非法请求 39 种全部 `INVALID_ARGUMENT`，且没有启动引擎（Popen 计数桩） |
| 错误路径 | 基本通过，P3-1 |
| 日志不含正文 | 通过。真引擎一期加边界实验共 35 行日志，字段只有 t/module/op/status/ms/error；不含票号、金额、购买方、批次名、`[BLOCKED]`、核验人、理由、文件名 |
| 路径闸门未被绕过 | 通过 |
| 无外连 | 通过（采样）。命令行带实验目录的 107 个 python 进程，TCP、UDP 都是 0 条；驱动只监听 127.0.0.1 |
| 测试覆盖新代码 | 基本通过，有两处缺口：P3-2，以及 P3-1 没有用例 |
| 无机密入库 | 通过 |

## 实际跑过的命令

- **克隆核对**：`git rev-parse`、`status`、`log`、`show f1c0275`、`diff --stat`（含 `engines`）。导出用 `git archive`，再用 Python 的 tarfile 解压（Windows 自带 tar 处理不了中文文件名）。
- **作者用例**：B 线解释器跑 `test_invoice.py` 和 `test_retainer_driver.py`，74 passed、2 skipped；C 线解释器（`-B`、`PYTHONDONTWRITEBYTECODE`）跑驱动用例，10 passed；T5 和 main 相关用例 106 passed。
- **自写实验**（都只放在副本里）：
  - `test_zz_rvb_busy.py`：S1–S7，排队边界
  - `test_zz_rvb_req.py`：39 种非法请求，39 passed
  - `exp_period.py`：真引擎一期（plan → run → analyze → exclude×2 → analyze → prepare → reimburse 预览 → --apply），加 N50 与 `--参数=值` 的边界；同时用 `sampler.ps1` 每约 150 毫秒采一次 TCP 和 UDP
  - 购买方各种取值、P3-1 的假引擎与真引擎复现
  - `exp_drv.py`：真服务 `python -m lawbench`，端口 19411、19412。起服务前，设置里四个服务器地址都指向 127.0.0.1 上没人监听的 19413–19416；TEMP、TMP、LOCALAPPDATA、APPDATA 和应用数据目录都指到实验目录
  - 两次变异：日志变异、lifespan 变异。都从归档逐字节复原，哈希一致
- 全程没有调测试连接，没有用 Key，只连了 127.0.0.1。

## 残留审计

- 命令行带 `rvC15b` 的进程：0 个；采样器已自行退出。
- 17801、19411–19419 都没有在监听。
- 实验目录已删除（`Test-Path` 返回 False）。
- 复核克隆 `git status` 干净。
- B 线、C 线 `.venv` 近一小时新写的 `.pyc`：0 个。
- `soffice.bin` 只有原来的 10028、42468。
- 机器上 `rvC15a` 的进程属于另一位复核员，没有碰。

## 证据缺口

- 连接取证是约 150 毫秒一次的采样，存活更短的连接可能漏采；走系统 DNS 服务的域名查询不归属到引擎进程，这种方法看不到。
- 在 netstat 状态名被本地化的系统上，没有实测找监听进程这一步。
- Host（Electron）怎样结束服务进程不在本次范围，崩溃路径用强杀进程模拟。

AMEND
﻿