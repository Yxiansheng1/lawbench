# 设置页三提交复核 AMEND 的关闭（line-A `c5fba37`，T13）· 复核记录（单人，窄范围）

- target：`c5fba37`（父 `8dc72d8`）；复核克隆 `D:\lawbench-rv\rv-A41`
- 派发：Opus 5.5 只读复核员，2026-10-04 17:4x
- 归档：主编排于 2026-10-04 17:53 (+08:00) 从复核员交回原文抄录，未改内容

## 复核员原文## 结论
上一轮的五条复核意见（P1、P2、两条 P3、一条 NOTE）都已经关上。这次提交只有交回件里说的那些内容，没有夹带别的改动。只剩一条 NOTE，不影响放行。

## findings
- **NOTE（独立后续，不阻断）**：`host\path-state.ts` 只拦开头两个字符是斜杠或反斜杠的路径。像 `\foo` 这种从当前盘根目录写起的路径，Node 在 Windows 上认作绝对路径，所以会被收下去查。
  - 影响：只是在本机盘上查一下有没有，不走网络，也不读内容，没有实际风险。
  - 最小修法：再加一条只接受带盘符的路径 `/^[A-Za-z]:[\\/]/`。也可以不改。

## 关闭核对表
| 项 | 结果 | 独立证据 |
|---|---|---|
| 身份与范围 | 过 | 复核克隆 HEAD 是 `c5fba37…`，父提交 `8dc72d8`，工作区干净。14 个文件逐段看过，都能归到 P1、P2、pathState、forgetIfGone、切换菜单不再听滚动、P-4 版本号、PATCHES.md、交付说明这几类，没有夹带 |
| P1 关窗口拦截 | 关 | ① 在 `ui\`、`host\` 里搜 `beforeunload`，只剩 `settings-draft.ts` 第 5 行一条注释。<br>② 我自己构建出的 `lib\` 里一处都没有。<br>③ 静态读了 DSH `main.ts` 的 1113–1152 行：`finishQuit` 先藏窗口、关 Host，最后才 `app.quit()`；主进程不处理"页面阻止关闭"那个事件，所以只要页面拦一下就会卡住。现在页面这边已经没有拦截。<br>④ 有用例 `settings-save.spec` "有修改时关窗口不阻止"，同时断言 `installUnloadGuard` 已经不导出 |
| P2 Ctrl+, 重开 | 关 | 第三个按钮文案改为 `KEEP_LABEL` "留着修改（下次打开设置还在）"，选了直接返回 `'cancel'`，什么都不做。`reopenSettings` 已删，`dsh-ext` 里搜 `KeyboardEvent` 为 0。有用例 |
| pathState 输入与超时 | 关 | 正则 `/^[\\/]{2}/` 能拦 `\\host`、`//host`、`\\?\`、`\\.\`。相对路径、空值、不是字符串的输入，都由 `isAbsolute` 和类型检查拒掉。stat 改成异步，3 秒超时，超时回 `TIMEOUT`、权限等其他错误回 `UNKNOWN`，两种情况界面都不撤。`REMOTE_METHODS` 里登记的是 `pathState` 带一个参数 `request`，和方法签名一致；构建时也报"方法形参名与方法表一致"。这个方法不写日志（`host\index.ts` 里它前后没有 `this.log`） |
| 先问 pathState 再撤 | 关 | 变异 M1：删掉 `forgetIfGone` 里"先问、问不到就返回"那两行，`rightbar.spec` 有 1 例变红，改回后哈希一致。`index.tsx` 已经改成调用 `forgetIfGone`（这一处是看代码确认的） |
| 超时不能当作"不在" | 关 | 变异 M2：把超时也当成"不在"处理，`path-state.spec` 有 1 例变红，改回后哈希一致 |
| NOTE 切换菜单 | 关 | `case-switcher.tsx` 只保留窗口变大小时收起，挂监听和卸监听两边对称 |
| 版本号 P-4 | 过 | 本提交对 P-4 只加了 `CurrentVersionRow.tsx` 和 `components.client.spec.tsx` 两节。`DSH_CLIENT_VERSION` 在桌面端的定义和用处（`client-metadata.ts`、`tsdown.config.ts`）这次都没碰。`brand.spec` 用例核对的是 `LAWBENCH_VERSION = '${PRODUCT_VERSION}'` |
| 补丁链 | 过 | 新克隆 DSH，检出 `477b4f4`，按 PATCHES.md 的顺序打 16 个补丁，每个都返回 0。共 143 个路径，和 `D:\lawbench-A\dsh` 的哈希逐个比对：139 个一致，另外 4 个 `welcome-*` 测试文件在两边都已删除，所以 0 不一致 |

八项清单：
- 契约一致：过（方法表与形参对得上）。
- 边界输入：过（只剩上面那条 NOTE）。
- 错误路径：过（超时、权限错误都按"不知道"处理，不撤）。
- 日志不含正文：过。
- 路径闸门没被绕过：过（网络路径和设备路径都不收）。
- 无外连：过（本轮没起任何服务）。
- 新代码有测试：过（pathState 三例、forgetIfGone 一例、关窗口一例、版本号一例）。
- 无机密入库：过（diff 里没有 Key 或令牌）。

## 实际跑过的命令（实验目录 `D:\lawbench-rv\x-A41`，内容从 `git archive` 导出）
- dsh-ext 全量 `node scripts\test.mjs`：46 个文件，607 例通过、6 例跳过。
- 类型检查 `tsc -p tsconfig.json --noEmit`：返回 0。
- 构建 `node scripts\build.mjs`：返回 0，纯 ESM 检查和方法形参检查都过。
- `check_ui_words.py --dsh D:\lawbench-A\dsh`：零命中。
- 干净 DSH 克隆打全部补丁并做哈希比对，结果见上表。
- 变异 M1、M2 各跑一次，都变红，都已复原并核过哈希。

## 残留审计
- 本轮没起服务，19420–19429 端口没有监听。
- 机器上在跑的 4 个 node 进程是 17:42 启动的，比我开工早，不是我起的，没有碰。
- 实验目录已删。删之前先单独拆掉了指向 `D:\lawbench-A\dsh` 的联接，删完核过 `D:\lawbench-A\dsh` 和 `D:\lawbench-A\dsh-ext\node_modules` 都还在。
- 复核克隆 rv-A41 工作区仍然干净，HEAD 仍是 `c5fba37`。
- 没有往 `D:\lawbench-A` 写任何东西。

## 证据缺口
- 没做桌面端实测，也没做 Electron 实验：没有亲眼看到"带着未保存的修改点退出，进程能正常结束"。只按 DSH 退出流程的代码和页面侧零拦截推断。建议在验收机上实点一次。
- DSH `ui-settings-general` 那 13 例没在我的克隆里跑（克隆没装依赖）。版本号这一项靠补丁内容、哈希一致和 dsh-ext 的 `brand.spec` 用例来确认。
- `brand.spec` 读的是 `..\dsh` 里已经打过补丁的源码，要是子模块没打补丁，这一例会红。这是测试环境本身的前提，不算缺陷。

PASS

