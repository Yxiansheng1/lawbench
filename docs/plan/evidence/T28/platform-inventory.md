# T28 平台盘点：Windows 专属点 → macOS（Apple 芯片）方案

> 线 D · 2026-10-06 · 基座 main `27b1f78`。依据：执行令 `致D-ORCH-执行令-T28开工与平台盘点-20261006-1412`、注记 `…能复用就复用-20261006-1414`。
> 只读盘点，未改任何代码。DSH 部分只读看了 `D:\lawbench-A\dsh`（提交 477b4f4 + 已打补丁）。
> "复用/新写"列：**复用** = 现有代码原样或只加平台参数；**分支** = 现有函数里加一个 `darwin` 分支，Windows 路径字节不变；**新写** = 现在没有。

## 0. 结论

1. **DSH 本身已支持 macOS arm64**：`dsh\scripts\primary-runtime\lock.json` 已有 `mac-arm64` 目标（python-build-standalone `aarch64-apple-darwin`，sha256 `81a359f1…4b2b`；node `darwin-arm64.tar.gz`），`electron-builder-config.mjs` 已有 `mac`（dmg+zip、hardenedRuntime、notarize）。我方只需让它**在没有签名环境变量时也能出 ad-hoc 包**（现在 `resolveMacOSSigningEnvironment` 缺变量直接抛错），改在 P-4。
2. 我方代码的平台差异集中在 **约 12 个文件**，绝大多数是"加一个 darwin 分支 / 把写死的 `.exe`、`;`、`resources\` 换成平台参数"。真正新写的只有：**钥匙串读写**、**`packaging\mac\build.sh`**、**两个工作流**、**进程收尾的 posix 版（进程组）**。
3. **发票整理在 Mac 上跑不起来**：引擎 `engines\invoice-ledger\scripts\runtime_cache.py:163` 写死"仅支持 Windows AMD64"，自带运行时是 `vendor\env-win_amd64.zip`。不改 `engines\` 就没法用 → 候主编排 / 律所（第 5 节第 1 条）。
4. 证件识别驱动（retainer）是 Python + RapidOCR + onnxruntime，**跨平台可用**；只是"结束驱动"那段用 `netstat`/PowerShell，要加 Mac 分支。
5. Word/WPS COM 在 Mac 上没有：Mac 一律走内置 LibreOffice（已有完整路径），不做 Word for Mac 的 AppleScript。

## 1. 逐项盘点

| # | Windows 专属点（现位置） | 复用/新写 | macOS 方案 | 改在哪 | Windows 侧影响 | 用例 |
|---|---|---|---|---|---|---|
| 1 | **Word/WPS 转 PDF 走 COM**：`office\convert.py` 的 `_com`/`processes()`（`ctypes.windll` Toolhelp32 快照）/`_kill_pid`（taskkill）；`office\com_worker.py`（pywin32） | 分支 | `sys.platform=='darwin'`：`to_pdf` 的顺序只剩 `libreoffice`；设置里显式选 word/wps 时直接 `_Failed("not_installed")`，**不调用** `processes()`；`from ctypes import wintypes` 挪进函数内或加守卫（Mac 上导入是否报错首跑核实，守卫了就无所谓） | `service\lawbench\office\convert.py` | 不变（分支外字节不动） | monkeypatch `sys.platform='darwin'`：auto→只调 LO；choice=word→CONVERTER_UNAVAILABLE 且未调 processes；导入模块不触发 windll |
| 2 | **旧格式（.doc/.xls）转换**：`ingest\libreoffice.py` 的 `CANDIDATES`（`C:\Program Files\…\soffice.exe`）、`CRASH_EXIT_CODES`、`_long()` | 复用 + 分支 | 查找顺序不变（`LAWBENCH_SOFFICE` → PATH → 默认位置）；darwin 默认位置加 `/Applications/LibreOffice.app/Contents/MacOS/soffice`；打包后 Host 传 `LAWBENCH_SOFFICE`，用不到默认位置。`-env:UserInstallation`、外链拦截、超时杀树原样。配置目录路径约 60 字符，低于 100 上限 | `ingest\libreoffice.py`（CANDIDATES 按平台） | 不变 | darwin 下 CANDIDATES 含 .app 路径、不含 `C:\` |
| 3 | **兼容模式导出**：`export\compat.py`（只改 docx 里的 settings.xml） | 复用 | 纯 XML，无平台差异 | — | — | 已有用例在 Mac 跑即可 |
| 4 | **pandoc 查找**：`export\pandoc.py:find_pandoc`（`%LOCALAPPDATA%\Pandoc\pandoc.exe`、`ProgramFiles`）；`CREATE_NO_WINDOW` | 复用 + 分支 | `LAWBENCH_PANDOC` 优先（打包后 Host 传）；darwin 默认位置加 `/opt/homebrew/bin/pandoc`、`/usr/local/bin/pandoc`；`getattr(subprocess,"CREATE_NO_WINDOW",0)` 在 Mac 上本来就是 0 | `export\pandoc.py` | 不变 | darwin 候选；env 优先用例已有（test_export 复用） |
| 5 | **进程树收尾**：`procs.kill_tree` 非 nt 只 `proc.kill()`（只杀直接子进程）；`office\convert._kill_pid` | 分支（小新写） | darwin：起子进程时 `start_new_session=True`，收尾 `os.killpg(pgid, SIGKILL)`；三处调用方（LO、发票、证件驱动）加 `start_new_session` 参数（Windows 不传，行为不变） | `procs.py`、`ingest\libreoffice.py`、`retainer\driver.py` | 不变 | 假 soffice 脚本再起孙进程，darwin/posix 下收尾后孙进程不在（这条只能在 Actions 的 Mac 上真跑；Windows 上 monkeypatch 只验调用参数） |
| 6 | **证件识别驱动**：`retainer\driver.py` 的 `_listener_pid`（`netstat -ano`）、`_is_our_driver`（PowerShell `Get-CimInstance`）、`PASS_ENV`（SYSTEMROOT…） | 分支 | darwin：`lsof -nP -iTCP:17801 -sTCP:LISTEN -t` 取 pid，`ps -o command= -p <pid>` 取命令行（比较同样按完整路径）；`PASS_ENV` 加 `HOME`、`TMPDIR`、`LANG`。驱动本身（rapidocr + onnxruntime）有 macOS arm64 轮子，模型 sha256 核对原样 | `retainer\driver.py` | 不变 | monkeypatch 平台 + 假 `subprocess.run` 输出，验解析 |
| 7 | **发票引擎**：`engines\invoice-ledger` 自带 `env-win_amd64.zip`，`runtime_cache.ensure_runtime` 非 Windows 直接抛错；`invoice\runner.py` 的 `PASS_ENV` | **做不了**（要改 engines） | 第一阶段建议：Mac 上发票整理入口显示"Mac 版暂不支持发票整理"，服务端 darwin 下直接返回 ENGINE_FAILED/对应码，不起引擎。要支持需律所出 Mac 环境包或允许改引擎 | `invoice\runner.py`（守卫）；界面文案 | 不变 | darwin 下不起子进程、返回固定错误 |
| 8 | **云同步目录检测**：`case\gate.py` 读注册表 OneDrive、`SYNC_ENV_VARS` | 复用 + 分支 | `winreg` 已是惰性导入、ImportError 返回空，Mac 上自然跳过。darwin 加：`~/Library/Mobile Documents`（iCloud 云盘）、`~/Library/CloudStorage`（Mac 版 OneDrive/Dropbox/Google Drive 都在这里）两个根；`SYNC_NAME_MARKERS` 加 `Mobile Documents`、`CloudStorage`。**另见第 5 节第 5 条（"桌面与文稿"iCloud 同步）** | `case\gate.py` | Windows 走注册表不变；markers 列表多两项对 Windows 无实际影响（Windows 路径里不会出现），如要求字节不变就只在 darwin 追加 | darwin 下 `~/Library/CloudStorage/OneDrive-x/案` 判为同步目录 |
| 9 | **路径大小写**：`gate._norm` 用 `normcase`（posix 下不折叠）；P-15 / P-9 `lawbenchPathInside` 只在 win32 折叠 | 复用（建议不改） | APFS 默认不区分大小写。不折叠的后果只会是"同一目录换个大小写写法被拒"（偏严，不会放行越界）。建议保持，加用例锁住"大小写不同→拒绝" | — | — | darwin 用例：大小写不同的根→拒 |
| 10 | **文件名长度**：`materials._too_long` 非 nt 返回 False；`gate.MAX_COMPONENT=255`（按字符） | 分支 | macOS 单级文件名上限 **255 字节（UTF-8）**，一个汉字 3 字节 ≈ 85 个汉字。darwin 下按 `len(name.encode())>255` 拒绝，给同样的"文件名太长"提示 | `case\materials.py` / `case\gate.py` | 不变 | 90 个汉字的文件名 darwin 下被拒 |
| 11 | **应用数据目录**：服务 `config._default_appdata`（APPDATA）；dsh-ext `shared\file-log.ts`、`agent\index.ts`、`session-store`、`cordis.patch.yml` 的 `appData`/`documentsDirectory`（`LOCALAPPDATA ?? homedir()`） | 分支 | Mac 上 `LOCALAPPDATA` 不存在 → 会落到 **`~/lawbench`（家目录里的可见文件夹）**。darwin 改 `~/Library/Application Support/lawbench`。抽一个 `defaultAppData()`（file-log.ts 已有同名函数）供各处共用，cordis.patch.yml 的 `!!js` 表达式同样按 `process.platform` 选 | `shared\file-log.ts`、`cordis.patch.yml`、`service\lawbench\config.py`（只在没传 LB_APPDATA 时用） | 不变（win32 分支保留原表达式） | vitest：platform=darwin → Application Support；win32 → 原值 |
| 12 | **隔离目录（P-4 lawbench-isolation）**：`lawbenchIsolatedPaths` 要求 `APPDATA`+`LOCALAPPDATA`，否则返回 undefined | 分支 | Mac 上现在**不隔离**，会和原版 DSH 共用 `~/Library/Application Support/@deepseek-ai/dsh-desktop` 与 `~/.dsh`。darwin：`userData=~/Library/Application Support/lawbench-desktop`、`DSH_HOME=~/Library/Application Support/lawbench/dsh-home`（与执行令一致）。卸载在 Mac 上是拖进废纸篓，不清数据（说明里写清两个目录） | `dsh-patches\P-4-brand.patch`（lawbench-isolation.ts 及其测试） | 不变 | 原测试 + darwin 两条（目录、开发期不搬家） |
| 13 | **"装好的客户端"判断与安装布局**：`install-layout.ts` 认 `<exe 旁>\resources\app.asar`；命令 `python\python.exe`、`soffice.exe`、`pandoc.exe`；`PATH` 用 `;` 拼；`cordis.patch.yml` 的 `customSkillDirs` 同一判断；P-11 `enginesDirectory` = exe 旁 `engines` | 分支（参数化） | Mac 的 execPath 是 `X.app/Contents/MacOS/X`，载荷在 `X.app/Contents/Resources/`。抽 `payloadRoot(execPath, platform)`：win32 = exe 所在目录（原样），darwin = `../Resources`；之后各处 `join(root, …)` 复用。darwin 下：`python/bin/python3 -I -m lawbench`、`tools/LibreOffice.app/Contents/MacOS/soffice`、`tools/pandoc/bin/pandoc`、`PATH` 用 `path.delimiter`（win32 上仍是 `;`） | `host\install-layout.ts`、`cordis.patch.yml`、`dsh-patches\P-11`、`effectiveConfig` 的 `checkPython` 正则（加 `python3`） | 不变 | install-layout 用例按 platform 参数各跑一遍 |
| 14 | **管理员 Skill 目录**：`%ProgramData%\lawbench\skills`（默认 `C:\ProgramData`）、安装器 `set-skills-acl.ps1` | 分支 | darwin：`/Library/Application Support/lawbench/skills`（不存在就跳过，同 Windows）。第一阶段**不做**建目录与权限这一步（dmg 没有安装器），说明里写管理员手工建法 | `install-layout.ts`、`cordis.patch.yml` | 不变 | darwin 目录名 |
| 15 | **Host 传给服务的环境变量白名单**：`host\index.ts:64`（SYSTEMROOT、APPDATA、COMSPEC…） | 分支 | darwin 白名单：`HOME`、`USER`、`LOGNAME`、`TMPDIR`、`PATH`、`LANG`、`LC_ALL`、`LC_CTYPE`、`__CF_USER_TEXT_ENCODING` | `host\index.ts` | 不变 | darwin 下 env 只含这些 + LB_* |
| 16 | **日志里去本机路径**：`host\index.ts:476-488` 只认盘符 / `\\` 路径 | 分支 | darwin 加 posix 绝对路径（`/Users/…`、`/Volumes/…`、`/private/…`、`/var/folders/…`）同样换成 `<路径>`，安装目录内换 `<安装目录>/…`。**不加会把 Mac 上的案件名、材料名写进日志** | `host\index.ts`（及 supervisor 用的同一函数） | 不变 | 含 `/Users/x/张三案/起诉状.docx` 的错误行 → 无文件名 |
| 17 | **凭据**：`credentials\credman.ts`（PowerShell + advapi32）；`SOURCE='windows-credential-manager'`；服务端 `keyring` Windows 后端 | **新写**（Mac 一个文件） | 新 `credentials\keychain.ts`：`security` 命令。写：`security -i` 从**标准输入**读 `add-generic-password -U -s lawbench/LAWFIRM_KEY -a lawbench -w …`（Key 不进命令行参数，同 Windows 的设计）；读：`find-generic-password -s … -a … -w`；删：`delete-generic-password`。条目名与 Python `keyring` macOS 后端（service=`lawbench/LAWFIRM_KEY`，account=`lawbench`）一致，服务端代码不用改。`index.ts` 按平台选 credman/keychain，`Store` 接口不变 | `credentials\keychain.ts`（新）、`credentials\index.ts`（选择一行 + SOURCE） | 不变 | 假 `security`（spawn 打桩）验：参数里无 Key、标准输入有、超时、未找到返回 undefined |
| 18 | **界面文案"Windows 凭据管理器"**：`ui\settings.tsx:79`、P-3 首次配置页提示 | 分支 | darwin 显示"钥匙串"。平台从 Host 现有状态接口带一个 `platform` 字段（不动契约：这是插件内部接口，非 `contracts\`；如属契约，改为前端读 DSH 已有的平台标记）| `ui\settings.tsx`、`P-3` | 不变 | 渲染用例 darwin/win32 各一 |
| 19 | **Smart App Control / SmartScreen 文案** | 新写（文档） | Mac 对应是 **Gatekeeper**：ad-hoc 签名、未公证的包首次打开被拦。macOS 15 起右键"打开"绕过已取消，要到"系统设置 → 隐私与安全性 → 仍要打开"，或终端 `xattr -dr com.apple.quarantine /Applications/<名>.app`。写进 Mac 版安装说明。自检里"长路径支持"文案在 Mac 上不会出现（`longPathsEnabled` 非 win32 已返回 true），复用 | `packaging\mac\README.md`（新）、用户安装指引 | 无 | — |
| 20 | **小工具 PyInstaller**（`build.ps1` 223-260 行，`--windowed --onedir`）；`tools\convert\finder.py` 写死 `.exe`、`%LOCALAPPDATA%\Programs` | 复用 + 分支 | 同一命令在 Mac 上产出 `splitter.app`、`convert.app`（用同一份 pbs Python，自带 tkinter/Tcl-Tk）。finder：darwin 下 `_client_roots` 用 `/Applications/<名>.app/Contents/Resources/tools`，可执行文件名去 `.exe`、soffice 用 `LibreOffice.app/Contents/MacOS/soffice`、pandoc 用 `pandoc/bin/pandoc`。**放哪、怎么打开见第 5 节第 4 条** | `packaging\mac\build.sh`、`tools\convert\finder.py` | 不变 | finder darwin 候选列表 |
| 21 | **所内/所外自动切换（EasyTier）** | 复用 | 产品里只是两套地址 + 连不上就换（`settings.py`），**无平台差异**，已确认。律师 Mac 要另装 EasyTier 客户端（有 macOS arm64 版）才能所外访问——属部署，不进安装包 | — | — | — |
| 22 | **字体** | 复用（记风险） | LibreOffice 转 PDF 时，宋体/仿宋_GB2312 在 Mac 上会被替换（宋体-简/华文仿宋等），归档 PDF 版式可能与 Windows 不同。不随包带字体（许可）。真机核对 | — | — | 真机 |
| 23 | **内置 Python 隔离**：`packaging\python\python312._pth`（Windows 嵌入式机制）、`sitecustomize.py` | 复用 + 分支 | Mac 没有 `._pth`。服务以 `-I` 起（不读 PYTHONPATH、用户 site）；驱动等子进程已由 `procs.python_env` 设 `PYTHONNOUSERSITE=1`；`sitecustomize.py` 原样放进 site-packages | `build.sh` | 无 | 打包后自检：`python3 -I -c "import sys;print(sys.path)"` 不含 `~/Library/Python` |
| 24 | **依赖闭包** `[client.pip]` | 复用 | 全部有 `macosx_11_0_arm64` 或 universal2 轮子（onnxruntime、opencv-headless、shapely、pyclipper、rpds-py、lxml、tokenizers、pymupdf、pypdfium2…）；`pywin32`、`pywin32-ctypes` 已有平台标记，Mac 上不装。`versions.lock` 加 `[client-mac.pip]` 分节（只差这两项则可共用，构建时 `pip download --platform macosx_11_0_arm64` 核实） | `packaging\versions.lock` | 只追加分节 | build.sh 离线 `--no-index` 装成功即证 |
| 25 | **DSH 的 `dsh:` 协议** | 复用（记） | Mac 上同样注册 `dsh:`（Info.plist），与原版 DSH 同名，同 Windows 已记的遗留 | — | — | — |

## 2. 载荷来源与 sha256

| 载荷 | 来源 | sha256 怎么来 | 放进 .app 的位置 |
|---|---|---|---|
| Python 3.12.14 | **python-build-standalone** `cpython-3.12.14+<日期>-aarch64-apple-darwin-install_only_stripped.tar.gz` | **直接用 DSH `lock.json` 里 `mac-arm64.pythonSha256`（`81a359f1…`）**，与 Windows 回退路径同一做法（DSH 构建时已校验下载缓存） | `Contents/Resources/python/` |
| LibreOffice 26.8.0.3 | download.documentfoundation.org `LibreOffice_26.8.0.3_MacOS_aarch64.dmg` | TDF 镜像提供同名 `.sha256`（mirrorbrain）与 `.asc`；首次拉取时记录，写进 `versions.lock [client-mac]`，之后每次构建按锁核对 | `Contents/Resources/tools/LibreOffice.app` |
| pandoc 3.11 | github.com/jgm/pandoc releases `pandoc-3.11-arm64-macOS.zip` | 发布页不给校验文件：首次拉取时计算、入锁，之后核对（同 Windows 的做法） | `Contents/Resources/tools/pandoc/`（含 COPYING、COPYRIGHT，GPL 全文随包） |
| tokenizer.json | 同 Windows（已入锁 `87a7830d…`） | 复用 | `Contents/Resources/service/lawbench/llm/` |
| contracts、skills、service、engines | 本仓库 | 复用 build.ps1 同样的拷贝清单与排除规则（`__pycache__` 等） | `Contents/Resources/…` |
| 轮子 | PyPI，`pip download --only-binary=:all: --platform macosx_11_0_arm64 --python-version 3.12` | pip 记录 hash，入 `[client-mac.pip]` | `python/lib/python3.12/site-packages` |
| PyInstaller | PyPI 轮子（同 Windows 版本） | 同上 | 只构建用，不进包 |

许可证表：`packaging\THIRD-PARTY-LICENSES.md` 复用，追加"仅 Mac 版"行（LibreOffice Mac 版、pandoc Mac 版来源不同，许可证相同）。

**Python 运行时选 python-build-standalone 的理由**（执行令要求说明）：
1. **DSH 已为 mac-arm64 锁定了同一份**（含 sha256），和 Windows 现在复用 DSH 下载缓存的做法一致，不新增来源。
2. 它是可整体搬动的 tar 包，解压即用；python.org 的 macOS 安装包是 `.pkg`，装到 `/Library/Frameworks`，搬进 .app 要拆包并改动态库路径（`install_name_tool`），一改原签名就失效。
3. Windows 上换官方版是为了 Smart App Control 逐个查 DLL 签名；Mac 的 Gatekeeper 只在首次打开时查**整个 .app**，ad-hoc 签名 + 不开 hardened runtime 时内部动态库不做"同一开发者"校验，官方签名带不来好处。将来上开发者证书（N74 A/B）时整包重签，两种来源都一样。

## 3. electron-builder / 签名

- DSH 的 `electron-builder-config.mjs` 在打 Mac 包时**强制要求**签名身份与公证凭据环境变量（缺了就抛错）。P-4 里加：`LAWBENCH_MAC_ADHOC=1` 时跳过两者，`mac.identity='-'`（ad-hoc）、`hardenedRuntime=false`、`notarize=false`、`target=[{target:'dmg',arch:['arm64']}]`；`-SignIdentity` 预留：给了身份就走 DSH 原有签名+公证流程。Windows 构建不经过这段（`packagesMacOS` 为假）。
- 载荷进包：Windows 用 `extraFiles`（放 exe 旁），Mac 改 `extraResources`（放 `Contents/Resources`），同一个 `LAWBENCH_STAGE_DIR`。
- **`codesign --deep -s -` 的问题**：`--deep` 会把 LibreOffice.app 上 TDF 的正式签名改成 ad-hoc。建议改为"由内到外签我方二进制（python、pandoc、PyInstaller 产物），LibreOffice.app 保留原签名，最后签外层 .app"，效果同样能启动。与工单原文不一致，见第 5 节第 3 条。

## 4. GitHub Actions

- runner：`macos-15`（arm64，M1 3 核、7 GB）。工作流 `workflow_dispatch` 手动触发，**不引用任何 secrets**，子模块 dsh 从公开上游取。
- 缓存（`actions/cache`）：pnpm 存储、DSH `.desktop-build/downloads`、LibreOffice dmg、pandoc zip、轮子目录，键含 `versions.lock` 哈希。
- 预算：私有库免费额度 2000 分钟/月，Mac 按 10 倍计 → **约 200 Mac 分钟**。估算首跑（无缓存）35–45 分钟，有缓存后构建约 20 分钟、冒烟约 5 分钟 → **每月约 7 次完整运行**。第一阶段计划 3–5 次就出绿。
- **⚠ 产物存储**：私有库免费 artifact 存储 **500 MB**，dmg 预计 0.8–1 GB（含 LibreOffice）。超限且消费上限为 0 时上传会失败。见第 5 节第 6 条。
- 冒烟：挂载 dmg → 拷到 `/Applications` → `xattr -dr com.apple.quarantine` → 起应用（设置里两组地址都指 `127.0.0.1` 死端口 18831/18832）→ 等窗口 → `screencapture` → 读启动自检输出 → 退出。runner 的屏幕录制权限是否放行首跑实测；不行就退用 Electron 的远程调试端口截首屏（只测时开，不进产品）。
- 扫描：dmg 解开后对全部文本做 Key / 用户名字串扫描，结果进日志与证据。

## 5. 要主编排定的事（原文摘录 + 建议）

1. **发票整理在 Mac 上不可用**。依据 `engines\invoice-ledger\scripts\runtime_cache.py:163` "当前环境包仅支持 Windows AMD64"；工单"不改 `engines\`"。建议：第一阶段 Mac 版发票整理入口提示"Mac 版暂不支持"，另上候 owner：请律所给 Mac 环境包，或同意我方改引擎的运行时一段。
2. **设置里"转换程序"选 Word/WPS 在 Mac 上怎么办**。建议：Mac 上设置页不列 Word/WPS，只剩"自动（内置 LibreOffice）"；服务端遇到旧设置值按不可用报错，不悄悄改用 LibreOffice（保持"指定了就不换"的原口径）。
3. **工单原文"ad-hoc `codesign --deep -s -`"**。建议改为不加 `--deep`、保留 LibreOffice.app 原签名（第 3 节），能否启动由 Actions 冒烟证明。
4. **两个小工具在 Mac 上放哪**。Windows 现状：`build.ps1` 把 `splitter.exe`、`convert.exe` 放在 `<安装目录>\tools\` 下，没有快捷方式、界面里也没有入口（仓库里未查到）。Mac 上放进 `.app` 内部，律师基本找不到。建议：dmg 里与主程序并排放 `长截图切分.app`、`格式互转.app`，说明里写"一起拖进'应用程序'"；finder 按 `/Applications/<主程序>.app` 找 LibreOffice、pandoc。
5. **SEC-14 与 Mac 的"桌面与文稿"iCloud 同步**。Mac 用户常开"iCloud 云盘 → 桌面与文稿文件夹"，此时 `~/Documents` 路径不变但在同步；而 Host 默认文档目录正是 `~/Documents`（`host\index.ts:207`）。路径字样查不出。建议：darwin 下检测 `~/Library/Mobile Documents/com~apple~CloudDocs/Documents` 是否存在，存在就把 `~/Documents`、`~/Desktop` 也视为同步目录；第一阶段先做，真机再核。
6. **Actions 产物存储 500 MB 不够放 dmg**。需要用户看一下 GitHub 账号套餐与消费上限：要么允许少量超额计费，要么产物只保留 1 天并在跑完后手动下载。不影响开工，首跑前要定。
7. **钥匙串弹窗**。Host（`security`）写、服务（内置 Python 的 keyring）读，是两个程序，第二个读时 macOS 可能弹"允许访问钥匙串"；写入时用 `-T` 把两个程序都列为可信可避免，但 ad-hoc 签名每次构建都变，升级后可能再弹一次。只能真机验证；必要时改为只由 Host 读、经启动环境传给服务（要动 Spec 8.1 的口径，届时再报）。
8. **Mac 版管理员 Skill 目录**的建目录与权限（Windows 由安装器一步做）第一阶段不做，只在说明里写手工步骤。可否？

## 6. 工期拆分（第 2–6 步）

| 步 | 内容 | 估时 | 提交 |
|---|---|---|---|
| 2 | 服务端：#1 #2 #4 #5 #6 #7 #8 #10 #11（服务部分），darwin 用例；Windows 全量计数对比 | 1.5 天 | `T28: service 平台隔离` |
| 3 | 客户端：#11–#18（dsh-ext 与 P-4/P-11/P-3/cordis），keychain.ts；dsh-ext 与 DSH test:gui 计数对比 | 2 天 | `T28: dsh-ext/补丁 平台隔离` |
| 4 | `packaging\mac\build.sh`、`versions.lock` 分节、许可证表、P-4 ad-hoc 构建开关、finder | 2 天 | `T28: mac 打包脚本` |
| 5 | 两个工作流；首跑到出 dmg + 冒烟截图（按 3–5 次运行算） | 2 天 | `T28: Actions` |
| 6 | 证据、交付说明 | 0.5 天 | `T28: 交付说明` |
| 合计 | | **约 8 个工作日** | 真机完整流程另计 |

本机环境（dsh 本地克隆、node_modules 复制与联接重建、借用 venv）在第 2 步开工时按执行令搭，不联网。
