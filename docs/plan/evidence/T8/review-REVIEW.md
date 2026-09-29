# T8 复核记录（/core 五个命令与 8 个 AI 工具）与主编排裁决

- 复核员：主编排派出的子代理，Opus 5.5 · high，只读。停摆前（00:2x）派出的那一名因用量上限中断、没有留下结论，本份是 01:3x 重新派出的另一名
- target：head `6ef6dbd232476086900bd5e19a42a4a5c1aedfe8`（line-B），base `30f7425`；范围 `git diff 30f7425 6ef6dbd` 的全部
- 复核位置：主编排临时目录里的克隆和实验目录；应用数据目录显式指到实验目录；只连复核员自己在 `127.0.0.1` 上起的服务
- 时间：2026-09-30 01:33 起，约 26 分钟（无人值守窗内）
- 第一部分是复核员最终报告的原文，未作删改；第二部分是主编排的裁决

---

## 第一部分 复核员报告
# T8 独立复核报告（line-B @ 6ef6dbd，范围 30f7425..HEAD）

先亲验：克隆 `rv-B8` 的 `git rev-parse HEAD` = `6ef6dbd232476086900bd5e19a42a4a5c1aedfe8`，`git status --short` 为空（复核前后都是）。`git diff --stat 30f7425 HEAD` 共 24 个文件，+2087/-6。契约目录与 origin/main 一致（diff 为空）。Spec 和工单都取自 `origin/main`。

**不变量（一句话）**：插件和 AI 只能凭 `task_id` 在它所属的案件里读写 `工作区/任务/<task_id>/`。材料一律按材料名经闸门去读。每次读取都记进 `reads.json`，覆盖清单只按真实读过的内容来算。任务状态按 pending → running → finished/abnormal 单向推进。
**受影响的旅程**：插件调 `/core/*`；AI 调 8 个 `case_*` 工具；界面调 `/api/task`、`/api/tasks`；`/api/case/open`（新挂了 `mark_abnormal`）。

---

## Findings（按严重度）

### P1-1 覆盖清单会把"只读到一部分的单元"记成读完，单元剩下的内容读不到（范围内阻断）
- **问题**：单个单元超过 `max_chars` 时，`case_read_material` 截断返回，`reads.json` 却把整个单元记成已读，`next_start` 直接跳到下一个单元。被截掉的部分用任何工具都读不到，覆盖清单还显示"全部读过"。
- **违反的不变量**：Spec 9.2 要求覆盖清单"按 reads.json 的实际读取记录计算，不采信模型自报"。这里的记录本身就不真实。
- **影响**：
  - `max_chars` 由 AI 控制，契约最小值 500。AI 传 500 时，凡是超过约 500 字的页或段都会被截断，覆盖却算读完。
  - 默认 8000 也会触发。Word 里"表格整体算一段"（formats.md 第 2 节），大表格超过 8000 字时，后半部分永远读不到。
  - 律师看到"全部读过"，实际没读完。
- **证据**：
  - 代码：`tools/materials.py` 第 53–59 行，截断后仍写 `from=picked[0].no, to=picked[-1].no`；第 56 行 `nxt` 取下一个单元。
  - 实验 exp2 C′：虚构 txt 里有一行 3360 字，`max_chars=500` 时第 2 单元"返回 500 字 截断=True next=3"，结果 `coverage fully_read=['长行说明']`。
  - 变异 M8（把截断分支改成不截断）后 71 个用例全部不变红，说明没有任何测试盯着截断。
- **最小修复**：单元被截断时，不把它记进 `reads.json`（或者 `to` 只写到上一个完整单元），让它进 `partially_read`。"读单元余下部分"要加参数，属于改契约，交主编排。

