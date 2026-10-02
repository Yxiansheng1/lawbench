# T20 准备（品牌与 P-4、内置 Python、锁与许可证、build.ps1 骨架、启动自检、缓存路径）+ T26 三条记录项 · 独立复核记录（第一轮）

- 复核员：一名 Opus 5.5 只读复核员（首次派出被用量上限杀停，本记录为重派后的完整报告）
- target：line-A `46ed38e`；范围 `754b6b8`、`d8671e8`、`46ed38e`
- 复核克隆：scratchpad `rv-A26`
- 归档：主编排于 2026-10-02 08:39 (+08:00) 从复核员交回原文抄录，未改内容（无人值守窗）

## 第一部分 复核员原文
# T20 准备 + T26 三条记录项 · 独立复核（rv-A26，line-A `46ed38e`）

我亲自核过 HEAD：`46ed38e`，`git status` 干净。范围是 `754b6b8`、`d8671e8`、`46ed38e` 三个提交，共 38 个文件，新增 1607 行、删除 4 行，与派单一致。
- 没有碰 T17 的会话存储和路由：`host/index.ts` 只加了 `selfCheck`。
- 没有改 T26 的业务逻辑：`http-json.ts` 和 `fake-tools.mjs` 都没动，只加了测试和 `fake-tools.d.mts`。
- 上一名复核员留下的 `rv-A26-lab` 已清掉：先解开里面 1 个联接，再删目录。

## Findings

**P2-1 · 锁文件漏了证件识别驱动的三个运行时依赖，打出来的包里证件识别会起不来**
- 问题：`versions.lock` 的 `[client.pip]` 没有 `colorlog`、`requests`（连带 `urllib3`）、`tqdm`。原因是 `gen_lock.py` 的 `EXTRA_ROOTS` 只列了 onnxruntime、opencv 等，没有列 rapidocr 自己要的依赖。
- 依据：
  - 驱动内附的 `vendor/rapidocr/main.py` 在模块顶层导入 `utils.log`（要 colorlog）、`utils.load_image`（要 requests）、`download_models`（要 requests 和 tqdm）。
  - T25 交付说明 P12 把这几个包都列成驱动依赖。
  - 作者的 945 项测试用的是线 C 的 `.venv`，里面恰好装了这几个包，所以没暴露出来。
- 实测：用线 C 的解释器加 `-I`，把这几个包屏蔽掉之后 `from rapidocr import RapidOCR`。只屏蔽 colorlog 时报 `ModuleNotFoundError: colorlog`；放开 colorlog、只屏蔽 requests 和 tqdm 时报 `requests`。三个包在 `[client.pip]` 里都查不到。
- 影响：照锁文件装出来的客户端 Python 起不了证件识别驱动。
- 最小修复：`EXTRA_ROOTS` 加上 `colorlog`、`requests`、`tqdm`，然后重跑 `gen_lock.py`。另外，`omegaconf` 已经随驱动内附在 `vendor/` 下，不用再标"候补"。
- 归类：范围内阻断（步骤 5）。

**P2-2 · PyMuPDF 是 AGPL-3.0，在许可证清单里写成"候补"，没有像 pandoc 那样报给主编排**
- 依据：PyMuPDF 1.28.2 元数据的 License 字段原文是"GNU AFFERO GPL 3.0 or Artifex Commercial License"，66 个字符；`license_of()` 只收短于 60 字符的写法，这个包又没有 License 分类，结果落成"候补"。交付说明和交回件只点了 pandoc 的 GPL。
- 影响：随安装包分发 AGPL 组件要承担对应义务，而主编排没收到提示。
- 最小修复：`license_of` 对较长的 License 字符串不要直接丢掉；`THIRD-PARTY-LICENSES.md` 里给 PyMuPDF 标 AGPL-3.0，并在交付说明"请主编排定"里补一条。
- 归类：范围内阻断（步骤 5 要求"无遗漏"）。

