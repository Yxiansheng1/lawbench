# T20 第五版前小修一批 · 独立复核记录（AMEND）

- 复核时刻：2026-10-07 14:25–14:58 (+08:00)；复核员：一名 Opus 只读复核员（克隆 `D:\lawbench-rv\rv-A49`，实验目录 `rv-A49-exp`）
- target：line-A `2234f10`（令 1337 九条：新 P-23 剔 `libreoffice-kit-win32-x64` 184 MB + `primary-runtime` 286 MB、安装器缓存改道 `%LOCALAPPDATA%\lawbench\installer-cache`、AUMID、versions.lock 3.12.10、scrubPaths、PATCHES/F6、`-I` stderr 断言、primary-runtime 用途答复）；基座 `f75f2ed`；13 文件 +748/-53
- 裁决（主编排）：**AMEND**，只返修 `scrubPaths` 两处（进包，修完再打第五版）；P3 两条一并；注记 0934 四小项下批。令 `致A-ORCH-执行令-小修批AMEND-scrubPaths两处先修再打包-20261007-1458.md`。

## 复核员报告（原文，路径已去用户名）

**Verdict：AMEND。** 主体对：P-23 剔除、安装器缓存改道、AUMID、versions.lock、`-I` 断言核过无问题；返修只 `scrubPaths`（令第 5 条）两种常见输入仍漏名。

### Findings
**P2-1 `scrubPaths` 末段遇"点加数字"即停，案件名漏出**（范围内阻断）：末段扩展名 `\.\w{1,5}\b` 把日期/版本号当扩展名。`rv-A49-exp\scrub.mjs` 实跑：`NotADirectoryError: D:\案卷\2026.10.07 张三 诉 李四` → `<路径> 张三 诉 李四`；`D:\案卷\张三 诉 李四 2026.10 定稿` → `<路径> 定稿`；`D:\案卷\孙八 案 第2.3稿 起诉状` → `<路径>稿 起诉状`。修复：`\.[A-Za-z][A-Za-z0-9]{0,4}\b`，补 3 用例。
**P2-2 安装目录路径后跟 UNC 整条漏出**（范围内阻断）：`another` 检测归一化后的 `rest`，`\\fs01` 被压成 `\fs01`，START 只认双反斜杠。`OSError: E:\law\python\x.pyd from \\fs01\案卷\张三 诉 李四.pdf` → `<安装目录>\python\x.pyd from \fs01\案卷\张三 诉 李四.pdf`。修复：对未归一化原串尾部 `p.slice(installDir.length)` 检测，补 UNC 用例。
其余刁钻输入（无引号带空格、安装目录后跟 `E:\x\材料名.docx`、UNC 带空格、分号连两条、`run.py:12 open(D:\…)`）均正确；线 A 8 条用例与断言一致。
**P3-1** `lawbench-windows-payload.spec.ts` 单独重跑输出未落盘（全量那遍第 3 例 5 秒超时）；修：存证据、加 timeout。
**P3-2** 安装中途失败 `lawbench\installer-cache` 可能残留约 750 MB（`un.CleanData` 不清）；修：`customUnInstall` 补删。
**NOTE**：`prepare-dsh` 按本机平台、electron-builder 按目标平台判断剔除，仅交叉打包时不一致（我方不交叉）；`lawbench-python-source.json` 随 python 进包无机密；注记 0934 四小项本批未做，不阻断。

### 逐项核对（均通过）
1. **P-23 三处一致**：`omitOfficeEngine = lawbenchOmitOfficeEngine(...)` 运行时清单不收引擎、自检跳过；beforePack office 列表 `[]`；`extraResources` win32 加 `!primary-runtime/**`；打包前 `rmSync(DSH_OUTPUT_ROOT)`；`verify-runtime-archive` 清单与 asar 两边都无引擎不会报缺；`runtime-payload-smoke.mjs` 不读；`smoke-runtime.ts` 只在 `lawbenchOmitPrimaryRuntime` 真时跳过 Office 输入，Mac/原版不变；`windows-asar-unpack` 两例期望翻转合理。
2. **运行期用不到 primary-runtime**：Host 入口只读 argv[2][3][5][6]；`office.ts` P-12 下 `void desktopOffice`；`git grep --cached`：`DSH_PRIMARY_RUNTIME` 只在 SDK profile 的 cordis.patch.yml；`tool-workspace-dependencies`、`skill-office` 只经 office.ts；pty/脚本用 `runtime\bin`（Electron 当 node）与 `runtime\pnpm`；`installOfficeEngineResolution` 不影响启动；`preserveSignature` 只签名构建用。
3. **严格补丁链**：`rv-A49-exp\dsh` 基座 `477b4f42…`、`autocrlf=false`，18 补丁 `git apply --index` 全成功 0 警告，157 路径（与线 A 工作区零差异未复验——禁区）。
4. **安装器缓存改道**：app-builder-lib 26.15.3 模板引用 `APP_INSTALLER_STORE_FILE` 仅 `include/installer.nsh:93` `copyFile`（先 CreateDirectory）；宏由 `-D` 给出、我方头部在模板前，`!undef` 重定义有效；拷贝在 `installApplicationFiles` 先于 `customInstall` 的 `lawbenchAfterInstall`，删除生效；新路径 `%LOCALAPPDATA%\lawbench\installer-cache\`，perMachine:false；原版 updater 目录装卸都不碰。
5. 其余：`setAppUserModelId` 经 `main.ts:62` 顶层 `applyLawbenchIsolation(app)` 在 `whenReady` 前、只装好的包、Mac `?.` 不出错、与 `$AppId` 一致有用例；lock python 行 3.12.10 sha `0eb85c2d…` 与 payload-fetch/build 一致；`gen_lock` 无来源文件退回 pbs 行；`build.ps1` python 步先删 `stage\python`；`-I` 断言在 sitecustomize 之后、`Run` 按退出码；PATCHES.md P-23 行、P-4 两行、⑤ F6 句；共用点清单 7、13 项同步。
6. 测试：dsh-ext vitest 661/6/0；tsc 0；`check_ui_words` 零命中；证据无用户名。

### 跑过的命令（摘要）
`git log/diff`；`git -c core.autocrlf=false clone --no-checkout --shared D:\lawbench-A\dsh rv-A49-exp\dsh` + `checkout 477b4f42` + 18 次 `apply --index` + 计数；`git grep --cached`；只读 app-builder-lib 模板与 NsisTarget.js；`node rv-A49-exp\scrub.mjs`；`node scripts\test.mjs`；`tsc --noEmit`；`check_ui_words.py`；证据用户名扫描。借用全拆，`rv-A49` 干净，未写 `D:\lawbench-A`。
