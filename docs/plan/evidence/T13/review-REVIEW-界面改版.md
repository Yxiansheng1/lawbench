# 用户看程序后的界面改版四件 + 三小项与计时暂停（line-A `429e1d6`…`6eca648`，T13/T20/T7）· 复核记录（单人，八项清单）

- target：8 个提交，父 `874f470` = main；复核克隆 `D:\lawbench-rv\rv-A36`
- 派发：Opus 5.5 只读复核员，2026-10-04 13:1x
- 归档：主编排于 2026-10-04 13:30 (+08:00) 从复核员交回原文抄录，未改内容

## 复核员原文## 结论先说
8 个提交都在两份令的范围内，没有夹带。安全面、机制不变、计时暂停、`call()` 修法这几项我都亲自跑过或读过代码核实。没有 P0、P1、P2，只有 4 条 P3 和几条 NOTE，都不挡合并。三张卡都 PASS。

身份：`D:\lawbench-rv\rv-A36` 的 HEAD 是 `6eca648cc738…`，工作区干净。`874f470..HEAD` 共 8 个提交，39 个文件，+1121/−162，与复核包一致。

## Findings
**P3-1 "日常事务"遇到不会自己好的错误时，会一直重试下去**
- 问题：`ui\cases.ts` 的 `landOnDailyCase` 是个不会退出的循环（`for (;;)`），只要结果不是 ok 就继续：前 30 秒每 2 秒取一次，之后每 10 秒一次。
- 影响：设置被云同步规则拒（`putSettings` 抛错）或登记被拒（`CASE_IN_SYNC_FOLDER`）时，每次重试都要读写一次设置，Host 再记一条 `daily_case.ensure` 警告（只有元数据，约一天 1 MB）。律师看不到任何提示。作者在交付说明里披露了这个风险，但写的是"下次启动再建"；代码实际是在本次会话里每 10 秒重试一次。另外，被同步规则拒时错误码报成了 `SERVICE_UNAVAILABLE`，不准确。
- 证据：`host\daily-case.ts` 的 catch 把所有异常都归成 `SERVICE_UNAVAILABLE`；`cases.ts` 的 `landOnDailyCase`。
- 最小修复：遇到 `CASE_IN_SYNC_FOLDER`、`INVALID_ARGUMENT` 这类不会自己好的错误就停止重试，或者只在下次启动时再试。
- 归类：独立后续。

**P3-2 "文档"位置是写死的**
- 问题：代码用的是 `USERPROFILE\Documents`，不是系统登记的"文档"文件夹。
- 影响：文档文件夹被 OneDrive 重定向时，文件夹会建在 `C:\Users\<用户>\Documents\连越律师工作台`。这样恰好躲开了同步拒绝，但律师在资源管理器里点"文档"看不到它。
- 证据：`host\index.ts` 的 `dailyCase()`。
- 归类：臆测，NOTE。

