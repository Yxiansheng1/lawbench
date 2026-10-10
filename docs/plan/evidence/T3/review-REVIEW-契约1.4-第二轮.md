# T3 契约 1.4 AMEND 关闭 + case_open.kind · 独立复核记录（第二轮，PASS）

- 复核时刻：2026-10-10 15:55–16:15 (+08:00)；复核员：一名 Opus 只读复核员（换人；克隆 `D:\lawbench-rv\rv-B25`，实验目录 `rv-B25-exp`）
- target：line-B `e4d320e`（累计 `0770efd`→`faa77cf`→`e4d320e`；`49d3b44` 端口四修另案已合，不在范围）；基座 `e595c6c`
- 裁决（主编排）：**PASS**。属第八版：待第七版包出并复核后再合 main（避免打包期 rebase 带入 1.4 造成客户端 1.3 配服务 1.4）。P3-1 提示语与 NOTE-2 测试改法令 B 小修（主编排亲核）。

## 复核员报告（原文摘要，路径已去用户名）

**verdict：PASS。** 上轮 P1 已关闭并实测；两项 P2 与 `kind` 均有用例、去代码即红。

### Findings
- **P3-1 损坏索引的提示语引导"重新扫描"，但 scan/list 遇坏索引也 500**：`rel_path` 改 `../外面/说明.txt` 后 remove→200 每份 failed"材料索引已损坏，未移除；请先重新扫描"、回收函数未调用、文件都在；`/api/materials/scan` 与 `/api/materials` → 500 INTERNAL。修：提示语改"请联系技术支持"，或 scan/list 把 `ContractError` 转业务码。提示语为本次引入、500 为此前既有；不阻断。
- **NOTE-1** NOTE 2 处理与令出入（整请求每份 failed、不动文件）判断合理；只在 `_load_index` 抛 `ContractError` 时触发，`a..b.pdf` 照常；用例写得宽松但去捕获即红（M4）。
- **NOTE-2** `test_has_recycle_bin_only_on_fixed_local_drive` 对 `__file__` 调真回收函数，闸门去掉时会把测试文件自己移进回收站（M2 实际发生）。修：改 `tmp_path` 临时文件或 monkeypatch `_recycle_windows`。
- **NOTE-3**（臆测）固定盘下的卷挂载点 `GetDriveTypeW` 只看盘符会判"有回收站"。

### 逐项
P1-1：`has_recycle_bin` 探测 `<HOME>\连越律师工作台\…`、`D:\…`、`\\?\C:\`、`\\?\D:\` 判有；`\\localhost\D$\…`、`\\?\UNC\…` 判无。实测本地 D 盘 remove 成功进回收站、文本清；UNC 案件根 remove→failed、回收 0 次、原件与文本都在；直接 `trash.recycle(UNC)`→`OSError no recycle bin`，文件仍在；未加 `FOF_WANTNUKEWARNING`；M1/M2/M5 红。P2-2：M3 红。`kind`：枚举、case.db meta、`case_open`/`case_recent`/`cases.json` 带回、不带沿旧、非枚举按 null、`"合同"`→INVALID_ARGUMENT、换数据目录仍读得到；M6 红；gen_schemas 61/gen_examples 71 零 diff、VERSION 1.4。P3-1 `load_card`→`CASE_CARD_INVALID` 有用例；P3-2 持锁；NOTE 1 文案改；NOTE 4 Spec 20.12 与 4.2 第 5 条已改，Spec.html 同步（build_docs 未重跑：venv 缺 markdown_it）。无回归：本地案件不误判；`_WIKI_LOCK` 只在 `write_bytes` 持锁、`mark()` 锁内只读写本地、无嵌套锁/网络等待；`before_remove` 不嵌套案件锁。全量 1335 过/8 跳过（B 自报 1336/7，合计同 1343）；check_examples 71/0；build_skills --check 过。

### 跑过的命令
`git diff --stat e595c6c e4d320e`；service 全量（800 秒）；check_examples；副本 gen_schemas/gen_examples/build_skills；`recycle_exp.py`、`note2_exp.py`、`mutate.py`/`mutate2.py` M1–M6（基线 67/1，六变异各红一例）；`Shell.Application NameSpace(10)` 查回收站。副作用：本机回收站留 `rvB25-probe-local-155716.txt` 与一份副本 `test_materials_remove.py`（可清）。克隆干净。
