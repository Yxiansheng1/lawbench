# T3/T10 第二轮复核三条 P3 小项 · 主编排亲核记录（2026-10-01 17:45 (+08:00)）

- target：line-B `d1ae7b4`（注记 1644；清单 = `T10\review-REVIEW-第二轮.md` 第二部分表）
- 核法：独立克隆 `rv-B16`，B 线解释器。
- diff 核对：`contracts.py` 登记时去掉各份契约 `\` 并按 `DRAFT202012.create_resource` 登记（P3-a）；`_CONTROL_REL_PATH = [\x00-\x1f]` 只对 pattern 等于 common `rel_path` pattern 的字段使用（P3-b，按主编排定）；`citations._chinese_only` 对"年Y"单独判（P3-c）；`checks/__init__.py` 读 `SKILL.md` `errors="replace"`；用例五条；T3 交付说明第 14 节划改、第 15 节；T10 第 6/8 节。无无关改动。
- `test_t3_single_line.py` + `test_checks.py`（随 `test_sentence`）156 passed。
- 变异：登记时保留 `\`（`body = dict(sch)`）→ `test_ref_into_whole_documents_keeps_check` **红**（1 failed / 18 passed）；复原后树净。
- "三种模式"线 B 理解为校验返回真/假两种配置——接受（生产模式不校验返回本就 200，开发/测试模式校验返回是这条 P3 的实际路径）。
- 结论：**通过**。随 T24 一起 cherry-pick 进 main。
