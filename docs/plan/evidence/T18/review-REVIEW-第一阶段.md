# T18 第一阶段（样本、要点、正文静态核、预算预估）· 独立复核记录

- 复核员：一名 Opus 5.5 只读复核员
- target：line-B `8e2fb48`（基座 main fb04b55）；432 文件
- 复核克隆：scratchpad `rv-B21`
- 归档：主编排于 2026-10-02 15:18 (+08:00) 从复核员交回原文抄录，未改内容

## 第一部分 复核员原文
## T18 第一阶段复核（target `8e2fb48`，基座 main `fb04b55`，只读）

我自己的克隆是 `...\scratchpad\rv-B21`。HEAD 是 `8e2fb483bb4e6ef3bfcc75f9d893b8135b48d060`，处于 detached 状态，父提交 `fb04b55`，`status` 干净。line-B 分支包含这个提交。改动共 432 个文件，+8114/-140，全部是新增或修改：
- 408 个在 `skills\*\tests\`：要点.md 18 个、任务说明.md 72 个，上游成果、已有成果和模拟 L0 卡片 25 个，案卷材料 293 个；
- 18 个 `SKILL.md`；
- 6 个在 `docs\plan\evidence\T18\`。

没有动产品代码，没有动 `_shared`、`capsules.default.json`、`contracts\`、`docs\src\`，也没有无关改动。

**结论：没有发现阻断项。** 唯一要紧的是 P2-1，它不是这次提交的错，但 T18 实测之前必须由主编排拍板。其余都是小问题。

### Findings

**P2-1 样本用的位置标记和真实导入对不上，按现在的解析，大半样本和要点在实测时用不了**（作者已列为第三节第 1 条交你定，我核实了实际影响）
- 影响范围：
  - 293 份材料里，171 份用【第N页】或【第N段】（页 147、段 24）；
  - 13 个 Skill 的 `要点.md` 里，出处按页或段写；
  - 只有 bid、tender、archiving、wiki-build 四组是按行写的。
- 实测：我把 `criminal-applications\样本01\起诉意见书.txt` 交给现行的 `ingest.text.parse` 和 `case.materials.render` 处理。
  - 结果：单位是 line，共 42 行，只有一个块【第1行】。原来的"【第1页】"被加了全角空格，降成正文。
  - 再用 `checks.citations.check_text` 核三条出处：
    - 〔起诉意见书 第2页〕和〔起诉意见书 第1页〕都报 **E 类必须修改**，提示"出处位置不对，这份材料按第N行定位"；
    - 〔起诉意见书 第13行〕通过。
- 后果：
  - 模型照样本的页码写出处，每条都会被打回；模型改成按行写，又对不上 `要点.md` 的判分。
  - `doc-revise` 样本04 故意埋了一处错误出处"对账单 第3页"，会被所有"第N页"出处的报错淹没，测不出来。
  - `contract-review` 样本01 的 `.md` 合同不是 Word。`tools\edit_list.py:135` 对非 Word 材料直接报 `not_word_material`，SKILL 第 7 步也会跳过修改清单，所以这个样本本来要测的修改清单永远测不到。
- 技术意见：建议选"测试工具先转 docx/pdf 再导入"，不建议"测试工具特殊处理"。理由是前者走真实的解析、出处核对和修订版判定链路；后者等于测试绕开产品解析，测的不是律师实际用的那条路。转换时要守三条，转完再用 `case_read_material` 读回，核对标记序列和样本一致，不一致就让工具报错：
  1. 每个【第N页】块生成一页 PDF，要强制分页，并核对页数；
  2. 每个【第N段】块生成**一个** Word 段落，块内换行用段内换行。有 17 个文件的段块是多行的：表格段，以及"第一条 标题 + 1.1 正文"这种写法，比如 `contract-review` 的样本02、03、04，`contract-draft` 的样本03、04。逐行拆成段落会让段号整体错位；
  3. 表格段转成 Word 表格。
- 已验证：`contract-review` 样本01 可以直接导入 `tests\fixtures\contract-01\采购合同.docx`。我逐段比对过，47 段里只有第 46 段（样本编号所在段）不同，其余逐字一致。
- 最小修复：主编排定方案后，由 T18 步骤 1 的测试工具实现转换和读回校验。样本本身不用改。
- 归类：独立后续（实测前必须先做）。

**P3-1 `case-wiki-build\SKILL.md` 里的实测数字和 T16 证据、报告不一致**
- SKILL 写的是"大卷宗（21 份、74 页、24 段）实测 36 次调用、约 5 分钟"，这是 Spec D6 早期 wiki 测试的数。
- `skill-report.md` 同一行写的是"T16 大卷宗实测 30 次（上限 79）"。T16 的复核记录也是 30 次、149 秒、上限 79，按公式反推是 18 段。
- 最小修复：SKILL 改成 T16 的实测数（30 次、上限 79），或者注明 36 次的出处。
- 归类：本次引入。

**P3-2 测试附件的约定散在 72 份任务说明里，测试工具难以统一处理**
- 不该当材料导入的文件，命名有四种：`上游成果-*.md`、`已有成果-*.md`、`案件卡片（模拟L0）.md`、`L0案件卡片.md`。
- "不给模型看"的测试说明，有的用"（测试用说明，不给模型看：…）"括号嵌在律师原话里（criminal-applications、defense-opinion、sentence-calc），有的用 `---` 分隔线隔开。
- 自动化时容易把判分提示漏给模型。
- 最小修复：在 `skills\` 下写一句统一约定（文件名前缀、分隔线），或者至少把括号式改成分隔线式。
- 归类：本次引入的不一致。

**NOTE**
1. **作者有两处说法偏宽：**
   - "18 个都补了 `ask_user_question` 写法"：bid-drafting、tender-review、case-archiving 只写了"一次问完"，没写工具名。系统提示 `dsh-ext\persona.md:7` 已经写了"用 ask_user_question 问"，所以影响小。
   - "每个 Skill 至少一个样本故意缺必问项"：case-wiki-build、legal-workflow 本身没有必问项，实际是 16/16 适用的 Skill 都满足，另 2 个不适用。
2. 三处表头还写着"（出处）"作列名，不是出处写法本身，不算违规：
   - `criminal-evidence-review\SKILL.md:65`
   - `cross-exam-opinion\SKILL.md:63`
   - `criminal-reading-notes\SKILL.md:67`
3. **"LBFX"字样还有残留。**完整的 LBFX- 特征串确实清零了，但 3 处虚构统一社会信用代码里有 "LBFX"（`91999900LBFXTS0018`、`91999900MA0LBFX0B4`），合同样本里还有超链接 `http://127.0.0.1/lbfx-attachment`。SEC-01 `find_leaks` 按完整特征串匹配，不受影响；但用 "LBFX" 宽匹配的反向断言（比如 `test_materials_api.py:290`）如果碰到样本正文，会误报。
4. **两处虚构号码的前缀和真实号段相同：**虚构账号 `6299 …` 是银联 62 开头，电话 `0999-8800■■21` 的区号 0999 是真实区号。两者都标了"（虚构）"、有遮挡，不构成真实信息，备注一下。
5. `要点.md` 有 3 份首行带 `#`，其余是纯文本；四节结构和表头"| # | 要点 | 关键出处 | 判分要求 |"、"扣分项"、"必问检查"在 18 份里完全统一。五组子代理分做，风格基本一致。

