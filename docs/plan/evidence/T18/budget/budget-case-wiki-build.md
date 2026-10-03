# T18 预算实测（2026-10-03T22:54:11+08:00）

案件：case-wiki-build；时间窗：不限 至 不限
口径：模型 = 会话里 step/start 次数（流水线取 运行记录.json）；工具 = case_* 里除 case_save_draft 外的调用（skill、ask_user_question 不计）；超预算按 task.json 的 budget 判。

| 任务 | 类型 | Skill | 状态 | 模型 实测 / 自报 / 上限 | 工具 实测 / 自报 / 上限 | 分钟 / 上限 | 超预算 | 工具分列 | 服务日志 core | 自报（skill-report 预估：典型 ‖ 大） |
|---|---|---|---|---|---|---|---|---|---|---|
| P-20261003224448-6b03 | pipeline | case-wiki-build | completed | 14 / 14 / 37 | — / 0 / 1 | 6.9 / 45 | 否 | — | progress×3、tool×15、task_end×3、task_begin×2、context×2 | 约 12–14 次（上限 37–40） ‖ T16 大卷宗实测 30 次（上限 79） |

实测来源：运行记录.json
