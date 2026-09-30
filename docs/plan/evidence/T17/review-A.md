# T17 第一步复核记录 · Reviewer A（改动纪律与可维护性）

- 复核员：主编排派出的子代理，Opus 5.5 · high，只读；与 Reviewer B 同一条消息并发派出，互相看不到
- target：head `2827c695111527cd4dc5027457507f6eec794b79`（line-A），base `661f57b`；提交 `d105303`、`2827c69`
- 范围：只改配置关 22 行入口；拖入守卫 `ui\drop-guard.ts`；证据
- 复核位置：主编排临时目录里的克隆和实验目录；没有联网，没有启动桌面端
- 时间：2026-09-30 10:25 起，约 11 分钟（用户已回来，值守窗已关）
- 以下是复核员最终报告的原文，只把本机路径里的用户名替换成 `<用户>`，其余未作删改；综合裁决另见 `review-综合裁决.md`

---
T17 第一步复核结论（Reviewer A，只看改动纪律和可维护性）：可以收。22 行关得一行不差，DSH 源码没动；拖入守卫是最小实现，范围扩大有依据，但要主编排追认。没有 P0、P1、P2，下面 7 条 P3 和 5 条 NOTE 都不阻断。

**要求的行为（一句话）**：只在 `dsh-ext\cordis.patch.yml` 里关掉执行令点名的 22 行，候用户的那几行和 DSH 源码一律不碰；再加一道守卫：往对话区拖文件、往对话框粘贴文件时不生成引用标签、不进附件，弹中文提示。

target 已亲验：HEAD 是 `2827c695…`，工作区干净，`661f57b..2827c69` 是 2 个提交、34 个文件、+3482/−2。

## 一、Findings（按严重度）

**P3-1 交付说明第 1 节有几处说法过时，和第 2 节、实物对不上**
- 位置：`docs\plan\evidence\T17\交付说明.md`
  - 1.1 写"没有动：… `ui-deliverables`"，1.9 写"`ui-deliverables` 的去留：请示中"；
  - 开头写"关 21 行"，实际是 22 行；
  - 1.3 写"共 70 行"，脚本实际输出"必须关的行（71 行）"；
  - 2.2 写"16 个文件 204 项通过"，`ts-test.txt` 和我实跑都是 17 个文件。
- 违反的不变量：证据和自述要一致。
- 影响：第 2 节有一句"以本节为准"兜底，不会误导裁决，但读的人要自己对账。
- 最小修复：在第 1 节这几处加删除线或"（已由第 2 节更新）"，把"16 个文件"改成 17。
- 归类：独立后续。

**P3-2 "P-5 接上后粘贴让路"这条分支没有测试守着**
- 位置：`dsh-ext\ui\drop-guard.ts` 里 onPaste 的 `|| deps.intakeActive()`。
- 我在副本上删掉它，`tests\drop-guard.spec.ts` 8 项仍全过，这个变异活了下来。拖入那一侧的让路有测试。
- 影响：现在还没有调用方（P-5 源码补丁没落地），所以不影响当前行为；等 P-5 接上时才会暴露。
- 最小修复：在粘贴用例里加一行"`intake = true` 时粘贴文件不拦、不提示"。
- 归类：范围内，但不阻断。

**P3-3 反向检查脚本里同一份名单写了两遍**
- 位置：`check_plugin_tree.py` 的 `T17_STEP1` 和 `MUST_OFF` 里新增的 22 行是两份独立抄写。
- 变异结果：只从 `T17_STEP1` 删掉 `ui-open-in-app`，同时把静态树里这一行改成 `disabled: false`，脚本 rc=0，没报出来。
- 最小修复：直接从 `MUST_OFF` 取这 22 行，或者加一条断言"`T17_STEP1` 必须包含在 `MUST_OFF` 里"。
- 归类：独立后续。

**P3-4 DSH 自带测试的失败分类说得不够准**
- 交付说明说"只在改后失败的 6 项都是签名、打包类超时"。实际其中一项 `package-target-errors … on darwin` 是断言失败，不是超时。
- 原因：前一项 win32 超时后，环境变量 `DSH_DESKTOP_PACKAGING_RUN_DIR` 没有还原，连带让下一项失败（`desktop-tests.txt:163`）。
- `desktop-rerun.txt` 单独重跑这 5 个文件全部通过，"与本步无关"的结论成立，只是措辞要改。
- 归类：独立后续。

**P3-5 拖入落点的截图证据分辨力弱**
- `09-拖到输入框给提示.png` 和 `10-拖到对话区别处给提示.png` 画面几乎一样：提示框挡住了落点，也没有记录拖入坐标。
- "拖到左侧栏也给提示"写的是"以页面文字核对"，没有对应的证据文件。
- 最小修复：补一个记录每次拖入目标元素和坐标的 txt，或者截取弹框前的画面。
- 归类：证据缺口。

