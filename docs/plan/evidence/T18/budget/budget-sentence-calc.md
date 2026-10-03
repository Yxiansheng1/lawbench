# T18 预算实测（2026-10-03T19:59:17+08:00）

案件：sentence-calc；时间窗：不限 至 不限
口径：模型 = 会话里 step/start 次数（流水线取 运行记录.json）；工具 = case_* 里除 case_save_draft 外的调用（skill、ask_user_question 不计）；超预算按 task.json 的 budget 判。

| 任务 | 类型 | Skill | 状态 | 模型 实测 / 自报 / 上限 | 工具 实测 / 自报 / 上限 | 分钟 / 上限 | 超预算 | 工具分列 | 服务日志 core | 自报（skill-report 预估：典型 ‖ 大） |
|---|---|---|---|---|---|---|---|---|---|---|
| T-20261003195839-8c68 | agent | sentence-calc | budget_stopped | 8 / 8 / 8 | 6 / 6 / 24 | 0.3 / 45 | 否 | ask_user_question×1、case_calc_sentence×1、case_read_material×4、case_search×1、skill×1 | task_begin×1、context×1、tool×6、task_end×1 | 刑期计算：模型 5–6，工具 8–12 ‖ 刑期计算：模型 6–7，工具 10–14；量刑分析：工具 25+ |

实测来源：DSH 会话记录
