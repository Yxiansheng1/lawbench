# T3 端口被占原因分类（第七版待办 10）· 独立复核记录（AMEND）

- 复核时刻：2026-10-10 14:55–15:05 (+08:00)；复核员：一名 Opus 只读复核员（克隆 `D:\lawbench-rv\rv-B23`，实验目录 `rv-B23-exp`）
- target：line-B `9bcc4fd`；基座 main `5e0d218`；`portdiag.py` 新 83 行、`__main__.py` +14、`test_main.py` +57
- 裁决（主编排）：**AMEND**。P3-1 阻断（含端判断无用例守），P3-2/3/4 一并小修；令 `致B-ORCH-执行令-端口原因分类复核AMEND-<HHMM>.md`。NOTE-1 转线 A 注记（客户端接入要点）。返修后主编排亲核累计范围。

## 复核员报告（原文摘要）

**verdict：AMEND。** 主体按令实现正确。

### 范围内已核实
netsh 固定参数列表、`shell=False`、`CREATE_NO_WINDOW`、`timeout=3.0`，超时 kill 后落 DENIED；`decode("mbcs","replace")` 不崩，本机真跑 netsh 解析出 8 段（含 `5357 5357` 单端口段），表头任何代码页不影响；只取行首两个数字、`*` 行可识别、起点>终点或 >65535 丢弃；再绑取错误码用 `127.0.0.1` 与 uvicorn 一致、`finally` 关 socket；lifespan 失败不会误判端口；`_silence_uvicorn` 保证分类行是 stderr 首行、显式 UTF-8 写 `sys.stderr.buffer` 并 flush；退出码仍 2；日志只多 `error=type(e).__name__`；契约未改。

### Findings
- **P3-1 含端判断无用例守**（范围内阻断）：`a <= port <= b` 改为 `<` 任一端，用例结果与基线同（M1/M6 变异存活）。最小修复：加 5357→RESERVED、18700/18799→RESERVED 三条断言。
- **P3-2 netsh 相对名**：`NETSH = ["netsh", ...]` 按名查找，CreateProcess 先找 python 目录与当前目录。修：`%SystemRoot%\System32\netsh.exe`。
- **P3-3 两端口都失败时 netsh 跑两次**：与令"只跑一次"不符，最坏串行 6 秒。修：`lru_cache(1)`。
- **P3-4 `bind_error` 建 socket 在 try 外**（臆测）：极端情况进程退出码 1 带回溯而非 2+DENIED。修：进 try / 外层兜底。
- **P3-5 探测时占用方刚退出会落 DENIED**（臆测，独立后续）：可不改。
- **NOTE-1（给线 A）**：`host\supervisor.ts` 的 `lastErrorLine` 只取末 20 行里最后一条"异常类名: 消息"，分类行会被忽略；退出码 2 固定文案"被其他程序占用"，端口一律填 `forwardPort`。接入：取 stderr 去空首行按 `^(PORT_IN_USE|PORT_RESERVED|PORT_DENIED) (\d+) (.*)$` 解析；确认 `host\index.ts:716` 解码 UTF-8；确认 `maxBytes 65536` 缓冲保留头部。

### 跑过的命令
克隆内 `pytest tests\test_main.py -q -p no:cacheprovider` 6 passed；实验目录副本变异 M1–M6（M2/M3/M4/M5 红，M1/M6 存活；副本基线 2 例因缺 `contracts\VERSION` 失败，与改动无关）；本机真跑 `portdiag.run_netsh()`；只读查看 `__main__.py`、`logs.py`、`dsh-ext\host\supervisor.ts`、`host\index.ts:690-724`。