### 重点逐项核对

**1. 机密与真实信息**
- 408 个文件全部是 `.md` 或 `.txt`，都是 UTF-8，没有 BOM、没有 NUL、没有二进制。
- 身份证号 26 个，全部 99 开头。
- 手机号 0 个；本机用户名、IP、邮箱、Key 都是 0。
- 律所只出现"某某虚构律师事务所"，另有"律师事务所"作泛称。
- 法院、公安、检察、看守所、公司名称全部带"虚构市/虚构区/虚构县"前缀。
- 案号全部是"虚"字号或无地区号。
- 24 字片段比对：和 `docs\reference\client-skills` 重合 0；和 `tests\fixtures` 的重合都属于有意派生（README 写明全部虚构，wiki-test 大卷宗经用户 09-29 确认虚构）。
- 大卷宗原名（周立新等）只在 wiki-build 样本01 的任务说明里作为改名映射出现一次。
- 我人读了 10 份材料，没有发现真实信息：
  - crn 样本02 起诉意见书
  - archiving 样本03 刑事判决书
  - tender 样本04 询价通知书
  - case-reading-notes 样本04 送货单（内含故意埋的注入测试句，属于测试设计）
  - legal-workflow 样本04 模拟 L0
  - doc-revise 样本04 律师函
  - defense 样本04 一审判决书
  - bid 样本03 公司简介
  - general-drafting 样本03 装修合同
  - wiki-build 样本01 银行明细

**2. 样本质量**
- 18 个 Skill 各 4 个样本目录加 `要点.md`，每个样本都有任务说明。
- 要点是可核的条目，每条带出处、判分要求、扣分项和必问检查，不是泛话。
- 要点里的 664 条出处，我逐条核了材料名和位置是否存在：663 条存在；剩下 1 条是 criminal-evidence-review 有意设计的"原件不在卷"。
- sentence-calc 的期望日期，我用 `calc.sentence.calc` 对样本01、02、02b、04 和"答复前调用"的情况重算，起止日、二分之一节点、羁押天数、折抵天数、notes 全部和要点一致。

