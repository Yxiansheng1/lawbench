# T20 第二版前修法关闭 + 第二版候选包 · 独立复核记录（PASS）

- 复核时刻：2026-10-05 11:40–11:50 (+08:00)；复核员：一名 Opus 只读复核员（克隆 `D:\lawbench-rv\rv-A44`，实验目录 `rv-A44-exp`）
- target：line-A `0093ba1`（令 1038 修法）、`ef1cdc8`（第二版包构建改动与证据），基座 `e537126`
- 安装包：`packaging\out\lawbench-0.1.0-win-x64-unsigned.exe`，779999352 B，sha256 `8f15e75b2c07b44296aa0d1914a4210c89b34b5ca569dfdd10b026f9aaa64841`（复核员与主编排各自算得一致；不入库）
- 裁决（主编排）：**PASS**，合并 line-A 整条进 main。P3-1 注记线 A 随下一轮小修；P3-3（DSH 自带 primary-runtime 内未签名 Python）令线 A 查明是否用到；其余记独立后续。

## 复核员报告（原文，路径已去用户名）

**Verdict: PASS**。上一轮冻结 5 条全部关闭；哈希、证据数字、补丁链、锁文件、包内容抽查都对得上。剩 1 条范围内 P3 与 3 条独立后续，不阻断。

### Target
- 克隆 HEAD `ef1cdc8`，父提交 0093ba1、e537126。0093ba1 改 7 文件（+135/-8）；ef1cdc8 改 7 文件（P-4 补丁、runtime-lock 9709 行、三份证据、截图、交付说明）。

### 冻结清单逐条关闭
**P2-1 已关闭。** `supervisor.ts:163-177` 每次 startup_timeout 计数 +1，到 `MAX_STARTUP_TIMEOUTS=2` 先代次 +1 再 kill，旧代次退出在 onExit 第 202 行直接返回不再重启，随后 `setState('failed')` 写一条 `service.start_failed {reason:'startup_timeout'}`。第一次超时仍受 60 秒窗限额。计数在进入 running 和 start() 清零；非超时退出不清零（NOTE-1）。用例走真实流程（虚拟时钟每 probe +10 秒），断言 spawns==2、start_failed 只写一条、文案正确；单跑通过；去掉计数会失败，能抓回归。

**P2-2 已关闭。** build.ps1:180 把 sitecustomize 拷进 `python\Lib\site-packages\`；包内 `python312._pth` 为 `DLLs / Lib / Lib\site-packages / ..\service / import site`。在 `rv-A44-exp\simpy` 用本机官方 3.12 搭同布局 `-I` 跑：有 sitecustomize → 被导入、isolated=1、stderr utf-8、异常行中文完好；移走 → stderr gbk。stdout 仍 gbk 但不影响（就绪靠 `/health`，Host 只收 stderr，index.ts:572）。invoice runner 本就按 utf-8 解码；convert/driver 丢弃 stderr。包内 sitecustomize 与仓库一致。`stderr-encoding.spec.ts` 两条实跑（cp936 未跳过），能抓"删 reconfigure"，抓不住"拷错位置/_pth 去 import site"（NOTE-2）。

**P2-3 已关闭。** 函数抄到 `rv-A44-exp\scrub.mjs` 跑，线 A 6 条用例全符合；刁钻输入 `\\?\D:\…`、路径后中文标点、`D:/`、`E:\law2`、`file:///D:/…`、WinError 32 双引号路径均不漏名。残留见 P3-1。

**P3-1 已关闭**（build.ps1:306 空清单 return）。**P3-2 已关闭**（注释与交付说明均改）。

### 第二版包核对
- 哈希一致。补丁链：`rv-A44-exp\dsh` read-tree 477b4f4 + 16 个 `git apply --cached` 全 exit 0，148 路径；installer.nsh 内 `!macro customInstall` 仅 1 个；DSH customInstall 第 241 行 `!insertmacro lawbenchAfterInstall`，在 SetErrors/ClearErrors 之前；宏内 `Push $0/Pop $0` 成对。
- `runtime-lock\pnpm-lock.yaml`：盘符绝对路径、/Users/、用户名、authToken、`sk-`、password 0 命中；`file:` 均为相对 tarball。
- 证据数字：解释器 31 行全 Valid（PSF + 2 个 Microsoft vcruntime）；未签名分项合计 210；stage 口径二进制 339；载荷 1548 MB——与 build.txt、交回件一致。

### 包内容抽查（7za 只读解到 `rv-A44-exp\pkg`，12955 文件，未运行任何程序）
安装根 `THIRD-PARTY-LICENSES.md`、`tools\pandoc\COPYING.rtf`/`COPYRIGHT.txt` 在；`python\` 下 pyc 0、`Scripts\*.exe` 0；`python\python.exe`、`python312.dll` 签名 Valid（CN=Python Software Foundation）；`skills\manifest.json` source 为 `"skills"`；用户名搜索命中均为词表/测试数据，`sk-` 0 命中。

### 测试
vitest 617 通过 / 6 跳过 / 1 失败（brand.spec 读 `dsh\apps\desktop\scripts\lawbench-product.mjs` ENOENT，克隆 dsh 未打补丁，环境问题，与线 A 618/6 等价）；tsc exit 0。借用联接已 rmdir 撤掉，线 A 目录完好。

### Findings
**P3-1 不带引号、最后一段带空格的路径仍漏空格后的部分**（范围内，不阻断）：`OSError: cannot open D:\案卷\x\起诉书 张三.pdf` → `<路径> 张三.pdf`；`\\fs01\案卷\张三 诉 李四.docx 读失败` → `<路径> 诉 李四.docx 读失败`。Python 内置 OSError 用 repr 带引号，只有自写 f-string 触发。证据：`scrub.mjs` 末三条；scrubPaths 第二个正则末段 `[^\s\\/"'<>|]*`。最小修复：不带引号的路径吞到行尾或最后一个 `\.\w{1,5}\b`（宁多吞），补用例。

**P3-2 PATCHES.md P-4 说明未随改名更新**（独立后续）：第 176、182 行仍写"加 `customInstall`"；第 176 行记 `windows-directory-installer.spec.ts` 通过，但重名冲突到 NSIS 编译才暴露。

**P3-3 signcheck 只覆盖 stage，包里 DSH 自带 primary-runtime 内有未签名 Python**（独立后续，第一版已有）：`resources\runtime\primary-runtime\dependencies\python\python.exe`、`python312.dll` NotSigned（python-build-standalone），该运行时下 8464 个文件；resources\ 下另有 158 个二进制不在清单。若 lawbench 会调用它，开智能应用控制的机器会同样被拦。最小修复：signcheck 纳入 resources\；查明是否用到，用不到剔除，用到并入 N73。

**NOTE-1**：超时计数为"上次就绪以来累计"非严格连续；failed 需重启程序恢复（index.ts:603 只 start 一次）；新机首启 Defender 扫描/冷启动若连续两次 >30 秒会停在"请联系技术支持"（主编排定 2 次，知悉）。
**NOTE-2**：可在 build 步加 `python -I -c "import sys;assert sys.stderr.encoding=='utf-8'"`。
**NOTE-3**：包内 `engines\retainer\docs\*` 开发日志含律所工具作者机器路径（非本机用户、无 Key），第一版已有、engines 原样使用；3.12.10 少几个安全补丁已写明；`versions.lock` 仍记 3.12.14 为线 A 遗留。

### 实验目录
`rv-A44-exp`：`dsh`（补丁链克隆）、`pkg`/`pkg2`（解包约 323 MB，可删）、`pkg-list.txt`、`scrub.mjs`。