### P1-2 同一案件再次打开时，正在执行的任务被打成 abnormal，连 `case_save_draft` 都被拒（范围内阻断）
- **问题**：`/api/case/open` 每次都调用 `mark_abnormal`，不区分"上次硬退出留下的 running"和"本进程正在跑的 running"。
- **违反的不变量**：Spec 9.2 只要求在"硬退出（进程被结束、断电）：下次打开案件时"标异常中断；9.2 还要求保证模型总有机会保存。
- **影响**：律师在 AI 执行中从最近列表再点一次同一案件，当前任务的所有工具调用都返回 `TASK_NOT_FOUND`，包括 `case_save_draft`。随后 `task/end` 又把 abnormal 改写成 completed。
- **证据**：
  - 代码：`api/ui.py` 新增的 `case_open`；`case/task.py` 第 197–219 行。
  - 实验 exp1 G：开始时工具 ok → 重开同一案件 → 工具返回 `TASK_NOT_FOUND`，task.json state 为 abnormal，save_draft 返回 `TASK_NOT_FOUND`，end 返回 `completed`。
- **最小修复**：`TaskStore` 在内存里记下本进程 `begin` 过的 task_id，`mark_abnormal` 跳过这些任务。也可以只在本进程第一次打开该案件时执行一次。

### P1-3 `result.json` 的读-改-写没有互斥：progress 和 save_draft 交错时草稿记录丢失，结束时还把"进行中"错改成"未完成"（范围内阻断）
- **问题**：`progress`、`case_save_draft`、`end` 都是"读 result.json → 改 → 整份写回"，不加锁，接口又跑在线程池里（`ui.py` 第 46 行 `run_in_threadpool`）。
- **违反的不变量**：结果清单要如实记录草稿（Spec 9.2、20.8）。F-RUN-04 规定只有"没保存过正式草稿"才改名为 `未完成-<时间>.md`。
- **影响**：
  - 插件在 `assistant/message` 时异步调 progress，同一轮的工具调用几乎同时到达，两者重叠是现实的时序。
  - 一旦重叠，`drafts` 被覆盖成空：`task/end` 把 `进行中.md` 改名为 `未完成-…md`，`/api/tasks` 里该任务的草稿数为 0，但草稿文件其实在盘上。
- **证据**：
  - 代码：`case/task.py` 第 267–273、275–289 行；`tools/drafts.py` 第 35–39 行。
  - 实验 exp2 I2（用确定的交错顺序复现）：草稿文件 `['答辩状-v1.md','进行中.md']`，但 `result.drafts: []`；end 之后目录为 `['未完成-…md','答辩状-v1.md']`；`/api/tasks` 里 drafts 为 `[[]]`。
  - 真实 DSH 时序没法实测（T7 未就绪），所以复现手段属于人为交错，但代码里确实没有任何互斥。
- **最小修复**：用 `TaskStore._lock`（或按任务的锁）包住这三处 result.json 的读-改-写。

### P2-1 "本页需识别"的占位页也算已读（范围内；语义可请主编排确认）
- **证据**：exp4 把虚构 PDF 的第 2、3 页改成 `（本页需识别）` 占位后逐页读完，结果 `coverage: fully_read=['起诉意见书']`。代码见 `case/task.py` 第 247–262 行，单元总数包含占位单元。
- **最小修复**：覆盖计算不把占位单元算进"已读"（或把它算进 partially/unreadable 并写明原因）。

### P2-2 草稿版本号可能相撞或互相覆盖（范围内）
- **并发同标题**：exp3 I′ 中两次并发 save_draft 都返回 v1，盘上只剩一份内容，`result.drafts` 只有 1 条。
- **大小写不同的标题**：exp1 B 依次存 Report / report / REPORT，都返回 v1。盘上只剩一个文件，内容是最后那次；`result.drafts` 有 3 条，指向同一个文件。
- **原因**：`tools/drafts.py` 第 29–33 行，版本匹配区分大小写，而 NTFS 不区分；计算版本和写文件之间也不加锁。
- **最小修复**：在锁内取版本并写入；匹配已有版本时两边都用 `os.path.normcase`（或 casefold）。

### P2-3 `case_suggest_wiki` 并发时丢建议、编号重复（范围内）
- **证据**：exp2 I3 两次调用都返回 `S0002`，文件里只剩"事实2"，"事实1"丢了。代码见 `tools/drafts.py` 第 44–58 行。
- **最小修复**：读-改-写加锁。