**3. Skill 正文静态核**（逐字对照 `contracts\tools\*.schema.json` 和 `common.schema.json`）
- **contract-review**：
  - 修改清单的六个字段（id/para/action/find/text/comment）、必填项、`accepted`/`out_of_scope` 和契约一致；
  - 范围外情形和 `tools\edit_list.py` 的判定一致（表格、页眉页脚、超链接或域代码、找不到或多次出现）；
  - 先存审查意见、再调修改清单的顺序符合 Spec 12.2。
- **case-archiving**：13 个参数和契约必填完全一致，`lawyer`、`fee_settled` 的含义取自契约描述；`case_archive_match` 的 `items`/`matched.folder`/`reason`/`unmatched`/`ignored`，以及 `case_list_materials` 的 `type`/`status`，都对。
- **sentence-calc**：`penalty`、`years`、`months`、`execution_start`、`custody[].from/to/kind`，返回的 `start`/`end`/`offset_days`/`custody_days`/`milestones`/`basis`/`notes`，都对。
- **suggest_wiki**：`field` 的枚举、`value`/`source`/`reason` 都对。
- **read_material**：`start`/`offset`/`max_chars`（最多 8000）/`next_offset` 都对；`read_input` 没有 `offset`，正文也没有误用。
- **legal-workflow**：12 个 skill 胶囊加 2 个工具胶囊，和 `capsules.default.json` 一致；"L0 不含已有成果、不直接写案件类型"和 `case\context.py` 的 `build_l0` 一致；"开始前要给什么"一表和各 SKILL 的必问项一致。
- **bid-drafting / criminal-applications**：都已改成回读原件再写出处。
- 全部 SKILL 的改动都没进入"共用规则"标记段之间；`_shared` 不在 diff 里，`--check` 也报"共用规则：全部一致"。

**4. 构建与契约自检**（在实验副本上跑）
- `build_skills.py --root skills --strict`：退出码 1，18 条错误，全部是"owner 未指定"，没有"测试集不全"。
- `--check`：通过。
- 同步构建前后，产物和源文件逐字节一致。
- `contracts\check_examples.py --skills skills`：退出码 0，58 个样例，0 个不符合预期。

**5. 预算复算与并发问题**
- 复算三个 Skill：
  - criminal-reading-notes 典型样本：并发时我算 6–7 次（加载、提问、读、检索、保存、可能的重存、最后回复），作者写 5–6，偏乐观 1 次；大卷宗工具 30–32 次、超出 64K 窗口，复算一致。
  - contract-review：7–8 次，和作者"贴上限"一致。
  - case-archiving：并发约 6 次和作者一致；串行我算约 10 次，作者写约 9 次。
  - 都在可接受误差内。
- **DSH 并发问题的答案：一次模型回复可以带多个工具调用，全部在同一步执行完，只算一次模型调用。** 依据：
  - pi-ai openai-completions 按 `toolCall.index` 分块，没有设 `parallel_tool_calls:false`；
  - `llm-pi-ai\src\stream.ts` 按 contentIndex 支持多个 tool-call 块；
  - `agent-loop\src\tool-calls.ts` 的 `executeToolCalls` 逐个执行本步的全部调用；
  - 但 case_* 注册时没有声明 `isConcurrencySafe`（`dsh-ext\agent\index.ts:167`），按 `tools\src\index.ts:1305` 视为 exclusive，所以**同一步里是串行执行，不是并行**。
  - 对预算的含义：作者"能并发"那一列的模型次数成立，只是耗时按串行算。qwen38-27b 实际会不会一次发出多个调用，仍待实测。
- 补充两点：
  - `task-state.ts`：`ask_user_question` 和 `skill` 不计入工具次数，但各占一次模型调用；
  - 45 分钟从任务开始按墙钟计算，**等律师回答的时间算在内**（`ask_user_question` 在同一轮里等待）。这回答了报告第二节第 5 条。

**6. 改动纪律**
- 构成：样本、要点、任务说明 408；正文 18；报告与证据 6。
- 每处正文改动都能在报告第一节找到对应理由。

**7. 全量测试**（`D:\lawbench-C\.venv`，`-B`，短路径副本）
- 结果：1252 passed、7 skipped、1 failed，用时 22 分 37 秒。
- 唯一的失败是 `test_tokens.py::test_tokenizer_json_ignored_by_git`。原因是 `git archive` 导出的副本不是 git 仓库；在 git 克隆里单跑这个文件是 7 passed。属于环境原因，和本提交无关（本提交没有代码改动）。
- 比作者多 1 个 skip，同样是导出副本的环境差异，没有深究。

### 冻结清单

