# T17 第三步返修累计（第四轮）· Reviewer A（改动纪律与可维护性）

- target：line-A `bc6e86e`（已 rebase 到 main 297f9cd）；范围 `93a864f`（T17 第三步返修）、`bc6e86e`（T13 N51 小项）+ 第三步累计
- 冻结清单：`review-综合裁决-第三轮.md` 第 3 节
- 派发：两名 Opus 5.5 只读复核员同一条消息并发派出，素材相同，互相看不到
- 复核克隆：scratchpad `rv-A21`
- 归档：主编排于 2026-10-01 13:45 (+08:00) 从复核员交回原文抄录，未改内容

## 复核员原文

## Reviewer A（改动纪律与可维护性）· T17 第三步返修累计范围 + T13 N51 小项

**核实 target**：克隆 rv-A21，`HEAD = bc6e86e6aef281ed1fb29045b6ef89e18841d0d7`，工作区干净，merge-base 就是 main `297f9cd`。本轮范围是 `93a864f`（T17 第三轮返修）和 `bc6e86e`（T13 N51）。rebase 后第三步主体对应 `af517c6`，N46 ② 对应 `155069f`；原来的 `995814a`、`5d685cf` 对象还在。实验都在 `git archive` 导出的副本 `rv-A21-lab` 里做，结束后已删除。

---

### 一、Findings

**P2-1 旧工作区去掉失败时代码照样挂到新工作区，同一编号会记在两处，DSH 下次启动工作区服务起不来**（本次修正引入）
- 白话：作者自己找到的最严重后果（整个侧栏不可用），在"去掉"这一步写盘失败时又会出现。`attach-sessions.ts:76-85` 对 `detachSession` 的异常只记日志，第 85 行仍然对同一编号 `attach`。
- 影响：只要 `$DSH_HOME\storages` 的那次写入失败一次（盘满、文件被杀毒占着、没权限），下次启动 `validateStoredState` 就抛 "workspace domain is inconsistent"，工作区服务和会话服务都起不来，只能手工改登记文件。
- 证据：实验 X1 用真 `WorkspaceRegistry` 和我方路由，按"复制、启动时缓存名单是旧位置"的场景，让旧工作区的 `detachSession` 抛错。结果 `{"attached":1,"failed":0}`，旧、新两条原始记录都含 `s1`。重启报：`workspace domain is inconsistent: session 's1' is accounted by both workspace … and workspace …`。
- 最小修复：去掉失败的编号不再挂，计入 failed。补一条用例：旧工作区 detach 抛错时，新工作区不挂，重启正常。
- 归类：范围内阻断（B-F2 修法的一部分，不是 B-F2 原来那个根因）。

**P2-2 名单换掉后，"编号 → 实例"表不跟着失效，复制场景仍会续写进旧文件夹**（B-F1 的残留路径，机制和 B-F1 不同）
- 白话：B-F1 修好了名单本身。但路由的编号表 `owner` 在名单整个换掉之后不作废。启动时缓存名单还是旧位置，第一次 `list()` 早于刷新（缓存不空时 `list()` 不等首刷，工作区登记启动时就会 list），编号表就记成旧位置。刷新后到下一次 `list()` 之前，`open(id,'write')` 走 `locate` 的已知分支（`router.ts:160-161`），直接用旧实例写。投影缓存的 `ownerOf` 同样指向旧位置，也写进旧文件夹。
- 触发方式：启动后不经首页"打开案件"（那条路会走 `attachCaseSessions → list()`，把表纠正过来），直接点侧栏旧位置工作区下的会话接着写。作者桌面端复测第二节走的是先进新位置，没覆盖这条。
- 证据：实验 X3（假后端，按根分"磁盘"）的顺序是：缓存只有旧位置时 `router.list()`，然后 `roots.replace([新位置])`，再 `open('s1','write')`。输出 `X3 write root [ 'OLD' ] header cwd OLD`。再跑一次 `list()` 之后变成 `NEW`。这条没有在真 JSONL 或桌面端上复现。
- 最小修复（1–3 行）：`locate` 里已知实例的 `caseRoot` 不在当前名单上时，当作 miss，和 B-F6 的处理一样；或者 `replace()` 有变化时清掉相关表项。补一条对称用例：复制，刷新前列过一次，刷新后直接续写，断言落进新文件夹、旧文件夹逐字节不变。
- 归类：范围内阻断。**请主编排注意止损线**：裁决写的是"B-F1（复制后写进旧文件夹）同根因再露不再返修"。我的判断是根因不同：B-F1 是名单合并时保留旧根，已关闭；这条是路由缓存没跟着名单走，窗口也窄得多，所以给 AMEND。如果止损线按括号里的症状读，这一条够得上止损，由主编排定。

