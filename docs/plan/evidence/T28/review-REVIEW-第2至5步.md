# T28 第 2–5 步 · 独立复核记录（AMEND）

- 复核时刻：2026-10-06 15:12–15:52 (+08:00)；复核员：一名 Opus 只读复核员（克隆 `D:\lawbench-rv\rv-D1`，实验目录 `rv-D1-exp`）
- target：line-D `ff0a0f9`（service 平台隔离）、`19dfe65`（dsh-ext + P-22）、`381457a`（packaging\mac）、`0c58b2a`（工作流）、`306450b`（交付说明）；基座 main `27b1f78`；39 文件 +1940/-32
- 裁决（主编排）：**AMEND**。Windows 不变量成立（本卡最高不变量）；返修限工作流两条 P2 + 五条小 P3（令 `致D-ORCH-执行令-第2至5步复核AMEND-工作流权限与钉版-<HHMM>.md`）；P3-2、P3-6 记后续，真机/首跑核。

## 复核员报告（原文，路径已去用户名）

**结论：Windows 行为不变这一条成立。** service、tools、dsh-ext 和 P-22 的每一处改动都在 darwin 分支或默认取平台的参数后面，Windows 那一支字节不变或等价；各套用例数字与线 D 自报一致。需返修的是工作流：权限太宽、第三方 action 未钉 SHA。**AMEND**。

### 1. 复核对象
HEAD 306450b；`git diff --stat 27b1f78..HEAD` 39 文件 +1940/-32；区间含盘点提交 458c2a7（只文档）。

### 2. Windows 不变量（逐文件读 diff）
`procs.py` `own_group()` nt 返回 `{}`，`kill_tree` nt 分支未动、darwin 新 elif；`libreoffice.py`/`driver.py` Popen 多传 `**procs.own_group()` Windows 展开空字典；`gate.py` 同步名单/同步根/UTF-8 字节长度只 darwin；`convert.py` `wintypes` try 导入 Windows 照常、darwin 分支提前返回；`config.py`/`pandoc.py`/`invoice/runner.py`/`finder.py` darwin 提前返回或报错；`install-layout.ts` win32 三函数逐行相同、`checkPython` 等价；`host/index.ts` `passThroughEnv` 与 `scrubPaths` win32 不变；`credentials/index.ts` win32 仍 credman、`SOURCE` 不变、新导入无副作用；`file-log.ts` 不变；`cordis.patch.yml` 5 个 `!!js` 表达式 win32 分支逐字相同；`ui/settings.tsx` `keyStoreName()` Windows 文案逐字相同、`converterOptions` 非 Mac 返回原 `CONVERTERS`；`ui/invoice.tsx` 多包一层渲染相同；`ui/platform.ts` 读 `navigator.platform`/`userAgent`，Electron 渲染进程稳定。

### 3. P-22 对 Windows 包的影响
`rv-D1-exp\dsh`（固定提交 477b4f42…）按 PATCHES.md 顺序 17 个补丁 `git apply --cached` 全 exit 0，152 路径。win32 打包时 `packagesMacOS=false`、`macAdhoc` 恒 false：identity/forceCodeSigning/hardenedRuntime/notarize/target/dmg.sign/update/afterSign/artifactBuildCompleted 取回原值；`extraFiles` 条件多一恒真项；`extraResources` 不加载荷；`package-target.ts` win32 等价；isolation/retainer win32 原分支；`WelcomePage.tsx` Windows 文案相同（拆为相邻文字节点）。**无影响。**

### 4. 用例与变异
service `test_t28_macos.py` 20 passed（1284→1304）；tools 69；dsh-ext 638/6；tsc 0；brand.spec 首跑环境缺文件、补入后 5/5。
变异：M1 gate 不追加同步根 抓到；M2 kill_tree 不 killpg 抓到；M3 驱动 env 用 Windows 名单 抓到；M6 去 UTF-8 字节检查 抓到；**M4/M5 Popen 去 own_group 没抓到**；K1 Key 进 argv 抓到；K2 Key 明文进 stdin 抓到；K4 darwin 去路径退回 Windows 版 抓到；**K3 可信程序列表去 python3 没抓到；K5 darwin SOURCE 仍 windows 没抓到**。

### 5. keychain.ts
Key 只经 `security -i` 标准输入、十六进制（`-X`）、不进 argv；stderr 丢弃、报错只带退出码；写完读回核对；超时 15 秒同 credman；退出码 44 = 无条目；条目名 `service=lawbench/LAWFIRM_KEY`/`account=lawbench` 与 `app.py` `KEYRING_SERVICE`/`KEYRING_USER` 一致；拒非 ASCII 理由成立（`-w` 遇不可打印输出十六进制）；`-T` 三项：`/usr/bin/security`（必需）、Host execPath（多余无害）、内置 python3（服务端 keyring 在 Python 进程内调 Security 框架，有用）；ad-hoc 下 ACL 绑 cdhash（P3-2）。

