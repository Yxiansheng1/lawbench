# T8 返修复核记录（第二轮）

- 复核员：一名 Opus 5.5 只读复核员（新人，未参与第一轮）
- target：`695191feddcf461309f38f285617952ea4a45ffd`（line-B，已 rebase 到 `main` `be6aef7`）
- 范围：第一轮返修令 `致B-ORCH-执行令-T8返修-20260930-0201` 冻结的 14 条 + 契约 1.2 服务侧（`致B-ORCH-执行令-T8任务单契约1.2-20260930-1054`、`契约1.2其余各项-1134` 中归 T8 的部分）
- 复核克隆：scratchpad `rv-B9`（`--no-hardlinks --no-checkout`，detach 到 target）；实验在 `git archive` 副本上做；未碰 `D:\lawbench-B`
- 归档：主编排于 2026-09-30 13:00 (+08:00) 从复核员交回原文抄录，未改内容

## 第一部分 复核员原文

# T8 返修复核报告（line-B @ 695191f，第二名复核员，只读）

结论先说：冻结清单 14 条和契约 1.2 的服务侧改动，逐条看都做到了。任务单 1.2 的语义在真服务上全部走通，我做的 23 个变异里 22 个能让测试变红。

但 P1-2 的修法留了一个时间窗口：`begin` 正在写文件的那一小段时间里如果有人重开同一案件，刚开始的任务照样会被标成"异常中断"，`case_save_draft` 也会被拒。这个问题我用固定的交错顺序稳定复现了。它和上一轮 P1-2 是同一类问题，修起来只要几行，所以给 AMEND。

先亲验：克隆 `git rev-parse HEAD` = `695191feddcf461309f38f285617952ea4a45ffd`，`git status --short` 为空，复核前后一致，没有 `__pycache__`。导入路径打印为副本的 `...\rvB9t\f\service\lawbench\__init__.py`（`git archive` 导出的副本）。

## Findings

### F1（P2，范围内阻断：P1-2 没修全）begin 和重开案件之间有竞态，本进程刚 begin 的任务被打成 abnormal
- **问题**：`begin` 在 `self._lock` 里先写 `task.json`（state=running），再写 `result.json`、`reads.json`，最后才把任务记进 `self._begun`（`case/task.py` 第 245–253 行）。`mark_abnormal` 不拿任何锁（第 275–297 行）。它只要在这段时间里读到这个任务，看到的就是"running 且不在 `_begun` 里"，于是标成 abnormal。
- **违反的不变量**：Spec 9.2 只标"上次硬退出"留下的任务；冻结清单 P1-2 要求"跳过本进程 begin 过的"。
- **影响**：和上一轮 P1-2 一样。当前任务的所有工具调用都返回 `TASK_NOT_FOUND`，包括 `case_save_draft`。窗口只有两次带 fsync 的写文件那么长（毫秒级）。触发场景是律师点"打开案件"（或界面切回该案件）的同时发出一条消息。
- **证据**：exp1 B。在 `TaskStore._write` 写完 running 的 `task.json` 后让 begin 线程停住，这时调 `mark_abnormal`，结果是"标了 1 个；新 begin 的任务 state = abnormal"；随后 `save_draft` 返回 `TASK_NOT_FOUND`。
- **最小修复**：`begin` 在第一次 `_write` 之前（锁内）就写 `self._begun[tid]`；`mark_abnormal` 整体包在 `self._lock` 里（或者读完 task.json 后在锁内再查一次 `_begun`）。补一个用确定交错顺序的测试。

### F2（P3，测试缺口 + 独立后续）`end` 的任务锁没有测试守着；`end` 之后迟到的 `case_save_draft` 仍会改已结束的任务
- **测试缺口**：变异 X4b（只去掉 `end` 外面的 `task_lock`）后 105 个 T8 用例全绿。
- **迟到的 save_draft**：`/core/tool` 在锁外检查 `state=="running"`（`api/core.py` 第 26 行），`save_draft` 拿到任务锁之后不再检查一次。
  - exp1 D：工具请求已经过了检查，`end`（aborted）这时插进来。之后 `save_draft` 照样给已取消的任务追加了草稿，`result.drafts` 从 `[]` 变成 1 条，status 还是 cancelled。
  - 草稿目录里同时有 `未完成-….md` 和 `迟到-v1.md`，与 F-RUN-04"存过正式草稿就不改名成未完成"对不上。