**P3-1 私有字段 `table` 不在、`indexHeaders` 还在时，"退回路径"并不安全**
- 白话：PATCHES.md 核对清单写"方法或字段不在时……复制场景挂不上、只记日志"。但只有 `table` 改名或去掉时，代码退回看过滤后的 `sessionIds`；这时索引已经重建，旧工作区看不出记着它，于是不去掉直接挂，又是两处都记着。
- 证据：实验 X2（登记只给 `list` 和 `indexHeaders`）结果 `{"attached":1}`，旧、新原始记录都含 `s1`，重启报登记不一致。
- 缓解：W4 用例直接引用 `b.reg.table`，换 DSH 提交时按清单跑测试会先变红。
- 最小修复：`registry.table?.get` 不是函数时跳过 `indexHeaders`。这样 `attach` 拿缓存的旧 cwd 核对会失败、只记日志，不会写出重复。另外改正 PATCHES.md 的这句话。
- 归类：范围内（文档声称和代码不符）。

**P3-2 投影缓存的替身存储域依赖 DSH 内部写法，没有登记进"换 DSH 提交核对清单"**
- 依赖的有三处：storageDomain 的 `open(spec) → {table(), global, close()}` 形状；`SessionProjectionCache` 用到的 KvTable 方法子集（`get`/`put`/`update`/`delete`）；cordis 只通知同一隔离作用域依赖方的行为（交付说明 7.3 自己写了这一点）。
- 清单现在只有 3 行（`PATCHES.md:69-71`）。
- 最小修复：加一行，指向 `projection-cache.spec.ts` 的"接 DSH 原版缓存类"一组。
- 归类：独立后续（可维护性）。

**P3-3 Host 包装 `LawbenchRemote.attachCaseSessions` 没有直接用例；注释和代码不一致**
- 参数不对返回 `INVALID_ARGUMENT`、两个服务不在返回 0、异常转成 `INTERNAL`，这三条没有用例。方法表测试只核了方法存在和形参名。
- `host/index.ts` 注释写"界面不等结果"，而 `ui/index.tsx:117` 是 `await call(...)`。打开案件要等 `persistence.list()` 走完所有案件根，每个挂住的根最多等 3 秒。
- 最小修复：二选一，把注释改成"会等"，或改成不等待；补 2 条 Host 用例。
- 归类：范围内小项。

**P3-4 投影缓存 `get()` 用同步 `readFileSync` 读案件根**（臆测，没有复现）
- 案件放在映射网络盘、盘挂住时，会卡住 Host 的事件循环，抵消 B-F5 的 3 秒上限。
- 只在这个会话此前已经被路由记到这个根时才会发生。
- 最小修复：写进 7.7 已知限制，与已列的"建实例那一步同步检查根目录"并列。
- 归类：独立后续。

**P3-5（T13 bc6e86e）`notice` 的 try/catch 没有被测试守住，红测说法不准**
- 实验：只去掉 try/catch、保留 `r.value?.code`，`dock-a19.spec` 21 项全过。连 `?.` 一起去掉，N2 才变红。
- 所以真正挡住 N2 的是 `?.`，try/catch 是没被测到的第二道保护。`catch {}` 不记日志。
- 最小修复：把 `N51补充\red-tests.txt` 改成"去掉 try/catch 且去掉 `?.`"，或删掉多余的 try/catch。
- 归类：范围内文档小项。

**NOTE**
1. 交付说明整份换行符从 CRLF 改成 LF：diff 显示 1219 行，实际改动 127 行（`--ignore-cr-at-eol`）。复核噪声，不影响内容。
2. `ui/fixtures/invoice_run.json` 补 `"failed": false`：与 T17 无关，是 rebase 到契约 1.3 后的必要随带（`invoice_run.schema.json` 已把它列为必填），7.9 已说明。最好单独提交。
3. A-P3-2 用"子目录 cwd"代替"搬家后的根"：对记录头改写、Proxy 句柄、编号表这条路是等价的。"旧 cwd 在盘上已不存在"这一点覆盖不到，由 5.2/7.1 的真 JSONL 搬家、复制用例覆盖。我认为充分，请主编排确认接受这处偏离。
4. B-F2 从裁决写的 `ui/index.tsx` 改到 Host 做：理由成立（界面拿到的 `workspaces` 客户端没有 `attachSession`）。`attachCaseSessions` 不在 `API_ROUTES`（不走 `/api`），在 `REMOTE_METHODS` 里，方法表测试和"界面调用都在表里"测试都覆盖。
5. 截图里侧栏留着 3 个空的同名"民事-虚构乙"工作区（每复制一次留一个）。独立后续，UX 问题。