### Findings
- **P2-1 工作流权限太宽**（范围内阻断）：顶层 `permissions: contents: write` 覆盖全部步骤；`actions/checkout` 默认把 token 留在 `.git/config`；build 步跑 npm 安装脚本与 PyPI 最新 pyinstaller——第三方代码可读可写仓库 token。证据 `mac-build.yml:11-12,26`。修法：顶层 `contents: read`；checkout `persist-credentials: false`；建 release 拆独立 job 单独 `contents: write`；smoke job 若需下载草稿单独授权。
- **P2-2 action 未钉 commit SHA**（范围内阻断）：`checkout@v4`、`setup-node@v4`、`cache@v4`、`upload-artifact@v4`（`mac-build.yml:26,31,39,82,96,114`）。修法：`@<40 位 SHA> # v4.x.y`。
- **P3-1 运行时 Python 往签好名的 .app 写 pyc**（独立后续，真机核）：`python3 -I -m lawbench` 从 `/Applications/<名>.app/Contents/Resources` 起，`-I` 忽略 `PYTHONDONTWRITEBYTECODE`，Mac 默认用户可写 `/Applications` → 写 `__pycache__` 破坏签名封印；`build.sh:128` 自检在清 pyc 之后又无 `-B`。修法：启动命令与 build.sh 自检加 `-B`。
- **P3-2 ad-hoc 下钥匙串 ACL 跨版本可能失效**（臆测，真机核）：`-T` 记 cdhash，重打包即变；`-U` 覆盖不更新 ACL → 升级后读 Key 可能弹窗或读不到。修法：先删后加；真机验证。
- **P3-3 测试缺口**：Popen 收到 own_group（M4/M5）、macStore 列 python3（K3）、darwin SOURCE（K5）各补一条断言。
- **P3-4 冒烟"无外连"证据偏弱**：`smoke.sh:76-84` 启动后 ~15 秒 lsof 一次；`pgrep` 空时 lsof 失败、结果空、仍判"127.0.0.1 only"（空过）。修法：PIDS 空判失败；启动起每秒采样。
- **P3-5 无 tokenizer 包标注不显眼**：`LAWBENCH_ALLOW_NO_TOKENIZER=1` 写死；dmg 名与程序看不出。修法：dmg 名加 `-smoke-no-tokenizer`。
- **P3-6 Mac 小工具 PyInstaller 未钉版**（`build.sh:174` 取最新；bootloader 随 .app 发出，"不随包发出"不准确）。修法：`[mac]` 段钉版本与哈希。
- **P3-7 `test_t28_macos.py` 单独跑 8 个 ERROR**：`darwin` fixture 先改 `sys.platform`，pytest 首建临时目录调 `os.getuid`。修法：fixture 先 `tmp_path_factory.getbasetemp()`。
- **NOTE**：手动触发；不引用 `secrets.*`；release draft+prerelease、日志 artifact 14 天；外部来源只有 python-build-standalone/TDF/pandoc raw.githubusercontent/PyPI/npm·corepack/GitHub 上游；`[mac]` 5 项发布方 sha256、`fetch()` 每次核；pip 轮子"首次记录"同 Windows；草稿 release 需人工删；build.sh/sign-adhoc.sh 照裁决 3（由内到外、不 `--deep`、LibreOffice.app 排除保留原签名并核验）、`set -euo pipefail`、载荷与 build.ps1 一致（engines 去 `env-win_amd64.zip`）、清 pyc、`python3 -I` 自检、小工具并排、stage/.app 扫 Key 与家目录；`gen_lock.py` 不冲 `[mac]`；无用户名。

### 跑过的命令（摘要）
`git rev-parse/diff`（rv-D1）；`git clone --no-checkout --shared D:\lawbench-A\dsh rv-D1-exp\dsh` + `read-tree 477b4f42` + 17 次 `apply --cached`；`D:\lawbench-C\.venv\Scripts\python.exe -B -m pytest tests\test_t28_macos.py --basetemp=…`（PYTHONPATH 指克隆 service）；tools pytest；dsh-ext robocopy `/E /XJ` + 12 联接 + `node scripts/test.mjs` + `tsc --noEmit`；变异脚本 `mut.py`/`mut6.py`/`mut-ts.py`（改后均还原，`git status` 干净）；收尾 rmdir 三个借用联接，A 目录完好。未进 `D:\lawbench-D` 与各线目录（只读借用 A 的 node_modules/packages 与 `git log -1`）。约 40 分钟。
