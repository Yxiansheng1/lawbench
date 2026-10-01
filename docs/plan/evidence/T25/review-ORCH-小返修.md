# T25 小返修 · 主编排亲核记录（2026-10-01 17:30 (+08:00)）

- target：line-C `c095ee6`（第二轮双人复核综合裁决第 2 节清单：B-P3-1、lifespan 用例、`stop` 提示、交付说明）
- 核法：独立克隆 `rv-C17` detach 到 `c095ee6`，B 线解释器，TEMP 指短路径（深路径下引擎用例出 FileNotFoundError——即 T20 输入里的 ~110 字符缓存路径限制，与本卡无关）。
- diff 核对：`runner.py` 1 行条件（`run` 只在 `code == 0` 另存）；`driver.py` 新增 `MSG_STOP_PENDING`、日志 `error` 字段（stop_pending / not_ours / port_taken / not_running）、`kill_tree` 后端口未放开返回 `running:true` + 该提示；三条新用例；交付说明 16 行。无无关改动。
- `test_invoice.py` + `test_retainer_driver.py`：**78 passed / 2 skipped**（作者 80 passed 在 C 线解释器；2 skip 为驱动依赖缺失，与第二轮复核员一致）。
- 变异：把条件改回 `action in ("prepare", "reprint", "run")` → `test_run_exit2_does_not_touch_same_name_old_batch` **红**、`test_run_exit0_still_writes_copy` 绿；复原后克隆树净。
- 结论：**通过**。T25 任务门=过；合流门等 T12 返修复核结果，与 T12 一起合并 line-C。
