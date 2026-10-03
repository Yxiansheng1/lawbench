# T18 预算实测（2026-10-03T22:53:19+08:00）

案件：case-archiving-2；时间窗：不限 至 不限
口径：模型 = 会话里 step/start 次数（流水线取 运行记录.json）；工具 = case_* 里除 case_save_draft 外的调用（skill、ask_user_question 不计）；超预算按 task.json 的 budget 判。

| 任务 | 类型 | Skill | 状态 | 模型 实测 / 自报 / 上限 | 工具 实测 / 自报 / 上限 | 分钟 / 上限 | 超预算 | 工具分列 | 服务日志 core | 自报（skill-report 预估：典型 ‖ 大） |
|---|---|---|---|---|---|---|---|---|---|---|
| T-20261003225149-2962 | agent | case-archiving | budget_stopped | 8 / 8 / 8 | 4 / 4 / 24 | 1.3 / 45 | 否 | ask_user_question×1、case_archive_match×1、case_read_material×2、case_save_archive_plan×1、case_save_draft×2、skill×1 | task_begin×1、context×1、tool×6、progress×3、task_end×1 | 工具 6–7，模型约 6（串行约 9），单次约 1 万 ‖ 工具基本不变，输入约 1.5 万 |

实测来源：DSH 会话记录