- **影响**：时序上少见（插件在 turn/end 前工具已经跑完），但终态保护（P2-4）没盖到 save_draft。
- **最小修复**：`save_draft` 在任务锁里重新 `locate` 一次，不是 running 就报 `TASK_NOT_FOUND`。补一个用确定交错顺序、针对 `end` 锁的测试。

### F3（P3，P2-5 带来的轻度回归）`index()` 不拿锁以后，读和原子替换会在 Windows 上撞 PermissionError
- **证据**：exp1 E，1 个线程连续 `atomic_write_bytes(index.json)`，3 个线程连续 `index()`，跑 8 秒：
  - 读侧 3333 次成功、1 次 PermissionError（在工具里就是 500 INTERNAL）；
  - 写侧 7 次把 10 次重试全部用完后失败（扫描会因此失败）。
- **说明**：这是极端压力。实际上工具调用间隔以秒计，概率很低。
- **最小修复**：`contracts.read_json` 遇到 PermissionError 时做有上限的重试（和写侧 `_replace_with_retry` 对称）。可以作为独立后续。

### F4（P3，独立后续）Excel 单元表头很长时，分段读的返回会超过 `max_chars`
- **原因**：`_read_part` 里 `room = max(1, limit - overhead - len(TRUNC_TAIL))`；表头两行（overhead）本身就超过 `max_chars` 时，至少仍返回表头 + 1 字。
- **证据**：构造一个表头约 1000 字的 cell 单元，`max_chars=500` 时返回 1046 字。
- **说明**：真实表头要超过 500 字才会出现（宽表 + `max_chars` 取最小值时）。
- **最小修复**：overhead ≥ limit 时把表头截短，或只在第一段带表头。

### F5（P3，臆测：产品路径碰不到）旧选择拒删时，同一秒内的新选择可能取不到
- **问题**：旧的待执行单目录里有别的文件时，按令拒删。这时如果新单和旧单 `created_at` 同一秒，`_pending_for` 用严格 `>` 比较，结果由遍历顺序决定。
- **证据**：exp1 C 跑 6 次，5 次取到旧的 A。不同秒时取新的，但该会话会同时留有 2 张待执行单。
- **说明**：1.2 下待执行单从不执行，产品自己不会往里写文件，只有人为放文件才会出现。
- **修复**：平局时按写入顺序决胜（例如锁内记下该会话最新的 task_id）。

### NOTE（不挡合并）
1. `current()` 在全局 `TaskStore._lock` 里遍历所有最近案件的全部任务目录，界面"每次显示之前"都会调。案件和任务多了以后，会拖慢所有案件的 `begin` 和 `add_read`。建议 T18 实测。
2. 选择"管到改掉为止"之后，任务单里记的输入 sha256 是设置那一刻的。输入文件之后一变，之后每条消息的 `/core/context` 都报 `INPUT_CHANGED`，直到重新设置。这是 1.2 语义的自然结果，界面（T13）需要知道。
3. 自由对话的选择，`/api/task/current` 返回的是带 null 的对象而不是 `selection: null`。契约两种都允许，作者已在交付说明第 11 节写明，请主编排知悉。
4. `llm/tokens.py` 模块头的 docstring 还写"其余按 UTF-8 字节数 / 4"，与 `count()` 的实际算法不一致（P3-4 只改了交付说明）。
5. `redgreen_t8_rework.py`（20/20）的第 1、12、13、20 类针对的是 1.2 之前的代码，按现在的源码已经对不上。作者在第 11 节说明过，由 `T3\redgreen_contract12.py` 第 9–15 类接替；作者没有重跑过旧脚本。
6. `_void_pending` 用 `task.json` 里的 `task_id`（不是目录名）去定位要删的目录。这个值是服务自己写的，AI 影响不到；另有"目录里只能有 task.json"一层兜底。

## 冻结清单核对

