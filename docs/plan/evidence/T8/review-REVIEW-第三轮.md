# T8 复核记录（第三轮：第二轮返修的累计范围）

- 复核员：一名 Opus 5.5 只读复核员（新人；前一名因用量上限中断、无结论）
- target：`4bb0e406df4db0b7496f79653a968f515758d167`（line-B）；范围 `ccda698`、`79ffb87`、`4bb0e40` + 第一轮 14 条抽跑
- 复核克隆：scratchpad `rv-B10`；实验在 `git archive` 副本；未碰 `D:\lawbench-B`
- 归档：主编排于 2026-09-30 15:52 (+08:00) 从复核员交回原文抄录，未改内容

## 第一部分 复核员原文
# T8 第二轮返修复核报告（line-B @ 4bb0e40，累计范围，只读复核员）

**结论：** F1 到 F5 和 NOTE 4 都修到位了。F1 用固定交错顺序复现上一轮的实验，这次新任务不再被标成异常中断，随后保存草稿也正常；作者的 F1 测试在两层修复同时回退时会变红。第一轮 14 条的关键实验在进程内和真服务上都重跑通过。tokenizer 只从本地文件读，拦掉全部网络后照常工作，没有任何联网尝试。全量测试除了一条"副本不是 git 仓库"导致的已知失败，其余全过。没有阻断问题，只有几条不挡合并的注记。

**亲验 target：** 克隆 `rv-B10` 的 `git rev-parse HEAD` = `4bb0e406df4db0b7496f79653a968f515758d167`，`git status --short` 为空。复核结束时再看一次，结果相同，也没有 `__pycache__`。实验用的是 `git archive` 导出的副本，打印出的 `lawbench.__file__` = `C:\Users\<用户>\AppData\Local\Temp\claude\rvB10t\f\service\lawbench\__init__.py`，确认导入的是副本。上一名复核员留下的 `rvB10t` 和 `rv-B10-T8-lab` 半成品，我先确认没有进程在用，然后删掉重建。

## Findings

没有 P0、P1、P2 问题。以下五条都不挡合并。

- **NOTE 1（P3，独立后续）`count()` 函数说明过时了。**
  - 问题：`llm/tokens.py` 里 `count()` 的说明最后一句还写着"与真实长度的偏差：没有 tokenizer，未核实"。4bb0e40 之后已经有了真分词器，偏差也测过了（交付说明第 13 节：1.03–1.90 倍）。
  - 影响：只是文字。
  - 最小修复：改成引用第 13 节的数字。

- **NOTE 2（设计选择，知悉即可）F4 在表头放不下时整段去掉，而不是截短。**
  - 做法：`tools/materials.py` 的 `_read_part` 在表头放不下时，把列名表头整个去掉，只留 `【表:…】`。
  - 影响：表头约 490 字以上、`max_chars` 又取得小时，模型在这一段看不到列名。冻结清单的原话是"截短"，但它要保证的"不超过 max_chars"已经做到了。
  - 实测（exp1）：约 1600 字宽的表头，max_chars 取 500、501、777、1000、1500、3000、8000，每一段都不超过上限，拼回来 2500 字一字不少。表头超宽、正文很短的单元，返回也不超过 500。

- **NOTE 3（P3，独立后续，不在冻结范围）极端压力下，写 index.json 时仍会用完重试次数。**
  - 实测（exp3，1 个线程写、3 个线程读，每轮 8 秒）：写侧每轮有 5–18 次把 10 次重试用完失败（raw 12–17、retry 17–18、index 5–8）。
  - 这不是本轮引入的：没有读侧重试的对照组里，写侧同样失败 12–17 次。F3 冻结的只是读侧，读侧已经修好，见冻结清单核对。
  - 影响：只有在这种极端压力下，扫描才可能失败。实际工具调用间隔以秒计，概率很低。

- **NOTE 4（知悉）F1 有两层保护，作者的测试只在两层同时回退时才变红。**
  - 两层是：begin 提前记下"本进程开始过"（`_begun`），以及 `mark_abnormal` 拿锁。任意一层单独就能守住这个竞态，所以只去掉其中一层时测试仍是绿的（变异 M1a、M1b）。作者在交付说明第 12 节写明了这一点。
  - 我在 exp1 里单独证实了锁这一层：begin 持锁时，`mark_abnormal` 被挡住 1 秒以上，begin 放锁之后才返回。
  - 两层以后如果被先后去掉，测试能抓到这个回归。

