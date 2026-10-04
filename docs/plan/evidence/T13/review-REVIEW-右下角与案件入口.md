# 技术支持右下角 + 删侧栏案件入口 + 案件名跟文件夹（line-A `bab30d7`/`fb6246b`，T20/T13）· 复核记录（单人，八项清单）

- target：两提交，父 `22a225d` = main；复核克隆 `D:\lawbench-rv\rv-A39`
- 派发：Opus 5.5 只读复核员，2026-10-04 16:1x
- 归档：主编排于 2026-10-04 16:27 (+08:00) 从复核员交回原文抄录，未改内容

## 复核员原文## 结论先说
- **T20（技术支持只留右下角）**：没问题。
- **T13（去掉侧栏案件入口、案件名跟文件夹）**：有一处本次引入的回归，要修。律师选文件夹时用的路径写法，如果和服务、DSH 规范化以后的写法不一样（映射网络盘、subst 盘、上级目录是 junction），"移除旧位置登记"会把**刚打开的案件**从侧栏撤掉。日常事务每次启动都走这条路，所以也会中招。
- 你最关心的"盘暂时不在会不会被撤登记"：**不会**，和 T17 的口径不冲突。

## Findings

**P1｜本次引入的回归｜范围内阻断**
- **问题**：`openCase` 里找"同一 case_id 原在别处"时比的是字符串（`dsh-ext\ui\cases.ts`，`prev = …!samePath(x.root, dir)`）。界面记的是律师选的写法 `dir`；首页读到的列表里，同一案件的 root 是服务用 realpath 存的写法。DSH 建工作区时也做 realpath（`workspace\src\index.ts` 的 `realpathNormalize`）。两边写法一不同，`prev` 就会命中，接着 `forgetCaseWorkspace(prev.root)` 按规范写法找到的，正是刚由 `openCaseWorkspace(dir)` 打开的那个工作区，把它删了。
- **日常事务**：Host 返回的 root 是拼出来的路径（`host\daily-case.ts` 的 `join(dir, DAILY_NAME)`），`landOnDailyCase` 又先调 `loadRecent` 再 `openCase`。所以只要办公目录在映射盘上，每次启动都会把日常事务的工作区撤掉。
- **影响**：案件刚打开就从侧栏消失，它的会话落进"未分组"。文件和会话本身不丢。工单集里已有说法："律所的案卷放在文件服务器上是常态"，所以这个条件并不罕见。
- **证据**：
  - 实测（父目录 junction）：用 `<X>\lnk\案件\张某` 打开，服务登记成 `<X>\real\案件\张某`；Node 的 `fs.promises.realpath` 也得到 `<X>\real\…`。这里 `<X>` 指实验目录。
  - 界面层用例：先在首页列表放一条同 case_id 的规范写法，再用另一种写法 `openCase` → 被删的工作区就是刚打开的那个 `w-just-opened`。用例通过，说明这个行为确实发生。
  - 映射盘会被 realpath 还原成 `\\服务器\共享` 这一点是推断，本机不做 `net use`。
- **最小修法**：让 `openCaseWorkspace` 带回它打开的 workspaceId，`forgetCaseWorkspace` 永远不删这个 id。重启核对同理，排除刚打开的、当前所在的工作区；或者比较前双方都换成 DSH 的规范路径。补一例"同一位置换写法打开不撤登记"。

**P3｜独立后续**
- **问题**：重启核对时，凡是不在服务案件列表里的 DSH 工作区一律撤掉。服务的 `cases.json` 一旦重置或丢失，其他案件会全部被撤（实验：列表里只剩日常事务时，返回 `['w1','w2']`）。
- **缓解**：重新打开案件时，`attachCaseSessions` 会按 cwd 把会话挂回来，所以只算界面层面的扰动。
- **修法**：列表来自服务、但只有日常事务一条时不做核对；或者只撤"同一 case_id 换了位置"的那些。

**P3｜范围内小瑕疵**
- `dsh-ext\ui\home-page.tsx` 第 4 行的文件头注释还写着首页"底部'技术支持'一行"，已经过时。

**NOTE**
- "切换案件 ▾"菜单里，`exists=false`（盘不在）的案件没有任何标记，点了以后才报打不开。
- 窗口很窄时，右下角那行可能压到底部状态栏的文字上（不接鼠标，不挡点击）。

## 核对表
1. **身份**：`rv-A39` 的 HEAD 是 `fb6246b`，父链 `bab30d7` → `22a225d`，工作树干净。
   - 逐段归类：T20 = `brand.tsx` 的 VendorCorner、`index.tsx` 登记到 `shell.overlay` 并删掉侧栏那行、`home-page` 删掉页脚、`brand`/`home-page` 两个 spec。
   - T13 = 新增 `case-switcher`、`cases.ts`（folderName 和 prev/moved 两处移除）、`index.tsx`（删 CASES 面板、加 header.actions 和重启核对）、`rightbar.ts` 的 `staleWorkspaces`、`state.ts`（folderName 取代 caseBlockLabel）、`kit.tsx` 的 Nav 加 `forgetCaseWorkspace`、相关 spec，以及交付说明和三张截图。
   - 没有改 `dsh-patches` 和 `engines`。
