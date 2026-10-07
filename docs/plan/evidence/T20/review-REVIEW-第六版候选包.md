# T20 第六版候选包 · 独立复核记录（PASS）

- 复核时刻：2026-10-07 18:45–19:05 (+08:00)；复核员：一名 Opus 只读复核员（克隆 `D:\lawbench-rv\rv-A51`，实验目录 `rv-A51-exp`）
- target：line-A `0d8ce47`（端口重试用满直接 failed；首次配置页重读期间不可填；PATCHES 路径）、`6ee6f40`（第六版包证据）；基座 `193a62d`
- 包：`lawbench-0.1.0-win-x64-unsigned.exe` 655925037 B，sha256 `058648538564055428f63bb43c055360c20542cdbb7af5c298966ba388f298b4`（复核员与主编排一致；不入库）。**第六版 = 律所第二批试用版（覆盖第四版）。**
- 裁决（主编排）：**PASS**，line-A 整条合并进 main。NOTE 两条记下轮小修（注记 0934 四小项同批）。

## 复核员报告（原文，路径已去用户名）

**PASS。** 上轮冻结 P2-1、P3-1、P3-2 已关闭；包核、补丁链、dsh-ext 测试、tsc 全过；无新阻断、无新回归。`193a62d..6ee6f40` 10 文件（代码 6），范围未超令。

### 冻结清单关闭
- **P2-1 已关闭**：`onExit` 退出码 2 且 `portRetries < MAX_PORT_RETRIES` 仍换端口重试，用满后 `setState('failed')` 并 return。假时钟实验 `rv-A51-exp\sv\real.spec.ts`：每次拉起 3.0/3.4/4.0/8.0 秒均在第 6 次后 failed，`lastFailure.port=18765`，`start_failed` 只记一条，假时间 18/20.4/24/48 秒；退出码 1 仍走原窗口逻辑（4 秒/次 4 次后 failed；25 秒/次不 failed，与原一致）。变异（去掉新分支）：4 秒用例拉起 31 次仍不 failed 变红，3.4/8 秒同样变红。
- **P3-1 已关闭**：P-23 `WelcomePage.tsx load()` 读不到设置保持 `loading=true` 3 秒再读；读到原因或满 100 次才 `setLoading(false)` 直接 return 不 `setFields`，到期不会空值覆盖；所有输入框与两按钮 `disabled={loading}`（129–146 行）；两条新用例成立。
- **P3-2 已关闭**：PATCHES.md 无 `T20[7`，`T20\1337\desktop-单独重跑.txt` 存在。

### 包核
大小/哈希一致；`primary-runtime` 零条；`libreoffice-kit` 仅 `app.asar.unpacked` 下 koffi 6 条（同上轮）；`app.asar` 127315578 B（上轮 127315496 B）哈希不同，编译产物含 `if (code === EXIT_PORT_IN_USE) { if (portRetries < MAX_PORT_RETRIES) {…} this.setState("failed"); return; }` 与首配页 `++A<100){Q=setTimeout(he,3e3);return}_e(!1);return}` 新逻辑；`\<用户名>\` 零命中；Key 形态（`sk-` 后 20+ 位）零命中（纯 `sk-` 362 处为 desk-/task- 等普通词）；2 张新截图无用户名。

### 测试
dsh-ext vitest 52 files 665/0/6；tsc 0；补丁链 `477b4f4205` 起 `git apply --whitespace=error-all` 18 个全成功零输出，158 文件，`diff --check` 0。

### Findings
- **NOTE 1（独立后续）**："最多读 100 次"用例只断言次数，未断言到期后表单放开、字段仍空；加一句 `#lawyer` 不再 disabled。
- **NOTE 2（独立后续，旧问题）**：`getSetup()` 若直接抛错（promise 被拒）无 catch，表单一直不可填；基座亦无 catch；前提 `welcome-api` 总返回 `{ok:false}` 未核实。

### 跑过的命令（摘要）
`git log/diff 193a62d..6ee6f40`；`rv-A51-exp\sv` 真版与变异版 vitest；robocopy node_modules（顶层 3 个与 `.pnpm` 内 5 个联接改指克隆内）+ `rv-A51\dsh` 只读联接；`node scripts\test.mjs`、`tsc --noEmit`；`git clone --shared rv-A50-exp\dsh → rv-A51-exp\dsh`、`autocrlf=false`、检出 `477b4f4`、18 补丁严格打；`Get-FileHash`、7za `l -slt`、解 `resources\app.asar` 字串比对（pkg 已删）。借用已拆，`rv-A51` 干净。约 20 分钟。