**P3-3 先建文件夹，后过闸门**
- 问题：`ensureDailyCase` 先 `mkdir` 再调 `/api/case/open`。闸门在服务端：设置写入时走 `check_office_dir`，打开案件时走 case/open 的同步规则。
- 影响：被拒时会留下一个空的 `日常事务\`。闸门本身没被绕过：办公文件夹在保存设置时已经按同一条同步规则校验过；默认路径也要先经 `putSettings` 校验，失败就不建。网络路径对普通案件本来就允许（律所文件服务器），不算绕过。
- 归类：NOTE。

**P3-4 胶囊读失败会被缓存（既有问题，这次影响变大）**
- 问题：`dock.tsx` 的 `loadCaps` 会把读失败的结果缓存下来，这是改版前就有的写法。
- 影响：以前首页还有一份带重试的胶囊入口；现在输入框上方是唯一入口，第一次读失败后要到重启或"管理胶囊"保存之后才会出现。按现在的挂载顺序（先打开案件，打开前已读到案件列表，说明服务已就绪），实际很少碰到。
- 归类：独立后续。

**NOTE**
- 输入框上方的工具胶囊只有"发票整理"有用例；"文件生成"（委托材料窗口）没有用例。代码是 `openRetainer(caseRef)`，读过没问题。
- 中间提交 `429e1d6` 单独构建不过（TS6142），是作者自报的。只影响二分查找，HEAD 已修好。
- 我这边测试跳过 6 项（凭据管理器 5 项、符号链接 1 项），作者报的是跳过 1 项。差别来自运行环境，不是用例被删。
- 和令不一致的两处，作者已在交付说明披露，请主编排定：
  - "日常事务"登记时 `template: null`，没有套民商事或刑事的标准子目录。令的原话是"目录结构与普通案件相同"。
  - 令要求"首次配置完成时创建"，实际是首次配置做完后、界面第一次问到时才建。
- **流程偏差，我自己造成的**：在打了补丁的 DSH 克隆根目录跑 vitest 时，`node_modules` 是联接到 `D:\lawbench-A\dsh\node_modules` 的。结果 vitest 把结果缓存写进了 A 那边：`D:\lawbench-A\dsh\node_modules\.vite\vitest\da39…\results.json`（13:28，93 KB），`.vite-temp` 目录的修改时间也变了（里面是空的）。这只是测试结果缓存，不影响演示实例。我没有再去动它，因为删除也是一次写入。

## 核对表
1. **提交归类**：8 个都是必需实现，各自带验证，没有无关提交。
   - `429e1d6`：T20 改版第 1、2 条。
   - `f91effa`：第 3 条。
   - `81d4369`：第 4 条。
   - `0f9a706`：令 1117 第 3 项，加注记 11:28 的计时暂停。
   - `048eac2`：令 1117 第 1、2 项。
   - `28c5ea3`：第 4 条补修。
   - `30c9709`：logo 补修，另把 DSH 鲸鱼标换成律所 logo，属品牌口径。
   - `6eca648`：补修 `call()` 和打开时机。
   - 三处补丁逐段看过，没有夹带：
     - P-3：律师姓名、`message` 原样显示、底部技术支持一行，外加测试。`profile.lawyer_name` 契约里本来就有（`contracts\files\settings.schema.json`）。
     - P-4：只改了两个字，"莫莱特"改"莫来特"。
     - P-19：只改轮次进度的名称、读屏播报和计时，判断依据是正在跑的 `ask_user_question` / `request_user_input`。消息内容没碰。
2. **安全面**
   - `dailyCase` 写回设置时只改 `office.dir`，其余字段原样带回。
   - `REMOTE_METHODS` 里登记为 `{dailyCase, params: []}`；界面的方法描述由方法表生成；构建时"方法形参名与方法表一致"检查通过。
   - `brand-assets.ts` 里只有两个 `data:image/png;base64` 常量。
   - 闸门情况见 P3-3。
3. **机制不变**
   - 点第二层胶囊调的是 `pickCapsule` → `setSelection`，还是原来那条任务单路径（`/api/task`，`sheetHold` 没改）。
   - 原来的"胶囊"下拉框已删，只剩一套选择器；Skill 下拉是二级选择，保留。
   - 工具胶囊：发票打开发票页，"文件生成"调 `openRetainer`。
   - 没有删用例文件。`home-retry` 改成只看最近案件，"服务晚就绪自动重读、30 秒后给重试"这条守护还在。
4. **计时暂停**
   - 遇到 `ask_user_question` 时暂停（`agent\index.ts` 的 `preTool` 和 `beforeTool` 两处）。
   - `beforeModelCall` 一开头就 `resume`，45 分钟上限和 40 分钟收尾线用的是补过暂停时长的起点。
   - 恢复路径有用例：第 70 分钟时 `elapsed` 是 1200 秒，说明恢复后又开始走表。
   - 变异：去掉 `resume` 后变红。
5. **`call()` 修法**
   - 只对方法表里 `params` 为空的方法不传参数，其余照旧。
   - 通过 `call()` 调用的无参方法只有 `selfCheck`、`dailyCase`；`setupState`、`getSettings`、`listSkills` 是直接走 `lb()` 的，不受影响。
   - "启动检查提示条从未显示"属实：基线 `874f470` 的 `home.tsx:318` 是 `call('selfCheck')`；DSH 网关 `packages\api\gateway\src\client\index.ts:495-500` 参数个数不符就抛错。这条记为既有缺陷，已修。
   - 有参方法没有回归：`call-args.spec` 覆盖了 `caseRecent`、`getCapsules`。
6. **测试与品牌**：结果见下面"跑过的命令"。

## 八项清单
- **契约一致**：通过。`case_open` 的 `template` 允许 null；`profile.lawyer_name` 在契约里；`check_examples` 过。
- **边界输入**：通过。律师姓名为空、超过 40 字、含控制字符都拒，有用例。
- **错误路径**：有 P3-1。
- **日志不含正文**：通过。`daily_case.ensure` 只记 ok、code、created，不记路径。
- **路径闸门未被绕过**：通过，见 P3-3。
- **无外连**：通过。新代码只有 127.0.0.1 上的服务调用。
- **测试覆盖新代码**：通过。只有 retainer 工具胶囊没用例（NOTE）。
- **无机密入库**：通过。

## 跑过的命令
全部在 `D:\lawbench-rv\a36x`（已删）里做。代码是 rv-A36 工作区的拷贝；DSH 是从 `D:\lawbench-A\dsh` 新克隆、checkout `477b4f4` 后打的补丁，依赖用联接指向 A。
- 按 PATCHES.md 顺序打 14 个补丁：每个 `git apply --check` 都是 0，`apply` 也都是 0。打完后 129 个改动路径里 125 个与 `D:\lawbench-A\dsh` 逐字节一致，另 4 个是 P-3 删掉的文件。
- `node scripts\test.mjs`：40 个文件，577 项通过，6 项跳过，0 失败。
- `tsc --noEmit`：退出码 0。
- `node scripts\build.mjs`：通过，包括纯 ESM 导入检查和形参名检查。
- `check_ui_words.py --dsh <补丁后的 DSH 克隆>`：零命中。
- `check_examples.py --skills skills`：通过。
- DSH 端：`chat-view.client.spec -t P-19` 1 项通过；`lawbench-first-run.spec` 和 `lawbench-welcome-page.client.spec` 共 14 项通过。
- 4 条变异，都变红，改动的文件都按哈希复原：
  - 不写 `daily-case.json`：2 项红。
  - 去掉 `resume`：1 项红。
  - `call()` 改回总是传参：1 项红。
  - 点胶囊不调 `pickCapsule`：30 项红。
- 品牌：
  - `make_brand.py` 重跑：19 个品牌文件逐字节一致。`brand-assets.ts` 与提交里的版本 blob 哈希一致（`08dc494`）；直接比工作区文件只差 CRLF 换行。
  - "上海莫来特智能科技有限公司"出现在：侧栏 `VendorLine`、首次配置页（P-3 的 `VENDOR_LINE`）、设置"关于"；DSH 关于面板也有（P-4）。
  - 代码里不再有"莫莱特"，只剩 PATCHES.md 里描述这次改名的一行。

## 残留审计
- 没有起后台进程，所有命令都是前台跑完退出的。19370–19379 没有监听。
- 联接先拆后删：DSH 包下的 630 个和 dsh-ext 内部的 12 个都先单独拆掉，再用 `rmdir /s /q` 删实验目录。之后确认 A 那边的 `node_modules\vitest\vitest.mjs` 和 `workspace\lib` 都还在。
- `D:\lawbench-rv\a36-p3.diff` 已删。rv-A36 工作区干净，HEAD 没变。
- 唯一越界写入是上面说的 vitest 结果缓存。

## 证据缺口
- 没有跑 DSH 全量 `pnpm run build`，也没有单独构建 `429e1d6` 去复现 TS6142，两者都是作者自报。
- 没有做桌面端实测，包括真网关下启动检查提示条真的显示出来、两层胶囊的真实观感。
- P-19 没有做变异。
- 文档文件夹被 OneDrive 重定向的机器没有实测（P3-1、P3-2 是读代码推断的）。

T13: PASS
T20: PASS
T7: PASS

