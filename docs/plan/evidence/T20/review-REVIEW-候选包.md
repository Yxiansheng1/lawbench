# T20 第一版候选安装包（line-A `25e1bef`；包 `lawbench-0.1.0-win-x64-unsigned.exe` sha256 c0ce0ae4…6240）· 复核记录（单人，八项清单）

- target：`25e1bef`（父 `87de3f8` = main）；复核克隆 `D:\lawbench-rv\rv-A42`
- 派发：Opus 5.5 只读复核员，2026-10-04 20:0x；实验全程代理指死端口、未联网
- 归档：主编排于 2026-10-04 20:14 (+08:00) 从复核员交回原文抄录，未改内容

## 复核员原文## T20 第一版候选安装包复核（target line-A `25e1bef`，父 `87de3f8`）

**结论：AMEND。** 最要紧的那一条没问题：装好的程序启动时不会自己往外连，更新策略、自动更新、遥测、语音模型下载这几条路都不通。载荷来源也查得到：这一个安装包里装了哪些 npm 包，和作者的清单一致。

要返修的是两件事：
- 安装包里没有带许可证表，pandoc 也没带它的 GPL 许可证全文。复核包把"许可证表在包内"列为要核的项，这一项没过。
- 打包时 DSH 每次都按 registry 的当前版本重新挑 234 个第三方 npm 包。这一版装进去的有一部分已经比 DSH 仓库锁文件里的版本新，所以下次打出来的包可能又不一样。

修起来都不大。

### Findings

**一、外连相关**

