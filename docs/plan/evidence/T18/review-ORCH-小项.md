# T18 第一阶段小项 + N60 说明 · 主编排亲核记录（2026-10-02 15:54 (+08:00)）

- target：line-B `41a639b`（T18 小项：共用规则两条、wiki-build 实测数、`skills\README.md` 约定、97 个附件改 `_` 前缀、72 份任务说明分隔线统一、LBFX 残留换掉、三处补 `ask_user_question`）、`a5445f3`（T16 交付说明：`use_prep` 契约必填、默认不勾落界面）。
- 核法：ff 合并到 main 后在 main 跑：`check_examples --skills` 过；`build_skills --check` 过；`--strict` 只剩 18 条 owner 未指定；`skills\` 下 LBFX/用户名 0 命中；引用 `skills` 的 7 个测试文件 475 passed / 3 skipped。
- 线 B 自报一次 `--amend`（只动交付说明计数、未推送、自己分支）——违反"不 amend"规矩，已提醒；无实际影响。
- `use_prep`：维持契约 1.3 必填，不改契约；"默认不勾"由界面侧（线 A，T14 联调时）把勾默认 false——记 T14 观察项。
- 结论：**通过**。main 推送。
