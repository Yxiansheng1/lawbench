# T9 `GET /api/source` 原文查看（T14 派修，line-B `8088538`）· 复核记录（单人，八项清单）

- target：line-B `8088538`（父 `37b5160`）；复核克隆 `D:\lawbench-rv\rv-B22`
- 派发：Opus 5.5 只读复核员，2026-10-03 16:3x
- 归档：主编排于 2026-10-03 16:50 (+08:00) 从复核员交回原文抄录，未改内容

## 复核员原文## 结论先说

被复核的提交是 line-B `8088538`（复核克隆 `git rev-parse HEAD` = `80885387f516…`，父提交 `37b5160`）。它要做的事，说白了就是：律师在界面上点一条出处，服务端按这条出处找到这份材料对应的页、段、行或单元格，把那一段文本返回；如果是 PDF，再附上那一页的页面图片；如果这份原件在出处记下之后改过，就提示"原件已更新"。整个过程只读，不出案件目录，日志只记编号。

功能本身我逐项实测过，都对：契约字段一个不多一个不少，越权请求全部被拒，只读，日志干净，定位准确，复用的是现成函数而不是复制了一份。我判 **AMEND**，原因只有一个：新代码里有两处是路径闸门（取页面图片时读原件、判断"原件已更新"时读各任务的 result.json），把闸门去掉换成直接拼路径，10 个用例照样全绿。也就是说，这两处闸门现在没有任何测试守着。在涉密项目里，这类安全路径应该有回归用例。要补的就是两三条用例，不用改产品代码。

## 发现的问题

**P2-1 两处路径闸门没有测试守着（范围内阻断）**
- 问题：`service\lawbench\case\source.py` 里有两处闸门调用：
  - `_page_png` 中的 `gate.resolve_read(root, meta["rel_path"], op="source_view")`
  - `_changed` 循环里的 `gate.resolve_internal(root, f"{TASK_DIR}/{d.name}/result.json", ...)`
- 证据：我在副本上做了两个变异（`D:\lawbench-rv\exp\mut.py`，跑完已删）：
  - 第一处换成 `pathlib.Path(root) / meta["rel_path"]`：`10 passed`，没变红；
  - 第二处换成 `d / "result.json"`：`10 passed`，没变红。
  - 对照：我加的"别案不查本案索引"变异是红的，作者的四条变异重跑也都红了。
- 影响：今天的行为是对的，后面的实验都能证明。但以后谁重构把闸门拿掉，测试发现不了。
- 最小修复：在 `tests\test_source.py` 加两三例：
  - 原件所在的文件夹（如 `卷一`）换成指向案外的联接，期望 `page_png_base64` 为 null、文本照返、日志里有一条 `gate denied`；
  - `工作区\任务\<id>` 换成指向案外的联接，期望那份案外的 result.json 不被读到；
  - 可选：`工作区\任务` 整个目录换成联接，期望返回 OUT_OF_CASE。

**P3-1 `logs.event` 新加的格式校验没有测试（独立后续）**
- 问题：`service\lawbench\logs.py` 新加了两条校验：`material_id` 必须是 `M` 加 4 位数字，`unit` 只能是 page/para/line/cell。全仓库测试没有一条断言这两个 ValueError（我按 `material_id 不是`、`未知定位单位` 搜过，0 处）。
- 说明：我原本想做这条变异，但锚定的文字没匹配上，所以没跑成。这条结论只靠搜索，没有变异证据。
- 风险：低。现在唯一的调用方传的是 index 里的编号，而 index 是按契约校验过的。
- 最小修复：加一例，传 `material_id="起诉意见书"` 期望抛 ValueError。

**P3-2 每点一次出处，都要把本案所有任务的 result.json 读一遍并做契约校验（独立后续）**
- 证据：`exp2.py` 造了 300 个任务、每个 50 条出处，点一次耗时 8.06 秒，日志 `"ms": 8062`。
- 真实案件的规模会小很多，但这个开销随任务数线性增长，而且每次点击都要付一次。
- 建议：交给 T18 计量，或者按文件修改时间做缓存。

