# T20 与原版 DeepSeek Harness 隔离 + 第三版候选包 · 独立复核记录（AMEND）

- 复核时刻：2026-10-05 15:28–15:38 (+08:00)；复核员：一名 Opus 只读复核员（克隆 `D:\lawbench-rv\rv-A45`，实验目录 `rv-A45-exp`）
- target：line-A `fcfcc9e`（P-4 新 `lawbench-isolation.ts`：装好的包在单实例锁前把 userData 改 `%APPDATA%\lawbench-desktop`、`DSH_HOME` 改 `%LOCALAPPDATA%\lawbench\dsh-home`）、`fd3f897`（第三版包证据）；基座 `ef1cdc8`
- 第三版包：780000339 B，sha256 `fbb093f3e73c4ed53ea203368c4ea64a1746169d2c3a2e2a70423ea96d3b1628`（复核员与主编排各算一致；不入库）
- 起因：律师电脑已装原版 DSH；线 A 回执 1452 判三处同名（userData、`~/.dsh` profile 与锁、单实例锁）不能共存。
- 裁决（主编排）：**AMEND**。F1/F2 必修，F3/F4 同轮，F5/F6 记后续；令 `致A-ORCH-执行令-隔离复核AMEND-端口与卸载-20261005-1539.md`。第三版包**不发给装过原版 DSH 的机器**；未装 DSH 的机器可用。

## 复核员报告（原文，路径已去用户名）

**结论：AMEND。** 改 userData 和 DSH_HOME 的时机对、修法进了包；但同机装原版 DSH 时还有两处共用点会让一方起不来或删掉对方数据（F1、F2），线 A 的三处冲突分析未覆盖。

### 核实过的
- 目标与补丁链：HEAD fd3f897，父 fcfcc9e，基座 ef1cdc8；DSH 基座 `477b4f4`（0.1.7-rc.2）；16 个补丁 `git apply --cached` 0 失败，150 路径。
- **userData 改得够早**：打补丁后 `apps/desktop/src` 读 userData/logs 只有 main.ts 四处（109、303、589、897 行）均在函数内；`requestSingleInstanceLock` 只在 `claimDesktopSingleInstance`（main.ts:1212，模块顶层末尾）；`setAsDefaultProtocolClient` 1105 行；被 import 的模块顶层不读路径；electron-updater 6.8.9 用到时才创建。包内主进程产物顺序：`applyLawbenchIsolation(app)`（偏移 116067472）< `app.setAppLogsPath()` < `new DesktopFatalRecovery` < `getPath("logs"/"userData")` < 单实例锁（116114379）。
- **DSH_HOME 设得够早**：`resolveDshHome()` 调用时才读 env，无模块顶层求值；Host 子进程 env 由 `desktopNodeEnvironment` 展开 `process.env`（node-environment.ts:12）继承；机器上已有全局 `DSH_HOME` 也被覆盖（脚本 case1b）。
- **开发期不受影响**：`isPackaged` 开发期 false、包内 true；`development-app.ts` 改名 exe 仅 macOS；打包目标只有 nsis。
- **Key 不在旧目录**：Key 存 Windows 凭据管理器 `lawbench/LAWFIRM_KEY`（我方凭据插件替换 credentials-local；`service/lawbench/app.py:33` keyring 读）。
- `%LOCALAPPDATA%\lawbench` 只有我方用（`dsh-ext/cordis.patch.yml:358`、retainer）。
- 包核：哈希一致；app.asar 内 `lawbench-desktop` 1 处、`dsh-home`、`applyLawbenchIsolation` 2 处；无 `app-update.yml`；`python-signatures.txt` 仅首行时间戳变化；证据无用户名。appId `cn.lianyue.lawbench`；Skill 读取 `includeDefaultRoots:false` 不读 `~/.agents`。

### Findings
**F1 P1｜范围内阻断：两边 Host 都固定监听 127.0.0.1:19387，不能同时运行**
- `apps/desktop-host/src/index.ts:33` 写死 `['--no-open','--port','19387']`，cordis.patch.yml 未覆盖；webserver EADDRINUSE 直接启动失败（webserver README:55；DSH `fatal-recovery.spec.ts:37`）。
- 影响：锁分开后两程序能同时启动，后起者 Host 端口被占弹致命错误；两边关窗都留托盘，"另一个还开着"很常见。令 1444 的"直接起不来"只是从锁换成端口。线 A 冒烟"与原版同开"未核。
- 最小修复：装好的包 Host 用 `--port 0` 或专用端口（`lawbench-request-policy` 按 `ctx.webServer.port` 放行，不依赖 19387）。冒烟：node 先占 127.0.0.1:19387 再启动我方，须进主窗口。

