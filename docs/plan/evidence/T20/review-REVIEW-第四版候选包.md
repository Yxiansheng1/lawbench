# T20 隔离修法关闭 + 第四版候选包 · 独立复核记录（PASS）

- 复核时刻：2026-10-05 16:20–16:35 (+08:00)；复核员：一名 Opus 只读复核员（克隆 `D:\lawbench-rv\rv-A46`，实验目录 `rv-A46-exp`）
- target：line-A `c96ae54`（F1 Host `--port 0`、F2 卸载清理目标、installer.exe 只删本次、安装器日志目录、F3 用例、F4 交付说明）、`c50bd12`（第四版包证据 + 《与原版 DSH 同机共用点清单》16 项）；基座 `fd3f897`
- 第四版包：780000161 B，sha256 `5efaf7882f726e593490df52ac5768da42ffb09855c1b21c216b6998eee8c9fe`（复核员与主编排各算一致；不入库）。**用户口径：一版给所有机器，不分装没装过原版 DSH。**
- 裁决（主编排）：**PASS**，line-A 整条合并进 main。P3-1 与 NOTE-2/3 记下一轮小修（随下一次打包，不单独发版）；F5（第一/二版旧目录残留）由主编排写进操作说明。

## 复核员报告（原文，路径已去用户名）

**结论：PASS。** F1–F4 已关闭；《共用点清单》16 项逐项核对成立；清单外另查 7 处无阻断。一条 P3、三条 NOTE 均独立后续。

### 一、目标与补丁链
c50bd12 → c96ae54 → fd3f897 属实；相对基座改 7 文件。DSH 基座 `477b4f42…`；`rv-A46-exp\dsh` read-tree 后 16 个补丁 `git apply --cached` 16/16，151 路径。

### 二、冻结清单逐条关闭
**F1 端口：已关闭。** `lawbench-isolation.ts:46` 装好的包设 `env.LAWBENCH_HOST_PORT='0'`，在 `main.ts:62` 执行，先于 `setAppLogsPath`（84）、`DesktopFatalRecovery`（94）、`claimDesktopSingleInstance`（1212）；`DesktopHostProcess` 默认取 `process.env`、`desktopNodeEnvironment` 原样展开；`desktop-host/src/index.ts:35` `'--port', process.env.LAWBENCH_HOST_PORT ?? '19387'`，上游 `web-app/startup.ts:53` 支持 `--port 0`；`webserver/index.ts:298` 取实际端口，Host `index.ts:106` 拼就绪 URL，主进程 `main.ts:406` 存 `hostUrl`；`lawbenchRequestAllowed` 按 `hostUrl` host:port 精确放行（`main.ts:619`），ws 过滤器 `ws://127.0.0.1/*` + host 比对不依赖 19387；上游 `main.ts:458` 已按"新 Host 可能换端口"处理。`19387` 全部命中只剩开发期回退、注释、测试替身、上游文档；CSP 为 `connect-src 'none'`；lawbench 仓库 dsh-ext/service/脚本零命中；Python 服务 `net.py` 只看 Origin。包内 asar：`process.env.LAWBENCH_HOST_PORT ?? "19387"`、`env.LAWBENCH_HOST_PORT = "0"` 在，`'--port', '19387'` 零命中。

**F2 卸载与安装后清理：已关闭。** `uninstall.nsh:26/33/35` 清 `$APPDATA\${PRODUCT_FILENAME}`（连越律师工作台）、`$APPDATA\lawbench-desktop`、`$LOCALAPPDATA\lawbench\dsh-home`；`APP_PACKAGE_NAME` 目录、`UninstallRemoveEmptyParents`、更新缓存目录删除已全部去掉；保留 `${isUpdated}`、`/KEEP_APP_DATA` 提前返回（升级不清数据）。`installer.nsh:106-136` 两边 `FileSeek END` 取大小（缓存 installer.exe 与 `$EXEPATH`），打不开初值 -1/-2 不相等不删；`RMDir` 不带 `/r` 空了才删；`DSH_INSTALLER_LOG_DIR` 改 `$LOCALAPPDATA\lawbench\installer-logs`（190 行）。

