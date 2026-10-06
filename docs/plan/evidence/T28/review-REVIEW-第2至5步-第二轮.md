# T28 第 2–5 步 AMEND 修法 · 独立复核记录（第二轮，AMEND）

- 复核时刻：2026-10-06 15:50–15:54 (+08:00)；复核员：一名 Opus 只读复核员（克隆 `D:\lawbench-rv\rv-D2`，实验目录 `rv-D2-exp`）
- target：line-D `bb37956`（修法 + tokenizer 走 Release 资产）、`f01b9ad`（交付说明）；基座 `306450b`；13 文件 +259/-72
- 裁决（主编排）：**AMEND**，四处各一两行（令 `致D-ORCH-执行令-修法复核AMEND-四处一两行-20261006-1555.md`），改完主编排亲核即合。

## 复核员报告（原文）

**Verdict：AMEND。** 权限拆分、钉版、tokenizer 流程和小修都到位；两处会让检查静默放行：一处是本次引入的回归，一处让 P3-4 实际没关上。各改一行。

### Findings
**P2-A｜build 失败被 `tee` 吞掉，没过密钥扫描的 dmg 照样进草稿 Release**（引入的回归，阻断）：旧版 `test "${PIPESTATUS[0]}" -eq 0` 被删；工作流未写 `shell:`，默认 `bash -e {0}` 无 pipefail → `build.sh … | tee` 成败只看 tee。`build.sh step_package` 先拷 dmg 进 `out/`、后 `scan_dir`（Key/家目录扫描），扫描 `die` 时仍判成功 → dmg 交出、release job 建草稿、smoke 照跑。实验 `bash -e -c 'false | tee /dev/null; echo continued'` 输出 continued。修法：加回 PIPESTATUS 断言或 `shell: bash`。

**P2-B｜smoke 的 lsof 采样子进程首次无网络连接即退出，"只连 127.0.0.1"对空记录判过**（P3-4 未真关，阻断）：采样子 shell 继承 `set -euo pipefail`，`[ -n "$p" ] && lsof … | awk` 管道失败触发 `-e`；macOS 上被问 PID 无网络连接时 lsof 退 1（刚启动、GPU/渲染子进程常见）→ 第一秒即停，`wait … || true` 吞掉，`connections.txt` 空或仅一次快照。实验 `rv-D2-exp\sampler-exp.sh`：`sampler exit=1`、`raw lines: 0`。修法：lsof 管道后 `|| true`；合并后断言非空且含 Host 127.0.0.1 监听。

**P3｜tokenizer 查询任何错都静默降成冒烟包**：`gh release view … 2>/dev/null | grep -qx` 不分"不存在"与"网络/权限错"；`assets-v1` 若为草稿只读令牌看不到。有 `-smoke-no-tokenizer` 文件名与正文首行兜底。建议 README 写明须已发布、或只在明确"不存在"时降级。

**P3｜smoke 截图失败、窗口一直没出现都不判失败**（工作流早有）：`screencapture -x … && say …` 失败仅少日志；窗口循环 60 次 `n=0` 继续。修法：写 FAIL 并 `exit 1`。

**NOTE**：checkout `11d5960…` 是否 v4.4.0 离线核不了；setup-node v4.4.0 `49933ea…`、cache v4.3.0 `0057852…`、upload-artifact v4.6.2 `ea165f8…` 与所知一致；SHA 不存在首跑直接报错。跨系统缓存两边 `enableCrossOsArchive`，不一致时 `fail-on-cache-miss` 直接失败不放行。keychain 先删后加后成败靠读回核对，写入失败旧 Key 已删需重存，可接受。

### 工作流累计状态（读整个文件）
权限：顶层 `contents: read`；build/smoke `contents: read`；仅 release job `contents: write`，只有 `actions/cache/restore` + 一个 `run`（sha256 核对 + `gh release create`），不 checkout、不跑 npm/pip/仓库脚本；两处 checkout `persist-credentials: false`。钉版：9 处 `uses:` 全 `@40hex # vX`；无 `secrets.*`，只用 `github.token`。dmg 传递：Actions 缓存键 `mac-dmg-${run_id}-${run_attempt}` 精确匹配、无 restore-keys、`fail-on-cache-miss`；release 与 smoke 均按 build 输出 sha256 `-c` 核对。tokenizer：私有库读已发布资产 `contents: read` 够；完整 sha256 在 `mac-build.yml:27` 与 `versions.lock:53` 一致；`shasum -c` 不符即失败；不存在时 `LAWBENCH_ALLOW_NO_TOKENIZER`、dmg 名 `-smoke-no-tokenizer`、草稿首行标注。触发只 `workflow_dispatch`；外部来源未扩大；`--draft --prerelease`；artifact 14 天。

### smoke.sh
PIDS 为空判失败 通过；地址 127.0.0.1:18831–18834 死端口 通过；每秒采样 **未通过**（P2-B）；截图失败不判失败（P3）。

### 小修关闭
`install-layout.ts` mac 命令含 `-B`、`build.sh` 自检 `-I -B -c`：关闭。变异：去掉 libreoffice.py/driver.py 两处 `**procs.own_group()` → 2 失败/21 通过，已还原。`macTrusted`、`credentialSource('darwin')` 断言直接调被测函数。未跑 vitest（借用 node_modules 写缓存风险），TS 只读代码；线 D 自报 640。keychain 先删后加 + stdin 开头断言：关闭。`test_t28_macos.py` 不带 `--basetemp` 单独跑 23 passed。

### Windows 不变量
`credentialSource('win32')` 仍 `windows-credential-manager`；`install-layout.ts` 只改 `macPackagedConfig`；`keychain.ts` 只经 `macStore` 在 darwin 用。不变。

### 跑过的命令
`git rev-parse/log/show --stat/diff 306450b f01b9ad`；`git grep 87a7830d`；正则核 `uses:`/`secrets`/触发器；`D:\lawbench-C\.venv\Scripts\python.exe -B -m pytest tests\test_t28_macos.py -q -p no:cacheprovider`（23 passed）；变异后 2 failed/21 passed 并 `git checkout` 还原；`bash rv-D2-exp\sampler-exp.sh`；`bash -e -c 'false | tee /dev/null; echo continued'`。未进 `D:\lawbench-D`，无外连。
