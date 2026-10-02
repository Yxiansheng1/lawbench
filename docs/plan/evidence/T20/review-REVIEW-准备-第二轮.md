# T20 准备返修累计 + 步骤 3 可离线部分 · 独立复核记录（第二轮）

- 复核员：一名 Opus 5.5 只读复核员（换人）
- target：line-A `3470968`；累计 `754b6b8`、`d8671e8`、`46ed38e` + `9b35040`、`cf17516`、`3470968`
- 冻结清单：`review-REVIEW-准备.md` 第二部分 + 令 0127 步骤 3 六条
- 复核克隆：scratchpad `rv-A27`
- 归档：主编排于 2026-10-02 10:17 (+08:00) 从复核员交回原文抄录，未改内容（无人值守窗）

## 第一部分 复核员原文
# T20 准备返修累计范围 + 步骤 3 可离线部分 · 独立复核（rv-A27，line-A `3470968`）

**总体结论：AMEND。** 冻结清单里的四条 P2 都已关闭，我逐条复现过。不过步骤 3 这批新交的打包布局有两个实打实的 P2 缺口，另有一个 P2 关于工具找不到；冻结项 P3-1 只做到一半。

**环境核对**
- HEAD 为 `3470968`，`git status` 干净；累计范围就是那三个提交。
- T17 的会话存储和路由没动：`host/index.ts` 只改了 `apply` 开头的配置选取，`cordis.patch.yml` 只改了 Skill 目录那一行。

## Findings

### 本次修正引入（含步骤 3 首次交付的范围）

