# 与原版 DeepSeek Harness 同机共用点清单（第四版候选包，注记 1547）

适用：`lawbench-0.1.0-win-x64-unsigned.exe` sha256 `5efaf788…eee8c9fe`，基座 `c96ae54`。"原版"指 DeepSeek Harness 官方桌面版，包名同为 `@deepseek-ai/dsh-desktop`。行号对应 `D:\lawbench-A\dsh` 工作区，即补丁全部打上后的源码。

| # | 共用点 | 原版用什么 | 我方用什么 | 是否分开 | 证据（文件:行） |
|---|---|---|---|---|---|
| 1 | Electron userData | `%APPDATA%\@deepseek-ai\dsh-desktop`（Electron 按包名） | `%APPDATA%\lawbench-desktop` | **分开** | `apps/desktop/src/lawbench-isolation.ts:27,41`；`main.ts:62` 调用，在单实例锁、`setAppLogsPath` 之前；冒烟：新目录生成数据，原版目录不生成 |
| 2 | DSH_HOME（profile、锁、storages、会话索引） | `~/.dsh`；profile `~/.dsh\profiles\desktop`，锁 `…\lock` | `%LOCALAPPDATA%\lawbench\dsh-home`，下同结构 | **分开** | `lawbench-isolation.ts:27,42`（设 `DSH_HOME`，Host 继承）；`apps/desktop/src/paths.ts:19-20`（profile、锁都在 DSH_HOME 下）；冒烟：`~\.dsh` mtime 前后不变 |
| 3 | 单实例锁 | Electron `requestSingleInstanceLock`，按 userData 区分 | 同一 API，但 userData 已分开 | **分开** | `apps/desktop/src/single-instance.ts:20`；随第 1 项 |
| 4 | Host 监听端口 | `127.0.0.1:19387`（写死） | 系统分配（`--port 0`，冒烟实测 57551） | **分开** | `apps/desktop-host/src/index.ts:35`；`lawbench-isolation.ts:46`；冒烟：先占 19387 再启动，能进主窗口 |
| 5 | 服务转发端口 18765 | 不用 | 工作台服务对 Agent 的模型转发（`127.0.0.1:18765`） | **不冲突**（原版没有这项） | `dsh-ext/cordis.patch.yml:217,359` |
| 5b | 我方其余本机端口 | 不用 | 服务端口由 Host 挑空闲端口；证件识别驱动 `127.0.0.1:17801` | **不冲突** | `dsh-ext/host/index.ts`（`freePort`）；`apps/desktop/src/lawbench-retainer.ts:23` |
| 6 | `%LOCALAPPDATA%\lawbench` | 不用 | 设置、日志、`dsh-documents`、临时 | **不冲突**（原版不碰） | `dsh-ext/cordis.patch.yml:358,383` |
| 7 | updater 缓存目录与 installer.exe | `%LOCALAPPDATA%\@deepseek-aidsh-desktop-updater\`（electron-builder 按包名） | **同名目录**：我方安装器也往里拷 `installer.exe`；装完只删与本安装包大小相同的那一份，目录空了才删；卸载不再碰这个目录 | **名字同，内容不留**（原版的文件不碰） | `apps/desktop/scripts/installer.nsh:106-133`；冒烟：装完目录不存在 |
| 8 | 安装器日志目录 | `%LOCALAPPDATA%\@deepseek-aidsh-desktop-updater\installer-logs` | `%LOCALAPPDATA%\lawbench\installer-logs` | **分开** | `installer.nsh:190` |
| 9 | 卸载清理目标 | `%APPDATA%\<产品名>`、`%APPDATA%\@deepseek-ai\dsh-desktop`、updater 缓存目录 | `%APPDATA%\连越律师工作台`、`%APPDATA%\lawbench-desktop`、`%LOCALAPPDATA%\lawbench\dsh-home`；不碰包名目录与 updater 缓存 | **分开** | `apps/desktop/installer/uninstall.nsh:12-36`；冒烟：卸载后两个新目录不在，原版目录里的 `marker.txt` 仍在 |
| 10 | 注册表卸载键 | 由原版 appId 算出的 GUID | 由 `cn.lianyue.lawbench` 算出的 GUID `2a87e7ff-697f-54c4-aa45-87f170dbea7e` | **分开** | `apps/desktop/scripts/electron-builder-config.mjs:105`（appId）；打包日志 `APP_GUID=2a87e7ff-…`；appId 由 `build.ps1` 写进 `.env.windows` |
| 11 | 安装目录 | `%LOCALAPPDATA%\Programs\DeepSeek Harness` | `%LOCALAPPDATA%\Programs\连越律师工作台` | **分开** | `installer.nsh:9-12`（`APP_FILENAME` 用产品名）；未在本机核默认目录，候用户新机 |
| 12 | 开始菜单 / 桌面快捷方式名 | DeepSeek Harness | 连越律师工作台 | **分开** | `electron-builder-config.mjs:114`（`productName`，快捷方式名默认取它）；未在本机核，候用户新机 |
| 13 | `dsh:` 协议 | `dsh:` | `dsh:`（P-4 有意没改） | **同名**：Windows 里谁后启动谁占用注册；只影响 `dsh://open` 把前台窗口唤起（`main.ts:1108`），第一版没有用到这个唤起，记后续（F6） | `electron-builder-config.mjs:106`；`main.ts:1105` `setAsDefaultProtocolClient('dsh')` |
| 13b | 应用内协议 `dsh-app:` | 进程内注册 | 进程内注册 | **不冲突**（Electron 自定义协议只在本进程内） | `apps/desktop/src/ipc.ts:86` |
| 14 | 凭据管理器条目 | 原版不用凭据管理器（DSH 源码里没有 CredWrite、keytar、safeStorage） | `lawbench/LAWFIRM_KEY` | **不冲突** | `dsh-ext/credentials/credman.ts:8` |
| 15 | `%TEMP%` 固定名文件 | 没有固定名：DSH 运行时都用 `mkdtemp` 随机后缀（`dsh-subprocess-*`、`dsh-subprocess-launch-*`、`dsh-shell-*`、`dsh-open-in-app-*`） | 同一套代码，也是随机后缀；我方自己的临时文件在 `%LOCALAPPDATA%\lawbench\临时\` 下 | **不冲突** | `packages/subprocess/subprocess-local/src/output.ts:43`、`runner-protocol.ts:104`、`shell-activity.ts:66`；`packages/host/open-in-app/src/icons.ts:67,105`；`dsh-ext/host/index.ts`（`pasteDir`） |
| 16 | 命名管道 | DSH 源码里没有 `\\.\pipe\` 固定名管道；主进程与 Host、子进程之间用 Node 的 `ipc` / `pipe` 标准输入输出，是匿名管道 | 同 | **不冲突** | 全仓 grep `\\.\pipe` 零命中（`packages`、`apps`、`dsh-ext`、`service/lawbench`）；`apps/desktop/src/host-process.ts:200`（`stdio: [... 'ipc']`） |

## 结论

只剩 `dsh:` 协议同名（第 13 项），影响仅限 `dsh://open` 前台唤起，第一版不用，记后续 F6。其余各项都分开或本来不冲突。第一、二版留下的旧目录（`~/.dsh\profiles\desktop`、`%APPDATA%\@deepseek-ai\dsh-desktop` 下我方以前的数据）归 F5，写进操作说明。

**未在本机核**：第 11、12 项默认目录名和快捷方式名；与**真的**原版 DSH 同时开（本机没装原版，端口、目录分开已用模拟核过）。
