# T12 第三轮返修（N56 ①）· 主编排亲核记录（2026-10-02 13:15 (+08:00)）

- target：line-C `2f2ef47`（令 1218）；`ocr/queue.py` +23/-7、`test_ocr_queue.py` +116
- diff：`_finalize` 改为任务留在内存标 `finalizing`，合并与 `UPDATE done` 写成后才 `pop`，`finally` 清标记——二选一选了"标完成写成后才移出内存"；y1/y2 收为用例；`finalizing` 防重入、已结束出内存各补一例。
- 核法：独立克隆 `rv-C25`，C 线解释器 `-B`（B 线 venv 缺 pypdf——T23 新依赖，合流门改用 C 线解释器）。
- `test_ocr_queue.py` 连跑 2 遍：33 passed ×2；复核员 `test_lab_c18.py` y1–y4：4 passed。
- 变异：`pop` 挪回 `finalizing = True` 之后 → 3 failed（y1/y2/收尾相关）；复原后树净。
- rebase 冲突说明（`api\ui.py` 与 T16 路由；`path_params` 成无用参数）记独立后续。
- 结论：**通过**。T12 任务门=过；line-C 整条（27 提交：T12/T25/T15/T23 + 小项）`git merge --no-ff` 进 main `ae6a617`，合流门在跑。