- **NOTE 5（臆测，P3）begin 写到一半失败时的边角情况。**
  - 问题：`_begun` 现在在写文件之前就记下了。如果 begin 在写完 running 的 `task.json` 之后、写 `result.json` 时抛了异常，这张半成品任务在本进程里不会再被重开标成异常中断，要等服务重启后才会被标。旧代码下，下一次重开案件就会标它。
  - 影响：只在写盘失败时出现；这张任务也不会出现在 `/api/tasks` 里（没有 `result.json`）。
  - 最小修复（可选）：begin 写文件失败时 `pop` 掉 `_begun[tid]`。

## 冻结清单逐条核对

| 编号 | 结论 | 依据 |
|---|---|---|
| F1（P2，止损线） | **关闭** | 代码：`case/task.py` 的 `begin` 在锁内、第一次 `_write` 之前就记 `self._begun[tid]`；`mark_abnormal` 整个过程拿 `self._lock`（交给 `_mark_abnormal` 做）。<br>exp1（我自己的确定交错）：begin 线程停在写完 running 的 `task.json` 之后，这时另一线程调 `mark_abnormal`，它被挡住，begin 放锁后才返回，标了 0 个；新任务仍是 running；随后 `case_save_draft` 成功。<br>上次硬退出留下的 running 任务仍被标 abnormal（标了 1 个）。经 `/api/case/open` 重开后，本进程的任务仍是 running。<br>真服务 exp2：begin 之后重开案件，save_draft 成功。<br>作者测试 `test_f1_*`：两层同时回退（M1）变红，P1-2 本体变异（M1c）变红；只去一层时的情况见 NOTE 4 |
| F2 | 关闭 | 代码：`tools/drafts.py` 在任务锁里重新 `locate`，不是 running 就报 `TASK_NOT_FOUND`。<br>exp1：复现上一轮的 exp1 D——save_draft 已经过了 `/core/tool` 的检查，停在拿任务锁之前，`end`（aborted）插进来。结果 save_draft 返回 `TASK_NOT_FOUND`，`drafts` 仍为空，status 是 cancelled，没有生成 `迟到-v1.md`。<br>变异 M2（去掉锁内再核）变红 2 条；**M2b（即上一轮的 X4b，只去掉 end 的锁）现在变红**，上一轮这条不变红的缺口已经补上 |
| F3 | 关闭 | 代码：`contracts.read_json` 遇 PermissionError 最多重试 10 次、每次等 0.03 秒，第 10 次仍失败就抛出，有上限。<br>exp3，每轮 8 秒：读侧**不重试**的对照组 2 轮出了 11 次、23 次 PermissionError；**本轮的重试**组 3 轮都是 0 次（每轮约 2.4–2.5 万次读取）；走真实 `MaterialStore.index()` 的读侧 3 轮也都是 0 次，每轮约 3300 次，这就是和 T5 材料解析、扫描原子替换的接缝。<br>变异 M3（去掉重试）变红。写侧情况见 NOTE 3 |
| F4 | 关闭 | exp1 各档 max_chars 的每一段都不超过上限（上一轮是 1046 > 500）。变异 M4 变红 |
| F5 | 关闭 | exp1：同一秒建两张、旧单里人为放文件被拒删，连续 20 次，current 和 begin 都取到后写的那张；三张同一秒（前两张都拒删）时，current 取第三张。<br>真服务：连设两张，current 取后一张。变异 M5 变红 |
| NOTE 4（上一轮） | 关闭 | `tokens.py` 模块头说明已和 `count()` 的算法一致；函数内那句过时的话见本轮 NOTE 1 |
| 4bb0e40（真计数） | 关闭 | `pyproject.toml` 加了 `tokenizers>=0.23.2,<0.24`。源码全文搜过，只有 `Tokenizer.from_file(本地路径)`，没有 `from_pretrained`，也不用 hub。<br>exp4：先把 socket 连接和 DNS 解析全部拦掉，再导入 tokenizers、读本地 `tokenizer.json` 计数，成功，网络尝试 0 次；`huggingface_hub` 和 `requests` 都没被导入。<br>`git check-ignore` 在真克隆里确认 `tokenizer.json` 被 `service\.gitignore` 第 4 行忽略。<br>没有这个文件时，`test_tokens_exact.py` 的 3 条自动跳过，不算失败。<br>把 `D:\lawbench-B` 的 `tokenizer.json` **只读复制**到第三个副本后，跑 `test_tokens_exact`、`test_tokens`、`test_core`、`test_t8_rework`、`test_t8_rework2`、`test_tools`：121 passed，1 failed。失败的是 `test_tokenizer_json_ignored_by_git`，原因是副本不是 git 仓库，同上。`test_core` 里加长了的 L1 用例在真计数下也通过 |
| 第一轮 14 条抽跑 | 没被弄坏 | exp1：<br>- 3360 字长行、`max_chars=500`，分 8 步读完，`next_offset` 依次为 471、942、1413、1884、2355、2826、3297、null；拼回来 3360 字；只在第 8 步记 (2,2)；再读一遍不重复记。<br>- 终态保护：再调 end 返回原来的 completed；迟到的 progress 不写 `进行中.md`；`/core/tool` 被拒。<br>- 新选择顶掉旧的；begin 两次都按新选择执行、不消耗它；`/api/tasks` 不列待执行、列出两次执行。<br>真服务 exp2 上同样走通 |

