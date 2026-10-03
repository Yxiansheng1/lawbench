# T20 收尾（不要服务器的部分，`1890c05`）· 复核记录（单人，八项清单）

- target：line-A `1890c05`（父 `a464e9f`）；复核克隆 `D:\lawbench-rv\rv-A33`
- 派发：Opus 5.5 只读复核员，2026-10-03 11:5x
- 归档：主编排于 2026-10-03 12:04 (+08:00) 从复核员交回原文抄录，未改内容

## 复核员原文# T20 收尾（不要服务器的部分）复核：target `1890c05`（line-A，父提交 `a464e9f`）

**一句话说清要求**：打包脚本的 dsh 步要用一个明确指定的 pnpm 离线包仓库（store）。不给参数时去 `.modules.yaml` 里读，读不到就在动 dsh 之前报错退出。另外四件事：核 "DeepSeek Harness" 残留、gen_lock 在 dsh 没检出时报错、核 office.spec、给锁文件补包。全程不许联网。

**身份**：复核克隆 `D:\lawbench-rv\rv-A33` 的 `HEAD` 是 `1890c058c52c…`，工作区干净。改动 9 个文件，+228/−4，作者 Yxiansheng1。

**逐处归类**：
- 必需实现：
  - `build.ps1` 新增参数 `-PnpmStore` 和函数 `Resolve-PnpmStore`，dsh 安装带上 `--store-dir`。
  - `build.ps1` 新增 dsh-ext 的离线安装。这超出执行令点名的范围，但同属 dsh 步，而且干净克隆必须有它。
  - `gen_lock.py` 的 `EXTRA_ROOTS` 加 `six`；`versions.lock` 多一行 `six==1.17.0`；`THIRD-PARTY-LICENSES.md` 多一行 `six 1.17.0 MIT`。
- 必需验证：`brand-remnants.txt`、`pnpm-store.txt`、`office-spec-baseline.txt`、`payload-inventory.md`（包数改成 55）、交付说明末节。
- 无关改动：没有。

## Findings

**P3-1：`-PnpmStore` 给相对路径时，检查和实际使用不是同一个目录**
- 问题：`Resolve-PnpmStore` 按调用者当前目录用 `Test-Path` 检查通过，但 pnpm 是在 `Push-Location dsh` 和 `Push-Location dsh-ext` 之后才拿到这个相对路径的，会解析到两个不同的目录。
- 证据：我在 `D:\lawbench-rv` 下用 `-PnpmStore exp-A33-T20-store` 跑 dsh 步，检查通过，输出 `[build] pnpm store: exp-A33-T20-store`（没转成绝对路径）。
- 影响：因为带了 `--offline`，结果只会是安装失败，不会联网；只是报错让人看不懂。
- 最小修复：`$store = (Resolve-Path $store).Path`。
- 归类：独立后续。

**P3-2（以前就有，不是本次引入）：python 步的提示语说错了下一步**
- 问题：`build.ps1` python 步缓存里没有压缩包时，报错让人 "run the dsh step first"。但 dsh 步里的 `pnpm run build`（`scripts/build.ts`：build:native-system、build:lib、build:web）不会往 `.desktop-build\downloads` 里放东西。往那里放东西的是 DSH 的 `prepare:primary-runtime`（`scripts/primary-runtime/prepare.ts:28,40`），它会从 github.com 和 nodejs.org 下载。
- 影响：干净的构建机照提示去跑 dsh 步也凑不齐压缩包；要凑齐就得跑一个联网的脚本。这件事和"正式构建需联网"属同一类，已经记在 `payload-inventory.md`。
- 最小修复：提示语改成"把 DSH 下载缓存（或 `prepare:primary-runtime` 在联网构建机上的产物）拷到这里"。
- 归类：独立后续。

**NOTE-1：残留清单只按 "DeepSeek Harness" 统计了 packages 里的文件**
- 执行令要求的 `deepseek` 宽口径，在 packages 层没有列清单。
- 我补查了 client 包里只写 "DeepSeek"（不带 Harness）的文案：分布在 ui-chat 的账号报错、ui-model-selection 的"DeepSeek 账号"、ui-settings-web-search 等处。对应的插件 `deepseek-account`、`ui-model-selection`、`ui-settings-web-search`、`ui-settings-models`、`ui-settings-account` 在 `dsh-ext\cordis.patch.yml` 里全是 `disabled: true`。
- 结论不变：律师看得到的是 0 处。归类：证据缺口，已由我补上。