**F3 用例：已关闭。** `rv-A46-exp\iso\harness.mjs` 变异：`//` 注释、删调用、挪到 setAppLogsPath 后/锁后/`main()` 内、`if (false)` 单行、端口改回写死——均抓到；原文件与 CRLF 版通过。

**F4：已关闭。** `needsWelcome` 只看 `!configured`（`dsh-ext/host/index.ts:346`：settings.json 存在且凭据管理器有 Key），设置文件未搬，"升级后不会再出首次配置页"与代码一致。

### 三、《共用点清单》16 项
文件:行全部属实。第 10 项卸载键 GUID 用 electron-builder 命名空间对 `cn.lianyue.lawbench` 算 UUID v5 得 `2a87e7ff-697f-54c4-aa45-87f170dbea7e` 一致；第 16 项 `\\.\pipe` 两仓零命中。第 7 项措辞不准见 P3-1。

### 四、清单外自查（无用户可见冲突）
sessionData 随 userData（隔离在 ready 前）；`setAppLogsPath()` 无参落 `<userData>\logs`；无 `crashReporter.start`；`setLoginItemSettings`、`globalShortcut` 零命中；`new Tray` 不传 GUID、exe 路径不同；包无 `app-update.yml`，`update-coordinator.ts:53` 不启用更新器；安装器按 `$INSTDIR\<exe>` 全路径判进程；未调 `setAppUserModelId`，快捷方式 AUMID 为 appId（模板 `SetLnkAUMI ${APP_ID}`）两边不同。

### 五、包核
780000161 B、sha256 一致；asar 内 `LAWBENCH_HOST_PORT` 2、`lawbench-desktop` 1、`installer-logs` 0（在 NSIS 脚本不在 asar，正常）；package.json `dshDesktopAppId` = `cn.lianyue.lawbench`。NSIS 脚本无法提取（本机 7za x86 不支持 nsis），卸载行为以 build.txt 冒烟记录为准。证据无用户名。冒烟截图 Key 显示"已保存"佐证 19387 被占时 Host 已起。

### Findings
- **P3-1 清单第 7 项"原版的文件不碰"不准确**（独立后续）：模板 `include/installer.nsh:93` 无条件 `copyFile "$EXEPATH" "$LOCALAPPDATA\${APP_INSTALLER_STORE_FILE}"` 且在 `customInstall` 之前，原版缓存的 installer.exe 先被我方覆盖、随后大小相等被删。影响：原版下次升级拿不到差分基准退回整包下载，不丢数据。最小修复：`installer.nsh` 顶部 `!ifdef APP_INSTALLER_STORE_FILE / !undef`，让模板不复制，大小比对块可删；或改清单措辞。
- **NOTE-1** F3 正则只认 `//` 注释，块注释/上一行 `if (false)` 抓不到（故意规避，不必再修）。
- **NOTE-2** 系统通知默认 ID 两边相同（推断 `electron.app.@deepseek-ai/dsh-desktop`）；第一版唯一发通知的更新提醒未启用，眼下无可见影响；可在隔离函数加 `app.setAppUserModelId('cn.lianyue.lawbench')`。
- **NOTE-3** 补进 F6：卸载器不删 `HKCU\Software\Classes\dsh`，若最后注册的是我方，卸载后 `dsh://` 指向已删 exe 直到原版下次启动重注册。

### 跑过的命令（摘要）
`git log/diff`（rv-A46）；`git -C D:\lawbench-A\dsh log -1`（只读）；`git clone --no-checkout --shared … rv-A46-exp\dsh` + `read-tree` + 16 次 `apply --cached` + `diff --cached --name-only`（151）；`git grep --cached` 19387/--port/.port/lawbenchRequestAllowed/LAWBENCH_HOST_PORT/setAppUserModelId/setLoginItemSettings/globalShortcut/crashReporter/setPath(/tmpdir()/\\.\pipe/connect-src/displayBalloon/new Tray(/customCheckAppRunning；只读看 app-builder-lib 26.15.3 NSIS 模板与 electron 44 exe 字串；`node rv-A46-exp\iso\harness.mjs`、`node --experimental-strip-types rv-A46-exp\iso\unit.mts`、node 算 UUID v5；`Get-FileHash`；7za 列包/解 asar；`7za l -tnsis` 失败。
