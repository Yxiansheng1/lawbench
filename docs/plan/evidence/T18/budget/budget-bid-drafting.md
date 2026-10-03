# T18 预算实测（2026-10-03T21:44:56+08:00）

案件：bid-drafting；时间窗：不限 至 不限
口径：模型 = 会话里 step/start 次数（流水线取 运行记录.json）；工具 = case_* 里除 case_save_draft 外的调用（skill、ask_user_question 不计）；超预算按 task.json 的 budget 判。

| 任务 | 类型 | Skill | 状态 | 模型 实测 / 自报 / 上限 | 工具 实测 / 自报 / 上限 | 分钟 / 上限 | 超预算 | 工具分列 | 服务日志 core | 自报（skill-report 预估：典型 ‖ 大） |
|---|---|---|---|---|---|---|---|---|---|---|
| T-20261003214428-e04e | agent | bid-drafting | budget_stopped | 8 / 8 / 8 | 7 / 7 / 24 | 0.3 / 45 | 否 | case_list_materials×1、case_read_input×1、case_read_material×5、skill×1 | task_begin×1、context×1、tool×6、task_end×1 | 工具 5–6，模型约 5（串行 8–9），单次 1.5–2 万 ‖ 工具约 23，模型串行约 26 |

实测来源：DSH 会话记录
