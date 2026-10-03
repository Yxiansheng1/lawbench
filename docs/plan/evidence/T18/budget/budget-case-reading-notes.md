# T18 预算实测（2026-10-03T22:36:25+08:00）

案件：case-reading-notes；时间窗：不限 至 不限
口径：模型 = 会话里 step/start 次数（流水线取 运行记录.json）；工具 = case_* 里除 case_save_draft 外的调用（skill、ask_user_question 不计）；超预算按 task.json 的 budget 判。

| 任务 | 类型 | Skill | 状态 | 模型 实测 / 自报 / 上限 | 工具 实测 / 自报 / 上限 | 分钟 / 上限 | 超预算 | 工具分列 | 服务日志 core | 自报（skill-report 预估：典型 ‖ 大） |
|---|---|---|---|---|---|---|---|---|---|---|
| T-20261003223517-9743 | agent | case-reading-notes | budget_stopped | 8 / 8 / 8 | 6 / 6 / 24 | 1.0 / 45 | 否 | case_list_materials×1、case_read_material×5、case_save_draft×1、skill×1 | task_begin×1、context×1、tool×7、task_end×1 | 工具 8–10，模型 8–9（串行约 12），单次 15K ‖ 工具 26–29，输入 90–115K，输出 20–30K |

实测来源：DSH 会话记录