2. **右下角常驻**：成立。
   - `position: fixed`，右 12、下 6，`pointer-events: none`。
   - `shell.overlay` 是 DSH 整个窗口的覆盖层（DialogHost 也在这一层）。
   - 侧栏那条 `sidebar.footer.action` 的 vendor 登记、首页的 footer 都已删掉。
   - "关于"页还在（`settings.tsx:139`）；首次配置页在 P-3 补丁里，没动。
   - 截图 02 里右下角的位置不挡输入框和发送键。
3. **案件入口**：成立。
   - CASES 面板和 CaseIcon 已删，侧栏只剩首页、新会话、会话列表。
   - 菜单数据和首页同源，都是 `app.cases`，来自 `loadRecent`。
   - 日常事务显示"（非办案）"，有用例。
4. **移除旧登记的三个时机**：
   - **盘暂时不在**：服务的 `registry.recent()` 不过滤，`exists=false` 的照样返回，所以 root 还在列表里，不会被撤。实验确认：U 盘案件 `exists:false` → `staleWorkspaces` 返回 `[]`。
   - **服务读不到**：`landOnDailyCase` 要等 `loadRecent` 成功才往下走，重启核对不会执行；列表为空时也什么都不撤。
   - **和 T17 的关系**：会话存储 router 在根还在列表上、只是不在盘上时，`caseMoved` 为真，盘插回后解除；和这里的移除不冲突。
   - **问题在写法不一致**，见 P1。
5. **改名查证**（只做到服务包和会话存储包这一层）：
   - 服务 `CaseRegistry`：打开 → 改名 → `recent` 显示 `('甲', exists False)` → 用新名重开，case_id 相同 → 列表只剩 `甲（改名）` 一条，老记录被替换。
   - 会话存储：`session-store.spec` 的 N55 ② 用例（`renameSync` 以后 `caseMoved` 为真，改回来解除）实跑通过。
6. **测试与检查**：
   - dsh-ext 全量 44 个文件，**595 项通过、6 项跳过**，和作者自报一致。
   - `tsc --noEmit` 退出码 0。
   - `check_ui_words.py --dsh D:\lawbench-A\dsh` 零命中。
   - 3 条变异全部被测试抓到，复原后逐字节一致（见下）。

## 八项清单
1. **契约一致**：通过。没有新增接口字段，`forgetCaseWorkspace` 只是界面内部的 Nav 方法。
2. **边界输入**：不通过，路径写法不一致的情况见 P1。
3. **错误路径**：通过。移除都包了 `.catch`；服务读不到时不撤。
4. **日志不含正文**：通过，新代码不写日志。
5. **路径闸门**：未被绕过。只撤 DSH 登记，不碰文件。
6. **无外连**：通过。
7. **测试覆盖新代码**：基本覆盖，但缺"同一位置不同写法"这一例。
8. **无机密入库**：通过。截图里的用户名已遮。

## 跑过的命令（都带超时）
- `git rev-parse` / `status` / `diff 22a225d HEAD`
- 把 dsh-ext、service、scripts、contracts、skills 用 robocopy 复制到 `D:\lawbench-rv\x39`，重建 12 个 node_modules 联接；`dsh\node_modules` 和 `dsh\packages` 只读联接到 `D:\lawbench-A\dsh`
- `node scripts\test.mjs`（全量）
- `tsc -p tsconfig.json --noEmit`
- `check_ui_words.py --dsh D:\lawbench-A\dsh`
- 复核用例 `zz-review.spec.ts`（4 例）和 N55 ② 一起跑：15 项通过
- `exp.py`：CaseRegistry 的 junction 写法实验和改名重开实验，Node realpath 对照
- 变异：
  - M1：删掉 `staleWorkspaces` 里的空列表保护 → 1 项失败
  - M2：删掉 `pointerEvents: 'none'` → 1 项失败
  - M3：删掉 `openCase` 里的 forget → 1 项失败
  - 三处都已复原，哈希一致。

## 残留审计
- 没有起任何服务或后台进程；19400–19409 端口无监听。
- 先用 `rmdir` 逐个拆掉联接（拆完剩 0 个），再删除 `D:\lawbench-rv\x39`；之后确认 `D:\lawbench-A\dsh` 和 dsh-ext 的 node_modules 都完好。
- `rv-A39` 仍在 `fb6246b`，工作树干净。
- 没有写入 `D:\lawbench-A`，没碰别人的进程。

## 证据缺口
- 映射网络盘被 realpath 还原成 UNC，是推断；验收机上请用真实映射盘打开一次案件、重启一次，看侧栏。
- 没有做桌面端真机复现，P1 的证据是界面层用例加 realpath 实测。

T13: AMEND
T20: PASS