- **NOTE-1（确认，不是问题）P-4"去掉强制更新策略"有效，主进程启动时没有远端轮询。**
  - 证据：用 electron-builder 缓存里的 7za 解开安装器（40547 个文件，2.8 GB），再用离线的 `@electron/asar` 解开 `app.asar`：
    - `package.json` 里没有 `dshMandatoryUpdatePolicy`。`main.js` 第 11737 行：打包状态下读不到这个字段，就得到 `resolveDesktopPolicyConfig(undefined)`，返回 undefined，策略对象不会建。
    - 自动更新只在 `resources\app-update.yml` 存在时才启用（`main.js` 第 6914 行），包里没有这个文件，所以 `checkForUpdates` 永远走不到。
    - `lib\*.js` 里的网址字面量只有两条：`http://127.0.0.1:17801`（证件识别驱动）和一条 js-yaml 许可证注释里的 github 地址。
    - `renderer\`、`lib\welcome\` 的 html、css 里没有外链，字体是包内的 woff2。
  - 补丁后的 DSH 源码：按 PATCHES.md 的顺序打 16 个补丁，0 失败，共 144 个路径。`electron-builder-config.mjs`、`package-target.ts`、`smoke-runtime.ts`、`lawbench-product.mjs` 四个文件和 `D:\lawbench-A\dsh` 构建工作区逐字节一致。
- **NOTE-2 运行时插件包里的远端地址，逐条判定都走不到。**
  - 我对 `@deepseek-ai/*` 和 `lawbench-dsh` 共 1296 个文件做了网址清点，有风险的几条如下：
    - `harness-telemetry.deepseeksvc.com`（dsh-base 的 `session-telemetry-otel` 行）：lawbench 的 `cordis.patch.yml` 已把这一行关掉。
    - `api.deepseek.com`、`platform.deepseek.com`（llm-deepseek、web-search、deepseek-account）：同样已关。
    - `registry.npmjs.org`、`npmmirror`（插件管理）：已关。
    - `huggingface.co`、`hf-mirror.com`（语音输入 sensevoice）：语音组合包不在桌面端 web profile 里。web profile 只有 dsh-base、dsh-web-app、lawbench-dsh 三个（`main.js` 第 3265 行）。
    - `feishu.cn`（账号设置页）：已关。
  - 其余都是许可证注释、JSON schema 的 `$id`，或文档预览库里的字面量，不是请求地址。
  - lawbench-dsh 里的 fetch 只连 `127.0.0.1`。
- **P3-1 随包的 LibreOffice 自带在线更新组件，现在的调用方式不会触发。**
  - 证据：`tools\libreoffice\program\updchklo.dll` 存在，`version.ini` 里有 `UpdateURL=https://update.libreoffice.org/check.php`。工作台服务（`service\lawbench\ingest\libreoffice.py:166`）和小工具（`tools\convert\core.py:208`）都用 `--headless`，并且每次用新的配置目录，不会走到更新检查。
  - 影响：只有有人用图形界面打开这份 LibreOffice 时才可能外连。
  - 建议：验收日抓包时顺带覆盖；以后可以考虑打包时删掉 `updchklo.dll` 或清空 UpdateURL。
  - 归类：独立后续。

**二、其他**

- **P2-1 包里没有许可证表，pandoc 也没带 GPL 许可证全文。**
  - 证据：在整个解包目录里搜 `THIRD-PARTY*`，0 个。`tools\pandoc\` 里只有 `pandoc.exe`。仓库里的 `packaging\THIRD-PARTY-LICENSES.md` 第 15 行自己写着 pandoc"按 GPL 要附许可证全文"。LibreOffice 自带的 `license.txt` 和 `NOTICE` 在包里。
  - 影响：复核包"许可证表在包内"一项不过；分发时 GPL 合规缺一块。
  - 最小修复：`build.ps1` 的 package 步把 `THIRD-PARTY-LICENSES.md` 拷到暂存目录根；pandoc 旁边放 COPYING。源码获取方式仍等主编排或 owner 定。
  - 归类：范围内阻断。
- **P2-2 DSH 运行时的 234 个第三方 npm 包每次打包都重新挑版本，同一份源码两次打包结果可能不同。**
  - 证据：`D:\lawbench-A\dsh\apps\desktop\scripts\prepare-dsh.ts:125` 先跑 `pnpm install --lockfile-only`，从 registry 现场生成锁文件，第 130 行再按这份锁文件装。
  - 拿 `runtime-npm-packages.txt` 的 234 个外部包对照 DSH 仓库根的 `pnpm-lock.yaml`，粗算约 63 个对不上，实查确认的几例：
    - ws：8.22.0，锁文件里是 8.21.0
    - @img/sharp-win32-x64：0.35.5，锁文件里是 0.35.3
    - @aws-sdk/core：3.978.1，锁文件里是 3.974.20
    - bundle-name：4.1.1，锁文件里是 4.1.0
  - 清单本身是准的：抽 11 个，包里实际版本与清单完全一致。所以这一个安装包可以追到来源，但不能复现，`versions.lock` 也没有覆盖这批包。
  - 影响：下一次打包可能装进开发期没测过的新版本，作者的偏离①只写了"要联网"，没写版本会浮动。
  - 最小修复：把这次生成的运行时 `pnpm-lock.yaml` 留存并提交；之后由补丁让 prepare 用这份锁文件、跳过 `--lockfile-only`，或者至少把锁文件连同 integrity 存进 evidence。
  - 归类：范围内，可以和 P2-1 一起修，也可以由主编排改成独立后续。
- **P3-2 包里有大量构建机路径 `D:\lawbench-A\...`，没有本机用户名。**
  - 证据：grep `Users\<用户>` 为 0（`<用户>` 的其余命中都是哈希或数据里的数字）。`D:\lawbench-A\` 出现在 5046 个文件里：
    - 4973 个是 `python\Lib` 下的 `.pyc`，打包时编译，共 640 个 `__pycache__` 目录随包；
    - 18 个 `python\Scripts\*.exe` 的 shebang 指向 `D:\lawbench-A\packaging\stage\python\python.exe`，装到用户机器上跑不起来，但服务是 `python -I -m lawbench` 启动，不用它们；
    - `skills\manifest.json` 的 `source` 字段；
    - 48 个 DSH 前端 `client.js` 的 `//#region \0dsh-css:D:\lawbench-A\dsh\...` 注释。
  - 影响：不泄密，只暴露构建目录名；Scripts 下那些 exe 是坏的启动器。
  - 修复建议：打包时去掉 `__pycache__` 和 `Scripts\*.exe`，manifest 的 source 改成相对路径。
  - 归类：独立后续。
- **P3-3 证据和脚本说法不一致，有三处。**
  1. `build.txt:48` 写的管理员 Skill 目录是 `%ProgramData%\连越律师工作台\skills`，代码里是 `ProgramData\lawbench\skills`（`host\install-layout.ts` 的 `ADMIN_DIR_NAME='lawbench'`，`cordis.patch.yml` 也是这个）。代码是对的，文字写错了。
  2. `payload-fetch.txt:2` 说"electron-builder 的下载地址指向 127.0.0.1 的空端口兜底"，但 `build.ps1` 里没有设 `ELECTRON_BUILDER_BINARIES_MIRROR` 一类变量，只设了 `ELECTRON_MIRROR`。
  3. `build.ps1` 头注释写"All steps run offline"，括号里列的联网项没有 npm registry，与第 347 行附近的说明矛盾。
  - 最小修复：改文字；如果确实要兜底，就在脚本里设那个镜像变量。
  - 归类：范围内（证据准确性），不阻断。
- **P3-4 P-4 补丁 `package-target.ts` 的注释里混进了一个退格控制字符（0x08）**，`packaging\build.ps1` 写成了 `packaging<BS>uild.ps1`。只影响注释，归独立后续。
- **P3-5 小工具找不到同一安装目录里的 LibreOffice 和 pandoc。**
  - 证据：`tools\convert\finder.py` 先找 `%LOCALAPPDATA%\Programs\<产品名>\tools\...`，再找"程序所在目录\libreoffice"。装好之后小工具在 `<安装目录>\tools\convert\`，兄弟目录 `..\libreoffice` 不在候选里。
  - 影响：装在默认位置时没问题；用 `/D` 装到别处时会退回系统装的 LibreOffice，或者找不到。作者冒烟用的是 `/D=D:\lawbench-smoke-install`，开发机又装了系统 LibreOffice，这种情况会被掩盖。
  - 修复：候选里加 `_bundled_root().parent / 'libreoffice'` 和对应的 pandoc。
  - 归类：独立后续。
- **NOTE-3** `document.title` 仍是"DeepSeek Harness"：`dsh-web-frontend\dist\index.html` 的 `<title>`，作者已列为遗留。
- **NOTE-4** 包里带了 engines 原样的测试目录（证件识别测试图约 13 MB）。`make_corpus.py` 写明全部是脚本生成的虚构内容，按"engines 原样使用"处理，不算真实测试数据。

### 冻结清单核对表

| 项 | 结果 | 依据 |
|---|---|---|
| 1 身份、逐 hunk、P-4/P-12 新段 | 过 | HEAD=`25e1bef`、工作区干净；改动 12 个文件；16 个补丁 0 失败、144 路径；P-4 三处、P-12 一处，内容与 PATCHES.md 末节一致 |
| 1 装好后无远端轮询（asar 网址逐条判定） | 过 | 见 NOTE-1、NOTE-2 |
| 2 布局齐全 | 过 | contracts、`asar\lib\welcome`、python、service 加 tokenizer、tools 下 libreoffice / pandoc / splitter / convert、engines 两个、skills 18 个、`installer\set-skills-acl.ps1` 都在 |
| 2 versions.lock 55 包对照 wheel | 过（全量，不止抽 5 个） | 55/55 版本一致，0 缺失；多出的只有 pip |
| 2 THIRD-PARTY-LICENSES.md 在包内 | **不过** | P2-1 |
| 2 无 .env、Key、用户名路径、.vite、我方测试数据 | 过（有附注） | 没有 `.env*` 文件；没有 `sk-` 长串（只抽查了解开的 asar，全量 grep 超时）；用户名路径 0；`.vite` 0；我方 tests\fixtures 0；构建路径残留见 P3-2 |
| 3 payload-fetch 每条有域名和 sha256 | 过 | 三段都写了来源域名和 sha256（运行时那段文件名就是 sha256） |
| 3 npm 234 包对照 DSH 锁文件抽 10 | 清单准确，但与锁文件不一致 | P2-2 |
| 3 electron-mirror 只监听本机、只给缓存、构建后退出 | 过 | 实跑在 19432：只监听 127.0.0.1；`..%2F`、`..%5C` 两种越界都返回 404；目录和 POST 返回 404。它不会自己退出，由 `build.ps1` 的 finally 按 PID 结束 |
| 4 启动自检路径与布局一致 | 过 | `host.js` selfCheck 查 `service\lawbench\llm\tokenizer.json`、`tools\libreoffice\program\soffice.exe`、`ProgramData\lawbench\skills`，安装布局里都对得上 |
| 4 ACL 脚本只动 `-Dir` 指定目录 | 过 | `set-skills-acl.ps1` 只对传入目录设"去继承 + 普通用户只读"，里面原有内容改为继承 |
| 5 build.ps1 新步骤；`-PnpmStore`、`--offline` 仍在 | 过 | 第 111、117 行都还是 `--frozen-lockfile --offline --store-dir`；头注释的问题见 P3-3 |
| 5 document.title 遗留 | 确认 | NOTE-3 |

### 八项清单

1. 契约一致：本次没动契约，过。
2. 边界输入：镜像越界和非 GET 请求都返回 404，过。
3. 错误路径：镜像端口被占时打包会失败而不是外连；`build.ps1` 的 finally 一定按 PID 停镜像，过。
4. 日志不含正文：镜像日志只记方法、路径、状态码，过。
5. 路径闸门：本次没碰，过。
6. 无外连：装好的程序启动不外连，过；构建期的联网已披露，但版本会浮动（P2-2）。
7. 测试覆盖新代码：`lawbench-stage.spec` 加了版本和"无策略"两例，`brand.spec` 一例。我没有跑测试，属于可选项，静态读了。
8. 无机密入库：`.env.windows` 不入库、内容无密钥；包内没有 Key，过。

### 实际跑过的命令（都在 `D:\lawbench-rv\rv-A42-exp`，代理指向 127.0.0.1:19431 死端口，没有联网）
- `git rev-parse` / `status` / `diff 87de3f8 25e1bef`
- `7za x` 解开安装器（只读安装器本身）
- `node @electron/asar extractAll`（模块来自 `D:\lawbench-A\dsh` 的 node_modules，只读引用）
- 网址清点；`grep -a -r` 查 `Users\<用户>`、`lawbench-A\`；`sk-` 查了解开的 asar
- `versions.lock` 对照 dist-info；npm 清单对照 DSH `pnpm-lock.yaml`，以及对照 asar 里的实际版本
- `git clone --no-hardlinks D:\lawbench-A\dsh`，检出 `477b4f4`，按顺序打 16 个补丁，再与构建工作区比哈希
- `electron-mirror.mjs` 在 19432 端口实跑两次，用 `curl --noproxy` 探测，按 PID 停止

### 残留审计
- 起过的进程只有两个镜像（node，PID 36224、46308），都已按 PID 停止，确认不在了。
- 19430–19439 端口没有监听。
- 实验目录 `D:\lawbench-rv\rv-A42-exp`（解包内容、asar、dsh 克隆）已整个删除。
- 复核克隆仍在 `25e1bef`，工作区干净。
- 没有装安装器，所以不需要卸载，也没写注册表或开始菜单。
- 没碰 `D:\lawbench-A` 或其他目录，没动别人的进程。

### 证据缺口
- 没有真装、真启动。首次配置页、自检那一项、启动时实际有没有网络连接，留给验收日干净机断网安装和抓包（步骤 6）。
- `sk-` 只查了解开的 asar；全包 grep 20 秒超时，没有补跑。
- 两个小工具 `_internal` 里的依赖版本没有和 `versions.lock` 对照。
- dsh-ext 的 tsc 和 `brand.spec` 没跑（可选项）。

AMEND

