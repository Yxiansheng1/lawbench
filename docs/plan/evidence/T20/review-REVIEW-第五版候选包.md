# T20 第五版候选包（重打）· 独立复核记录（AMEND）

- 复核时刻：2026-10-07 17:50–18:25 (+08:00)；复核员：一名 Opus 只读复核员（克隆 `D:\lawbench-rv\rv-A50`，实验目录 `rv-A50-exp`）
- target：line-A `7352223`、`f291e9d`、`501baa4`、`2c19a71`、`193a62d`（含 c6d7fc4），基座 `2234f10`；21 文件 +350/-27
- 包：`lawbench-0.1.0-win-x64-unsigned.exe` 655923866 B，sha256 `3c87508eb19089fd3a1952b70c9a4e6123f85acaa16acf417b95cd88ac856300`（复核员与主编排一致；不入库；**作废**，第六版重打）
- 裁决（主编排）：**AMEND**。上轮冻结四条全关、包核全过；本轮新加的"端口被占原因链"P2 一条 + 首次配置页轮询覆盖输入 P3 一条须修后重打；令 `致A-ORCH-执行令-第五版复核AMEND-端口判定与首配页-<HHMM>.md`。

## 复核员报告（原文，路径已去用户名）

**Verdict：AMEND。** 冻结四条关闭，包核与补丁链全过；打回新加的"端口被占原因链"：依赖的重启窗口判定在机器稍慢时永远判不出 failed，线 A 本机实测正卡在临界值附近。

### 冻结清单关闭（全部）
- P2-1/P2-2 scrubPaths：`rv-A50-exp\scrub.mjs` 上轮 3+1 条全 `<路径>`；新增日期/版本号文件夹、`;` 接 UNC、repr 双反斜杠 UNC、`v1.2 钱七 起诉状`、`合同v1.2 …`、`.tar.gz`、路径后中文标点均对；安装目录用例仍 `<安装目录>\python\DLLs\_sqlite3.pyd`。
- P3-2：`customUnInstall` 有 `Delete "$LOCALAPPDATA\${APP_INSTALLER_STORE_FILE}"` 与 `RMDir lawbench\installer-cache`（补丁后 114–115 行）。
- P3-1：payload 用例 `30_000` 超时；`evidence\T20\1337\desktop-单独重跑.txt` 12 files / 99 passed。

### Findings
**P2-1 端口被占时机器稍慢永远到不了 failed，原因显示不出来**（范围内阻断）：Host 先换端口重试 6 次（退出码均 2）再走通用重启；通用重启要求最近 3 次落在 60 秒窗内才 failed → 一轮 6 次拉起须在 20 秒内（每次 ≤ 约 3.33 秒），超过则记录滑出窗口、每 3 秒拉起一次无限循环；首次配置页 5 分钟后停在"未启动"，首页一直"未启动"。线 A 冒烟 78 秒/24 次 ≈ 3.25 秒，离临界 0.08 秒；律所机器装杀毒/冷启动易超。证据 `supervisor.ts onExit` `MAX_PORT_RETRIES=5`、`RESTART_WINDOW_MS=60_000`、`MAX_RESTARTS_IN_WINDOW=3`；假时钟实验 `rv-A50-exp\sv\restart-window.spec.ts`：D=3000/3250 ms → 24 次 72/78 秒进 failed；D=3400/4000 ms → 41/42 次仍不 failed。修复：退出码 2 且 `portRetries >= MAX_PORT_RETRIES` 时直接 `setState('failed')`，约 20 秒给出原因，首页 30 秒重读可直接显示；补用例（每次拉起 4 秒能进 failed）。

**P3-1 首次配置页轮询成功时覆盖律师已填内容**（引入的回归）：首次读失败后 `setLoading(false)` 可填写，之后轮询成功 `setFields` 覆盖四个地址与律师姓名（写成 `''`）并 `setError('')` 清掉校验提示；Key 不受影响。证据 P-23 `WelcomePage.tsx` `load()`（补丁后 66–72 行，输入框只看 `disabled={loading}`）。修复：轮询期间保持 `loading` 直到成功或拿到原因；或只填用户没动过的字段。

**P3-2** PATCHES.md 第 241 行证据路径 `T20[7\desktop-单独重跑.txt` 应为 `T20\1337\`。

**NOTE**：退出码 2 只在 `__main__.py` 监听绑定失败返回（`EXIT_LISTEN_FAILED`）；模块缺失/`create_app` 异常为 1；argparse 退 2 但参数由 Host 拼不会误判；转发端口落在 Windows 保留段（WinError 10013）时"被占用"说法不准（推测，不阻断）。原因字符串无路径（端口句不含路径；其他仍走 `lastErrorLine(…, scrubPaths)`；只给界面不进日志）。darwin 无平台分支，两边一致。首页偏离若修 P2-1 自动消失。首次配置页最多 100 次（约 5 分钟）后停、无手动重读按钮需重开程序；首页 `useRetryLoad` 有上限。

### 包核（全过）
大小/哈希一致；`primary-runtime` 零条、无 libreoffice-kit（仅两个 `koffi.node` 约 1 MB）；`sitecustomize.py`、`THIRD-PARTY-LICENSES.md`、pandoc `COPYING.rtf`/`COPYRIGHT.txt` 在；`python.exe` Authenticode Valid（PSF）；`skills\manifest.json` source 相对；机密扫描（10437 文本 + asar，317 MB）`\19705\` 零命中、`19705` 命中均数字巧合、`sk-` 零命中；NSIS 脚本无法从包提取，改核补丁后 `installer.nsh`：`installer-cache` 重定向（15–19 行）、`lawbenchAfterInstall` 第 267 行调用、无删 `@deepseek-aidsh-desktop-updater` 语句（188 行保留）。

### 其余
补丁链 `477b4f4205` 严格 18 个全成功零警告 158 文件，`diff --check` 0；dsh-ext vitest 664/6；tsc 0；`check_ui_words` 零命中；3 张新截图无用户名。

### 跑过的命令（摘要）
`git log/diff 2234f10..193a62d`；`node rv-A50-exp\scrub.mjs`；`rv-A50-exp\sv` 假时钟 vitest；共享克隆 + `autocrlf=false` + 18 次 apply；`node scripts\test.mjs` + `tsc`（dsh 联接只读、node_modules robocopy、pnpm 顶层联接改指克隆内 `.pnpm`）；`check_ui_words.py`；7za `l`/`x` 文本类 + `Get-FileHash` + `Get-AuthenticodeSignature` + Grep。借用已拆，`rv-A50` 干净；一条读整包进管道的命令超时已停、无写入。