**NOTE（只记录，不阻断）**
1. `工作区\任务` 整个目录如果被换成联接，整次查看会直接返回 OUT_OF_CASE，而不是只把 `source_changed` 置为 false。这是往安全方向失败，可以接受。
2. `source_changed` 按位置精确匹配，有三种情况会漏提示：
   - 记录的是 `第2-3页`，点的是 `第2页` → false；
   - 记录的是 `{from:4,to:4}`，点的是 `第4页` → false；
   - 原件改了但还没重新扫描 → false，重扫之后才变成 true（实测 `重扫后 sha 变了: True | 查 第5页: True`）。
3. 待识别的材料：
   - 扫描版 PDF 未识别：返回占位文本"（本页需识别）"，同时有页面图片；
   - 图片材料未识别：只有占位文本、没有图片，律师什么也看不到（和作者的请定第 2 条有关）。
4. 页面图片大小（实测）：

   | 材料 | PNG 原始大小 | base64 后 |
   |---|---|---|
   | 文字版 PDF 一页 | 159–210 KB | 212–280 KB |
   | 扫描版一页 | 1.31–1.39 MB | 1.75–1.85 MB |

   尺寸都是 1654×2339 像素，上限受 render 的长边 2480 像素约束。文本长度没有上限：范围出处 `第1-5页` 返回 1137 字。
5. 同一个括号里同一材料出现两次，比如 `〔起诉意见书 第1页、起诉意见书 第2页〕`，只返回第一处。

## 契约逐字段核对（`contracts\api\source.schema.json`）

| 字段 | 契约要求 | 实现 | 结论 |
|---|---|---|---|
| 请求 case_id | uuid4 正则，必填 | 由 `_endpoint` 按 `$defs/request` 校验；格式坏的值返回 INVALID_ARGUMENT（实测） | 一致 |
| 请求 material_id | `^M[0-9]{4}$`，必填 | 同上；`../M0001` 返回 INVALID_ARGUMENT | 一致 |
| 请求 citation | citation_text 正则，必填 | 同上；缺少时、不带括号时都返回 INVALID_ARGUMENT | 一致 |
| 多余参数 | 不允许（additionalProperties false） | 带 `path=...` 返回 INVALID_ARGUMENT | 一致 |
| 返回 name | string | `meta["name"]` | 一致 |
| 返回 loc | common `loc`（page/para/line 用 from/to；cell 用 sheet+ref） | 取自 `find_cites` 的 item.loc；cell 实测 `{'unit':'cell','sheet':'流水','ref':'B3:C4'}` | 一致 |
| 返回 text | string | `Material.text_at(loc)` | 一致 |
| 返回 page_png_base64 | string 或 null | 只有 PDF 的 page 单位出图，其余为 null | 一致 |
| 返回 source_changed | boolean | `_changed()` | 一致（启发式规则见请定第 1 条） |
| 失败体 | common `fail`，code 在 error_code 枚举内 | 走 `ApiError(code, reason, detail)`，`ApiError` 构造时检查 code 必须在 MESSAGES 里；用到的码：INVALID_ARGUMENT、MATERIAL_NOT_FOUND、MATERIAL_NOT_READY、CASE_NOT_FOUND，另有闸门的 OUT_OF_CASE | 一致 |

每个成功返回在开发环境下还会按 `$defs/response` 校验，测试里也经过 `t8_helpers.ok` 校验。字段没有增减。

## 越权矩阵（全部是我自己用 TestClient 在进程内构造的请求）

395 用的是本机假服务，端口 19340/19341；6000D 地址填 `127.0.0.1:9`；不读 Key。

