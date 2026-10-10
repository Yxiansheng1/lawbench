# T13 首页拖文件夹建案件（第七版待办 20）· 独立复核记录（AMEND）

- 复核时刻：2026-10-10 14:55–15:08 (+08:00)；复核员：一名 Opus 只读复核员（克隆 `D:\lawbench-rv\rv-A55`，实验目录 `rv-A55-exp`）
- target：line-A `355cc7c`；基座 main `5e0d218`；18 文件 +583/-16
- 裁决（主编排）：**AMEND**。P2-1 与 P3-1 阻断（小），P3-2 一并修；令 `致A-ORCH-执行令-拖文件夹建案件复核AMEND-<HHMM>.md`。返修后换新复核员审累计范围。NOTE 1–4 记口径/独立后续。

## 复核员报告（原文摘要，路径已去用户名）

**Verdict: AMEND。** 无阻断性安全问题；安全面、落点分流、多文件夹逐个问、云同步退复制均核对成立。

### Findings
- **P2-1 "当过案件"判定比令宽**（范围内阻断）：`desk-actions.ts:droppedItems` 设 `has_case = 工作区 是普通文件夹`，`drop-case.ts:caseFromFolder` 命中即 `openCase` 不弹确认框；令第 6 条写的是"内有 `工作区/wiki` 或已登记"。律师文件夹里恰有"工作区"子目录会被静默登记（`registry._init_db` 无 case.db 时发新 id），该子目录随即成软件自用区。现有用例"乙案"建的是 `工作区\wiki`，区分不出。修：改看 `工作区\case.db` 或 `工作区\wiki`；补"只有 `工作区\`"弹确认框用例。
- **P3-1 `plainAbsolute` 守卫无用例守**（范围内阻断）：变异 M7 去守卫后 `drop-case.spec.ts` 13/13 仍绿（用例里 `\\fs01\案卷\丙` 不存在，靠 lstat 失败落 other）；实测 `\\?\D:\…`、`\\localhost\D$\…` lstat 可达。修：加真实存在的 `\\?\<tmp>\甲案` 期望 `kind:'other'`。
- **P3-2 取消守得不严**（独立后续）：取消改抛错后仍绿（被 `dropOnBlank` 的 `.catch` 接成"没能建案件"提示）。修：取消用例断言无 notice 对话框。
- **NOTE**：1 路径中间一级是联接照收（服务 `gate.check_root` 按 realpath 再拒，口径说明）；2 `dropInfo` 回任意本机绝对路径的顶层名字（≤50 项、children ≤2000，不读内容，日志只记个数），新增一个面；3 拖盘根先问"把『D:』建成案件？"后被服务 `root_is_drive` 拒，`badCaseName` 可先拦；拖用户目录/`C:\Windows` 服务不拒属既有口径；4 `.lnk` 文件夹快捷方式按文件提示；5 选的类型无下游用处（已答复：保留，1.4 候项 15）；6 变异 M1（去 `isSymbolicLink`）存活但冗余保险非缺陷。
- **核过无问题**：卡片 dragover/drop stopPropagation（M3 去 `onOver` 转红）、`missing` 卡片也拦；空白处只在 `types` 含 `Files` 时生效，胶囊排序不受影响；云同步复制目标经 Host `localCaseFolder`→`safeFolderName`+`localRoot(userProfile)`，同名 `(2)`，写不到用户目录外（M6 转红）；`target:null` 契约允许；多文件夹逐个问有用例；截图 01/03/05/06 无用户名。

### 检查
`drop-case.spec.ts` 13/13；全量 722/1/6（brand.spec 环境缺 dsh 子模块，与 A 自报 723/0 一致）；`tsc --noEmit` 0；`check_ui_words` dsh-ext 零命中（1 处命中在未检出的 dsh 子模块占位，环境原因）。

### 跑过的命令
`git diff --stat/diff 5e0d218 355cc7c`；三联接只读借用（`dsh\node_modules`、`dsh\packages`、`dsh-ext\node_modules`），vitest 以 `rv-A55-exp\vitest.rv.mjs` 包原配置、`cacheDir` 指实验目录；`node --experimental-strip-types rv-A55-exp\t.ts`（联接、父级联接、盘根、`\\?\`、`\Windows`、`D:relative`、`..`）；`q.cjs` 核 `\\?\`/`\\localhost\D$` 可达；变异 M1–M8 于 `rv-A55-exp\mut` 副本（M2/M3/M6 转红；M1/M4/M5/M7/M8 存活，M1/M4 冗余等效）。借用联接全部 `rmdir` 拆除，A 目录 `.vite` 时间戳不变、`.vitest` 不存在，克隆 `git status` 干净。