**作者自报两条的判断**
- ①"先去掉再挂"：正常路径守住了。我跑了作者的变异"先挂后去掉"，W4 变红（`1 failed | 6 passed`），W4 的步骤断言加重启核对是有效守卫。没守住的是"去掉失败"这一支（P2-1）。
- ② 两处私有依赖：`indexHeaders`（attach 拿登记缓存的记录头核对 cwd，不重建就挂不上）和 `table`（只有原始记录能看出纯搬家后旧工作区还记着它）都是最小必要，我没找到公开替代。已登记进核对清单，W1、W4、W5 会先变红。退回路径在两者都不在时安全，只有 `table` 不在时不安全（P3-1）。
- 维护成本：**私有依赖加核对清单，成本低于新开源码补丁。** 新补丁要进补丁链、每次换 DSH 都要重新生成、在 DSH 侧补测试，而且换提交时仍要人核对；私有依赖在换提交时同样会被 W 系列用例拦住。同意主编排的倾向，前提是修掉 P2-1 和 P3-1。

---

### 二、逐 hunk 清点

| 提交 | 文件 | 归类 |
|---|---|---|
| 93a864f | `session-store/case-roots.ts`（`replace`、load/save 日志） | 必需实现（B-F1、A-P3-5） |
| | `session-store/router.ts`（首刷等待、`within`、miss 重找、`checkAccess`、list 不等待） | 必需实现（B-F4/5/6、A-P3-3/5） |
| | `session-store/index.ts`（gate、投影缓存接线） | 必需实现（B-F4、A-P2-1） |
| | `session-store/projection-cache.ts`（新） | 必需实现（A-P2-1 ①） |
| | `host/attach-sessions.ts`（新）、`host/index.ts`、`shared/remote-methods.ts`、`ui/index.tsx` | 必需实现（B-F2） |
| | `cordis.patch.yml` | 必需实现（A-P2-1 配置；371 行说法改正；N46 注释） |
| | `P-5`、`P-9` 补丁 | 必需实现（A-P3-6、A-P3-1） |
| | `P-17`、`P-18` 补丁（只有 index 行和行号变化） | 必需验证（补丁链重新生成的随带） |
| | `PATCHES.md` | 必需实现（A-P2-2、私有依赖登记） |
| | `tests/*`（session-store、workspace-attach 新、projection-cache 新、intake） | 必需验证 |
| | `check_plugin_tree.py`、`mutate_check.py`、`plugin-tree*.txt`、`mutate-check.txt` | 必需实现（A-P3-4） |
| | 交付说明、`第三轮返修\*` | 必需验证 |
| | `ui/fixtures/invoice_run.json` | 与 T17 无关（rebase 随带，属必要） |
| bc6e86e | `ui/dock.tsx`、`dock-a19.spec.ts`、T13 交付说明 17.10/17.11、`N51补充\red-tests.txt` | 必需实现 / 必需验证 |

没有发现夹带。

---

### 三、冻结清单 16 条逐条核对

| # | 条目 | 结论 |
|---|---|---|
| 1 | B-F1 名单以服务为准 | **名单本身已关**（replace，对称用例齐，变异变红）；**残留 P2-2**（编号表不跟名单走） |
| 2 | B-F2 挂回 | 已做在 Host，新远程方法不在 `/api`、在方法表里；W1–W5 有效。**P2-1 本次引入** |
| 3 | A-P2-1 选 ① | 已关：原版缓存类加替身存储域，落 `<案件>\工作区\会话缓存\<编号>.json`，默认根只放内存；3 个变异都红；`reuseOrCreateBlank` 已核实写明 |
| 4 | A-P2-2 PATCHES.md P-9 登记 | 已关：`file:` 理由写明，测试名与 DSH 里的实际用例对得上 |
| 5 | A-P3-1 拼写检查 | 已关：`main.ts:606` 在首次配置窗口打开（1040 行）之前执行；去掉这行 main-startup 变红（我复现过） |
| 6 | A-P3-3 案件外会话续写拒绝 | 已关：给同一句说明，只读照常 |
| 7 | B-F4 首刷等待 ≤3 秒、提示文字 | 已关 |
| 8 | B-F5 单根 3 秒超时 | list/stat 已关；同步 I/O 剩余见 7.7 和 P3-4 |
| 9 | B-F6 编号表失效回退 | "表里实例说没有"已关；"表里实例已不在名单上"没覆盖（即 P2-2） |
| 10 | A-P3-2 契约整套 | 案件根、子目录根各跑一遍；flush 和重复编号用例都有；替代方案判为充分（NOTE 3） |
| 11 | A-P3-4/B-F7 静态树与检查脚本 | 已关：重新导出、第 8 项核 `allowOutsideCase`、3 个变异都报出 |
| 12 | A-P3-5 缓存出错日志、刷新不等 | 已关 |
| 13 | A-P3-6 P-5 钩子循环抽函数 | 已关（`askIntake`） |
| 14 | 子目录 cwd 改写为根 → 已知限制 | 已写入 7.7 |
| 15 | `/api/file` 可读会话记录 → 已知限制 | 已写入 7.7（Spec 14 由主编排改） |
| 16 | A-NOTE-4 | 主编排已记台账 |