| 项 | 结果 |
|---|---|
| 每个 Skill ≥4 样本 + 要点 | 符合（18/18） |
| `--strict` 只剩 owner 错误 | 符合 |
| `check_examples` 通过 | 符合 |
| 工具参数名与契约逐字一致 | 符合 |
| 〔〕出处写法 | 符合（只剩 3 处表头列名，见 NOTE 2） |
| 没改共用规则 | 符合 |
| 实测列留空，没改 PRD | 符合 |

### 八项清单

| 项 | 结果 |
|---|---|
| 契约一致 | 过 |
| 边界输入 | 有缺必问、识别不清、范围外、注入测试样本 |
| 错误路径 | 有失败材料、不是 Word、out_of_scope 样本 |
| 日志不含正文 | 不适用 |
| 路径闸门 | 不适用 |
| 无外连 | 过（样本里只有 127.0.0.1 的假链接） |
| 测试覆盖新代码 | 不适用（没有新代码） |
| 无机密入库 | 过 |

### 实际跑过的命令
- `git rev-parse`、`diff --name-status/--numstat/--word-diff`（fb04b55..8e2fb48）
- `build_skills.py --strict` / `--check` / 同步构建后逐字节比对
- `check_examples.py --skills skills`
- 自写扫描脚本：敏感信息正则、24 字片段重合、标记统计、要点出处定位
- 解析和出处核对实验（`ingest.text` → `render` → `check_text`）
- docx 段落比对（`ingest.docx`）
- `calc.sentence` 重算
- 全量 pytest，以及 `test_tokens.py` 在克隆里单跑

### 残留审计
- 我起的 python 和 bash 进程都已结束；19521–19529 端口没有监听。
- `C:\Users\<用户>\AppData\Local\Temp\claude\rvB21s\` 和 `...\scratchpad\rv-B21-lab\` 已删除。前者有超长路径，用 `\\?\` 前缀删除。
- 克隆 `rv-B21` 仍在 `8e2fb48`、状态干净，按约定留着。
- 没有碰别人的进程和仓库。

### 证据缺口
- 没有连 6000D，所以 qwen38-27b 实际会不会一次发出多个工具调用无法验证。
- 72 个样本没有逐份人读，只读了 10 份，其余靠脚本扫描。
- 要点出处只核了"材料和位置存在"，没有逐条核对数值确实落在那一行或那一页。

PASS
﻿
---

## 第二部分 主编排裁决（2026-10-02 15:18 (+08:00)）

**结论：PASS，T18 第一阶段收货，cherry-pick 进 main。** 408 个样本/要点文件无真实信息（身份证全 99 开头、律所/法院/公司全带"虚构"、24 字片段与 client-skills 重合 0）；要点 664 条出处 663 条落实；18 个 Skill 契约参数名逐字一致；`--strict` 只剩 owner 未指定；共用规则未动。

主编排裁定（报告第三节 14 条中归我的）：
| 条 | 裁定 |
|---|---|
| P2-1 样本位置标记（【第N页/段】）与 txt/md 真实导入只认行不符 | **T18 实测工具先把样本转成 docx/pdf 再导入**（走真实解析、出处核对、修订版链路），按复核员三条守则（每页块强制分页核页数；每段块一个 Word 段落、块内换行用段内换行；表格段转 Word 表格）并转完用 `case_read_material` 读回核对标记序列。样本不改。随 T18 步骤 1 做 |
| 第 2 条 "自检结果"进共用规则；"看不清"与 formats.md 不一致 | 接受：`_shared\共用规则.md` 加"输出前逐项自查并写出结果"（Spec 10.2 原话）；"照标看不清"改成 formats.md 的 ■/[看不清] 写法。随下一个 `skills` 提交做，跑 build_skills |
| 第 3 条 各 Skill 默认取法（defense-opinion 缺方向先问、sentence-calc 拘留段止日照抄逮捕日、contract-draft 不停下看骨架、doc-revise 矛盾先确认、criminal-reading-notes 加 prior、case-archiving 的 lawyer/fee_settled/opponent/结案日期） | 接受作者默认，写进交付说明；sentence-calc 那条随 N4/N53 请律师 |
| 第 4 条 合并运行覆盖清单按 reads.json、L0 不含已有成果 | 涉及程序/契约，记 T14 联调观察项；第一版维持现状 |
| 预算（第二节）模型上限 8 → 16 的建议 | 候实测（复核员核：一次回复可带多个工具调用、同一步内串行执行；45 分钟含等律师回答时间）；实测后若需调 F-RUN-05 再上候 owner |
| P3-1 wiki-build SKILL 实测数字改 T16 的 30 次/上限 79；P3-2 测试附件约定统一（文件名前缀 + 分隔线，去掉括号嵌入式）；NOTE 3 "LBFX" 残留三处改掉 | 注记线 B 随下一提交做 |