**P2-3 · `build.ps1` 的 lock 步路径写错，`gen_lock.py` 遇到空目录又不报错，会悄悄把已提交的锁文件清空**
- 问题：
  - `build.ps1` 第 112 行传给 `--site` 的是 `stage\python\site-packages`，而 python 步实际装到 `stage\python\Lib\site-packages`（第 83 行）。
  - `gen_lock.py` 拿到不存在的目录不会报错。
- 实测：给一个不存在的 `--site`，输出"[client.pip] 0 个包；候补 23 个"，`versions.lock` 和 `THIRD-PARTY-LICENSES.md` 都被改写；下一次 python 步会因为"no [client.pip] pins"停下。
- 最小修复：第 112 行改成 `python\Lib\site-packages`；`gen_lock.py` 在目录不存在或闭包为空时直接报错退出。
- 归类：范围内（骨架缺陷，今晚的路径走不到这一步）。

**P2-4 · P-4 改了产品名，但打包烟测脚本里还写死旧的 exe 名，`package:win:x64` 会在烟测这一步失败**
- 依据：打完全部补丁后：
  - `apps/desktop/scripts/smoke-packaged-runtime.ts:19` 仍找 `win-unpacked\DeepSeek Harness.exe`，而 Windows 打包路径在 electron-builder 之后一定会跑它（`package-target.ts:497`）。
  - 同类残留：`package-target.ts:492`、`package-macos.ts:81`（mac 的 `.app` 名），`electron-builder.config.d.mts:7` 的类型字面量，`installer/extract-report.h:117` 的安装器报错文案。
- 影响：现在 package 步标了"候补"，跑不到这里；到 T20 步骤 3/6 出包时必然撞上。
- 最小修复：P-4 里把这几处一起改，或改成从 config 的 `productName` 取值，然后重新导出补丁。
- 归类：范围内（P-4 没改全），当前没有阻断。