**P2-A　打包布局里缺 `contracts\`：装好的客户端里，服务的 /health 回 500，Host 永远等不到服务就绪**
- 原因：
  - 服务的 `config.py:11` 写的是 `REPO_ROOT = parents[2]`，打包后就是 `<安装目录>`；契约目录取 `<安装目录>\contracts`（`case_db.sql`、schema、版本号都在里面）。
  - `build.ps1` 不把 `contracts\` 放进 stage；`packagedConfig` 的 `env: {}` 也不给 `LB_CONTRACTS_DIR`。
  - `package -DryRun` 的缺项检查和 `payload-inventory.md` 都没列这一项。
- 实测：用暂存解释器按装好后的布局 `-I -m lawbench` 起服务（端口 19371，设置里四个地址都指向 127.0.0.1:19373–19376）。
  - `/health` 回 `500`；
  - 只加 `LB_CONTRACTS_DIR=<repo>\contracts`，回 `200 {"status":"ok","contract_version":"1.3"}`。
- 连带一件事：作者"暂存解释器跑服务全部测试 945 通过"是在加 `._pth` 之前跑的。加了 `._pth` 之后 `safe_path=1`，`test_main` 另起的 `python -m lawbench` 改从 `stage\service` 导入，2 例失败，原因就是这个契约目录。作者没有重跑。
- 最小修复：
  - python 步把 `contracts\` 拷进 `stage\contracts`，或者 `packagedConfig` 给 `LB_CONTRACTS_DIR` 并把目录放进包里；
  - DryRun 缺项检查和载荷清单都补上这一项；
  - 用带 `._pth` 的暂存解释器重跑服务全部测试。
- 归类：范围内阻断（步骤 3 第 4、5 条）。

**P2-B　`set-skills-acl.ps1` 会让目录里已有的文件谁都读不了**
- 原因：`/inheritance:r /grant:r '*S-1-5-32-545:(OI)(CI)RX' … /T` 套到文件上时，文件的 ACL 变成空的。
- 实测（在实验目录里，没提权跑脚本，没碰 `%ProgramData%`）：
  - 已有的 `existing.txt`、`sub\inner.txt` 用 `icacls` 看没有任何一条授权；
  - 当前用户读取报 `UnauthorizedAccessException`；
  - 子目录本身的权限是对的。
- 脚本头注释写的是"Existing files below get the same rights (/T)"，实际做不到。作者的 `skills-acl.txt` 把"改不了已有文件"当成成功，没有测"能不能读"。
- 影响：管理员先放 Skill 再跑脚本，或者重跑一次，客户端就读不到管理员 Skill。
- 最小修复：目录本身设权限时不带 `/T`，再对 `"$Dir\*"` 执行 `icacls /reset /T /C` 让下面的文件改为继承；`-Verify` 加上"读已有文件、读下层文件"两项。
- 归类：范围内（步骤 3 第 3 条）。

**P2-C　随包带的 LibreOffice 和 pandoc 放在 `<安装目录>\tools\`，但真正用它们的地方都不在那里找，自检却报"已就绪"**
- 三处各找各的：
  - 服务 `ingest/libreoffice.py` 的 `find_soffice` 只查 PATH 和 Program Files；
  - Host 不改 PATH，`packagedConfig` 的 `env: {}` 也不给位置；
  - 小工具 `tools/convert/finder.py` 找的是 `%LOCALAPPDATA%\Programs\<lawbench|律师工作台>\resources\…`。
- 而 `selfCheck` 用的 `sofficeCandidates` 和 `pandocCandidates` 正好指向 `tools\`，所以会报"已就绪"。
- 影响：没装系统 LibreOffice 的机器上转换照样失败，667 MB 的载荷白带了。
- 最小修复：Host 打包后在子进程 PATH 前面加上 `tools\libreoffice\program;tools\pandoc`，或者传 `LAWBENCH_SOFFICE` 并由服务读取（这一半要线 C 配合）；`finder.py` 一并对齐。
- 归类：范围内（打包布局），需要跨线，请主编排定。

**P3-1　冻结项 P3-1 没达到宣称的效果：`._pth` 加 `import site` 之后，用户目录的 `.pth` 仍然会执行**
- 实测，暂存解释器、不带 `-I`、APPDATA 指到实验目录：
  - 用户 site-packages 里放的 `zz_evil.pth` 执行了；
  - 这时 `sys.flags.no_user_site=0`，用户目录照样被加进来，只是之后被 sitecustomize 删掉了；
  - 把 sitecustomize 拿掉，那条路径就留在 `sys.path` 里。
- 已经做到的：
  - `PYTHONPATH=C:\evil` 确实进不了 `sys.path`；
  - pywin32 的三条路径照常；
  - 带 `-I` 时干净。
- 作者"补记二"只看了 sitecustomize 处理之后的 `sys.path` 和 `ENABLE_USER_SITE`。
- 补充实测：`PYTHONNOUSERSITE=1`、`PYTHONUSERBASE=<不存在的目录>`、`-s`、`-I` 四种办法都能挡住。所以主编排安排给线 C 的"子进程传 `PYTHONNOUSERSITE=1`"仍然必须做，不能因为有了 `._pth` 就省掉。
- 最小修复：改准 `python-reuse.txt` 补记二、PATCHES.md 结论行和交付说明里的说法。

**P3-2　`docs\plan\evidence\T17\check_plugin_tree.py` 的 `EXPECTED_SKILL_DIRS` 还是旧写法**
- 用现有的旧导出跑，照常通过。
- 我把导出里那一行换成 `9b35040` 的新表达式再跑：报"customSkillDirs 整项相等 不符"，退出码 1。也就是说，下次重新导出插件树，这道检查一定不过。
- 最小修复：期望值同步成新表达式。

**P3-3　产品名没有完全集中**
- 仍写死占位名的地方：
  - `installer/strings.nsh` 6 处；
  - `electron-builder-config.mjs:163` 里 mac 的麦克风说明。
- PATCHES.md 的 P-4 行没有登记这次新增或改动的文件：`lawbench-product.mjs`、`smoke-packaged-runtime.ts`、`package-target.ts`、`package-macos.ts`、`development-app.ts`、`electron-builder.config.d.mts`、`extract-report.h`、`package-macos.spec.ts`。
- 最小修复：NSIS 改用 electron-builder 提供的 `${PRODUCT_NAME}`，mac 文案用常量拼，补登记 PATCHES.md。

**P3-4　分词文件会被重跑的 python 步悄悄删掉**
- 先跑 tools 步、再单独重跑 python 步时，`Reset-Dir stage\service` 会把 tools 步放进去的 `tokenizer.json` 删掉。
- DryRun 的缺项检查只看 `python.exe`、`__main__.py`、`skills`、`engines`，不查 `tools\`、`tokenizer.json`、`contracts\`。

### NOTE（不阻断）
- **`names.txt` 改成 LF 的副作用**：本机 autocrlf=true，跑一次 brand 步后 `git status` 一直显示 `M packaging/brand/names.txt`（内容相同，`git diff --quiet` 返回 0，提示 needs update）。图片全部逐字节一致。建议在 `.gitattributes` 里写 `eol=lf`。
- **新用例的字符串写法**：`install-layout.spec.ts` 新增的那例用单引号写 `'C:\ProgramData'`、`'D:\node\node.exe'`，`\n` 被当成换行。断言碰巧不受影响，但写法错了。
- **包数没跟上**：`payload-inventory.md` 和交付说明仍写 50 个包、50 个轮子，现在是 53 个（我回装 53 个，缺 0 个）。
- **corepack 可能联网**：`corepack pnpm@11.7.0` 在 corepack 缓存里没有这个版本时会自己去下载，`--offline` 管不到。可加 `COREPACK_ENABLE_NETWORK=0`。这是构建机行为。
- **`package-dryrun.txt` 最后一行被截断。**

### 此前既有
- `gen_lock.py`：dsh 子模块没检出时，`git -C dsh rev-parse HEAD` 拿到的是外层仓库的提交号，记成了 dsh 的提交（来自 `d8671e8`）。
- `apps/desktop-host/tests/office.spec.ts` 单独跑也稳定失败（报 `UNLOADING`）。它属于 desktop-host，不在 T20 动过的补丁里，作者的基线只统计了 apps/desktop。

### 无关新发现
- **网页界面包里还有不少"DeepSeek Harness"**：插件管理的安全提示、模型设置的欢迎语、文档预览、账号引导，还有 system prompt 的身份句。这些超出 P-4（桌面壳）的范围，是否看得到取决于对应插件有没有关掉，建议另立一项核对。
- **环境问题，影响各复核员**：大约 09:47–09:48，有个东西扫了整个 scratchpad（在 `%TEMP%` 下），按年龄删文件、删空目录、删联接。
  - 被删的包括：各个 rv-* 克隆里空的 `dsh` 子模块目录（rv-A26、rv-A27、rv-T4 等现在 `git status` 都显示 ` D dsh`）、`.git\refs` 空目录、时间戳为 2024 的 Python 标准库、时间戳旧的 pnpm 文件。
  - 线 A 的 `dsh`、`dsh-ext` 我核过没受影响：`git status` 仍是 108 项，`node_modules` 完好。
  - 我已补回 rv-A27 的空 `dsh` 目录，状态干净。
  - 以后在 `%TEMP%` 下做构建或暂存，要防着这种清理。

## 冻结清单逐条核对

| 编号 | 结果 | 依据 |
|---|---|---|
| P2-1 | 关闭 | 暂存解释器只装锁文件里的 53 个包，`-I` 下导入 rapidocr、`docloader`、`fitz` 都成功；依次藏掉 colorlog、requests、tqdm，各自报 `ModuleNotFoundError`；omegaconf 来自驱动自带的 `vendor\` |
| P2-2 | 关闭 | PyMuPDF 标"Dual Licensed - GNU AFFERO GPL 3.0 or Artifex…"；`docloader.py:72` 里才导入 fitz；线 A 仓库和线 C 的服务代码都没有 fitz |
| P2-3 | 关闭 | 依赖目录不存在、为空、闭包为空三种情况都退出 1，`versions.lock` 和 `THIRD-PARTY-LICENSES.md` 逐字节不变；lock 步路径为 `python\Lib\site-packages`；用暂存目录重新生成，53 个包和许可证表与已提交的一致 |
| P2-4 | 实质关闭 | 点名的 5 个文件都改为取常量；打好补丁的 apps/desktop 非测试代码里，旧名只剩 README；集中得不彻底，见 P3-3 |
| P-4 | 关闭 | 13 个补丁 `apply --check` 和实际打上全过；108 个改动路径与线 A 工作区逐字节一致 |
| P3-1 | 部分 | PYTHONPATH 和 pywin32 达标；用户目录 `.pth` 未达标，见 P3-1 |
| P3-2 | 关闭 | 去掉 dsh 后 `-List`、preflight、brand 都通过 |
| P3-3 | 关闭 | 重跑 engines、python 后，`stage\service` 下只有 `lawbench`，`stage\engines` 下只有两个引擎 |
| P3-4 | 关闭 | 文字已改准 |
| NOTE 2、3、7 | 关闭 | 已改 |
| NOTE 5 | 关闭 | `powershell -File … -Step "python,engines,skills"` 实测能拆开 |
| NOTE 6 | 关闭 | 已加 `--offline`（corepack 的情况见 NOTE） |
| NOTE 8 | 关闭 | 已改，有副作用，见 NOTE |
| NOTE 4 | 关闭 | `effectiveConfig` 3 种分支、提示条 2 例都有用例；做了 6 处变异，全部变红并已复原；提权运行误报已记为已知限制 |

**步骤 3 各条**

| 条目 | 结果 | 依据 |
|---|---|---|
| 1 载荷清单 | 通过（包数待更新） | 抽核 5 项 sha256 全部对上：soffice.exe `a2823391…`、pandoc.exe `8063cc4b…`、tokenizer.json `87a7830d…`、发票引擎运行环境包 `c872e5bf…`、Python 压缩包 `7c45c962…`；版本 26.8.0.3 和 3.11 都对；许可证抽核 6 个包（pymupdf、colorlog、requests、urllib3、tqdm、reportlab）与清单一致 |
| 2 离线 wheelhouse | 通过 | 回装 53 个、缺 0 个；python 步本机全程跑通，`pip --no-index` |
| 3 管理员 Skill 目录只读 | 不通过 | 见 P2-B |
| 4 electron-builder 带上 stage | 有缺口 | 新增的 2 例测试通过，DryRun 能列出文件；但缺 contracts 和工具位置，见 P2-A、P2-C |
| 5 打包后写死、忽略环境变量 | 通过 | Host 由 `process.execPath` 起（`main.ts:149` → `host-process.ts`），"exe 旁有 `resources\app.asar`"这个判断有效；开发期仍能用环境变量；4 处变异都变红 |
| 6 PyInstaller | 属实 | 本机线 B、线 C 的 Python 和 PATH 上都没有，确为候补 |

无外网下载：`packaging` 下的脚本里没有 `Invoke-WebRequest`、curl、`pip download` 的实际调用，只出现在注释和提示文字里。

**第一轮通过项回归**
- 品牌生成可重复：二进制图片逐字节相同；`logo\` 目录树哈希仍为 `37a5c11`。
- 内置 Python 哈希在 build 步核对通过。
- 启动自检、缓存路径 110 字符边界、T26 三例：都在 dsh-ext 全量测试里通过。

## 八项清单
- **契约一致**：通过。没改契约；但打包布局漏带契约目录，见 P2-A。
- **边界输入**：通过（gen_lock 三种情况、110 字符边界）。
- **错误路径**：部分通过（P2-B、P3-4）。
- **日志不含正文**：通过（只加了一条 `config.packaged_layout`）。
- **路径闸门未被绕过**：通过。打包后不读 `LAWBENCH_SKILLS_DIR`、`LAWBENCH_ENGINES_DIR`、`LAWBENCH_SERVICE_*`，有用例和变异为证。
- **无外连**：产品侧通过；构建机侧见 corepack 那条 NOTE。
- **测试覆盖新代码**：部分通过。ACL 脚本没有"能读"的检查；暂存解释器加 `._pth` 后没有重跑服务测试。
- **无机密入库**：通过。证据和提交里没有用户名、没有 Key。

## 实际跑过的命令
- git：rev-parse、status、show、diff；在实验 dsh 里按顺序 `apply --check` 并打上 13 个补丁，与线 A 工作区逐字节比对；在整棵树里 grep "DeepSeek Harness"。
- dsh-ext：`test.mjs` 全量，31 个文件、491 通过、5 跳过；`tsc`、`build.mjs` 通过；6 处变异。
- 检查脚本：`check_ui_words` 零命中；`check_examples` 通过；`check_plugin_tree --inventory-overlay` 和 `mutate_check` 通过，另做了一次新表达式模拟。
- apps/desktop vitest 全量：失败 11 项。其中 upload-with-credentials 7 项和 profile-mcp 1 项是基线；desktop-build-commit、package-target-errors 各 1 项是机器负载超时，单独重跑通过；另有 desktop-host 的 office.spec 1 项，属此前既有。windows-signature 那两项这次通过。
- `repack_wheels.py`。
- `build.ps1`：python、engines、skills（经 `-File` 传逗号串）、重跑、package `-DryRun`、package、`-List`；去掉 dsh 后跑 preflight 和 brand。
- `gen_lock.py`：三种错误情况，加一次正常重新生成。
- `._pth` 三组实验；rapidocr 导入加藏包对照。
- 暂存解释器跑服务测试（线 A 的服务树）：927 通过、10 失败、8 报错。除 `test_main` 2 例来自 P2-A 外，其余都是实验路径太长（appdata_too_long）这类环境原因。
- 起服务探 `/health` 两次。
- 在实验目录里跑 ACL 脚本，跑完 `icacls /reset` 复原。
- 5 项哈希、许可证元数据抽核；查 PyInstaller。

## 残留审计
- 进程：我起的服务 PID 40272、13188 都已按 PID 结束；没有残留的 python 进程。
- 端口：19371–19379 无监听。
- 实验目录 `rv-A27-lab`：先拆掉 89 个联接，确认一个不剩，再用长路径前缀删除，目录已不存在。
- 线 A：`dsh`、`dsh-ext` 的 `node_modules`、`packages`、`apps` 抽查完好，`git status` 仍是 108 项。
- `rv-A27` 克隆保留，状态干净。

## 证据缺口
- 没有真跑 electron-builder 出包，也没跑 DSH 的 `pnpm build`。
- 服务全部测试没在短路径、有 LibreOffice 的环境里复现作者的 945/0。
- 线 C 的证件识别驱动测试没在暂存解释器下跑。
- 没确认那次 `%TEMP%` 清理是谁触发的（像是系统的存储清理）。

AMEND
﻿
---

## 第二部分 主编排裁决（2026-10-02 10:17 (+08:00)，无人值守窗）

**结论：AMEND，返修一轮，清单冻结。** 第一轮四条 P2 全部关闭并复现（53 包回装缺 0、gen_lock 三种错误退出 1 锁不变、P-4 补丁 108 路径逐字节一致）；步骤 3 的载荷清单哈希抽核全对、wheelhouse 本机跑通、打包后忽略环境变量有变异守。新缺口在打包布局：

| 编号 | 裁决 |
|---|---|
| P2-A 打包布局缺 `contracts\`，装好后 `/health` 500 | 必修：python 步把 `contracts\` 拷进 `stage\contracts`（服务 `REPO_ROOT = parents[2]` 口径）；DryRun 缺项检查与载荷清单补；**用带 `._pth` 的暂存解释器重跑服务全量**（现在 `test_main` 2 例红） |
| P2-B `set-skills-acl.ps1` 让已有文件谁都读不了 | 必修：目录设权限不带 `/T`，再对 `"\*"` `icacls /reset /T /C` 让文件继承；`-Verify` 加"读已有文件、读下层文件" |
| P2-C 随包 LibreOffice/pandoc 在 `tools\` 但服务/小工具不在那找，自检却报就绪 | 必修（跨线，主编排定）：**Host 打包后给服务子进程 PATH 前置 `tools\libreoffice\program;tools\pandoc` 并传 `LAWBENCH_SOFFICE`/`LAWBENCH_PANDOC`**；服务侧 `find_soffice`/pandoc 探测优先读这两个变量——归线 C 小项（主编排另发）；`tools/convert/finder.py` 对齐 `tools\` |
| P3-1 `._pth` + `import site` 仍执行用户目录 `.pth` | 一并做：改准补记二、PATCHES.md、交付说明；线 C 子进程 `PYTHONNOUSERSITE=1` 仍必须做（随 P2-C 小项） |
| P3-2 `check_plugin_tree.py` `EXPECTED_SKILL_DIRS` 旧写法 | 一并做：同步新表达式 |
| P3-3 产品名未完全集中（`strings.nsh` 6 处、mac 麦克风说明）；PATCHES.md P-4 未登记新改文件 | 一并做：NSIS 用 `\`、mac 文案用常量；补登记 |
| P3-4 重跑 python 步删掉 tools 步放的 `tokenizer.json`；DryRun 不查 `tools\`/`tokenizer.json`/`contracts\` | 一并做：Reset 只清自己放的；DryRun 补查 |
| NOTE `names.txt` autocrlf 噪声、spec 单引号 `\n`、包数 50→53、`COREPACK_ENABLE_NETWORK=0`、dryrun 输出截断 | 一并做 |
| 此前既有：`gen_lock.py` dsh 未检出时记外层提交号；`desktop-host/office.spec` 稳定失败 | 记独立后续 |
| 无关新发现：网页界面包里多处"DeepSeek Harness"（插件管理、模型设置、文档预览、账号引导、system prompt 身份句） | 记 T20 独立项"界面残留品牌核对"（看得到的才改） |
| 环境：09:47 有东西按年龄清理 `%TEMP%`（删了复核克隆的空 `dsh` 目录、旧 pnpm 文件） | 上候 owner 知悉 N59；主编排后续复核克隆改放 `D:\lawbench-rv\` |