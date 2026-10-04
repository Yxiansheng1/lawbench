# T18 实测后续（线 B 四提交：预算 16 `677c645` / 必问四处 `f50a927` / T10 按行每行标号 `e623573` / T23 对方当事人口径 `28eabfd`）· 主编排亲核记录

- 来件：`致ORCH-B-交回-T18后续-1125.md`；target → main cherry-pick（末 `f707b33`）
- 落件时刻：2026-10-04 11:27 (+08:00)
- 核过：
  - 契约未改（`contracts` diff 为空）；`DEFAULT_BUDGET` 16；17 个 SKILL.md 不再含"8 次"；共用规则加"剩 2 次先存稿"；PRD/Spec/业务编排已改并注 N68；`check_examples` 过、`build_skills --check` 过。
  - T10：`texts.render` 2 行，按行材料每行标【第N行】，存储格式不变；`test_tools` 新例随 166 passed（tools+checks+t5_marks）；`test_core` 26 passed。
  - T23：只改 SKILL.md（公诉机关写全称、民事写对方全称、无则 null）——接受"全称"理解。
- 未做项裁定：T8 "等律师回答不计入 45 分钟"的实现点在 Agent 插件 `dsh-ext\agent\task-state.ts` 的 `overTime`，属线 A——**转线 A**（随令 1117 第 3 项一起做）；PRD/Spec 已写的半句保留。"超过 8/12 份建议分批"的门槛维持不动（N68 只调模型调用数）。
- **通过。**