**P3-6 `check_plugin_tree.py` 里有过时注释**
- 注释写"固定提交 477b4f4 下 48 行全部存在"，现在已经是 71 行。
- 归类：独立后续。

**P3-7 `api-probe-product.txt` 只有结果，没有发请求的脚本或命令**
- 404 这件事目前只能凭作者的说法；静态树第 2d 项能从另一侧佐证。
- 归类：证据缺口。

**NOTE-1 守卫范围比执行令写得宽：我认为扩大成立，但不替主编排拍板**
- 执行令原话是"只拦对话框的输入区，别处不碰"。
- 我读了 DSH 源码核实：附件视图确实把拖入监听挂在整个 document 上（`packages\client\ui-attachment\src\client\drop-events.ts:75-78`），拖到对话区任何位置都会变成发不出去的标签。
- 执行令要的是"没有提示地卡住不行"。只拦输入框，其余位置照样没提示地卡住，达不到这个要求。所以把范围扩到"页面上有对话输入框时，带文件的拖入都接住，我方拖入区除外"，是有验收要求支撑的。
- 扩大后有三条边界把着：不带文件的拖动不碰；首页等没有输入框的页面不碰；粘贴仍只限输入框。
- 我查了 DSH 客户端里其他在 document 上收拖入的地方，只有 `ui-workspace\...\WorkspaceBrowser.tsx:96-97`，那是行排序拖动，不带文件，所以没有误伤 DSH 正常的拖入功能。
- 作者已经在 2.2 标明是偏离、请主编排过目。建议主编排追认。

**NOTE-2 线 A 工作目录此刻有未提交的 DSH 源码改动，不在本 target 里**
- `D:\lawbench-A\dsh\packages\client\ui-conversation\src\client\skeleton\InputBar.tsx` 在 10:35 被改过（删掉了输入框"+"指令按钮，净删 23 行，未提交）。
- 这比证据截图晚（截图 09 里"+"还在），和本 target 无关。
- 但执行令说过"不改任何 DSH 源码"，请主编排确认这是不是另行授权的工作。
- 归类：独立后续。

**NOTE-3 用选文件的方式附件，守卫管不到**
- 斜杠菜单里的"文件 file"（截图 02）和"+"按钮这两条附件入口，守卫都不覆盖。执行令只要求处理拖入和粘贴，这两条归 P-5 或 N41。
- 归类：独立后续。

**NOTE-4 `drop-guard.ts` 的类型里有两个字段没用上**
- `FileTransfer` 声明了 `files?` 和 `dropEffect?`，代码只读 `types`。微小多余，不要求改。

**NOTE-5 DSH 版本号带 "-dirty"**
- 截图里的版本号是 "0.1.7-rc.2-477b4f4-dirty"。这是 `dsh-patches` 里已登记的 P-3、P-10、P-12、P-13 补丁在工作树里生效造成的（这些文件的修改时间都是 04:13），不是本步改动。

## 二、文件归类（34 个）

**必需实现（6 个）**
- `dsh-ext\cordis.patch.yml`（+64 行，只在第 1c 节新增）
- `dsh-ext\ui\drop-guard.ts`
- `dsh-ext\ui\index.tsx`（+7 行：装守卫；`intakeActive` 标志；`registerIntake` 里加一个设标志的 effect）
- `dsh-ext\ui\home.tsx`、`dsh-ext\ui\materials.tsx`（各 1 行，标 `data-lawbench-drop`）
- `dsh-ext\tests\drop-guard.spec.ts`