## 八项清单

1. **契约一致**：通过。exp1 的所有请求都按契约校验了返回体和 `task.json`、`result.json`、`reads.json`；本轮没有改契约。
2. **边界输入**：通过。max_chars 取了下限 500、501 到上限 8000 各档；超宽表头配短正文的单元也测了。
3. **错误路径**：通过。end 之后的迟到保存、重开案件与 begin 的竞态、read_json 重试用尽后照常抛出（作者的 `test_f3_read_json_gives_up`，读代码核对上限）。
4. **日志不含正文**：通过。真服务 `service.log` 共 27 行，搜"长长长""迟到""张某甲""第一行"、skill 名、草稿标题，都没有命中。
5. **路径闸门未被绕过**：通过。本轮没有新增路径入口；F2 的再核走的是已有的 `locate`，F4 只改渲染。
6. **无外连**：通过。
   - 真服务只起在 127.0.0.1:18851/18852；起服务前，设置里 4 个服务器地址都预先改成 127.0.0.1:18858/18859（没人监听）；没调测试连接。
   - tokenizer 在拦掉全部网络的情况下 0 次尝试。
7. **测试覆盖新代码**：通过。9 个变异里 7 个变红；另外 2 个是双层保护只去一层，按设计不变红（NOTE 4）。
8. **无机密入库**：通过。本轮 diff 里没有 Key 或令牌；`tokenizer.json` 被 gitignore，没有提交。

## 全量测试

- 副本不带 tokenizer，短路径 basetemp，总超时 1800 秒：**705 passed、1 failed、6 skipped**，用时 565.9 秒。
- 唯一的失败是 `test_tokens.py::test_tokenizer_json_ignored_by_git`：副本不是 git 仓库，`git check-ignore` 用不了。我已在真克隆里直接跑 `check-ignore`，确认文件被忽略。
- 合计 712 个用例，和作者"有分词器 709 passed / 3 skipped"的总数一致。
- 6 个跳过：按总数推算，应是原来的 3 个加上没有 tokenizer 时自动跳过的 `test_tokens_exact` 3 个；这次没有加 `-rs` 逐条核对跳过原因。
- 作者"无 tokenizer 706 passed / 3 skipped"是 4bb0e40 之前的数字，只有 709 条（少了 `test_tokens_exact` 的 3 条）；换算过来，706 = 我的 705 passed 加上那条 git 用例（在真克隆里是通过的）。

## 实际跑过的命令