---

### 四、八项清单

| 项 | 结论 |
|---|---|
| 契约一致 | 通过：`check_examples` 通过，fixture 按契约 1.3 补字段 |
| 边界输入 | 有问题：P2-1（去掉失败）、P2-2（名单换掉）、P3-1（字段只缺一半） |
| 错误路径 | 去掉失败后继续挂（P2-1）；其余回退都记日志，T13 的 `catch {}` 不记日志（P3-5） |
| 日志不含正文 | 通过：新日志只记错误名、错误码、序号，用例断言不带路径和编号 |
| 路径闸门未被绕过 | 未变（P-15 第二步已定稿）；`attachCaseSessions` 只挂 cwd 等于该根的会话 |
| 无外连 | 通过：刷新只连 `127.0.0.1`；拼写检查关闭 |
| 测试覆盖新代码 | 大体覆盖。缺口：Host 包装（P3-3）、去掉失败、名单换掉后续写、T13 的 try/catch |
| 无机密入库 | 通过：改动文件扫过用户名和 Key 两类特征，只命中用例里的假令牌 `Bearer t`；截图路径不含用户名 |

---

### 五、实际跑过的命令（node `D:\node`，python 用 B 线的 venv）

- `git rev-parse HEAD`、`git status --short`、`git merge-base`、`git show`（各 hunk，含 `--ignore-cr-at-eol`）
- 从 `D:\lawbench-A\dsh` 新克隆，`checkout 477b4f4`，11 个补丁逐个 `git apply --check` 后 apply：全部 OK
- 补丁后的 62 个文件与 `D:\lawbench-A\dsh` 比对：58 个哈希一致；4 个 welcome 测试文件两边都是"已删除"。即 0 差异
- `node scripts\test.mjs`（dsh-ext）：**23 个文件 409 项通过、5 跳过**
- tsc：rc=0；`build.mjs`：通过，含纯 ESM 导入检查
- `check_ui_words.py`：零命中；`check_examples.py --skills skills`：通过
- `check_plugin_tree.py … --inventory-overlay`：通过；`mutate_check.py`：全部报出
- 作者 `mutate.py --only ext`：**21 个变异全红**，源文件逐字节复原
- DSH 侧变异"去掉 `setSpellCheckerEnabled(false)`"：main-startup 1 项失败，复原后 107 项全过
- DSH 受影响包（session-controller、session-persistence-jsonl、session-projection-cache、workspace、desktop 的 main-startup 和 lawbench-request-policy、ui-conversation）：104 个文件，2097 项通过、11 跳过。4 项失败是本机建符号链接 EPERM（环境原因）；session-controller 的 8 个 `*.client.spec` 在我的联接布局下载入失败（`window is not defined`，jsdom 环境没生效）
- 复核实验 `zz-rvA21.spec.ts`：X1、X2、X3，结果见上
- T13：`dock-a19.spec` 变异 M1（只去 try/catch）21 项全过；M2（连 `?.` 一起去）N2 变红

---

### 六、残留审计

- 我起的进程都已结束。本机现有 node 进程都早于本次复核，不是我的。19301–19309 没有监听。
- 第一次跑 DSH 测试时没重定向 TEMP，留下 `%TEMP%\dsh-jsonl-live-5B43Ib`，已删；之后的运行 TEMP 都指向实验目录。
- `rv-A21-lab` 删除方式：先逐个拆掉 1147 个联接（只删链接，不进目标），再删目录。
- 删除后核对：`D:\lawbench-A\dsh` 的 `git status` 仍是 62 项，`node_modules` 条目数 40 不变，dsh-ext 的 9 不变，workspace 的 `lib` 还在。
- 复核克隆 rv-A21 工作区干净。没有写过 `D:\lawbench*`、`D:\lawbench-coord`。

---

### 七、证据缺口

- 桌面端我没有跑。B-F2 侧栏归属以作者的 `桌面端复测.txt` 和截图为准；两者对得上（工作区计数与侧栏一致，路径不含用户名）。
- P2-2 只在假后端上复现，没在真 JSONL 或桌面端复现。
- session-controller 的 8 个客户端用例没能在我的环境里载入。
- DSH 侧变异只复现了 1/2（P-5 那个没跑）。
- `plugin-tree.txt` 我没有重新 dump；只核了它与 `cordis.patch.yml` 一致。

AMEND
