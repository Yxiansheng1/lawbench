# T26 第 3 步归档面板（`bcae688`）与 T20 五条记录项 + 技术公司 logo（`059fdc9`）· 复核记录（单人，八项清单）

- target：line-A `bcae688`（父 `2ec3e6b` = merge main `69f0218`）、`059fdc9`；复核克隆 `D:\lawbench-rv\rv-A32`（HEAD `fec9f79`，两者为其祖先）
- 派发：Opus 5.5 只读复核员；首派 20:20 卡死（10 分钟无输出）作废，20:45 重派
- 归档：主编排于 2026-10-02 21:08 (+08:00) 从复核员交回原文抄录，未改内容

## 复核员原文## 复核结论速览
- 克隆身份已核：`D:\lawbench-rv\rv-A32` 的 HEAD 是 `fec9f79`，工作区干净。`bcae688`、`059fdc9` 都是它的祖先，`bcae688^` 是 `2ec3e6b`（合入 main 的那个提交）。
- 实验目录是 `D:\lawbench-rv\rvT26-r2\`，里面用 `git archive` 导出三份：b=`bcae688`、p=`2ec3e6b`、t20=`059fdc9`。实验做完整个目录已删。前一名复核员留下的 `D:\lawbench-rv\rvT26-r2`……不对，是 `D:\lawbench-rv\rvT26-r2` 之外的 `D:\lawbench-rv\rvT26-exp`，我没动过。

### 两个 target 各要做什么
- **T26 第 3 步**：成果标签里"案卷归档"任务旁边加一个入口，点开读出 Agent 存的归档方案。律师可以改材料名称、每项里材料的合并顺序、两个日期、承办律师；办案结果必须点选，没选时"生成归档文件"按钮不能点。点了以后经 Host 的长路由（node:http）调 `/api/archive/build`，列出生成的文件、页码和要人手处理的事项，出错时显示中文。顺带修第 2 步留下的问题：打包后远程方法的形参被改名，导致调不通。
- **T20**：把五条记录项落实，再把技术公司 logo2 做成透明 PNG，放进关于面板和安装界面品牌图。

### 每块改动的归类
- **必需实现**：`host/archive-plan.ts`、`host/index.ts`（archivePlan 方法，以及导出 REMOTE_METHODS 供构建核对）、`shared/remote-methods.ts`、`ui/archive-logic.ts`、`ui/archive.tsx`、`ui/results.tsx`、`host/http-json.ts` 的别名导入。T20 侧：install-layout.ts、P-4 补丁、make_brand.py、build.ps1、versions.lock 和许可证表（合入 main 后缺 python-docx，必须补）。
- **必需验证**：`tests/archive.spec.ts`、`primitives-stub.ts` 里的 Modal 替身、`dev/fake-tools.mjs` 里的 `/api/archive/build`、`scripts/build.mjs` 的形参核对、install-layout.spec、update-error-renderer.spec、各证据文件。
- **无关**：T26 交付说明里有一处修正旧的反斜杠排版（`apps\desktop\tests`），没有影响。

## Findings

**P3-1：Host 读方案时"实际位置必须在案件根里"这道核对，没有任何用例守着**
- 证据：变异 M1 把 `archive-plan.ts` 里 `if (!rel || rel.startsWith('..') …) return fail('OUT_OF_CASE', …)` 删掉，archive.spec 12 例仍然全过。
- 只有我加的探针能抓到：让 `工作区` 目录本身是一个指向案件外的联接，这时变异版会直接读进来（`PROBE ancestor-junction => "READ"`）。
- 没改的代码能正确拦住（探针通过），所以代码本身没问题，缺的是测试。
- 最小修复：archive.spec 加一例"祖先目录是联接"。
- 归类：独立后续，不阻断。

**P3-2：成果标签里的入口按钮（"核对归档方案并生成归档文件…"）没有用例**
- 证据：变异 M4 把 `results.tsx` 的条件改成 `false && …`，全量 517 过、5 跳过，没有一例变红。
- 归类：独立后续。

**NOTE-1：生成后"结案报告由 Word 转成 PDF"的提示出现两次**
- 一次来自界面的 `converterHint`，一次来自服务的 `manual`（"结案报告由 word 转成 PDF…"，小写 word 是 T23 服务端写的）。我用真服务实测，面板文字里确实两句都有。
- 只是外观问题。
- 归类：独立后续。

**NOTE-2：Host 的 `archivePlan` 只检查 root 是不是绝对路径，不检查它是不是已登记的案件根**
- 它也不走服务端的路径闸门（OneDrive、网络路径等规则）。
- 能读的只有固定的 `<root>\工作区\任务\<T-…>\归档方案.json`，而且内容必须通过契约校验；界面传来的 root 本身来自服务开案件的结果，所以实际风险低。
- 作者在 7.5 已列为偏离，请主编排定。
- 归类：臆测 / 独立后续。

**NOTE-3：`build.mjs` 新加的形参核对子进程 `spawnSync` 没有设超时**
- 旁边原有的 ESM 导入检查也一样没设。
- 归类：独立后续。

T20 没有发现问题。

## T26 第 3 步验收逐条

| 项 | 结果 | 依据 |
|---|---|---|
| 办案结果未选时按钮不可用、不发请求 | 过 | archive.spec 第 1 例；我用真服务存的方案渲染面板，未选时 `disabled=true`，选了"胜诉"后可用 |
| 生成后列出归档总文件夹里的全部文件 | 过 | 真服务：磁盘上 5 个文件和回答里 `files` 的 5 个完全一致（`same=True`）；把真回答喂给面板，5 个路径和 7 条 manual 全部显示出来 |
| 页码范围 | 过 | 5 是第 1–3 页，6 是第 4–5 页，9 是第 6–10 页，13（程序生成）是第 11 页，和作者 `archive-build.txt` 一致 |
| manual 提示 | 过 | 显示在"还需要您手动处理"框里 |
| 错误体显示中文 | 过 | spec 的 CONVERTER_UNAVAILABLE 一例；真服务的 result=null 回 `PLAN_NOT_CONFIRMED / 请先确认办案结果`，plan 路径错回 `INVALID_ARGUMENT / 请求参数有误`；界面经 `errorText` 显示 |
| 长路由走 http-json（node:http），不走 fetch | 过 | `archiveBuild` 在路由表里是 LONG（10 分钟）；`callApi` 走 `requestJson`（index.ts:161） |
| 界面用语检查零命中 | 过 | 我跑 `check_ui_words.py`，结果"零命中"；host 里的两句提示我人工看过，也没有禁用词 |
| 归档逻辑全在服务端，界面不碰文件 | 过 | archive.tsx 和 archive-logic.ts 都没有 fs；Host 只读方案这一个文件，作者已列为偏离 |
| 和作者实测对照 | 一致 | 文件名、大小量级、页码、manual 条数都对得上；第 6 项改过的合并顺序在 `归档目录.md` 里生效（"转账截图、现场勘验图文"） |

### 第 2 步回归修复
- **是真回归**：在 p（`2ec3e6b`）上构建，`lib/host.js` 里出现了 `turnNotice(request2)`、`function(request2)` 等共 15 处 `request2`。DSH 网关 `assertExactArguments` 按形参名对参数（gateway/src/index.ts:1465–1490），所以对不上。`7940d3e` 里也已经有 `import { request } from 'node:http'`。
- **修法是最小的**：两行别名导入，加构建后核对，加一行导出。b 构建后 `request2` 为 0 处，方法形参都是 `request`。
- **核对可靠**：我在副本上把别名改回去，构建退出 1，并且列出 `importPastedImage(request2) … caseRecent(request2) …`；复原后 hash 一致。打包脚本 `packaging/build.ps1:87` 调的就是这个 build.mjs，所以打包也受这道核对保护。
- **第 1、2 步已过的用例仍然全过**：全量 32 个文件，516 过、5 跳过（invoice、retainer、host-api、remote-methods 都在里面），tsc 退出 0。

### 我自己选的 4 条变异
| 变异 | 结果 |
|---|---|
| M1 删 realpath 核对 | archive.spec 不红，只有我的探针红（即 P3-1） |
| M2 删 lstat 链接核对 | 红（链接那例）；realpath 仍拦得住 |
| M3 生成后不列文件 | 红 |
| M4 入口去掉 | 全量不红（即 P3-2） |

## T20 五条记录项和 logo
- **① 冒烟脚本**：P-4 补丁里加了 `.Replace('${PRODUCT_NAME}', $ProductName)`，`$ProductName` 是原脚本的必填参数（只读 `git show 477b4f4` 核过）。真编安装器那一步没跑。
- **② mutate_check 锚点**：`docs/plan/evidence/T17/mutate_check.py:63` 已是 `[p.join(process.env.ProgramData`，是在 cb21fad 改的，不在本提交里，符合作者说法。
- **③ apply 分支用例**：install-layout.spec 4 例全过。两条变异（不把 basePath 交下去；开发期交回拷贝并带上 `LAWBENCH_X`）各红 1 例；`apply` 里传的是 `process.env.PATH ?? ''`。
- **④ 删 `__pycache__`**：build.ps1 拷完以后删 `__pycache__` 和 pyc，自检加了 `-B`。这条是静态核的。
- **⑤ DryRun 缺项退出非 0**：缺项先收集起来，在 `if ($DryRun) return` 之前抛错；脚本开着 `$ErrorActionPreference='Stop'`，会以非 0 退出。也是静态核的。
- **logo 来源**：`D:\lawbench\logo\技术公司-logo2.jpg` 和仓库 `logo\` 下那份 SHA256 相同（986E55EA…）；本提交没改 `logo/` 目录。
- **生成可重复**：在 t20 副本上重跑 `make_brand.py`，`packaging\brand` 下所有文件和提交里的逐字节一致，0 处差异。
- **格式**：几张图都是 RGBA，带透明，没有 tEXt/iTXt/eXIf 元数据。
- **放的位置和补丁对得上**：主进程写死 `assets/vendor-logo.png`，make_brand 输出 `desktop\renderer\assets\vendor-logo.png`，按 PATCHES 的步骤拷进 `apps\desktop`；渲染页拒外部地址、`..` 和 `file:`。深色 2x 品牌图我看过，右下角标正常。
- **机密**：两个提交的新增行扫了 Key、内网地址、本机用户名，0 命中。

## 八项清单
1. **契约一致**：过。请求用契约 request 校验；真回答用契约 response 校验；方案用 `$defs/plan` 校验；没改 contracts。
2. **边界输入**：过。覆盖了任务编号格式、相对 root、BOM、坏 JSON、越界移动、空名称、不存在的日期。
3. **错误路径**：过。真服务的 PLAN_NOT_CONFIRMED、INVALID_ARGUMENT，假服务的 CONVERTER_UNAVAILABLE，读不到方案，界面都显示中文。
4. **日志不含正文**：过。只记 `archive.plan_read {ok, code}` 和 `api.call {method, ok, ms}`。
5. **路径闸门**：过，但有两处说明。链接、出案件根都拦住了（见 NOTE-2）；祖先目录是联接的情况缺用例（见 P3-1）。
6. **无外连**：过。Host 只连 127.0.0.1；我的实验在进程内跑，两组地址都填 127.0.0.1 上没人监听的 19321–19324，没调测试连接，没读 Key（key_getter 设成一读就报错，全程没触发）。
7. **测试覆盖新代码**：基本过，缺口见 P3-1、P3-2。
8. **无机密入库**：过。

## 实际跑过的命令（都带超时）
- `git rev-parse`、`git status`、`git show`、`git archive | tar`
- 在 b 副本：`node scripts\test.mjs tests/archive.spec.ts`（12 过）；全量（516 过、5 跳过）；`tsc --noEmit`（退出 0）；`node scripts\build.mjs`（b 和 p 各一次，外加一次别名变异）；`check_ui_words.py`
- `mut.py` 跑 M1–M4
- 真服务分四步，用 `D:\lawbench-C\.venv`、Starlette TestClient 进程内跑 main 的服务：
  1. criminal-01 建案件、扫描、走 task begin、case_archive_match、case_save_archive_plan；
  2. vitest 探针用 Host 的 `readArchivePlan` 读真方案，界面 `applyEdit`/`buildRequest` 生成请求，并过契约；
  3. POST `/api/archive/build`，用时 23 秒，转换程序是 word；
  4. 把真回答喂给 ArchiveDialog 渲染。
- 在 t20 副本：重跑 `make_brand.py` 比对 hash；PIL 查图片元数据；`mut20.py`（基线 4 过，两条变异各红）

## 残留审计
- 我起的 node、python 进程都已结束，Word 前后没有新增进程。
- 19320–19329 没有端口在监听。
- 先用 `rmdir` 拆掉 6 个指向 `D:\lawbench-A\dsh` 的联接，确认目标完好，再删整个 `D:\lawbench-rv\rvT26-r2`（已不存在）。
- rv-A32 的 HEAD 仍是 `fec9f79`，工作区干净。
- 系统 TEMP 下没有我留下的 `lb-*` 目录。
- 我没碰 exp32、rvB32* 的进程，没碰 10028、42468 这两个 soffice，也没碰前一名复核员留下的 `rvT26-exp`。

## 证据缺口
- 我没在桌面端（打包的 DSH）上亲手点过归档面板，打包产物里的形参名以构建核对和 grep 为证。
- 真服务是进程内跑的，没经过 Host 的 `callApi`/node:http 这一跳；这一跳由 host-api.spec 和第 2 步复核覆盖。
- T20 的 build.ps1 两条（④⑤）是静态核的，没真跑 python 步和 DryRun。
- 真编安装器的冒烟（P3-a）要构建机，没跑。

T26: PASS
T20: PASS