- 解释器：`D:\lawbench-B\service\.venv\Scripts\python.exe`（Python 3.12.3，tokenizers 0.23.2）。
- 环境：`PYTHONPATH` 指向副本的 `service`，`PYTHONDONTWRITEBYTECODE=1`；TEMP、TMP、LOCALAPPDATA、APPDATA、LB_APPDATA 都指到 `C:\Users\<用户>\AppData\Local\Temp\claude\rvB10t\` 下。
- git 命令：`rev-parse`、`status`、`log`、`diff --stat`、`show`（ccda698、4bb0e40、origin/main 上的第二轮复核记录）、`archive`（用 python tarfile 解出三份副本：f 跑全量和实验，m 做变异，k 放 tokenizer）、`check-ignore -v`。
- `runpytest.py`：带 1800 秒超时的全量 pytest，输出 `full-notok.txt`；以及副本 k 上 6 个文件的真计数测试，输出 `tok-exact.txt`。
- 实验脚本（都在实验目录）：
  - `exp1.py`：进程内实验，F1、F2、F4、F5 和第一轮的关键实验，**29/29**。
  - `exp2.py`：真服务 `python -m lawbench --port 18851 --forward-port 18852`，令牌随机生成、只放在子进程的环境变量里，**5/6**。没过的那条是我脚本的错：把 `/health` 的返回体当成了 `{ok:…}`，实际是 `{"status","contract_version"}`；其余各步都依赖服务正常，都通过了。
  - `exp3.py`：F3 压力实验，raw、retry、index 三种模式共 8 轮。
  - `exp4_tok.py`：拦网络加载 tokenizer。
  - `mut.py`：9 个变异，每个跑 4 个测试文件，最后逐字节复原：True。
- 实验目录：`C:\Users\<用户>\AppData\Local\Temp\claude\D--lawbench\780b8a59-1849-4c63-905e-c6705fafa3f6\scratchpad\rv-B10-T8-lab\`，里面是上面的脚本和对应的 `*-out.txt`、`mut-out.txt`、`full-notok.txt`、`tok-exact.txt`。

## 残留审计

- 我起的服务进程（PID 35684）已终止，18851–18859 没有监听。
- 没有命令行里含 `rvB10t` 或 `rv-B10-T8-lab` 的进程。机器上另有两个对 `rv-B10` 跑 `git grep` 的进程（PID 45168、3520），属于另一名复核员，我没动；两个 `soffice.bin` 也没动。
- `rvB10t` 已用 `shutil.rmtree`（加 `\\?\` 前缀）删除，确认不存在。它的 `mb` 子目录一度被 PowerShell 的保护规则挡住没删成，也随整个目录一并删掉了。
- 克隆 HEAD 仍是 4bb0e40，status 干净，没有 `__pycache__`。
- 没有向 `D:\lawbench*` 或 `D:\lawbench-coord` 写任何东西；对 `D:\lawbench-B` 的 `tokenizer.json` 只读复制过一次（复制后哈希一致），那份副本已随 `rvB10t` 删除。

## 证据缺口

- 没有真实 DSH 时序（按令不要求），F1、F2 都是用固定交错顺序复现的；对应的交错测试确实存在，也能抓到回归（M1、M2、M2b 都变红）。
- F3 是人为制造的压力，不是真实扫描加工具调用的场景。
- F4 用的是 openpyxl 生成的宽表，不是真实案卷里的表格。
- 真计数的偏差比例（1.03–1.90）我没有独立重算，只确认了 `test_tokens_exact` 在有 tokenizer 时通过。
- T5、T3 的改动（47562dc、1274f46）不归我核。

PASS

---

## 第二部分 主编排裁决（2026-09-30 15:52 (+08:00)）

**T8 通过。** F1 用固定交错顺序独立复现并关闭（锁这一层单独证实），上一轮 X4b 的缺口（只去 `end` 的锁）现已变红，F3 读侧 0 次 PermissionError（对照组 11/23 次），tokenizer 在拦掉全部网络后 0 次尝试。无 P0/P1/P2。

- NOTE 1（`count()` 说明过时）、NOTE 5（begin 写盘失败时 `pop` 掉 `_begun[tid]`）：作为小项交线 B，随 T9 提交一并做，不算返修轮次。
- NOTE 2（表头放不下时整段去掉而非截短）：接受，目标"不超过 max_chars"已达到；写进 T8 已知限制。
- NOTE 3（极端压力下写侧重试用尽）：不是本轮引入、不在冻结范围，记 T18 已知项（与 `task.current()` 全扫一起实测）。
- NOTE 4（双层保护只去一层不变红）：知悉，作者已在交付说明写明。
- 合流：等同一 target 上 T5+T3 的复核结论；三张都过、合流门全绿后合并 line-B 到 `4bb0e40`。