**必需验证（`docs\plan\evidence\T17\` 下 28 个）**
- 截图 00–11
- `check_plugin_tree.py`、`mutate_check.py`、`dump_inventory.ps1`（和 T13 版本一致）
- `plugin-tree.txt`、`plugin-inventory-desktop.json`、`plugin-tree-check.txt`、`mutate-check.txt`
- `api-probe-product.txt`、`client-modules-product.txt`
- `desktop-tests.txt`、`desktop-tests-baseline.txt`、`desktop-rerun.txt`
- `drop-guard-red-green.txt`、`ts-test.txt`
- `交付说明.md`、`调研-20260930.md`（执行令要求存档）

**无关：0 个。**

## 三、关行核对表（22 行）

逐行对了三处，22 行全部一致：
- 在 DSH 原版 `packages\bundle\web-app\cordis.patch.yml` 里存在（逐行位置见下表）；
- 在我方补丁第 1c 节写成顶层 `- id: X` 加 `disabled: true`，符合原版文件头"按行 id 整行替换 config 或 disabled"的规矩；只写 disabled、不写 config，所以不需要整行重写；
- 静态树第 2d 项核对为 `disabled: true`。

| 行 | DSH 原版位置 | 执行令批次 |
|---|---|---|
| terminal-controller | web-app:111 | 第一批 |
| ui-sidebar-terminal | web-app:276 | 第一批 |
| file-reference-local | web-app:78 | 第一批 |
| session-reference | web-app:75 | 第一批 |
| ui-reference | web-app:359 | 第一批 |
| workspace-files | web-app:113 | 第一批 |
| ui-sidebar-files | web-app:279 | 第一批 |
| open-in-app | web-app:62 | 第一批 |
| ui-open-in-app | web-app:69 | 第一批 |
| cordis-host-runner | web-app:144 | 第一批 |
| cordis-inspect-providers | web-app:150 | 第一批 |
| cordis-client-runner | web-app:227 | 第一批 |
| ui-cordis | web-app:322 | 第一批 |
| session-log-download | web-app:56 | 第一批 |
| ui-settings-plugins | web-app:399 | 第一批 |
| ui-settings-plugin-inventory | web-app:299 | 第一批 |
| plugin-inventory | web-app:98 | 第一批 |
| ui-settings-shell | web-app:405 | 第一批 |
| ui-settings-agent-loop | web-app:408 | 第一批 |
| ui-settings-subagent | web-app:411 | 第一批 |
| ui-settings-web-search | web-app:414 | 第一批 |
| ui-deliverables | web-app:328 | 09:39 裁决追加（注释写明依赖 `workspace-files`、要开回须两行一起开、记入 N41） |

- 没有多关、少关，补丁里没有重复 id（共 59 个）。
- 明令不关的 13 行（`permission`、`ui-permission`、`ui-model-selection`、`ui-agent-preset`、`ui-trajectory`、`workspace-changes`、`command-feedback`、`ui-goal`、`ui-plan`、`directory-picker`、`subprocess`、`pwsh-sandbox`、`sandbox`）都没碰，别的节也没改。
- 这 22 行只在 web-app 那一层出现，desktop 或 apps 层没有重新插入它们的地方。

**没改 DSH 源码**：`git diff 661f57b 2827c69 --stat -- dsh dsh-patches` 为空；子模块指针前后都是 `477b4f42…`。

## 四、反向检查与变异验证

**和 T13 版比，改了什么**
- `MUST_OFF` 正好加了这 22 行，同时从白名单里删掉，没有多删别的。
- `PENDING_DECISION` 为空。
- 新增三项检查：2b 启用但没激活、2c 我方四行在、2d 静态树都写着 disabled。
- 新增 `--inventory-overlay`，只给 `plugin-inventory` 这一行开豁免。
- `dump_inventory.ps1` 和 T13 版本一致。

**实跑结果**
- `check_plugin_tree.py … --inventory-overlay`：rc=0，"通过"；启用的 110 行里没激活的 0 个；我方行都已激活。
- 和提交的 `plugin-tree-check.txt` 对比：只差 BOM，内容一致。
- `mutate_check.py`：16 例全部符合预期，rc=0。
- 一个小坑：脚本在别的目录跑时，因为 `persona.md` 是按目录层级找的（`parents[4]`），基线会误报；按仓库结构摆放后正常。

**我自己加的变异（在副本上）**

| 变异 | 结果 |
|---|---|
| 静态树里 `plugin-inventory` 改成 `disabled: false` | 报出 |
| 静态树里 `ui-settings-web-search` 改成 `disabled: false` | 报出 |
| 静态树里删掉 `ui-deliverables` 整行 | 报出 |
| 运行时把 `cordis-client-runner` 改回启用 | 报出 |
| 不带取证声明时 `plugin-inventory` 启用 | 报出 |
| 带取证声明、但静态树里 `plugin-inventory` 没关 | 报出 |
| 从"必须关"里删 `ui-settings-shell`，同时运行时启用 | 以"清单外的启用行"报出 |
| 只从"必须关"里删 `ui-settings-shell` | 不报。预期如此：删的是规格本身，要靠复核 diff 发现 |
| 只从 `T17_STEP1` 删一行，同时静态树里该行没关 | 不报，见 P3-3 |

## 五、`plugin-inventory` 临时开一行取证的做法

- 交付说明 1.3、2.1 和证据互相对得上：
  - 静态树里这一行是 `disabled: true`；
  - `api-probe-product.txt` 里 `POST /api/pluginInventory/list` 返回 404；
  - `client-modules-product.txt` 里加载了 43 个界面模块，本批对应的界面包 0 个。
- 取证时的运行时清单和产品配置只差 `plugin-inventory` 这一行。我查了 DSH 源码：用到这个服务的只有 `ui-settings-plugin-inventory` 和 `ui-plugin-manager`，两者都关着。所以开它不会改变别的行能不能激活，证据仍有代表性。
- 这个办法的弱点在于"取证期"只是命令行上的一个声明。静态树第 2d 项已经堵上了一种风险：叠加层被误写进产品补丁时会报出来。

## 六、DSH 自带测试的核对

- **只在改后失败的 6 项**（分属 5 个文件）：
  - installed-update-builder、macos-signature、packaged-runtime-verification、windows-update-publisher 各 1 项，都是 5 秒超时；
  - package-target-errors 2 项：win32 那项超时，darwin 那项是它连带出的断言失败。
  - `desktop-rerun.txt` 重跑 6 个文件，只有 profile-mcp 失败（这是已知的），其余 5 个全过。
- **只在对照里失败的 1 项**：packaging-run 的 stage kill，同样是超时类。
- **两边都失败的 10 项**：upload-with-credentials 7 项、signature-batch 1 项、signature-cache 1 项、profile-mcp 1 项（`mcp-resources` 自 T4 起就关了）。
- 没有发现被归错类的真实失败。和 `cordis.patch.yml` 相关的只有 profile-mcp，那是本步之前就有的。

## 七、证据核对

- 截图 00–11 逐张看过：没有 Key、令牌、本机用户名，没有别的软件窗口。
  - 路径只出现 `D:\lawbench-A\.tmp-demo\…`、`D:\示例案件\…` 这类；人名、案名都是虚构的（带"虚构"字样，另有"李律师""某某律师事务所"）。
  - 截图 06 露出了两台服务器的内网地址，这是 Spec 里本来就公开的地址，不算机密。
- 文本证据搜过：没有 `<用户>`、`Users\<名>`、`sk-`、`Bearer`、password；测试日志里的路径已替换成 `%USERPROFILE%`。
- `调研-20260930.md` 没有用户名。`plugin-tree.txt` 和 `plugin-inventory-desktop.json` 里没有带用户名的路径，也没有 Key。
- 交付说明第 1、2 节的每条说法都找到了对应的证据文件，例外见 P3-5、P3-7。

## 八、我实际跑过的命令

实验都在 scratchpad 下的 `rv-A17-A-lab`：用 `git archive` 导出 HEAD 再用 python 解包；robocopy `/XJ` 复制 `dsh-ext\node_modules`，重建了 8 个 junction；`dsh\node_modules` 和 `dsh\packages` 用 junction 只读指向 `D:\lawbench-A\dsh`。

- `git rev-parse` / `status` / `diff --stat` / `ls-tree dsh`
- 在 DSH 仓库里用 Grep 定位这 22 行 id，读 `drop-events.ts`、`WorkspaceBrowser.tsx`
- `node scripts/build.mjs`：rc=0，纯 ESM 导入检查通过
- `tsc -p tsconfig.json --noEmit`：rc=0
- `node scripts/test.mjs`：17 个文件、204 项通过、5 跳过，和作者报的一致
- 守卫变异 2 个：删掉拖动经过时的 stopPropagation → 2 项变红；删掉粘贴时的 `intakeActive` 判断 → 没变红（见 P3-2）
- `python scripts\check_ui_words.py`：零命中
- `python contracts\check_examples.py --skills skills`：rc=0
- `check_plugin_tree.py` 和 `mutate_check.py` 各一次，加上自写的 9 个变异

## 九、残留审计

- 我起的 node、python 进程都已结束。
- 在场的 python 17584、24796 是线 C 的 pytest；soffice.bin 10028、42468 不是我的，另一个 24248 也不是我起的。都没有动。
- 实验目录先拆了 10 个 junction，再用 `shutil.rmtree` 删掉；删完确认 `D:\lawbench-A\dsh\node_modules` 和 `dsh-ext\node_modules\.pnpm` 完好。临时清理脚本也已删除。
- 复核克隆工作区干净，HEAD 仍是 `2827c69`。
- 没有写入 `D:\lawbench*` 和 `D:\lawbench-coord`，没有启动桌面端，没有联网，没有碰凭据管理器。

## 十、证据缺口（没启动桌面端，下面这些验证不了）

- 静态树 `plugin-tree.txt` 真是 `--dump-config` 在产品配置下导出的：只能从 2d 项全是 true 反推。
- `plugin-inventory-desktop.json` 是真实运行时导出的，并且取证后叠加层已恢复、哈希一致：没有原始哈希记录可以复算。
- 截图 01–04、06–08 显示的入口确实没有了（Ctrl+\`、Ctrl+Alt+O 无反应，Host 没有新建子进程）：只能看截图，"没有子进程"没有证据文件。
- 真实拖入时守卫生效，拖到左侧栏也弹提示（见 P3-5）；粘贴文件在桌面端没有实测，作者已说明。
- `SessionFileReferences` 子插件停在 pending 不影响会话：只有截图 07 能间接看出。
- `api-probe-product.txt` 的 404 能不能复现（见 P3-7）。

PASS
