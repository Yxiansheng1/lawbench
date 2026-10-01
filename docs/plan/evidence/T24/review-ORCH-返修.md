# T24 返修 · 主编排亲核记录（2026-10-01 17:45 (+08:00)）

- target：line-B `ffa2e72`（累计 `2b67ed7` 第一轮 + `ffa2e72` 返修；第一轮复核 `review-REVIEW.md` 第二部分清单）
- 核法：独立克隆 `rv-B16` detach 到 `ffa2e72`，B 线解释器，TEMP 短路径。
- diff 核对：`calc/sentence.py` `calc()` 外包一层捕获 `OverflowError`/`ValueError` → `INVALID_ARGUMENT date_out_of_range`（输入已过契约校验，ValueError 不会掩盖参数以外的错）；`SKILL.md` 处理步骤加第 4 条（数罪并罚、缓刑考验期、减刑后新刑期列为需律师判断并写进刑期计算表）；两条新用例；交付说明第 3/5/6/7 节、`rules.md` 改成事实。无无关改动。
- `check_examples.py --skills skills` 通过；`build_skills.py --root skills --check` 通过。
- `test_sentence.py`（含 `test_checks`、`test_t3_single_line` 一起）156 passed；`-k 'r13 or contract'` 33 passed。
- 变异：去掉 `except (OverflowError, ValueError)` → `test_date_out_of_range_is_bad_argument` **红**（1 failed / 36 passed）；复原后树净。
- Spec 13.4"不处理"行由主编排改写（工具输入无法识别这些情形，提醒由 Skill 承担），`build_docs.py` 已跑。
- 结论：**通过**。T24 任务门=过；六处法律口径随 N53 候律师，结果均带"（待律师核实）"。
