# T18 预算实测（2026-10-03T18:57:45+08:00）

案件：criminal-reading-notes；时间窗：不限 至 不限
口径：模型 = 会话里 step/start 次数（流水线取 运行记录.json）；工具 = case_* 里除 case_save_draft 外的调用（skill、ask_user_question 不计）；超预算按 task.json 的 budget 判。

| 任务 | 类型 | Skill | 状态 | 模型 实测 / 自报 / 上限 | 工具 实测 / 自报 / 上限 | 分钟 / 上限 | 超预算 | 工具分列 | 服务日志 core | 自报（skill-report 预估：典型 ‖ 大） |
|---|---|---|---|---|---|---|---|---|---|---|
| T-20261003185017-2bd1 | agent | criminal-reading-notes | budget_stopped | 8 / 8 / 8 | 4 / 4 / 24 | 5.8 / 45 | 否 | ask_user_question×1、case_read_material×4、case_save_draft×2、skill×1 | task_begin×1、context×1、tool×6、task_end×1 | 模型 5–6，工具 6–10，单次约 2 万 ‖ 不分批：工具 30–32、输入超 64K |

实测来源：DSH 会话记录