| 构造方式 | 结果 |
|---|---|
| 出处写的是别的材料（起诉意见书的编号配 `〔借条 第1段〕`） | INVALID_ARGUMENT |
| 〔推断〕 | INVALID_ARGUMENT |
| 〔未找到依据〕 | INVALID_ARGUMENT |
| 第0页 | INVALID_ARGUMENT，提示"页号从 1 起" |
| 范围写反（3-2） | INVALID_ARGUMENT，提示"范围写反了" |
| 超大页号（20 位数字） | INVALID_ARGUMENT，提示"超出材料范围（共 5 页）" |
| 第99页 | INVALID_ARGUMENT，同上 |
| 单位不对（PDF 写成"第1行"） | INVALID_ARGUMENT，提示"这份材料按第N页定位" |
| 单元格越界 Z999 | INVALID_ARGUMENT，提示"超出工作表范围" |
| 工作表不存在 | INVALID_ARGUMENT |
| 两条出处拼在一起（〔…〕〔…〕） | INVALID_ARGUMENT |
| 材料名里带 `..\` | INVALID_ARGUMENT |
| 材料名里带 `卷一/` | INVALID_ARGUMENT |
| material_id 不存在 | MATERIAL_NOT_FOUND |
| case_id 格式坏（`..\x`） | INVALID_ARGUMENT |
| case_id 不存在 | CASE_NOT_FOUND |
| 本案材料编号拿到别案去查 | MATERIAL_NOT_FOUND |
| 别案的 M0001 配本案材料的出处 | INVALID_ARGUMENT |
| 处理失败的材料（加密、截断的 PDF） | MATERIAL_NOT_READY |
| 用 POST 调 | 404 |
| 不带令牌 | 401 |
| 原件所在文件夹 `卷一` 换成指向案外的联接 | 文本照返（读的是工作区里的文本），页图为 null，不读案外文件 |
| 材料文本目录换成联接 | MATERIAL_NOT_READY |
| `工作区\任务` 换成联接 | OUT_OF_CASE |
| `工作区\任务\<id>` 单个目录换成联接 | 跳过不读，`source_changed=False` |
| 篡改 index.json，`rel_path` 改成 `..\outside\…` | MATERIAL_NOT_READY（文本路径过 check_ai_rel 时因 dotdot 被拒） |
| 篡改 index.json，`rel_path` 改成 `工作区/…` | MATERIAL_NOT_READY（reserved_top 被拒） |
| 原件被改成垃圾内容或被删掉 | 文本照返，页图为 null |
| 只读核查：连续三轮各种请求前后，对案件目录和应用数据（日志除外）做大小、mtime、sha256 快照 | 变化 0、0 |
| 日志 | 只有 `{"module":"source","op":"view","case_id":…,"material_id":"M0002","unit":"para"}` 和 `api/source` 的耗时；service.log 里搜不到材料名、〔、卷一、第1页、识别文本 |

## 定位正确性（实测）

- **文字版 PDF**：起诉意见书第 1、3 页，现场勘验图文第 1 页。文本等于该单元、不等于其他单元；页图与 `render_png(该页)` 逐字节相同。
- **扫描版 PDF 识别后**：讯问笔录第 1 页，文本等于该单元，页图逐字节相同。
- **docx**：第 3 段，csv 第 2 行，文本都等于该单元，无图。
- **xlsx**：B3 返回 2 字，B3:C4 区域返回 10 字。
- **图片识别后**：只有识别文本，无图（作者用例覆盖，我只核过行为）。
- **页图**：渲染失败时返回 null；范围出处取首页（作者用例，加上我重跑的变异"范围取末页图"变红）。

## 复用情况

- 确实复用：source.py 直接 import `checks.parse` 的 `MaterialSet`/`find_cites`，以及 `ocr.render`。
- 没有复制：`def text_at`/`check_loc`/`find_cites`/`render_png` 在 lawbench 目录里各只有一处定义。
- `logs.event` 只加了两个可选字段，不传时日志格式和原来一样。全量里所有日志类用例（test_api_case、test_checks、test_search 等）都通过。

## 作者的三处"请定"（只核事实和风险，不替主编排拍板）

1. **source_changed 的判断依据**
   - 作者自述的局限属实：同一处被旧任务和新任务都引用过时，从旧草稿点进来也不会提示。
   - 我另外实测到三种漏提示：范围和单页写法对不上、`4-4` 和 `4` 对不上、原件改了但未重扫。
   - 要精确到"这条出处属于哪个任务"，需要给请求加 task_id，这是改契约。
2. **图片材料不出图**：符合 Spec 4.3 的字面写法（只说了 PDF）。风险是：图片材料还没识别时，律师只能看到"（本页需识别）"，看不到原图。
3. **图片大小没有上限**：渲染长边被限在 2480 像素，所以单张图实际有上限。扫描页实测 base64 后约 1.8 MB；噪声更多的扫描件可能更大。文本长度没有上限。

## 八项清单

| 项 | 结果 |
|---|---|
| 契约一致 | 通过 |
| 边界输入 | 通过（0 页、超大页号、反向范围、单位不对、cell 越界、多余参数、缺参数） |
| 错误路径 | 通过（四种错误码加 OUT_OF_CASE；渲染失败时降级为页图 null） |
| 日志不含正文 | 通过 |
| 路径闸门未被绕过 | 行为上通过（联接和篡改实测都被拒），但测试守不住（见 P2-1） |
| 无外连 | 通过（只用了 127.0.0.1 上的假 395 和 :9 死端口；本接口不发网络请求） |
| 测试覆盖新代码 | **不完全**（P2-1 两处闸门、P3-1 日志校验没有测试） |
| 无机密入库 | 通过（增量里没有 Key 或真实材料，测试只用 `tests\fixtures`） |

## 实际跑过的命令

- 在复核克隆里：`git rev-parse HEAD`、`git diff --stat 8088538~1 8088538`、`git diff 8088538~1 8088538`。
- 用 `git archive` 导出到 `D:\lawbench-rv\s9`，用 Python tarfile 解包（Windows 自带的 tar 会把中文文件名弄坏）。
- `pytest -q tests\test_source.py`：**10 passed**。
- 全量 `pytest -q tests`（后台跑，basetemp `D:\lawbench-rv\s9t\full`）：**1274 passed、7 skipped、1 failed，用时 20 分 52 秒**。
  - 失败的是 `test_tokens.py::test_tokenizer_json_ignored_by_git`，原因是 `fatal: not a git repository`：导出的副本不是 git 仓库，属于环境问题，与本提交无关。
  - 和作者的 1276 过、6 跳过对得上：总数同为 1282；我这里多一个跳过，应是副本里没有 tokenizer.json。
  - test_checks* 和 test_ocr_queue 都在全量里，全部通过。
- `contracts\check_examples.py --skills skills`：通过。
- `D:\lawbench-rv\exp\exp_source.py`、`exp2.py`：上面的越权矩阵、定位、只读快照、联接、篡改 index、source_changed 和性能实验。
- `D:\lawbench-rv\exp\mut.py`（在第二份副本 s9m 上跑）：

  | 变异 | 结果 |
  |---|---|
  | 作者四条（文本取错单元、范围取末页图、不认材料名、从不提示） | 全红，失败数与 `source-mutations.txt` 一致 |
  | 我加的：别案不查本案索引 | 红 |
  | 我加的：页图绕过闸门 | 绿（P2-1） |
  | 我加的：任务记录绕过闸门 | 绿（P2-1） |
  | 我加的：日志校验 | 锚定文字没匹配上，没跑 |

  变异后 source.py、logs.py 已和原副本按哈希比对，逐字节复原。

## 残留审计

- 全量 pytest 进程 PID 41112 已正常退出；实验里起的 uvicorn 都是进程内线程，随脚本结束。
- 端口 19340–19349 上没有任何监听。
- `D:\lawbench-rv` 下我建的 s9、s9m、s9t、x9、x9b、exp 和输出文件都已删除：先逐个拆掉测试留下的联接，再用长路径前缀删掉超长目录。现在只剩 rv-A32、rv-A33、rv-B22。
- 复核克隆 rv-B22 的 `git status` 是干净的，HEAD 没变。
- 没有碰 D:\lawbench、-A、-B、-C 和 coord 目录，没有碰别人的进程。
- scratchpad 里留着一个清理脚本 `cleanup_rv9.py`。

## 证据缺口

- P3-1 只有搜索证据，没有变异证据。
- 没有在真桌面端里点过出处（界面那一侧不在本卡范围）。
- 没有用真 395 跑过。
- 没有大卷宗或几十 MB 级 PDF 的页图耗时数据。
- "原件已更新"提示只测了启发式规则本身，没有和 Host 端的界面文案对过。

AMEND


---

## 主编排裁决与补用例亲核（2026-10-03 17:01 (+08:00)）

- 裁决：**AMEND 只补用例**（功能已由复核员二十余种越权构造与只读快照证实）。线 B `d40a55b`（叠在 rebase 后的实现 `23ccbe9` 上）补三例闸门用例 + logs 校验两例，`test_source.py` 14 passed（main 上亲跑）。
- 我自己的变异：`_page_png` 的 `resolve_read` 换直接拼路径 → 7 红（含 NameError 连带）；`_changed` 每份 result.json 的 `resolve_internal` 换直接拼路径 → 1 红（联接用例）。复原干净。
- 三处请定：source_changed 启发式一期接受、`task_id` 入契约 1.4 候项；图片材料不出图按 Spec 字面、N66 候用户；图片大小接受。P3-2 交 T18 观察。
- **通过。** 两提交进 main。