**NOTE-2：pnpm 11 安装时打印 "Lockfile passes supply-chain policies (verified 3d ago)"**
- 这说明它用了本地缓存的校验结果。
- 我在把 `HTTP(S)_PROXY`/`ALL_PROXY` 指向 127.0.0.1:19331（没人监听）的情况下，dsh 全量离线安装和 dsh-ext 离线安装都成功（`downloaded 0`），说明这一步没有真要联网。缓存过期后还会不会去联网，没有验证。
- 归类：臆测，留给步骤 6 断网安装时观察。

没有阻断项。

## 五项核对表

| 条 | 结论 | 我亲做的证据 |
|---|---|---|
| 1 `-PnpmStore` | 通过 | ① 不给参数、没有 yaml：报 "pnpm store unknown … Pass -PnpmStore"，退出 1，dsh 目录 0 个文件被改。<br>② 给了不存在的目录（带不带 `\v11` 都试了）：报 "pnpm store folder not found: D:\lawbench-rv\nope-store"，退出 1。<br>③ yaml 读取：从线 A 拷来真实格式的 `.modules.yaml`（JSON 转义写法 `"D:\\.pnpm-store\\v11"`）→ 解析成 `D:\.pnpm-store`；自造的不带引号 YAML 写法 → 解析成功；yaml 里没有 storeDir → 报错。<br>④ 给参数 `D:\.pnpm-store` → 解析通过。<br>③④ 都是我把副本里的 `PATCHES.md` 临时移走，让脚本在解析完 store 之后、打补丁之前停下，所以没有真打包。<br>⑤ 两处 install 都带 `--frozen-lockfile --offline --store-dir`；整个脚本里没有 URL，没有不带 `--offline` 的 install，pip 也是 `--no-index`。<br>⑥ dsh-ext 离线安装我在副本里真跑了：退出 0，`downloaded 0`，装上 ajv、ajv-formats、yaml，这几个包都不需要构建脚本。<br>⑦ `build.ps1` 仍然是纯 ASCII，解析 0 错误。 |
| 2 残留清单 | 通过 | 先 clone dsh 到 `477b4f4`，13 个补丁 `apply --check` 和实际 apply 全部退出 0。<br>**关键一句"persona `complete: true` 整体替换系统提示"属实**：<br>· `persona/src/index.ts:62-68`：`complete` 时给 prefix 段加上 `complete: true`。<br>· `system-prompt/src/index.ts:597-634`：组装完成后，`sections` 被强制换成只剩 `[completeSection]`。<br>· 身份句（`system-prompt:426-430`）、`addHarnessSourceSection`（`app-boot:1060`）、`app:web-surface`（`web-app:236`）这三处都是 section，所以都会被换掉。<br>· `includeRuntimeContext: false` 在 persona 里调用 `suppressRuntimeContext()`，contexts 也被清空。<br>· 工具描述不受影响，但律师工作台 preset 只挂了 skill-filesystem、tool-skill、tool-ask-user，没有 shell 和 subagent。<br>**抽查 5 条全对**：<br>· `welcomeKeyDescription` 全仓只在 `apps/desktop/src/locale.ts` 定义，没人用。<br>· skill-badge 在 `bundle/base/cordis.patch.yml:299-301` 是 `disabled: true`。<br>· `tool-subagent-codex` 在三个官方 preset 里本来就是 `disabled: true`，而这三个 preset 又被我方关掉了；实际比作者说的还严。<br>· inspector 只在 experimental 自己的 patch 里出现，bundle 和 desktop 都没引用。<br>· ui-plugin-manager、ui-settings-account、ui-settings-models、ui-sidebar-documentpreview 都已关。 |
| 3 gen_lock | 通过 | 副本里 `dsh\` 是空目录时跑 `gen_lock.py --site <线 B venv>`：报"gen_lock: dsh 子模块没有检出（dsh\package.json 不在）…"，退出 1。`versions.lock` 和许可证表跑前跑后的 sha256 一致。检查写在 `client_sections` 第一行，任何写文件的动作之前。 |
| 4 office.spec | 通过（未复现失败） | 在打了 13 个补丁的 dsh 副本里离线安装（1 分 30 秒，退出 0，代理指向死端口），然后从仓库根连跑三次 `vitest run apps/desktop-host/tests/office.spec.ts office-engine.spec.ts`：三次都是 2 个文件 8 项全过，没有出现 `UNLOADING`。结果和作者、第三轮复核一致。基线（不打补丁）那组我没有跑。 |
| 5 锁 / 许可证 | 通过 | ① `six` 的 dist-info 元数据写的是 `License: MIT`、`Classifier … MIT License`，和许可证表一致。<br>② python-docx 1.2.0、pypdf 6.19.0、reportlab 5.0.1 都在锁里。<br>③ 锁里一共 55 个包，我逐个数过。<br>④ `service` 实际 import 对照抽了 8 个（docx、pypdf、reportlab、olefile、pypdfium2，另加 keyring、tokenizers、pywin32），全在锁里。<br>⑤ pyproject 的 `dependencies` 和 retainer 组全覆盖。<br>⑥ engines\retainer 里没有任何 `import six`，和作者说的一致。 |

## 八项清单
1. 契约一致：没动 `contracts\`。通过。
2. 边界输入：路径带不带 `\v11`、yaml 写成 JSON 还是 YAML、yaml 里没有 storeDir、目录不存在，这几种都试过，全对。相对路径有问题，见 P3-1。
3. 错误路径：store 解析不出来时，在打补丁和拷图之前就停（已实测）；gen_lock 不会写出半份锁（已实测）。
4. 日志不含正文：只打印 store 路径，不含材料内容。通过。
5. 路径闸门：这次没碰。不涉及。
6. 无外连：脚本里没有 URL，两处 pnpm 都 `--offline`，corepack 关了网络，pip `--no-index`。在代理指向死端口的情况下离线安装成功。DSH 自己的 prepare 下载脚本不在 build.ps1 调用链里（见 P3-2）。通过。
7. 测试覆盖：打包脚本没有自动化测试，靠作者的干净克隆实测记录和我的复现。可以接受。
8. 无机密入库：diff 里 grep 用户名、`sk-`、key、password、Bearer，0 处。通过。

## 实际跑过的命令（摘要）
- `git rev-parse` / `status` / `diff --stat`，`git archive` 导出到 `D:\lawbench-rv\exp-A33-T20`。用 bsdtar 解包时中文文件名的文件没解出来，但没有影响这次要用的文件。
- `powershell -File packaging\build.ps1 -Step dsh`，分别用了不给参数、不存在的路径、真实格式 yaml、YAML 写法、没有 storeDir 的 yaml、显式给 store、相对路径这几种情形。
- `corepack pnpm@11.7.0 install --frozen-lockfile --offline --store-dir D:\.pnpm-store`，分别在副本的 dsh-ext 和 dsh clone 里跑。
- `git clone --no-hardlinks D:\lawbench-A\dsh`，`checkout 477b4f4`，13 个补丁 `apply --check` 并 apply。
- `vitest run` office 两个 spec，跑三次。
- 在 dsh 为空的副本里跑 `gen_lock.py`，跑前跑后算哈希比对。
- grep 和读源码：system-prompt、persona、web-app、app-boot、base 和 preset 的 patch.yml、`dsh-ext\cordis.patch.yml`、service 的 import。

## 残留审计
- 我起的 PID 44476、3552、7968 都已经退出；命令行里含实验目录名的进程为 0。
- 端口 19330–19339 没有任何监听。我只把 19331 当成"死端口"填进代理变量，自己没监听。
- pnpm 安装时在共用的 `D:\.pnpm-store\v11\projects\` 下自动登记了两个指向我实验目录的联接。我已经用 `rmdir`（只删联接本身）删掉，再用 `rmdir /s /q` 删掉 `exp-A33-T20`、`-dsh`、`-store`、`-tmp` 四个目录和脚本、输出文件。现在 `D:\lawbench-rv` 下已经没有 `exp-A33*`。
- `D:\.pnpm-store\v11\index.db` 的修改时间更新了，这是 pnpm 的正常索引写入，没有下载新包。
- `D:\lawbench-A\dsh` 只读引用，完好。复核克隆 `rv-A33` 没有改动。别人的进程（包括 soffice.bin）没有碰。

## 证据缺口
- 没有在完整的干净克隆上把 ②③ 一路跑到 dsh 构建和 dsh-ext 打包。dsh-ext 离线安装和 dsh 全量离线安装是我分开独立跑过的，构建和打包这一段用的是作者的记录。
- office.spec 的未打补丁基线我没有重跑。第二轮复核机上那次"稳定失败"的根因还是不明。
- pnpm 供应链校验缓存过期后会不会联网，没有验证（NOTE-2）。

PASS

