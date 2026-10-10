# T13 左栏"添加案件"接建案件流程（DSH 补丁 P-24；第七版待办 21）· 独立复核记录（PASS）

- 复核时刻：2026-10-10 19:12–19:40 (+08:00)；复核员：一名 Opus 只读复核员（克隆 `D:\lawbench-rv\rv-A59`，实验目录 `rv-A59-exp`）
- target：line-A `e85f0d0`；基座 main `68c39e8`；9 文件 +326/-5（新补丁 P-24、PATCHES.md、dsh-ext 接线与六条用例、截图 01–03）
- 裁决（主编排）：**PASS**，cherry-pick 进 main，发重打第七版令。P3（选的入口仍说"拖"）记第八版小项；Ctrl+O 与菜单"添加案件…"列入重打冒烟项。

## 复核员报告（原文摘要，路径已去用户名）

**结论：PASS。**

1. **P-24**：改 `WorkspacePicker.tsx adoptDirectory`、新 `lawbench-adopter.ts`、`navigation.ts UiWorkspaceService.setDirectoryAdopter`，测试加两例。三入口调用链：`+`→`requestAddWorkspace`→`WorkspacePickFlow addOnly`→`adoptDirectory`；Ctrl+O→`shortcuts.ts:91 workspace.add`→同 flow；菜单→`WorkspacePickFlow.handleSelect(ADD_WORKSPACE)`→同处。客户端只此一处调 `createWorkspace`；`ui-workspace` 单 client 入口，单例不分裂。未设接手人分支与原版逐语句同；接手人抛错进原出错框、不建不半建（变异"成功后仍 createWorkspace"1 红）。PATCHES.md 清单/编号/理由一致。
2. **严格补丁链**：`rv-A52-exp\dsh` 共享克隆检出 `477b4f42…`，19 个补丁 `apply --check` 与 `--whitespace=error-all` 全 0 输出；161 路径。A 的 `WorkspacePicker.tsx`/`navigation.ts` 与打补丁克隆逐字节一致。
3. **DSH spec**：`workspace-picker.client.spec.tsx` 18/18（借 A node_modules 只读联接 313 个，cacheDir 指实验目录）。
4. **dsh-ext 接线**：`registerWorkspace` 调 `registerAddCaseAdopter(ctx.uiWorkspace, ctx.effect)`，卸下清回；`addCaseFromPicked`→`dropOnBlank([path], true)`→`dropInfo`→`caseFromFolder`；序列 `dropInfo → caseOpen → materialsScan`；取消不调 `caseOpen`；已登记只 `dropInfo, caseOpen`；云同步不同意不挂原文件夹。变异 M1（去 `setDirectoryAdopter`）1 红、M2（取消仍打开）2 红。`caseFromFolder` 用 `ctx.workspaces.create` 不经 `adoptDirectory`，不递归。
5. **安全**：路径进 `droppedItems` 走 `plainAbsolute`（UNC/`\\?\` 拒）、链接/联接 other、盘根 `isDriveRoot`、保留名 `badCaseName`——与拖入完全复用。
6. 检查：dsh-ext 743/1/6（brand.spec 环境缺 `dsh\apps`，联接后 7/7，合计 744/0/6）；tsc 0；check_ui_words 零命中；截图无用户名。

### Findings
- **P3（独立后续）**：`ROOT_TEXT`、`nameText` 在"选"的入口仍说"拖…进来"（`drop-case.ts:34,37,95,97`）；只有 `OTHER_TEXT` 有"选"版本。
- **NOTE**：P-24 用例只挂菜单 `WorkspacePicker`；`+`/Ctrl+O 走同组件同函数，`+` 真机核过，Ctrl+O→`controls.add` 由 `shortcuts.client.spec` 覆盖；Ctrl+O 与菜单列重打冒烟项。
- **NOTE**：`registerWorkspace` 里那一行接线无单测（去掉不红），真机在线；可补集成断言。
- **NOTE**（臆测）：插件加载前/失败时接手人未设会退回原版行为；P-14 规定无我方包 DSH 不启动，窗口极小。

### 跑过的命令
`git diff 68c39e8 e85f0d0`；dsh 共享克隆 + 19 补丁严格打；哈希比对；dsh-ext vitest 全量/单跑/变异 M1、M2；tsc；check_ui_words；DSH 单 spec + 变异 D1 后备份还原。联接全部拆除（rv-A59 4 个、dsh 313 个），A 目录 `.vite`/`.vite-temp` 无写入，克隆干净。实验目录留打好补丁的 dsh 克隆可复用。