**F2 P1｜引入的回归：卸载程序仍清理原版目录，却不清理我方新目录**
- `apps/desktop/installer/uninstall.nsh` `un.CleanData`（`installer.nsh:98-99` customUnInstall 调用，补丁未改）删 `$APPDATA\${APP_PACKAGE_NAME}`（= `%APPDATA%\@deepseek-ai\dsh-desktop`）与 `$LOCALAPPDATA\${DSH_UPDATER_CACHE_NAME}`；`lawbenchAfterInstall` 删同目录 `installer.exe`；`DSH_INSTALLER_LOG_DIR` 也写那里。
- 影响：卸载我方会清原版 DSH 的用户数据（登录态、设置、日志）与更新缓存，违反令 1444"不动原版任何目录"；我方 `%APPDATA%\lawbench-desktop`（含 `Partitions/retainer`，可能有委托人姓名证件）与 `dsh-home` 卸载后留着——比第二版退步。
- 最小修复：卸载清理改为 `$APPDATA\lawbench-desktop`，不删 `APP_PACKAGE_NAME` 与 updater 缓存目录；dsh-home 是否清理、installer.exe 是否只删本次写的，交主编排定。

**F3 P3｜测试缺口：用例 3 只比字符串位置**（`rv-A45-exp\iso\harness.ts` 变异）：挪到锁后/挪进 `main()` 抓到；注释掉调用、挪到 `app.setAppLogsPath()` 之后抓不到。修法：行首正则匹配未注释语句 + `apply < indexOf('app.setAppLogsPath()')`。

**F4 P3｜交付说明"升级后视为首次启动、重填首次配置"可能写错**：首次配置页条件是 settings.json 有 Key（P-3 第 665、718 行），settings.json 在 `%LOCALAPPDATA%\lawbench` 未搬、Key 在凭据管理器 → 升级后不会再出首次配置页，只是 profile 在新位置重建；"旧目录留着不动"与 F2 矛盾。未实装，按代码判定。

**F5 P3｜独立后续：第一/二版旧目录残留**：Key 不泄漏；`~/.dsh/profiles/desktop` 带 lawbench-dsh（以后装原版仍加载我方组合包）、`~/.dsh/storages` 有案件文件夹路径、`%APPDATA%\@deepseek-ai\dsh-desktop\Partitions\retainer` 可能有委托人信息，第三版"清除本机记忆"够不着。只影响装过第一/二版的机器。修法：操作说明写手动清理或一次性检测。

**F6 P3｜独立后续：`dsh:` 协议**：安装改写原版注册、卸载删 `dsh` 注册；运行时每次 `setAsDefaultProtocolClient('dsh')` 谁后起谁占；当前只有 `dsh://open` 带窗口到前台，影响小。

**NOTE**：无 APPDATA/LOCALAPPDATA 的环境启动时隔离悄悄跳过，可记一行日志；desktop/desktop-host 不用 tmpdir，Host 与主进程走 Node IPC；服务转发端口 18765 只我方用。

### 没跑的
DSH 包内 vitest（需检出整个工作区并借线 A node_modules，缓存会写进只读借用目录）——改用 node 去类型方式跑等价断言 + 变异；两提交未改 dsh-ext，故 test.mjs/tsc 未跑。

### 跑过的命令（摘要）
`git log/show/diff`（rv-A45）；`git -C D:\lawbench-A\dsh log -1`（只读）；`git clone --no-checkout --shared … rv-A45-exp\dsh` + `read-tree 477b4f4` + 16 次 `apply --cached` + `diff --cached --name-only`（150）；`git grep --cached` getPath/requestSingleInstanceLock/setAsDefaultProtocolClient/DSH_HOME/19387/tmpdir/uninstall；读 electron-updater、app-builder-lib 源码（只读）；`Get-FileHash`；`7za l/e … resources\app.asar` 到 `rv-A45-exp\pkg` 并搜字串与偏移；`node --experimental-strip-types rv-A45-exp\iso\harness.ts`。
