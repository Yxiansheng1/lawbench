# T3 契约 1.4（服务侧 + 契约文件 + Skill 适配）· 独立复核记录（AMEND）

- 复核时刻：2026-10-10 15:15–15:30 (+08:00)；复核员：一名 Opus 只读复核员（克隆 `D:\lawbench-rv\rv-B24`，实验目录 `rv-B24-exp`）
- target：line-B `7a065b5`（含 `b7ff580`）；基座 `9bcc4fd`；81 文件 +1611/-98，`contracts\` 29 文件
- 裁决（主编排）：**AMEND**。P1-1 阻断（非固定盘"移回收站"= 永久删，定口径：非 UNC 且 `DRIVE_FIXED` 才移，否则 failed，不弹框）；P2-2 补闸门用例；P2-3 定"标准目录走 folders、自填仍走 Host"；P2-4 补 `kind`；P2-1 prep395 版本由线 C 同车；P3/NOTE 一并小修。令 `致B-ORCH-执行令-契约1.4复核AMEND-<HHMM>.md`。返修后换新复核员审累计范围。

## 复核员报告（原文摘要，路径已去用户名）

**结论：AMEND。** 契约生成物、检查脚本、全量测试对得上，remove 路径闸门实验守住；"移到回收站"在网络盘上会变永久删除，违反 SEC-08 口径。

### Findings
- **P1-1 网络盘上的"移到回收站"实际是永久删除**（范围内阻断）：`case\trash.py _recycle_windows` 用 `SHFileOperationW` `FOF_ALLOWUNDO|FOF_NOCONFIRMATION|FOF_SILENT|FOF_NOERRORUI`，无 `FOF_WANTNUKEWARNING`；目标位置无回收站（UNC、映射盘、多数 U 盘、超容量）时静默永久删，`recycle()` 只查"文件还在不在"即报成功；`gate.check_root` 不拒 UNC/可移动盘。实测 `\\localhost\D$\…\rvB24-probe-unc-*.txt` 返回 ok、文件消失、`Shell.Application NameSpace(10)` 中无；本地 D 盘同法进回收站。修：移前核非 UNC 且 `GetDriveTypeW == DRIVE_FIXED`，否则 failed；加用例。
- **P2-1 prep395 测试合进 main 即红**（引入的回归）：`test_contract_version_fallback_matches_repo` 断言 `CONTRACT_VERSION_FALLBACK == VERSION`，现 1.3 vs 1.4（`1 failed`）。服务侧不校验 395 版本属实。修：线 C 同车改。
- **P2-2 remove 闸门无用例守**（范围内阻断）：`gate.resolve_read` 换 `pathlib.Path(root, rel_path)` 后 `test_materials_remove.py` 仍 7 过 1 跳过。修：联接逃逸用例。
- **P2-3 `case_open.folders` 替代不了 Host `caseFolders`**（需拍板）：Host `chosenFolders` 支持自填一级目录（≤20），服务只收标准目录；交付说明第 4 条"Host caseFolders 可以撤"照做会丢功能。标准目录名两端一致。
- **P2-4 候项 15 `case_open.kind` 未做未交代**（范围内遗漏）：注记 14:52 落，交回 15:10 无 `kind`。
- **P3-1 `CASE_CARD_INVALID` 只覆盖两处**：`context.load_card` 仍 `contracts.validate` 抛 `ContractError`→INTERNAL 500。
- **P3-2 `wiki_review` 写卡片竞态**（臆测）：`mark()` 拿 `_WIKI_LOCK`，流水线写 case.json（`steps\wiki.py` ~587）不拿。
- **NOTE**：1 闸门拒绝时 `failed.reason` 写"可能正被其他程序打开"不准；2 index `rel_path` 改 `../` 时 remove 500（其他篡改正确 failed）；3 `more_names` 合计略超 `max_chars` 十几字；4 Spec 20.12 "1.3 的客户端照常"误导（Host 严格比对，须同包升级）；5 全量 1327 过/8 跳过（B 自报 1328/7，总数同 1335）。

### 核实无误
remove 闸门实验（联接指案件外同名文件→failed、未调回收、外部文件在；`工作区/`、`成果/`、`工作区./` 均拒；正常只回收案件内一份）；回收站用 ctypes Shell API 自写、无新依赖、不外连；日志只记案件编号/耗时/错误类名；幂等、`source_deleted` 可移除、index 留 `removed`、编号不复用、检索/文本/识别页清掉、AI 读不到、原文查看 `MATERIAL_NOT_FOUND` 均有用例；N45 正则契约/服务 `_ITEM`/dsh-ext `CITATION_PATTERN` 三处一致、旧格式照过；新字段全部可选；实验目录重跑 `gen_schemas.py`/`gen_examples.py`（61 schema、69 样例）与克隆零 diff、VERSION 1.4；`check_examples` 69/0；`build_skills --check` 过；Spec.html 含 20.12 1.4 行、SEC-08 新口径、两新错误码（build_docs 未重跑：venv 无 `markdown_it`）；变异：去 folders 校验即红、`_ITEM`/契约正则改回旧版即红、remove 闸门存活（P2-2）。

### 跑过的命令
`git diff --stat 9bcc4fd 7a065b5`；service 全量 `pytest -q -p no:cacheprovider`（13 分钟）；prep395 `pytest tests/test_api_contract.py -k version`；`check_examples`、`build_skills --check`；副本重跑 gen_* 后 `diff -r`；`recycle_exp.py`（本地/UNC 实测）、`escape_exp.py`（联接与 index 篡改）；`git archive` 副本三处变异。副作用：本机回收站留 4 个虚构探针 `rvB24-probe-local-*.txt`（可清）。克隆 `git status` 干净。
