# T3/T10 独立后续两小项 · 主编排亲核记录（2026-10-02 00:24 (+08:00)，无人值守窗）

- target：line-B `38d1e01`（T3 gate `\\?\` 前缀归一）、`46be174`（T10 识别不清人名紧挨汉字）；令 `致B-ORCH-执行令-独立后续两小项-20261001-2301`
- 核法：独立克隆 `rv-B19`，B 线解释器，TEMP 短路径。
- diff：`gate._plain` 只归一 `\\?\C:\` 与 `\\?\UNC\` 两种，Volume/GLOBALROOT 原样仍拒；用在 `_real_top` 与 `is_within`（超出令文一处，同根因，不放宽语义——接受）。`citations._name_windows`：整串比不上再取含 ■、≥2 个认得出字的 4/3 字子串，不取 2 字。
- `test_gate.py` + `test_checks.py`：174 passed / 3 skipped。
- 变异：`_real_top` 去掉 `_plain` → `test_gate` 1 failed；`_NAME_LENS = ()` → `test_checks` 15 failed。复原后树净。
- 线 B 待定"？是否算识别不清"：**主编排定只算 `■`**（Spec 第 6 节识别不清标注只有 `■` 与 `[看不清]`；笔录普通问号多，算进去会大量误报）。
- 线 B 发现：T3 原红绿脚本 R6/R12 两条锚点在 main 上已对不上（后续改动改了写法）——记 T3 独立后续：锚点更新。
- 结论：**通过**。cherry-pick 3196032/da473d7 进 main，合流门另记 `evidence\T3\merge-小项.txt`。
