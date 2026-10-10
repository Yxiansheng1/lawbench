# T20 第八版候选包 · 独立复核记录（PASS）

- 复核时刻：2026-10-11 06:25–06:50 (+08:00)；复核员：一名 Opus 只读复核员（克隆 `rv-A58` 检出 `131e5d9`，包副本 `rv-A58-pkg`，实验目录 `rv-A58-exp`）
- target：line-A `131e5d9`；基座 main `75e65f9`
- 包：`lawbench-0.1.0-win-x64-unsigned.exe` 655,984,879 B，sha256 `75e592d590e20022bbd048541baccbcdd35be65d39c196bfff2e1c58f9251d30`，`LAWBENCH_BUILD_STAMP=202610110524`（复核员与主编排一致；派单转写曾多一字符，以实测为准）。**第八版 = 新律所首发版（第七版未发出）。** 含：契约 1.4（服务 + 客户端）、移除此材料、P0 技能加载↔压缩死循环修法（P-25、compaction 配置、Agent 三道兜底）、到顶前强制存稿、任务结束清 Skill 选择、确认保存只按本轮/结束必登记 + 服务 stale 兜底、预算 32、sentence-calc 改法、公司名更正、prep395 契约 1.4（395 侧随部署）。
- 裁决（主编排）：**PASS**，cherry-pick `131e5d9` 进 main，发包。走查第 3 项 wiki 8 分 19 秒按"有进度流水线项 10 分钟"放行（已改清单）；NOTE-1（5b 答复未给最低刑期，按"法律适用留律师"口径）接受；P3-1/2/3 证据瑕疵记录，不补拍。

## 复核员报告（原文摘要）
1. 大小/哈希一致。2. 列包 27,185 条：`primary-runtime` 零；`libreoffice-kit` 仅 koffi 6；无 `.env.local`/`tests\fixtures`；prep395 代码不进包（只有契约）。3. `app.asar` 127,428,068 B，sha256 `6E4C6DB8…D54936` 与 build.txt 一致：`PRODUCT_BUILD` 202610110524，旧戳零；`CONTRACT_VERSION` 1.4、`"1.3"` 零；`materialsRemove` 3、`移到回收站` 5；`wrap_up_only` 4、`只剩两次` 1；`skill_reload_loop` 1、`compaction_loop` 2；`任务结束后回到自由对话` 1、`TASK_END_FAILED` 16、`任务结束状态未能登记` 1；公司名明文 4 转义 1，旧写法零；P-25 新句 1；`cordis.patch.yml` 打进 asar，`headroomTokens: 16384`、`thresholdChars: 48000` 各 1。4. `contracts\VERSION` 1.4；`task.py` `"model_calls": 32`、`_close_stale` 2；`trash.py` `has_recycle_bin` 3；`sentence-calc\SKILL.md` `more_names` 4；258 文件与克隆逐一同哈希（除 3 个构建生成）。5. `<用户名>` 零；Key 零；四地址只在 settings/examples。6. `75e65f9..131e5d9` 27 文件全在 `evidence\T20\`；数字三处一致；24 截图路径 `<用户名>`、案件"（虚构）"。走查 8 项与截图对照：1/4/5a/5c/6/8 符；2 的字数、3 的起始时刻与调用数、5b"无压缩"仅自述（截图可见范围无压缩，7 轮 19 步）。
- **P3-1** 第 7 项自述"材料 4 份·待识别 1 份·成果 1 份"，截图为第 8 项中途状态"3·0·1"。**P3-2** 第 8 项"移除 1 份"一句截图滚过。**P3-3** 两张"关于"截图未含版本号区。**NOTE-1** 5b 答复"法定刑档次需律师确定"，未给最低刑期（流程过、问题本身保守）。**NOTE-2** 交付说明引用不存在的 `w1` 截图名。**NOTE-3** 识别完成后左侧案件卡片"待识别 2 份"不刷新（界面小问题）。
- 命令：`Get-FileHash`；`git diff 75e65f9..131e5d9`；7za `l -slt -sccUTF-8`/`x`；Python 计数/比对/泄密扫；Read 24 截图。实验目录已清空，克隆干净，未进禁区，约 25 分钟。
