# T20 准备 + 步骤 3 第二轮返修累计 · 独立复核记录（第三轮）

- 复核员：一名 Opus 5.5 只读复核员（换人）
- target：line-A `5bcfbf2`；累计 `754b6b8`、`d8671e8`、`46ed38e`、`9b35040`、`cf17516`、`3470968`、`5bcfbf2`
- 冻结清单：`review-REVIEW-准备-第二轮.md` 第二部分
- 复核克隆：scratchpad `rv-A28`
- 归档：主编排于 2026-10-02 12:24 (+08:00) 从复核员交回原文抄录，未改内容

## 第一部分 复核员原文
# T20 准备 + 步骤 3 第二轮返修累计范围 · 独立复核（rv-A28，line-A `5bcfbf2`）

**结论：通过（PASS）。** 冻结清单全部关闭，每条我都复现过。这一轮修改没有带进新的 P0、P1 或 P2 问题。新发现三条 P3，都只涉及测试或证据脚本，不影响产品行为，可以下一轮顺手修。

**环境核对**
- 克隆 `rv-A28`：HEAD 是 `5bcfbf2`，`git status` 干净。
- 累计范围：`754b6b8`、`d8671e8`、`46ed38e`（T26，不归我）、`9b35040`、`cf17516`、`3470968`、`5bcfbf2`。
- 累计范围对 dsh-ext 的改动只在这些地方：`host/index.ts`、`install-layout.ts`、`selfcheck*`、`cordis.patch.yml`、`remote-methods.ts`、`ui/home.tsx`、测试和 `dev/fake-tools.d.mts`。T17 的会话存储和路由都没动。
- `5bcfbf2` 对 `host/index.ts` 只改了一行，就是 `effectiveConfig` 多传一个 `process.env.PATH`。

## Findings

### 本次修正引入
**P3-a　改用 `${PRODUCT_NAME}` 后，DSH 自带的真安装器冒烟脚本会对不上文字**
- 原因：`apps/desktop/tests/windows-installer-smoke.ps1:17-19` 从 `strings.nsh` 原样读出各条文字，第 110 行（LAUNCH_FAILED）和第 186、190 行（RUNNING）按全文去找窗口。
- 现在文件里是字面的 `${PRODUCT_NAME} is running…`，而安装器编译时已经换成了测试用的产品名，两边对不上。
- 影响：只有 `pnpm run test:installer`（`scripts/test-windows-installer.mjs`）会受影响，它要在构建机上真编译 NSIS，不在 vitest 里，也不在 build.ps1 里。产品文案本身是对的。我没有真编 NSIS，这一条是读代码得出的。
- 最小修复：冒烟脚本读 strings 时把 `${PRODUCT_NAME}` 替换成 `$ProductName`，登记进 P-4。

**P3-b　`mutate_check.py` 没跟着 P3-2 一起改**
- 原因：第 62 行用来定位的文字还是旧写法 `[process.getBuiltinModule('node:path').join(process.env.ProgramData`。
- 我按 `cordis.patch.yml` 的新表达式模拟了一份重新导出的插件树（`plugin-tree-new.txt`）：`check_plugin_tree.py` 结果是"一致、通过"。但 `mutate_check` 的"两个目录顺序对调"这一例在 preset-lawbench 段里找不到定位文字，改到了别处（第 1468 行），结果仍是通过（退出码 0，期望 1），报"1 项不符合预期"。
- 另外，用仓库里现存的旧导出跑，`check_plugin_tree` 现在报"customSkillDirs 整项相等 不符"，`mutate_check` 的基线一例也红。这在等重新导出之前是预期内的，建议在交付说明里写一句。
- 最小修复：定位文字改成 `[p.join(process.env.ProgramData`。

**P3-c　P2-C 的接线和"开发期不传"没有用例守着**
- 我在 lab 副本里做了 6 处变异，跑 dsh-ext 全量测试：

| 变异 | 结果 |
|---|---|
| PATH 只留工具目录 | 变红 |
| 去掉 `LAWBENCH_PANDOC` | 变红 |
| 工具目录放到原 PATH 后面 | 变红 |
| `effectiveConfig` 不把 `basePath` 交下去 | 仍全绿 |
| `apply` 传 `''` 而不是 `process.env.PATH` | 仍全绿 |
| 开发期也带上工具变量 | 仍全绿 |