### P2-4 终态不受保护（范围内）
- **现象**：
  - `end` 可以重复调用并改写状态：cancelled → completed，用量也被覆盖。
  - `end` 之后再来的 `progress` 仍会写 `进行中.md` 并改用量。exp1 F 中结束后目录为 `['未完成-….md','进行中.md']`，usage 被改成 9/9。
  - 插件的 progress 是异步的，迟到的 progress 是现实场景。
- **代码**：`case/task.py` 第 267、275 行都不检查 `state`。
- **最小修复**：`end` 遇到 `state==finished` 时直接返回已写的状态；`progress` 在非 running 时不写。

### P2-5 材料扫描或导入期间，这个案件的全部工具调用和 `/core/context` 都要等扫描做完（范围内，活性问题）
- **原因**：T8 新增的 `Materials.index()` 要拿案件锁，而 `scan`/`import_` 在转换文件的整个过程中都持有这把锁（`materials.py` 第 222、393 行）。
- **影响**：等待没有超时，时长等于整次扫描的时间；线程池（默认 40）有可能被占满，拖累其他案件。
- **证据**：exp5 人为持锁 3 秒，工具调用 3.03 秒后才返回。
- **最小修复**：`index()` 不拿锁直接读。index.json 是原子替换写入的，读到的一定是完整的旧版或新版。

### P2-6（独立后续，T3 代码，落在 T8 旅程上）`gate._mkdirs` 的检查和建目录之间有竞态
- **问题**：同一任务的第一次 save_draft 如果有两个并发请求，其中一个在 `os.mkdir` 报 `FileExistsError`，返回 500 INTERNAL。
- **证据**：exp2 I 的 traceback 指向 `gate.py` 第 375 行。
- **最小修复**：在 `_mkdirs` 里捕获 `FileExistsError` 后继续做原有的复查。这属于 T3 返修范围，交那一轮。

### P3
1. **L1 实际 token 可以超过 40%**：目录那几行不计入预算。exp2 J 的极端例（61 份输入、标题较长）中，预算 13107，`l1.tokens=17078`。通常 2–5 份输入时只超几十 token。代码见 `context.py` 第 80–84 行。
2. **错误码不对**：对还没 begin 的任务调 `progress`/`end` 返回 500 INTERNAL，应该是 TASK_NOT_FOUND（exp1 F）。原因是 result.json 不存在。
3. **progress 不更新"已读材料"**：Spec 9.2 括号里写的是"已用调用次数、已读材料"，实现只更新用量。另外 `elapsed_s` 从 `/api/task` 建单的时间算起，不是从 begin 算起。
4. **证据和文档小错**：
   - `redgreen.txt` 的标题写的是"T3 红绿验证"（复用了 T3 脚本的标题）。
   - 交付说明第 2 节 `tokens.py` 那一行仍写"其余按 UTF-8 字节 / 4"，与第 8 节和代码不一致。
5. **近似计数的例外（臆测，手上没有 tokenizer）**：扩展区生僻字（UTF-8 4 字节）每字只按 1 算，字节级 BPE 下可能是 2–4 个 token，会少算。其他实测样本：中文按每字 1.00 计，数字按每位 1.00 计，都不会少算。

