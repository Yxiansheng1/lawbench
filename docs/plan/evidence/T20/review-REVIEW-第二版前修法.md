# T20 第二版前修法 · 独立复核记录（AMEND）

- 复核时刻：2026-10-05 10:27–10:38 (+08:00)；复核员：一名 Opus 只读复核员（克隆 `D:\lawbench-rv\rv-A43`，实验目录 `rv-A43-exp`）
- target：line-A `038113c`、`2fd1f03`（基座 `25e1bef`，26 文件）；对应令 2015/2033/2048、注记 2053
- 裁决（主编排）：**AMEND**，三条 P2 均在 dsh-ext Host、随包交付，先修再打第二版（令 `致A-ORCH-执行令-第二版前修法AMEND-先修三条再打包-20261005-1038.md`）。P3 两条一并修；NOTE 三条记录。

## 复核员报告（原文，路径已去用户名）

**Verdict：AMEND**

两处问题让令 2033、令 2048 要的"服务起不来时说出原因"在要紧场合失效：
- 服务 30 秒没就绪的情形永远到不了 failed，界面一直是"请稍后重试"。
- 中文 Windows 上，取到的异常消息中文部分是乱码，偏偏就是律师要看的那句"应用程序控制策略已阻止此文件"。

另有一处日志会带出材料名和案件文件夹名，违反 Spec"日志只记元数据"。其余各项做到了。

### 范围核实
- 克隆 HEAD `2fd1f03`，两提交在 `25e1bef..2fd1f03` 内；26 文件与 `--stat` 一致；无无关改动。
- 必需实现：`host/index.ts`、`host/supervisor.ts`、`host/install-layout.ts`、`host/selfcheck.ts`、`ui/settings.tsx`、`ui/cases.ts`、`tools/convert/finder.py`、`packaging/build.ps1`、`runtime-lock-compare.mjs`、`P-4-brand.patch`、`set-skills-acl.ps1`、`installer/README.md`、`skills/_scripts/install.py`、`THIRD-PARTY-LICENSES.md`、`gen_lock.py`。必需验证：五个 spec、`test_convert.py`、证据与文档五件。

### Findings

**P2-1 服务 30 秒没就绪时永远到不了 failed**（范围内阻断：令 2033 第 2 条）
- 影响：每 30 秒杀掉重启，状态一直 `starting`，律师一直看到"工作台服务未启动，请稍后重试"，不写 `service.start_failed`。
- 原因：`supervisor.ts onExit` 重启限额"60 秒内 >3 次"，每轮 ≥30 秒最多攒 2 次。
- 证据：`rv-A43-exp\timeout_loop2.mjs`（虚拟时钟）输出 `final state starting … startup_timeout 9 restart 9 start_failed 0`；现有用例只测文案 `startFailureText({reason:'startup_timeout'})`。
- 最小修法：连续 startup_timeout 单独计数转 failed；补流程用例。

**P2-2 中文系统上异常消息中文乱码**（范围内阻断：令 2048 第 3 条）
- 原因：`python.exe -I -m lawbench`（`install-layout.ts:35`），`-I` 忽略 `PYTHONIOENCODING`/`PYTHONUTF8`，stderr 接管道按 cp936；Host `readFrom(0).text` 按 UTF-8 解码。
- 证据：本机 ACP=936；`rv-A43-exp\enc.py` 用 `python -I` 抛同一异常重定向后按 UTF-8 读得 `ImportError: DLL load failed while importing _sqlite3: Ӧ�ó�����Ʋ�������ֹ���ļ���`；`sys.stderr.encoding` 为 gbk；`service-start-error.spec.ts` 直接用 UTF-8 字符串输入，测不出。
- 最小修法：命令加 `-X utf8`（确认服务 `open()` 默认编码无副作用）或 Host 解码失败退回 ANSI 代码页；补 GBK 字节用例。

