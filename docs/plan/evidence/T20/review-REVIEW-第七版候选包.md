# T20 第七版候选包（重打）· 独立复核记录（PASS）

- 复核时刻：2026-10-10 17:50–18:10 (+08:00)；复核员：一名 Opus 只读复核员（克隆 `D:\lawbench-rv\rv-A58`，包副本 `rv-A58-pkg`，实验目录 `rv-A58-exp`）
- target：line-A `736e2d3`（第七版重打证据）；基座 main `47f4ad0`
- 包：`lawbench-0.1.0-win-x64-unsigned.exe` 655,957,418 B，sha256 `33626f745e744f2ae97db68f168e4aa9e60aeb7c880a099e924cbe6df79799c2`，`LAWBENCH_BUILD_STAMP=202610101718`（复核员与主编排一致；不入库）。**第七版 = 律所第三批试用版（覆盖第六版）。** 第一个第七版包 `67a10102…`（戳 202610101611）因"拖文件夹建成后材料 0 份"作废未发。
- 裁决（主编排）：**PASS**，cherry-pick `736e2d3` 进 main。NOTE 1 复核员纪律记录（误跑一次 `git -C D:\lawbench-A status`，只读）；NOTE 2 引擎自带样本随包，按 engines 原样口径不动。

## 复核员报告（原文摘要，路径已去用户名）

**结论：PASS。** 七项核查全过，无阻断、无回归。

1. 大小/哈希与自报一致。
2. 7za 列包：`primary-runtime` 零条；`libreoffice-kit` 仅 `app.asar.unpacked` 下 koffi 6 条（同第六版）；无 `.env.local`、无 `tests\fixtures`；350 个 docx/xlsx/pdf 均为工具运行库（286）、retainer 空白模板、台账/录入模板、ocr-driver 测试样本、导出模板，无真实案卷。
3. `app.asar` 127,376,603 B（第六版 127,315,578 B）：`dropInfo` 4、`scanMaterials` 3（含 `onOpened: async … await scanMaterials(c)`）、"松开：建新案件"（\u 编码）、`PORT_IN_USE` 6/`PORT_RESERVED` 2/`PORT_DENIED` 2、`explorerArg` 2、`windowsVerbatimArguments` 4；`PRODUCT_BUILD = "202610101718"`，旧戳零命中。
4. 服务侧：包内 `portdiag.py` 与源 sha256 相同（含 `System32\netsh.exe`、`lru_cache(maxsize=1)`）；包内 `contracts\VERSION` = **1.3**，无 1.4。
5. 泄密扫（asar + 解出 service/contracts/skills 238 文件）：`<用户名>` 零命中；Key 形态零命中；四个预填地址只在 `settings.py`、`file_settings.json`、`gen_examples.py`；其余 `192.168.x` 为第三方库注释示例。
6. 证据：`47f4ad0..736e2d3` 8 文件全在 `evidence\T20\`；交付说明两节、`build.txt` 末节数字与实测一致；5 截图路径已遮；`versions.lock` 本提交未改（retainer 一行在 `bed589f`，已在 main）；两包代码差 = `bed589f..47f4ad0` 非 docs 部分 = `dsh-ext/ui` 四文件 + 一测试，与自述一致。
7. 未安装、未运行。

### Findings
- **NOTE 1**（复核纪律）：末条命令误跑 `git -C D:\lawbench-A status --short`（只读）。
- **NOTE 2**（独立后续，旧状况）：`engines\retainer\tools\ocr-driver\tests\format-corpus\license-*` 引擎自带测试样本随包发布。

### 跑过的命令
`Get-FileHash`；`git log/diff 47f4ad0..736e2d3`、`bed589f~1..bed589f -- packaging/versions.lock`、`bed589f..47f4ad0 -- . ':!docs'`；7za `l -slt`/`l -ba -sccUTF-8`/`e`/`x`（electron-builder 缓存里的 7za）；PowerShell 正则扫描与源文件哈希对照；Read 5 张截图。解包内容已删，`rv-A58` 干净，约 20 分钟。