- 前两种全绿的情况一旦发生，装好的客户端里服务进程的 PATH 只剩两个工具目录（没有 System32）。
- 现在的代码是对的，我实测过（见下方冻结清单 P2-C 一行）。
- 最小修复：在 `apply 用的分支` 用例里，对 packaged 断言 `p.config.env.PATH` 以给的 basePath 结尾，对开发期断言 `node.config` 就是原配置、env 里没有 `LAWBENCH_*`。

### NOTE（不阻断）
- **构建机上的缓存文件会被打进包。** python 步从工作区整份拷 `contracts\*` 和 `service\lawbench`，会把没入库的 `__pycache__` 一起带上。
  - 线 A 现有的 stage 里有 `contracts\__pycache__\check_examples.cpython-312.pyc`（所以是 126 个文件，入库的只有 125 个）、`service` 下 9 个 `__pycache__`、`python` 下 103 个 pyc（是跑测试时生成的）。
  - pyc 里嵌着源文件路径，本机是 `D:\lawbench-A\…`，不含用户名；如果构建机在 `C:\Users\<名>\` 下，就会带上用户名。
  - 建议拷贝时排除 `__pycache__`，或者按 `git ls-files` 拷。
- **DryRun 发现缺项也照样退出 0**，只打印 `MISSING`。我实测藏掉 contracts 和 tokenizer，两项都列出来了，退出码仍是 0。真打包前建议改成缺项就失败。

### 此前既有
- `desktop-host` 的 `office.spec`、`office-engine.spec`：在我的副本里单独跑，2 个文件 8 项全过，和作者说的一致，未复现上一轮的失败。

## 冻结清单逐条核对（`review-REVIEW-准备-第二轮.md` 第二部分）

| 编号 | 结果 | 依据 |
|---|---|---|
| P2-A | 关闭 | ① 只跑 python 步时 `stage\contracts` 125 个文件，与入库的一致，没有缓存文件。<br>② 按装好后的布局起服务：`-I -m lawbench`，端口 19381，转发 19382，设置里四个地址指向 127.0.0.1:19383–19386，`LOCALAPPDATA`/`APPDATA`/`TEMP` 指到实验目录。`/health` 回 200 `{"status":"ok","contract_version":"1.3"}`，进程连接只有 127.0.0.1。<br>③ 反证：拿掉 `stage\contracts` 后回 500。<br>④ 带 `._pth` 的暂存解释器（`flags.isolated=1`）跑服务全量：944 通过、6 跳过、1 失败。唯一失败的 `test_tokenizer_json_ignored_by_git` 是因为 git archive 导出的副本不是 git 仓库，在真克隆里单跑通过，所以等价于 945/0。`test_main` 两例通过。<br>⑤ 只跑 python 步时 `test_main` 两例失败，原因是缺 `stage\skills\capsules.default.json`，补跑 skills 步后通过；作者的 945 也是在全部步骤都跑过之后。<br>⑥ DryRun 和 `payload-inventory.md` 都补了这一项。 |
| P2-B | 关闭 | 临时目录里预先放了已有文件、下层两级文件、隐藏文件、只读文件，用未提权的 Medium 级别跑。<br>① 全部可读，不能写、不能新建、不能删、不能改名，`-Verify` 退出 0。<br>② 目录本身仍是显式规则、不继承上级（`AreAccessRulesProtected=True`）；下面的文件和子目录全部改为继承（`(I)`），说明 reset 没把目录本身也 reset 掉。<br>③ 重跑一次结果一样；空目录也能跑。<br>④ 变异：改回带 `/T`、不做 reset，`-Verify` 报"existing files readable: False"，退出 1。<br>⑤ 全程没碰 `%ProgramData%`。 |
| P2-C（Host 侧） | 关闭 | ① 用例断言了两个变量和 PATH。<br>② 实测：用原样摘出的 `passThroughEnv` 加 `packagedConfig` 的 env，经 DSH 真实的 `childEnv`（subprocess-local 构建产物）合并，再真起一个 cmd 子进程。装好的客户端：PATH 前两段是 `tools\libreoffice\program;tools\pandoc`，System32 还在，两个变量都对。开发期：PATH 不变，两个变量都没有。<br>③ `Path` 与 `PATH` 大小写混在一起时，DSH 的合并结果只剩新的 `PATH`。<br>④ `finder.py` 对齐 `tools\`：小工具 65 项全过；把布局改回 `resources`、去掉占位名，两种变异都变红。 |
| P3-1 | 关闭 | `python-reuse.txt` 补记三、PATCHES.md 结论行、交付说明三处说法已改准 |
| P3-2 | 关闭（有尾巴，见 P3-b） | 期望值与 `cordis.patch.yml` 一致，模拟新导出能通过 |
| P3-3 | 关闭（有连带，见 P3-a） | ① 13 个补丁在克隆的 dsh `477b4f4` 上依次 `apply --check` 并打上，全部无错；拷进图片后 108 个改动路径与线 A 工作区逐字节一致。<br>② `strings.nsh` 那 6 处都已是 `${PRODUCT_NAME}`；mac 麦克风说明用常量。<br>③ 非测试代码里旧名"DeepSeek Harness"只剩 README，占位名只剩两处常量。<br>④ PATCHES.md 的 P-4 行 8 个文件都已登记。 |
| P3-4 | 关闭 | ① 依次跑 skills、engines、tools，再单独重跑 python：`tokenizer.json` 还在（sha `87a7830d`），没有残留的 `.keep` 文件，`stage\service` 下只有 `lawbench`。<br>② DryRun 无缺项（28244 个文件，1504 MB）；藏掉 contracts 和 tokenizer 时两项都列为缺项。 |
| NOTE 五条 | 关闭 | ① 一次性克隆里跑 brand 步后 `git status` 为空，`names.txt` 不再有换行噪声，图片逐字节一致。<br>② spec 里的路径字符串已改成双反斜杠。<br>③ 包数 53。<br>④ 已加 `COREPACK_ENABLE_NETWORK=0`。<br>⑤ dryrun 证据不再截断。 |
| 既有：gen_lock | 关闭 | dsh 未检出时报错退出 1，锁文件和许可证表逐字节不变 |

**返修是否带进回归**
- `stage\contracts`：我自己拷的副本干净，没有 Key，没有本机用户名，只有示例里虚构的 `C:\Users\li`；`_build` 生成器也在里面。线 A 现有 stage 多一个 pyc，见 NOTE。
- ACL 脚本：目录本身的权限没被 reset。
- PATH 前置：开发期行为不变。
- 补丁链：13 个全过，与工作区逐字节一致。线 A dsh 目前的改动都在 P-4 范围内，没有补丁以外的在途改动。

**前两轮通过项回归**
- 品牌可重复：图片逐字节一致，`logo` 树 `37a5c11`，原件未动。
- 53 包回装：回装 53 个、缺 0 个，`pip --no-index` 装完。
- gen_lock：依赖目录不存在、为空两种情况都退出 1。
- 启动自检 7 例、110 字符边界、打包后忽略环境变量：都在 dsh-ext 全量测试里通过。

**`5bcfbf2` 改动纪律**
- 17 个文件逐个 hunk 归类，都能对上 P2-A/B/C、P3-1 至 P3-4、NOTE，或者执行令点名的"既有"项（gen_lock）。没有无关改动。
- 提交和证据里没有用户名，没有 Key。

## 八项清单
- **契约一致**：通过，契约没改，打包布局已带上契约。
- **边界输入**：通过（gen_lock 三种情况、110 字符边界、ACL 遇到隐藏和只读文件）。
- **错误路径**：通过（DryRun 能报缺项，但退出码不变，见 NOTE）。
- **日志不含正文**：通过，新代码不加日志。
- **路径闸门未被绕过**：通过，打包后不读 `LAWBENCH_*` 开发变量。
- **无外连**：通过，服务进程只连 127.0.0.1；packaging 下没有下载调用。
- **测试覆盖新代码**：基本通过，缺口见 P3-c。
- **无机密入库**：通过。

## 实际跑过的命令
- dsh-ext 全量测试：31 个文件，491 通过，5 跳过。`tsc` 退出 0，`build.mjs` 通过。
- `check_ui_words`：零命中。`check_examples --skills skills`：通过。
- `check_plugin_tree --inventory-overlay` 和 `mutate_check`：新旧两份导出各跑一次。
- 小工具测试 65 项通过（线 C 的 venv，因为要 numpy）。
- apps/desktop vitest：117 个文件，第一轮 14 项失败，其中：
  - 基线：upload-with-credentials 7 项，以及 profile-mcp 套件；
  - 机器负载超时：5 个文件（含 lawbench-stage）；
  - 实验副本少了几个包的 node_modules：4 个套件（semver/chokidar/zod）。
  - 补上联接、把时限放宽到 90 秒重跑 10 个文件后，只剩基线的 profile-mcp 1 项。
- `repack_wheels.py`；`build.ps1`：python、skills/engines/tools、单独重跑 python、package `-DryRun` 一次正常、一次藏掉 contracts 和 tokenizer。
- 起服务两次（正常 200，去掉 contracts 500）；服务全量测试两次。
- ACL 实验，以及 1 处 ACL 变异、6 处 Host 变异、2 处 finder 变异，全部逐字节复原。
- 环境变量合并实验；13 个补丁 `apply --check` 与逐字节比对；grep 品牌残留；`office` 两个 spec。

## 残留审计
- **进程**：我起的服务（PID 43240、第二次那个）、测试进程（32300、6568）、vitest（41232、41988）都已结束；命令行里含实验目录的进程为 0。
- **端口**：19381–19389 没有监听。
- **目录**：
  - 先用逐个删链接的办法拆掉 331 个联接，确认一个不剩，再用长路径前缀删掉 `rv-A28-lab`；
  - `%TEMP%\rvA28`（短路径的应用数据、pytest 临时目录）已删；
  - ACL 实验目录先 `icacls /reset` 再删；
  - 我放在 scratchpad 的临时文件已删。
- **线 A**：`dsh` 的 `git status` 仍是 108 项；`node_modules`、`dsh-ext\node_modules`、`packages\…\node_modules`、`scripts\…\lock.json` 抽查都在。
- **rv-A28 克隆**：保留，状态干净，HEAD `5bcfbf2`。

## 证据缺口
- 没有真跑 electron-builder 出包，也没编 NSIS，所以 P3-a 是读代码得出的。
- 服务侧读 `LAWBENCH_SOFFICE`/`LAWBENCH_PANDOC`（线 C `a90eb4d`）按令不归我核，只核了 Host 侧。
- `finder.py` 里的客户端目录名 `连越律师工作台` 是否就是安装器实际的默认安装目录，要等真出包才能确认。
- apps/desktop 测试在实验副本里联接了线 A 的 `node_modules`、`packages`（两边内容逐字节一致）。

PASS
﻿
---

## 第二部分 主编排裁决（2026-10-02 12:24 (+08:00)）

**结论：PASS，T20 准备部分与步骤 3 离线部分任务门=过。** 冻结清单全关并复现（stage\contracts 125 文件、装好布局 /health 200 去掉 500；ACL 临时目录全可读不可写、目录本身未被 reset；PATH 前置后 System32 仍在、开发期不传；13 补丁逐字节一致；带 ._pth 暂存解释器服务全量等价 945/0）。

记录项（随 T20 下一步一并做，不单独复核）：P3-a `windows-installer-smoke.ps1` 读 strings 时把 `\` 替换成实际名；P3-b `mutate_check.py` 定位文字改 `[p.join(process.env.ProgramData`，交付说明写明重导出前旧导出会红；P3-c `apply` 分支用例补 `PATH` 以 basePath 结尾、开发期 env 无 `LAWBENCH_*`；NOTE 拷贝排除 `__pycache__`（或按 `git ls-files`）、DryRun 缺项退出非 0。

T20 剩余：步骤 3 需联网下载的载荷（候用户在场）、步骤 4 PyInstaller（候补）、步骤 6 干净机断网安装与抓包（候用户）；N58 七件候 owner。合流：T20 提交随 line-A 整体（T17 N55 ② 改做法后双人复核通过）合并。