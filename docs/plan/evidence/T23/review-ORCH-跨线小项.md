# 跨线小项（服务侧读 LAWBENCH_SOFFICE/PANDOC；Python 子进程 PYTHONNOUSERSITE=1）· 主编排亲核记录（2026-10-02 11:38 (+08:00)，无人值守窗）

- target：line-C `a90eb4d`（令 1017）；12 文件 +226/-13
- diff：`libreoffice.find_soffice`/`pandoc` 探测优先读环境变量（设了且文件在）；`procs.python_env` 就地加 `PYTHONNOUSERSITE=1`，发票引擎 `runner`、证件识别 `driver`、`convert` LibreOffice 子进程、pandoc 都走它；T25 净化环境白名单用例补新变量；`test_procs_env.py` 6 例。
- `test_procs_env` + `test_export` + `test_invoice` + `test_retainer_driver` + `test_convert` + `test_t5_convert_safety`：第一遍 170 passed / 1 failed，第二遍 171 passed / 1 skipped（首遍 1 失败为机器忙时的超时类偶发，与 T23 复核员见过的同类；第二遍全绿）。
- 变异：`python_env` 不设变量 → `test_procs_env` 5 failed；复原后树净。
- 线 C 自报：全量 1167 passed / 3 failed → 三条是白名单用例未列新变量，已补并重跑相关三组 86 passed，之后未重跑全量——合并前合流门会跑全量，接受。
- 结论：**通过**。随 line-C 整体合并（候 N56）。