| 编号 | 结论 | 依据 |
|---|---|---|
| P1-1（按 1.2） | 关闭 | 读 3360 字的长行，`max_chars=500` 共 8 步，`next_offset` 依次为 471、942……3297、null；每段 ≤500 字，拼起来 3360 字一字不少；`reads.json` 只在第 8 步记 (2,2)。只读一部分就 end，归 `partially_read`；读两遍只记一次。变异 X1、X2、X10、X18 都变红 |
| P1-2 | **部分关闭（见 F1）** | 重开后工具、save_draft、end 都正常（真服务）；上次硬退出留下的照样标 abnormal；X3 变红。竞态窗口未关 |
| P1-3 | 关闭（测试缺口见 F2） | X4、X4a、X4c 变红；X4b 不变红 |
| P2-1 | 关闭 | X14 变红；归 `partially_read`，交付说明写明了 |
| P2-2 | 关闭 | 测试覆盖大小写和 4 个并发；作者的变异第 5、6 类 |
| P2-3 | 关闭 | X16 变红 |
| P2-4 | 关闭（save_draft 见 F2） | 真服务：end 再调返回原状态，迟到的 progress 不写 `进行中.md`；X5、X15 变红 |
| P2-5 | 关闭（副作用见 F3） | X9 变红 |
| P2-6 | 关闭 | `gate.py` 只改了这一处（diff 核对）；X17 变红 |
| P2-7（按 1.2） | 关闭 | 见下面的语义实验表；X6、X6b、X7、X7b、X8、X11 变红 |
| P3-1 | 关闭 | 代码核对 + 测试 |
| P3-2 | 关闭 | 测试 + 代码 |
| P3-3 | 关闭 | `elapsed_s` 用 `_begun`；契约里没有"已读材料"字段，按令不做 |
| P3-4 | 关闭 | `redgreen.txt` 标题已改，交付说明第 2 节已改（源码 docstring 仍旧，见 NOTE 4） |
| 测试缺口 M6、M7、M8 | 关闭 | 分别由 `test_gap_coverage_clips_unit_numbers`、`test_gap_add_read_is_locked`、`test_p1_1_long_unit_read_in_parts` 守着（X18 变红） |
| 1.2 其余各项 | 关闭 | `tasks_list` 的 `coverage`、`citation_check` 与 `result.json` 逐字相等；没保存过时都是 null。`/api/outputs` 空时 `{v:1,outputs:[]}`，有内容时原样返回并通过契约；索引坏了返回 500 INTERNAL（失败关闭）；未知案件 `CASE_NOT_FOUND`；多余参数 `INVALID_ARGUMENT`；只读 `成果/索引.json` 这一处（`OUTPUTS_REL` 常量）。`/health` 返回 `contract_version` 1.2 |

## 任务单语义实验表（真服务 127.0.0.1:18841，exp2）

| 步骤 | 结果 |
|---|---|
| 从没设置过时 current | `null` |
| 设 A → current | 返回 A 的对象（通过契约） |
| begin → begin | 两次都是 contract-review，两个新编号；A 仍是 pending；执行中的两份 `task.json` 契约错误都是 0 |
| `/api/tasks` | 不含 A，含两次执行 |
| 设 B | A 的目录已删；current 是 case-summary；begin 按 B |
| 设自由对话 | current 为 entry、skill 都是 null 的对象；B 的目录已删；begin 的 skill 为 None，params 用的是自由对话设的（thinking=低） |
| 被顶掉的 A、B | 不在 `/api/tasks`，不留 `result.json` |
| 同一秒内顺序连设 4 张 | 只剩最后一张，current 就是它 |
| 并发连设 6 张 | 只剩 1 张，current 就是它 |
| 旧单目录里人为放草稿 | 拒删（旧单留着，日志记 `NOT_EMPTY:<编号>`）；current 和 begin 取新的；再设第三张时第二张被删，拒删的那张一直留着；它不在 `/api/tasks`。同一秒的情况见 F5 |
| 两个会话 | 互不影响 |
| 同一会话 ID 设到另一个案件 | 各案件各留一张，current 取最新的（现实里一个会话只属于一个案件） |

## 变异结果（复核员自己做，在副本上改坏 → 跑 T8 三个测试文件 → 复原，最后逐字节复原：True）

- 基线：105 passed。
- 变红（22 个）：
  - 分段读：X1 去掉 `next_offset`、X2 截断仍记已读、X10 分段读不要求连续、X18 超长单元不截断；
  - 状态与锁：X3 `mark_abnormal` 不跳过本进程、X4 三处都去锁、X4a 只去 progress 的锁、X4c 只去 save_draft 的锁、X5 `end` 不保护终态、X15 progress 在非执行中照写；
  - 任务单：X6 顶掉时不删、X6b 只删目录不删 `task.json`、X7 begin 消耗掉待执行单、X7b begin 不看选择、X8 `/api/tasks` 列出待执行的、X11 current 恒为 null；
  - 其他：X9 `index()` 又拿锁、X12 `coverage` 恒为 null、X13 outputs 恒为空、X14 占位页算已读、X16 待确认去锁、X17 `_mkdirs` 不接 `FileExistsError`。