### NOTE（不挡合并）
- `/core/tool|context|progress|end` 只凭 `task_id` 定位，服务端不核对会话或 cwd。exp1 H 中，拿另一个案件的 task_id 调工具会成功。这是契约设计使然（请求里只有 task_id）；task_id 由插件注入，AI 的工具参数里没有。
- `find_by_root` 的实测结果：
  - 能匹配：大小写不同、`\\?\` 前缀、尾部斜杠、正斜杠、junction、尾点、尾空格、`\\.\` 前缀、`子目录\..`；
  - 返回 CASE_NOT_FOUND：子目录、不存在的路径、相对路径 `.`；
  - 本卷没有启用 8.3 短名，这一项没测到。
- `TaskStore.rel` 用 `\d`，会接受阿拉伯-印度数字。HTTP 层的契约用 `[0-9]`，已经挡住（exp3 N）。
- 草稿标题可以含 U+202E 等双向控制字符，文件名在资源管理器里的显示会被倒置；后缀固定是 `.md`，风险低。
- 修改清单文件名把 "/" 换成 "_"，材料名"证据/借条"和"证据_借条"在同一任务里会撞名、互相覆盖。
- `save_edit_list` 不核对原件的 sha256 是否仍等于 index 里的值（与取法 7 有关）。
- 性能：每次 save_draft 和 end 都重读全部材料文本来算覆盖；`case_search` 是线性扫描（T9 会替换）。
- 日志里 `/core/tool` 不记工具名，排障会难一些；合规没有问题。

---

## 影响地图

| 类别 | 结论 |
|---|---|
| 调用方与消费方 | 受影响：插件（/core）、界面（/api/task、/api/tasks、case/open）、T10（citation_check 占位）、T9（search 接口）、redline（修改清单）。旅程实测走通 |
| 公开接口 | 受影响：新增 5 个 /core 和 2 个 /api，全部按契约校验，实测 0 个契约错误 |
| 持久化 | 受影响：task/reads/result.json、草稿、待确认.json、修改清单。竞态见 P1-3、P2-2、P2-3；终态问题见 P2-4 |
| 授权与隔离 | 已凭证据排除越权：标题、材料名、index 篡改（rel_path 和 text_path 各种写法）都被闸门挡住或只落在 草稿/、修改清单/ 下。跨案件靠 task_id，见 NOTE |
| 并发与重试 | 受影响：P1-3、P2-2、P2-3、P2-6。save_draft 没有幂等性，插件超时重试会生成 v+1 |
| 配置与密钥 | 已排除：没有密钥；tokenizer.json 已加入忽略 |
| 依赖 | 已排除：没有新增依赖，`tokenizers` 未安装时自动降级 |
| 性能 | 受影响（轻）：覆盖计算和检索都是线性的；P2-5 的锁等待 |
| 平台变体 | 受影响：NTFS 大小写不敏感导致 P2-2。8.3 短名未知（本卷没有） |
| 可观测性与失败语义 | 日志合规；失败语义问题见 P3-2、P2-4 |

## 活性地图

| 锁或等待点 | 持有者 | 等待者 | 是否有界 |
|---|---|---|---|
| `TaskStore._lock`（全局，跨案件） | `begin`（扫该案全部任务目录 + 写 3 个文件；内部再拿 `SettingsStore._lock`）、`add_read` | 其他 begin 和 add_read | 有界（本地 IO）；加锁顺序只有 Task→Settings 一个方向，不会死锁 |
| `CaseRegistry._lock` | root_of、find_by_root、recent、open | 同左 | 有界 |
| `Materials._lock(case_id)` | scan/import（整个转换过程）、index/list | T8 的全部工具、context、end（覆盖计算） | 等待时长 = 扫描时长，没有超时（P2-5） |
| 不加锁的共享文件 | result.json、草稿版本、待确认.json、task.json 状态 | — | 竞态，见 P1-3、P2-2、P2-3、P2-4 |
| `run_in_threadpool` | anyio 默认 40 个令牌 | 所有接口 | 长时间持锁时可能被占满 |

## 八项清单

1. **契约一致**：基本通过。请求、返回、落盘都按契约校验，没有私自增减字段，错误码都在枚举里。两处例外：pending 任务上的 500 INTERNAL（语义不对）；Excel `start` 的实现与契约 description 不一致（取法 1）。
2. **边界输入**：22 种标题全部安全，设备名、`\t`、`LPT9.a` 被闸门拒。长单元截断是 P1-1。
3. **错误路径**：P2-4、P3-2。index 被篡改时一律失败关闭（OUT_OF_CASE，或 schema 不合格时 INTERNAL）。
4. **日志不含正文**：通过。真服务的 service.log 共 24 行，搜材料名、正文、会话名均无命中。
5. **路径闸门**：通过。
   - 逐个 `resolve_internal` 调用点核对了传入值：task_id 经正则；输入路径来自界面并在建单时校验；wiki 路径是固定拼的；material_id 受 schema `^M[0-9]{4}$` 约束；材料文本路径 = TEXT_DIR + 经 `check_ai_rel` 的 rel_path。
   - `text_path` 确实不被采信：exp1 D 把 text_path 改成 `工作区/case.db` 后照常读原文本。
   - AI 能控制的标题走 `write_bytes`，不经 `resolve_internal`。
6. **无外连**：通过。diff 里没有网络调用，只有测试里用 subprocess 跑 `git check-ignore`。
7. **测试覆盖**：部分通过。78 个 T8 用例。缺口：截断、并发、执行中重开案件、占位页、end 幂等。变异 M6、M7、M8 改坏后没有测试变红。
8. **无机密入库**：通过。

## 对交付说明第 5 节 7 条取法的看法

1. **Excel 的 start/end：与原文冲突，需要主编排定。**
   - formats.md 第 2 节原文："Excel 为工作表内的行号，跨工作表时从下一个工作表的第 1 行重新计数，`text` 中保留 `【表:…】` 标记。"
   - 工具契约 `case_read_material` 参数 `start` 的 description 也写"Excel 为工作表内的行号"。按 Spec 4.4，这段 description 会原样发给模型。
   - **照原文做的后果**：
     - 只凭一个整数分不清是哪张表的第几行；
     - 翻到下一张表时 next_start 会回到 1，出现循环，或者根本到不了第二张表；
     - reads.json 的 from/to 不带表名，覆盖清单没法算；
     - 要做成必须加表名参数或字段，也就是改契约。
   - **作者做法（全材料连续编号）的后果**：
     - 翻页和覆盖都自洽；
     - 但与模型看到的 description 相矛盾。模型按出处（如 `流水!D120`）跳读时传 start=120，会落到别的行。exp3 M 中，想读"汇总"表第 1 行传 start=1，实际拿到"明细"表第 1 行；
     - 本卡里的 Excel 用例在本机因环境原因没跑成（见证据缺口）。
   - 两条路都得改一边的文字（改契约 description，或改 formats.md），不能各说各的。
2. **待识别的材料能不能读：合理，但与原文字面略有张力，请主编排确认。**
   - Spec 20.1 原文是"材料未解析完、待识别或失败"。按内容判断"整份都是占位才拒"比按 status 判断更有用。
   - 这样一来占位页可以被"读到"，由此引出 P2-1。
3. **case_search 是临时实现：合理**，T9 替换，接口不变。
4. **出处核对留空：合理**，是工单原文。风险：T10 接入前，`/api/tasks` 的 `citation_passed` 会显示 true，界面可能误导律师，建议主编排知悉。
5. **L1 只放任务单选的输入：属于 Spec 与契约之间的冲突，需要主编排定。**
   - Spec 9.2 写的是"前序成果和 wiki 分节"，而 task.json 契约里没有 wiki 分节字段。
   - 作者的取法是唯一不违反契约的做法。
6. **L0 标"wiki 生成后新增或修改"：合理。**
7. **修改清单段号从原件重数：合理。** 建议顺带核对原件 sha256 是否仍等于 index 里的值（见 NOTE）。

## 实际跑过的命令和实验

（全部用 `D:\lawbench-B\service\.venv\Scripts\python.exe`，PYTHONPATH 指向克隆或副本，PYTHONDONTWRITEBYTECODE=1，TEMP/TMP/LB_APPDATA 都指到 rv-B8-lab，pytest 加了 `-p no:cacheprovider --basetemp <lab>`。导入路径已确认是克隆的 `rv-B8\service\lawbench\__init__.py`。）

- **全量测试**：443 passed、12 failed、8 errors、3 skipped（跳过的是符号链接用例）。总数 466，与作者报的 463+3 相符。
  - 20 个失败和错误全部是 `appdata_too_long`：实验目录路径超过 LibreOffice 配置目录 100 字符的上限，是环境原因。
  - 其中 T8 自己的是 `test_read_line_and_cell`、`test_search_normalization_and_cells`（都依赖 xlsx 转换）。
  - T8 三个测试文件：76 passed、2 failed（同一原因）。
- **exp1**：标题批量测试；大小写撞名；index 篡改 9 种写法 + 材料名篡改；cwd 14 种写法；状态机；执行中重开案件；跨案件 task_id。
- **exp2**：长单元截断与覆盖；并发 save_draft；progress/save_draft 丢更新；suggest_wiki 并发；L1 预算；近似 token。
- **exp3**：草稿目录已存在时并发同标题；Excel 编号；Unicode 数字。exp4：占位页覆盖。exp5：锁等待。
- **相邻旅程**：`python -m lawbench --port 18821 --forward-port 18822`，只绑 127.0.0.1，令牌随机生成、只放在环境变量里。依次走通：打开虚构案件 → 导入 4 份 fixtures 材料 → /api/task（选用上一任务的草稿作输入）→ begin（cwd 用全小写，也取到了待执行任务单）→ context → list、read、search、save_draft → progress → end → /api/tasks。每一步落盘的 task/reads/result/index.json 契约错误都是 0。服务已停止。
- **变异（在 git archive 导出的副本 `rv-B8-lab\m` 上做）**：
  - M1–M4（作者红绿脚本的第 1、4、8、6 类）：改坏即红、复原即绿、逐字节复原，与作者 redgreen.txt 的数字一致（"1 failed, 44/25 deselected"）；
  - M5（去掉 add_read）：3 个用例变红；
  - M6（去掉单元号裁剪）、M7（add_read 去锁）、M8（去掉截断分支）：改坏后没有测试变红，就是上面说的测试缺口。

## 残留审计
- 没有我起的进程残留。python/uvicorn 进程为 0；只剩两个 2026-09-29 21:51、22:01 启动的 soffice.bin，不是我的，没动。端口 18820–18829 没有监听。
- 克隆 HEAD 仍为 6ef6dbd，`git status` 干净，没有 `__pycache__`。
- `D:\lawbench-B\...\.venv` 近两小时没有新的 .pyc。`%APPDATA%\lawbench` 不存在。
- 实验目录：先摘掉 24 个 junction（大多是测试生成的），再删掉数据目录，只留脚本和输出：`C:\Users\19705\AppData\Local\Temp\claude\D--lawbench\780b8a59-1849-4c63-905e-c6705fafa3f6\scratchpad\rv-B8-lab\`（exp1–5.py、journey.py、mut.py、cleanup.py，以及 exp*.txt、full3.txt）。
- 没有向 `D:\lawbench*` 或 `D:\lawbench-coord` 写任何东西。

## 证据缺口
- xlsx 相关用例（含 T8 的 2 个）因实验目录路径太长没能跑通。Excel 分支我只用手造的材料文本验证了 `split_units`，没验证真实 xlsx 的解析输出。
- 本卷没有 8.3 短名，cwd 和 rel_path 的短名写法没测到。
- 没有 tokenizer.json 和 `tokenizers` 库，近似计数"偏大"只做了推算，没有和真实计数比对。
- 没有 T7 插件，P1-3 在真实时序下出现的频率没有实测，是用确定的交错顺序复现的。
- 作者红绿脚本的 14 类只抽查了 4 类。

AMEND

---

## 第二部分 主编排裁决（2026-09-30 02:01 (+08:00)）

**T8 不合并，返修。** 成立的部分：越权参数全部被挡住（22 种标题、9 种索引篡改、14 种 cwd 写法）；`resolve_internal` 的每个调用点传入值都不受 AI 影响；`text_path` 确实不被采信；请求、返回、落盘文件契约错误 0 个；日志不含正文；相邻旅程对真服务走通。没过的是"读取记录是否如实"和并发、状态机。

### 返修清单（冻结）

| 编号 | 裁决 |
|---|---|
| P1-1 | 必修。单元被截断时不得记成已读：该单元不进 `reads.json` 的已读范围，材料归入"没读全"。补测试（`max_chars` 取最小值 500、取默认值各一例）。单元余下部分怎么读要加参数，是改契约，已上候 owner 清单 N31，本轮不做 |
| P1-2 | 必修。`mark_abnormal` 只处理上次硬退出留下的任务，跳过本进程 `begin` 过的。补测试：执行中重开同一案件后工具调用和 `case_save_draft` 照常成功 |
| P1-3 | 必修。`result.json` 的读-改-写加锁（`progress`、`case_save_draft`、`end` 三处）。补一个用确定交错顺序的测试 |
| P2-1 | 必修。"本页需识别"的占位单元不算已读；含占位页的材料归入契约现有的、最贴近的那一类，不加字段，归哪类写进交付说明 |
| P2-2 | 必修。取版本号和写文件放在同一把锁里；匹配已有版本时不分大小写 |
| P2-3 | 必修。`待确认.json` 的读-改-写加锁 |
| P2-4 | 必修。`end` 遇到已结束的任务直接返回已写的状态，不改写；`progress` 在任务不是执行中时不写文件、不改用量 |
| P2-5 | 必修。`Materials.index()` 不拿案件锁直接读（`index.json` 是原子替换写入的） |
| P2-6 | 必修，允许改 `gate.py` 这一处：`_mkdirs` 里接住 `FileExistsError` 后继续原有的复查。和 T8 的返修一起交、一起复核 |
| P3-1 | 必修。目录那几行计入 40% 的预算 |
| P3-2 | 必修。对还没 `begin` 的任务调 `progress`、`end` 返回 `TASK_NOT_FOUND` |
| P3-3 | `elapsed_s` 从 `begin` 算起。"已读材料"：契约的 `core_progress` 里有这个字段就做，没有就不做，在交付说明里写明 |
| P3-4 | 必修。`redgreen.txt` 的标题、交付说明第 2 节 `tokens.py` 那一行改对 |
| 测试缺口 | 复核员的变异 M6（去掉单元号裁剪）、M7（`add_read` 去锁）、M8（去掉截断分支）改坏后没有测试变红：各补一个会变红的测试 |

### 不要求（记为独立后续或已知限制）

- 扩展区生僻字的近似计数可能少算：等 tokenizer 到位后用样本核。
- `/core/*` 只凭 `task_id` 定位、服务端不核对会话：契约设计如此，`task_id` 由插件注入，AI 的工具参数里没有。
- 草稿标题可含双向控制字符；`save_edit_list` 不核对原件 sha256；日志里 `/core/tool` 不记工具名：不要求。
- 修改清单文件名把 `/` 换成 `_` 会撞名：转 T16，与候 owner 清单 N25（材料重名）一并处理。
- `citation_passed` 在 T10 接入前恒为 true：转 T10、T13，界面在 T10 接入前不显示"出处核对通过"。
- 每次保存都重读全部材料算覆盖、检索线性扫描：T9 替换检索；覆盖计算的性能留到 T18 实测。

### 对 7 条取法的裁决

| 条 | 裁决 |
|---|---|
| 1. Excel 的 `start` / `end` 按整份材料连续编号 | **先按线 B 的做法，候用户定（N32）。** 契约原文"工作表内的行号"做不成：只凭一个整数分不清哪张表，翻页会在表与表之间打转，覆盖清单也没法算。线 B 的做法是唯一能自洽的。但契约里给模型看的参数说明还写着"工作表内的行号"，模型照着出处跳读会落到别的行。改参数说明是改契约 |
| 2. 整份都是占位才拒，部分有文字的照常读 | 同意。配合 P2-1 |
| 3. `case_search` 临时实现 | 同意，T9 替换 |
| 4. 出处核对留空 | 同意（工单原文） |
| 5. L1 只放任务单选用的输入 | 同意。契约的任务单里没有"wiki 分节"字段，AI 用 `case_read_wiki` 自取。Spec 9.2 的措辞由主编排在 T8 合并时回写 |
| 6. L0 标"wiki 生成后新增或修改" | 同意 |
| 7. 修改清单段号从原件重数 | 同意 |

### 下一轮复核

换新的复核员，审完整累计范围，逐条核对本清单。实验用的应用数据目录放短路径（这一轮复核员的实验目录太深，20 个依赖 LibreOffice 的用例因"数据目录路径太长"没跑成，其中 2 个是 T8 的 Excel 用例）。
