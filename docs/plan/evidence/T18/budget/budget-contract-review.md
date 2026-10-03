# T18 预算实测（2026-10-03T19:04:57+08:00）

案件：contract-review；时间窗：不限 至 不限
口径：模型 = 会话里 step/start 次数（流水线取 运行记录.json）；工具 = case_* 里除 case_save_draft 外的调用（skill、ask_user_question 不计）；超预算按 task.json 的 budget 判。

| 任务 | 类型 | Skill | 状态 | 模型 实测 / 自报 / 上限 | 工具 实测 / 自报 / 上限 | 分钟 / 上限 | 超预算 | 工具分列 | 服务日志 core | 自报（skill-report 预估：典型 ‖ 大） |
|---|---|---|---|---|---|---|---|---|---|---|
| T-20261003190150-87e0 | agent | contract-review | budget_stopped | 8 / 8 / 8 | 4 / 4 / 24 | 2.9 / 45 | 否 | case_list_materials×1、case_read_material×2、case_save_draft×3、case_search×1、skill×1 | task_begin×1、context×1、tool×7、progress×2、task_end×1 | 工具 4–6，模型约 8（串行 9），单次 12–15K ‖ 不适用（已写按份分次审） |

实测来源：DSH 会话记录
