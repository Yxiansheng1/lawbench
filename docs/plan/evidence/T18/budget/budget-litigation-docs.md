# T18 预算实测（2026-10-03T19:56:26+08:00）

案件：litigation-docs；时间窗：不限 至 不限
口径：模型 = 会话里 step/start 次数（流水线取 运行记录.json）；工具 = case_* 里除 case_save_draft 外的调用（skill、ask_user_question 不计）；超预算按 task.json 的 budget 判。

| 任务 | 类型 | Skill | 状态 | 模型 实测 / 自报 / 上限 | 工具 实测 / 自报 / 上限 | 分钟 / 上限 | 超预算 | 工具分列 | 服务日志 core | 自报（skill-report 预估：典型 ‖ 大） |
|---|---|---|---|---|---|---|---|---|---|---|
| T-20261003195518-4294 | agent | litigation-docs | budget_stopped | 8 / 8 / 8 | 3 / 3 / 24 | 0.9 / 45 | 否 | case_read_material×2、case_read_wiki×1、case_save_draft×4、skill×1 | task_begin×1、context×1、tool×7、progress×3、task_end×1 | 工具 6–9，模型 6–7（串行 12–13），单次 15–20K ‖ 工具 17–20，模型串行 20+ |

实测来源：DSH 会话记录