**P2-3 去路径处理不全，日志会带出材料名、案件文件夹名**（引入的回归：Spec"日志只记元数据"）
- 证据：`index.ts scrubPaths` 复制到 `rv-A43-exp\scrub_check.mjs` 实测：网络路径 `\\fileserver\案卷\张三诉李四\起诉状.docx` 原样留下；带空格路径从空格后全留；安装目录外路径只去目录留文件名，用例断言 `FileNotFoundError: x.txt`。
- 触发面：服务处理材料时反复崩溃到 failed，末条异常行入 `service.start_failed`。
- 最小修法：安装目录外绝对路径（盘符、`\\`、引号内带空格）一律换 `<路径>` 不留文件名；改掉该断言。

**P3-1 `-SignCert` 给了但待签清单为空时 sign 步报错停下**（范围内）
- PS 5.1 下 `$todo.Count=0` 时循环 `0..-1`，第二轮 `Select-Object -Skip -50` 报错，`$ErrorActionPreference='Stop'` 下中断构建（签过再重跑场景）。修法 `if ($todo.Count -eq 0) { return }`。

**P3-2 注释过时**（独立后续）：`StartFailure` 注释"不含服务输出"与 `error` 字段矛盾；交付说明令 2033 一节未标注被 2048 取代。

**NOTE**
- 安装包本身不签名：`-SignCert` 只签 stage 内文件，"安装包在 package 步之后签"未实现（已披露偏离）。
- 签名清单按包分组每包最多 6 个文件名，非"逐个列出"。
- 安装器改动实效（目录名、删 updater、Skill 目录询问）待重打包后核；机制读源码正确（自定义 include 在模板前、`APP_FILENAME` 由 `-D` 传入；updater 整包拷贝发生在 `customInstall` 之前）。

### 已做到且有证据
- 令 2033：安装根按 exe 目录推断（E:\law 用例）；程序不在只记相对路径 `PYTHON_MISSING`；`launch_error` 分类；`NOT_CONFIGURED` 不记 warn；updater 成因核清、P-4 装完删除。
- finder.py 只看 `sys.executable` 上上级、不读环境变量；系统无 pytest，改 `rv-A43-exp\finder_check.py` 复算：`soffice True pandoc True`，开发期返回 `[]`。
- stderr 缓存上限 `maxBytes: 65536`（DSH `subprocess/src/types.ts` 不配 spill 只留尾部）。
- 自检降级只对"目录不存在"降 info；存在但可写仍 warn。
- 令 2015：pandoc `COPYING.rtf`/`COPYRIGHT.txt` 缺则停；许可证表入安装根；`pip --no-compile` 后删 pyc 与 `Scripts\*.exe`（在 ensurepip/pip 之后，不伤解释器）；manifest 相对路径；三处文字；0x08 为 0；窗口标题。
- build.ps1：sha256 不匹配 `throw`；锁对账不一致非零退出 `throw`，在拷进 out\ 之前；无证书 sign 步打印 UNSIGNED。
- 补丁链：DSH `477b4f4` 按 PATCHES.md 打 16 补丁全 exit 0，148 路径与线 A 工作区 blob 逐一相同。
- `set-skills-acl.ps1` 默认 `%ProgramData%\lawbench\skills`；README 与整个 diff 无用户名、无 Key 模式。

### 测试
- `tsc --noEmit` exit 0；vitest 613 通过 / 6 跳过 / 1 失败（`brand.spec.ts`：克隆缺 `dsh\apps\desktop\scripts\lawbench-product.mjs`，环境缺口；手工核 `LAWBENCH_VERSION='0.1.0'` 与 `PRODUCT_VERSION` 一致）。

### 跑过的命令（只读）
`git diff/show 25e1bef 2fd1f03`；`git -C D:\lawbench-A\dsh log -1`；`git clone --no-checkout --shared … rv-A43-exp\dsh` + `read-tree 477b4f4` + 按序 `git apply --cached` + `hash-object` 比对；robocopy node_modules `/E /XJ` + 12 个联接 `mklink /J`；`tsc --noEmit -p .`；`node scripts\test.mjs`；`python -I enc.py`；`node scrub_check.mjs`；`node --experimental-transform-types timeout_loop2.mjs`；PS 5.1 复现 sign 步报错。未跑构建、`npm`/`pip install`；未进各线工作目录。
