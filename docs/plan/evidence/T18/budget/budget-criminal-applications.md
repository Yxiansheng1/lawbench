# T18 预算实测（2026-10-03T20:00:58+08:00）

案件：criminal-applications；时间窗：不限 至 不限
口径：模型 = 会话里 step/start 次数（流水线取 运行记录.json）；工具 = case_* 里除 case_save_draft 外的调用（skill、ask_user_question 不计）；超预算按 task.json 的 budget 判。

| 任务 | 类型 | Skill | 状态 | 模型 实测 / 自报 / 上限 | 工具 实测 / 自报 / 上限 | 分钟 / 上限 | 超预算 | 工具分列 | 服务日志 core | 自报（skill-report 预估：典型 ‖ 大） |
|---|---|---|---|---|---|---|---|---|---|---|
| T-20261003195929-4bf5 | agent | criminal-applications | budget_stopped | 8 / 8 / 8 | 4 / 4 / 24 | 1.3 / 45 | 否 | ask_user_question×1、case_read_material×4、case_save_draft×2、skill×1 | task_begin×1、context×1、tool×6、task_end×1 | 模型 4–5，工具 5–8，单次 8–12K ‖ 模型 5–7，工具 10–15，单次 15–25K |

实测来源：DSH 会话记录