- **不变红（1 个）**：X4b 只去掉 `end` 的锁（F2）。
- 作者红绿的抽查：我抽的 5 类（返修第 2、3、7、10 类，契约 1.2 第 11 类）改法与我的 X3、X4a、X16、X9、X7 等价，都是改坏即红。

## 八项清单

1. **契约一致**：通过。exp2 每个请求的返回都按契约校验，执行中的 `task.json` 契约错误为 0；current 的写法见 NOTE 3。
2. **边界输入**：通过。
   - offset 等于或超过单元长度、为负数：都返回 INVALID_ARGUMENT；
   - 跨单元：短单元带 offset 读尾部，`next_start` 指向下一个单元；
   - start 超出范围：INVALID_ARGUMENT。
   - F4 是 cell 单元的特例。
3. **错误路径**：未 begin 的任务调 progress、end 返回 TASK_NOT_FOUND；终态受保护；outputs 索引坏了失败关闭。问题见 F1、F2。
4. **日志不含正文**：通过。真服务 `service.log` 共 157 行，搜"虚构""长长长""借条""情况说明""第一行"、会话名、skill 名、案件文件夹名，都没有命中。
5. **路径闸门**：通过。
   - 12 种标题：`..`、`../x`、`CON`、`nul.txt`、`a:b`、`x::$DATA`、`COM1`、`LPT9.a`、`\\?\C:\x`、`C:x` 等，全部被拒或落在本任务的 `草稿/` 下；
   - `index.json` 篡改 5 种：`rel_path` 越界的返回 OUT_OF_CASE；`text_path` 改成 `工作区/case.db` 时不被采信，照读原文本；不合 schema 的返回 INTERNAL；
   - cwd 8 种写法：小写、`\\?\`、尾部斜杠、正斜杠、`子目录\..` 能匹配到案件；子目录和 `.` 返回 CASE_NOT_FOUND。
   - `resolve_internal` 的全部调用点（task.py 11 处、context、texts、drafts、inputs）逐个看过，传入值要么是固定串，要么是过了正则的 task_id，要么是界面给出并在建单时校验过的输入路径，要么是先过 `check_ai_rel` 的 `rel_path`，都不受 AI 影响。
6. **无外连**：通过。diff 里没有新增网络调用；真服务只起在 127.0.0.1:18841/18842，没有调用任何会探测 6000D 的接口。
7. **测试覆盖**：基本通过，缺口是 F2 的 `end` 锁和 F1 的竞态。
8. **无机密入库**：通过。

## 全量测试
- 在 `git archive` 副本上跑，短路径：**661 passed、1 failed、3 skipped**（668.9 秒）。
- 唯一的失败是 `test_tokens.py::test_tokenizer_json_ignored_by_git`：副本不是 git 仓库，`git check-ignore` 用不了。在真克隆里重跑 `test_tokens.py`：7 passed。
- 所以合计 662 passed、3 skipped，与作者报的数字一致。LibreOffice、xlsx 相关用例这次都跑通了（数据目录放在短路径上）。

## 实际跑过的命令
- 解释器：`D:\lawbench-B\service\.venv\Scripts\python.exe`。
- 环境：`PYTHONPATH` 指向副本的 `service`，`PYTHONDONTWRITEBYTECODE=1`；TEMP、TMP、LOCALAPPDATA、APPDATA、LB_APPDATA 都指到 `C:\Users\<用户>\AppData\Local\Temp\claude\rvB9t\` 下。
- `git -C rv-B9 rev-parse HEAD`、`status --short`、`log`、`diff`、`show`；`git archive` 导出两份副本（f 跑全量和实验，m 做变异）。
- `pytest -q -p no:cacheprovider --basetemp <短路径> tests`（全量），另在克隆里单跑 `tests/test_tokens.py`。
- `exp1.py`（进程内）：offset、边界、F1、F2、F4、F5、F3 的实验。
- `exp2.py`：真服务 `python -m lawbench --port 18841 --forward-port 18842`，令牌随机生成、只放在子进程的环境变量里；跑完已经结束进程。
- `mut.py`：23 个变异，每个都跑 T8 三个测试文件并加 `-x`。

## 残留审计
- 我起的服务进程已结束，18841–18849 没有监听。
- 现在机器上 python 进程的命令行是 `mut.py 1 2 3 5 7 9 10`、`--basetemp ...\rvB9a\bm`、`e_conc2.py`，属于另两名复核员，我没动。两个 `soffice.bin`（10028、42468）也没动。
- 短路径数据目录 `rvB9t` 已用 python 的 `shutil.rmtree`（加 `\\?\` 前缀）删除，确认不存在。
- `%APPDATA%\lawbench` 不存在。克隆 HEAD 仍为 695191f，status 干净，没有 `__pycache__`。
- 实验目录只留脚本和输出：`C:\Users\<用户>\AppData\Local\Temp\claude\D--lawbench\780b8a59-1849-4c63-905e-c6705fafa3f6\scratchpad\rv-B9-T8-lab\`（`exp1.py`、`exp2.py`、`mut.py`、`cleanup.py`、`env.ps1` 和对应的 `.txt` 输出）。
- 没有向 `D:\lawbench*` 或 `D:\lawbench-coord` 写任何东西。

## 证据缺口
- 没有 T7 插件和真实 DSH 时序，F1、F2 都是用人为的交错顺序复现的，真实出现的频率没有测。
- F3 是压力测试的数字，没有在真实扫描加工具调用的场景下测。
- F4 的超长表头是手工构造的单元，没有用真实的宽 xlsx 验证。
- 作者红绿只抽了 5 类（用等价的变异）；旧的 20/20 脚本没有重跑，它已经对不上现在的代码（NOTE 5）。
- 本卷没有 8.3 短名，cwd 的短名写法没测到。

AMEND

---

## 第二部分 主编排裁决（2026-09-30 13:02 (+08:00)）

**结论：AMEND，返修一轮，清单冻结。** 第一轮 14 条里 13 条关闭，P1-2 关了大半、留了一个毫秒级的竞态窗口；契约 1.2 服务侧（任务单顶替、执行不消耗、`task/current`、`tasks_list` 新字段、`/api/outputs`）在真服务上全部走通；23 个变异 22 个变红；八项清单只在"错误路径"和"测试覆盖"上有缺口。主编排采信。

### 返修清单（冻结，线 B 单独一个提交；与 T5 的返修可以同一批交回）

| 编号 | 裁决 |
|---|---|
| F1（P2） | 必修。`begin` 在第一次 `_write` 之前（锁内）就记 `self._begun[tid]`；`mark_abnormal` 整体放进 `self._lock`（或读完 `task.json` 后在锁内再查一次 `_begun`）。补一个用确定交错顺序的测试（在写完 running 的 `task.json` 后停住 begin 线程、调 `mark_abnormal`，断言新任务不被标 abnormal） |
| F2（P3） | 一并做。`save_draft` 在任务锁里重新 `locate` 一次，不是 running 就报 `TASK_NOT_FOUND`；补一个针对 `end` 锁的确定交错顺序测试（复核员变异 X4b 只去掉 `end` 的锁时 105 个用例全绿，这条缺口要堵上） |
| F3（P3） | 一并做。`contracts.read_json` 遇 `PermissionError` 做有上限的重试，与写侧 `_replace_with_retry` 对称 |
| F4（P3） | 一并做。`_read_part` 里表头开销 ≥ `max_chars` 时把表头截短，保证返回不超过 `max_chars` |
| F5（P3） | 一并做。`_pending_for` 同一秒平局时按写入顺序决胜（锁内记下该会话最新写入的 task_id） |
| NOTE 4 | 一并做。`llm/tokens.py` 模块头 docstring 改成与 `count()` 一致 |
| NOTE 5 | 不重跑旧脚本。交付说明写明 `redgreen_t8_rework.py` 第 1、12、13、20 类已由 `T3\redgreen_contract12.py` 第 9–15 类接替即可（作者已写） |
| NOTE 1 | 不在本卡做。`task.current()` 每次全扫已登记案件的任务目录，记为 **T18 独立后续**（T13 复核员也提到同一点） |
| NOTE 2 | 不改服务。"管到改掉为止"之后输入文件一变即报 `INPUT_CHANGED` 直到重设，是 1.2 语义的自然结果；主编排注记给线 A（T13 界面要把这个错误提示成"输入材料已变化，请重新选择"） |
| NOTE 3 | 知悉。自由对话的选择返回带 null 的对象而不是 `selection: null`，契约两种都允许，界面两种都处理（T13 复核员已核） |

### 止损线

F1 与第一轮 P1-2 同一根因，这是第二次修。**若下一轮复核仍在同一根因上查出问题，不再返修，上候 owner 清单。**

### 合流

line-B 三张卡（T3、T5、T8）都通过才合并。本卡 AMEND，line-B 暂不合并；返修后换新复核员核 T8 累计范围（`0201` 返修令起的全部改动 + 本轮返修）。