**P3-1 · 子进程隔离只做了一半：用户目录里的 `.pth` 仍会执行代码、加路径**
- 实测：在实验目录的 APPDATA 下放一个用户 site-packages 的 `.pth`。不带 `-I` 启动时，加了 sitecustomize 也照样执行了那段代码，额外路径照样能导入；带 `-I` 时干净。原因是 sitecustomize 在用户 site 处理完之后才运行，只能删掉那一条路径。作者"不加 `-I` 会读用户 site-packages"的结论我已复现，属实。
- 影响：证件识别驱动这类不带 `-I` 的子进程，仍可能被律师本机装过的 Python 环境干扰。
- 最小修复：在 `<安装目录>\python\` 放一个 `python312._pth`，列出 `Lib`、`Lib\site-packages`、`..\service` 和 `import site`（这样根本不会加用户目录）；或者让服务给子进程传 `PYTHONNOUSERSITE=1`（这一条归线 C）。

**P3-2 · DSH 子模块没检出时，`build.ps1 -List`、`brand`、`preflight` 全都报错**
- 依据：第 37 行在脚本顶层就读 `dsh\scripts\primary-runtime\lock.json`。实测报 "Cannot find path …lock.json"。和"每步可单独跑"的说法不符。
- 最小修复：把这三行挪进 python 步。

**P3-3 · python 步和 engines 步重复跑会叠目录、留下旧文件**
- 依据：`Copy-Item -Recurse` 复制到已存在的目标目录时，会生成 `stage\service\lawbench\lawbench`，旧代码留在原处（我在实验目录复现了）。engines 步同理。dsh 步用的是通配符拷贝，不受影响。
- 最小修复：复制前先删掉目标目录。

**P3-4 · 交付说明"占位第 1 条"和代码对不上**
- 交付说明写 `%ProgramData%\<产品名>\skills\` 会随产品名变化；实际 `cordis.patch.yml:309`、`:362` 写死的是 `ProgramData\lawbench\skills`。交回件已经把它列为待定项，所以只需要把交付说明这句改准确。

**NOTE（不阻断）**
1. "技术支持：上海莫莱特智能科技有限公司"在 `docs\`（PRD、Spec、事实索引）里找不到原话，是从 `logo\技术公司-logo.png` 的图上读出来的。律所全称在事实索引第 118 行有原话。建议把公司全称也列进"请主编排定"。
2. 锁文件 `[client.pip]` 的注释写"-I -S 隔离运行"，但服务实际只用 `-I`（加了 `-S` 连 site-packages 都没有了），措辞要改。
3. 首页的自检提示条放在胶囊区下面、最近案件上面，交付说明写的是"首页上方"。
4. "只读"的判断用的是试写一个文件，不是 icacls。在非管理员下我实测对 `C:\Program Files` 判为不可写，没有报错；长路径设置能读到（本机为 false）。以管理员提权运行时会误报"可写"。另外 `apply()` 里"按启动命令判断要不要查 Python"的分支和界面提示条都没有用例。
5. `build.ps1 -Step preflight,brand` 只在 PowerShell 进程内调用时有效；用 `powershell -File` 调用时整串当成一个步骤名。
6. dsh 步里的 `corepack pnpm install` 没加 `--offline`，在构建机上可能连 npm 仓库。这是构建机行为，不影响产品，但和"构建只读本机缓存"的说法不完全一致。
7. 第三方许可证清单只列了许可证名，没有附全文。全文在各包的 dist-info 里，会随 site-packages 一起带上。
8. `make_brand.py` 写 `names.txt` 时在 Windows 上换行是 CRLF。因为 autocrlf=true，git 视为相同；换一台关掉 autocrlf 的机器，会显示有改动。

## 冻结清单逐条核对
1. **品牌**：
   - 我用 Pillow 12.3.0 跑了两次 `make_brand.py`，`git status` 都干净，二进制图片逐字节相同；`build.ps1 -Step brand` 再生成一次也一致。
   - `logo\` 的目录树哈希与 main 相同（`37a5c11`），原件没动。
   - 13 个补丁按 PATCHES.md 顺序 `apply --check` 和实际打上全部通过。
   - P-4 改了 23 个文件：4 个源文件（strings.nsh、electron-builder-config、locale、main.ts），8 个用例文件，11 个期望文件，没有夹带别的改动；图片不在补丁里。
   - 律所名、公司名的出处见上面 NOTE 1；占位名和"没用到 placeholder 图"在交付说明里都列了。
   - 线 A 工作区的在途改动按"只读、不对照"处理，我没有逐字节比对线 A 的 `dsh` 工作区。
2. **内置 Python**：
   - DSH 下载缓存里的压缩包 sha256 与 `lock.json` 一致，版本 3.12.14。
   - build 的 python 步：哈希不对时报 mismatch；哈希对时解压、生成 37 行 requirements.txt，然后在缺 wheelhouse 处停下。
   - `-I` 与用户 site-packages 的结论已复现。
   - `.pth` 在 `-I` 下能把 service 目录加进路径。
   - 服务测试：线 C 服务树全量 1109 通过、23 失败、16 报错；我逐项看过，都和环境有关（没有 LibreOffice、实验路径 111 字符撞上发票缓存长度、没有 git、缺 docs）。`test_retainer_driver` 12 项全过。
   - "共用解释器时驱动拿不到依赖"的理由属实：线 C `driver.py:48` 用的就是 `sys.executable`。
   - 漏依赖的问题见 P2-1。
3. **锁与许可证**：
   - 用线 C 的 `.venv` 重跑 `gen_lock.py`，37 个包与已提交的逐行一致，只有 dsh 提交号不同（我那份 dsh 克隆打完补丁后提交过，属于环境差异）。
   - `[395]` 段在 diff 里没有一行改动。
   - 我抽了 12 个包核元数据：其中 11 个与清单一致（numpy、pillow、certifi、pywin32、opencv、protobuf、pypdfium2、reportlab、shapely、mpmath、onnxruntime），pymupdf 有问题（P2-2）。
   - pandoc 的 GPL 已标出。
4. **build.ps1**：
   - `-List` 正常列出 9 步；preflight、brand 能过；tools 停下；不带 `-Package` 时 package 跳过；带 `-Package` 时 package 停下；未知步骤报错。
   - 产物全在实验目录，没有写 `packaging\out`。
   - 脚本里没有 Invoke-WebRequest、curl、`pip download` 实际调用（只出现在提示文字里），没有用户名，不读 `.env.local`。
   - 问题见 P2-3、P3-2、P3-3。
5. **启动自检**：7 个用例覆盖每一项缺失，Host 只跑一次、出错时回空。真实依赖的检查见 NOTE 4。
6. **缓存路径**：只查 `<应用数据>\ivc`，上限 110 字符，与线 C 上 T25 交付说明第 98 行"给 T20 的配合"一致；main 上的 T25 review-B 实测 124 字符就失败。有边界用例：正好 110 通过，长路径开着时放行，读不到长路径设置时提示。
7. **T26 三条**：
   - 302 那一例：去掉 3xx 分支后变红。
   - 连接断开那一例：去掉 `r.destroy()` 后变红。
   - fake-tools：把假服务 review 改成不带 confirm 也成功后变红。
   - 三处改动都已逐字节复原。
   - P-11 那 5 个用例文件我数了是 107+9+4+5+10=135 项，与 PATCHES.md 一致。
8. **独立跑的结果**：
   - dsh-ext：29 个文件，485 通过、5 跳过，与作者一致。tsc、build 通过；`check_ui_words` 零命中；`check_examples` 通过。
   - `check_plugin_tree`（加 `--inventory-overlay`）通过；`mutate_check` 的变异全部被报出。这两项只能拿已有的 T17 证据输入跑，T20 也没改插件配置。
   - apps/desktop：P-4 和 P-11 两个版本都在同一台忙碌的机器上跑过。P-4 多出 3 项失败、`main-startup` 2 项失败，单独重跑后全过（107/107 和 43/43），属于机器负载导致的超时。不算这些后，P-4 的失败就是作者说的那 10 项（profile-mcp 1、upload-with-credentials 7、windows-signature-batch 1、windows-signature-cache-directory 1，最后这一项时好时坏），P-11 时就有，确认是原来就有的基线。
9. **改动纪律**：

   | 类别 | 行数 |
   |---|---|
   | 产品代码 | 194 |
   | 构建脚本（make_brand、build.ps1、gen_lock、.gitignore） | 458 |
   | DSH 补丁 | 564 |
   | 测试 | 150 |
   | 文档与证据 | 188 |
   | 数据（versions.lock、names.txt） | 53 |

   没有无关改动。证据里只有虚构的 `C:\Users\someone`，没有 Key。

## 八项清单
- **契约一致**：通过。没改契约；`selfCheck` 进了 `REMOTE_METHODS`。
- **边界输入**：通过。110 字符边界、版本号和缺项都有用例。
- **错误路径**：部分通过。见 P2-3、P3-2。
- **日志不含正文**：通过。只记各项 id 和结果。
- **路径闸门没被绕过**：通过。没动相关代码。
- **无外连**：产品侧通过；构建机侧见 NOTE 6。
- **测试覆盖新代码**：部分通过。`apply()` 的分支和界面提示条没有用例。
- **无机密入库**：通过。

## 实际跑过的命令
- git：rev-parse、status、diff、show、grep。
- dsh 克隆加 13 个补丁的 `apply --check` 和 apply。
- `make_brand.py` 两次；`build.ps1` 的 `-List`、preflight、brand、python（含哈希不对的情形）、tools、package、未知步骤，以及去掉 dsh 后的 `-List` 和 brand。
- `gen_lock.py` 两次：正确的 `--site` 和不存在的 `--site`。
- 内置 Python 的用户目录与 `.pth` 实验；rapidocr 屏蔽依赖导入实验。
- dsh-ext：test.mjs、tsc、build.mjs，四处变异。
- `check_ui_words`、`check_examples`、`check_plugin_tree`、`mutate_check`。
- apps/desktop 的 vitest：两个版本全量，加单独重跑。
- 服务 pytest：全量，加 retainer driver。
- 真实依赖的 `canWrite`，以及 `reg query` 读长路径设置。

## 残留审计
- 进程：我起的进程（10356、7792、35316、44356、42084）都已经结束。最后一个清理任务（它的目录扫描会进入联接）我在它开始删东西之前就停了，没有执行任何删除。
- 联接：改用不进入联接的方式扫描，解开了 355 个联接（包括 pytest 自己建的 16 个），再删掉 `rv-A26-lab`。删之前确认没有剩余联接，删完目录已不存在。
- 线 A：`D:\lawbench-A` 的 node_modules 抽查完好。`dsh\node_modules\.vite` 里 8:15 的写入时间与线 A 自己的 dsh-ext 缓存同一时刻，我的 vitest 缓存全落在实验目录。
- 端口：19361–19369 没有监听（本次也没用到端口）。
- `rv-A26` 克隆保留，状态干净。

## 证据缺口
- 没跑 DSH 的 `pnpm build` 和真实打包：本机 pnpm 存储里缺包，离线装不上。
- 没在真实 wheelhouse 上装依赖。
- 服务全量测试没能在干净的短路径和有 LibreOffice 的环境下复现作者的"945/0"，只复现了驱动部分。
- 没有逐字节对照线 A 的 `dsh` 工作区在途改动。

AMEND
﻿
---

## 第二部分 主编排裁决（2026-10-02 08:39 (+08:00)，无人值守窗）

**结论：AMEND，返修一轮（并入 T20 步骤 3 准备同一批做），清单冻结。** 品牌生成可重复、原件未动、补丁链 13 个全过、内置 Python 方案与 `-I` 结论复现、启动自检与缓存路径用例齐、T26 三条记录项变异全红、无机密。

| 编号 | 裁决 |
|---|---|
| P2-1 锁文件漏证件识别驱动运行时依赖（colorlog、requests/urllib3、tqdm） | 必修：`gen_lock.py` `EXTRA_ROOTS` 加三包并重跑；`omegaconf` 已随驱动内附，去掉"候补" |
| P2-2 PyMuPDF AGPL-3.0 被 `license_of` 丢成"候补"、未报主编排 | 必修：`license_of` 不丢长字符串；清单标 AGPL-3.0；**上候 owner N58 补一条**（随包分发 AGPL 组件的义务，或换 pypdfium2/pypdf 路径——由用户定） |
| P2-3 `build.ps1` lock 步 `--site` 路径错、`gen_lock.py` 空目录不报错会清空已提交锁文件 | 必修：路径改 `python\Lib\site-packages`；`gen_lock.py` 目录不存在或闭包为空直接报错 |
| P2-4 P-4 改产品名漏了 `smoke-packaged-runtime.ts`、`package-target.ts`、`package-macos.ts`、`electron-builder.config.d.mts`、`extract-report.h` 的旧 exe 名 | 必修：改成从 `productName` 取值或一并改，重新导出补丁 |
| P3-1 子进程隔离只做一半（用户目录 `.pth` 仍执行） | 一并做：`<安装目录>\python\python312._pth` 列 `Lib`、`Lib\site-packages`、`..\service`、`import site`；服务给子进程传 `PYTHONNOUSERSITE=1` 归线 C（T25/T12 小项，主编排另排） |
| P3-2 DSH 子模块未检出时 `-List`/`brand`/`preflight` 全报错 | 一并做：读 `lock.json` 挪进 python 步 |
| P3-3 python/engines 步重复跑叠目录 | 一并做：复制前删目标目录 |
| P3-4 交付说明"ProgramData 目录随产品名"与 `cordis.patch.yml` 写死 `lawbench` 不符 | 一并做：改准（定名后统一） |
| NOTE 1 "技术支持：上海莫莱特智能科技有限公司"无文档原话、从 logo 图读出 | 上 N58 请用户确认公司全称 |
| NOTE 2/3/5/6/7/8 | 一并做：注释 `-I -S`→`-I`；交付说明"首页上方"改准；`-Step` 多步参数解析；`pnpm install` 加 `--offline`；`names.txt` 换行 LF；许可证全文随 dist-info 带上写明 |
| NOTE 4 只读判断用试写、提权时误报；`apply()` 分支与提示条无用例 | 一并做：补用例；提权误报记已知限制 |