# T13 五提交（第一批小修、到顶前存稿、P0 压缩死循环、确认保存/结束登记、清 Skill 选择）· 独立复核记录（AMEND）

- 复核时刻：2026-10-11 04:43–04:58 (+08:00)；复核员：一名 Opus 只读复核员（克隆 `D:\lawbench-rv\rv-A62`，实验目录 `rv-A62-exp`）
- target：line-A `0185ba9`（累计 `473e6cc`→`267337c`→`1732538`→`871d8c5`→`0185ba9`）；基座 `d33cc44`；35 文件 +1247/-69
- 裁决（主编排）：**AMEND**。主修法成立；三处 P2（均为推算）与两处 P3 一并小修（令 `致A-ORCH-执行令-五提交复核AMEND-五处小修-<HHMM>.md`）：P-25 开头语补"检查点后无用户消息则 Pending Jobs 最近一条即当前请求"；`headroomTokens` 8192→16384；压缩收尾只数"无读取进展的压缩"；TASK_END_FAILED 不覆盖 BUDGET_STOPPED；spec 读 yml 去 CRLF。返修后派人只审该提交。

## 复核员报告（原文摘要）

**结论：AMEND。** 压缩触发点算式对照 DSH 源码核过、数值对；P-25 严格链 20 个 0 输出；各提交变异均红。

### Findings
- **P2-1 P-25 开头语使"一轮中途压缩"丢本轮请求**（引入的回归，推断）：`compaction-basic/src/region.ts selectCompactableRange` 只留尾部约 16%(W−O)，本轮用户消息常入摘要 Pending Jobs，而开头语叫模型把 Pending Jobs 当历史；49152 的 Skill 只留约 13107 估算 token（约 6 次读材料）。A 真机第 3 例只测新一轮发"你好"。修：补一句 + 中途压缩用例。
- **P2-2 预留 8192 偏小**（引入的回归，推算）：DSH 固定 4 字符/token 估算（`token-meter/estimate.ts CHARS_PER_TOKEN=4`），8000 中文字估 2000 实约 5500，并发读 3 份少算约 1 万；边界 73728+49152+8192=131072 零余量；超窗兜底 `maxOverflowRetries 1` 依赖报错文字命中 `isContextWindowExceededError`（网关/6000D 回文未核）。修：16384 或核报错文字。
- **P2-3 压缩超 3 次收尾截断正常长任务**（引入的回归，推算）：49152 的 Skill 压缩后约剩 2.8 万实际 token（约 5 次读满），读满 20 次左右即第 4 次压缩触发 `compactionLoop` 代存收尾；main 工具上限 48 下正常重读任务会被切断。修：只数无进展压缩，或放宽到 6。
- **P3-1** `turn-notices.ts note()` 每会话只留最新一条：BUDGET_STOPPED 后若 end 两次失败记 TASK_END_FAILED 会盖掉代存草稿提示（罕见）。
- **P3-2** `compaction-loop.spec.ts` 用 `\n` 定位，CRLF 检出下 2 例失败；LF 后 10/10。
- **NOTE**：一轮中途换 Skill 时 DSH 按上次请求 max_tokens 算触发点（原有行为）；代存只取最后一条回复（按令）；清选择极窄竞态。

### 核过成立
A 算式 `floor(min(W×ratio, W−O−B))` 与 DSH README/`index.ts` 一致；剪枝 48000 与 `case_read_material` 单次 ≤8000 字相符；摘要请求在窗口内。B P-25 只改 `summarizer.ts` 两处字符串；链 20/20、162 路径；哈希与 A 工作区一致。C pre-execute `arguments` 已解析、技能名取得到；pre-step 无"最后一条须为律师消息"约束；`compaction/summary` 为已登记事件；两套计数独立不误触发。D 最后一次只写文字正常结束；`case_save_draft` 出处核对只记不拒；代存在 end 前。E `TurnLocation.status` 真实字段；七种结束原因/budget/压缩收尾有用例；等必问时 Agent 非 idle，空闲兜底有 2 秒延迟 + 同任务比对。F 只清开始时那一份；老用例 4 处改期望合理。
变异 M1–M5 共 10 处全红。vitest 811/3/6（brand.spec 环境、compaction-loop 2 例 CRLF），折算 814/0/6；tsc 0；check_ui_words（`--dsh` 指实验目录 dsh）零命中。

### 跑过的命令
`git diff --stat d33cc44 0185ba9`；`rv-A59-exp\dsh` 共享克隆检出基线打严格链；外包 vitest 配置（cacheDir 指实验目录）全量与单跑；tsc；check_ui_words；M1–M5 变异后还原。联接已拆，A 目录无写入，克隆干净。
