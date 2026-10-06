# lawbench 项目档案（PROJECT-PROFILE）

> 2026-09-29。给仓库 `.claude\skills\` 下 13 个工程 skill（5gate、coordination-worktree、verify-3way、senior-review、keep-pushing、moniter-on、compass、compact-s、reboot、orch-plan、human-explain、cn-prose、formal-report）看的项目事实。
> skill 管"怎么做"，本项目"是什么"以本文件为准。**冲突顺序：`CLAUDE.md` 与事实索引 > 本文件 > skill 原文。**
> 本文件不写任何 Key、密码、网络密钥，只写存放位置。

---

## 1. 必读与台账

| 名称 | 路径（仓库根 = 你所在的工作目录） | 用途 |
|---|---|---|
| 五门台账 | `docs\plan\lawbench-工单集-第一版开发-20260928.md` | 工单 T0–T27 与五门格；**只由主编排在 `main` 上修改** |
| 事实索引 | `docs\plan\lawbench-关键事实索引-20260928.md` | 机器、会话表（第 7 节）、决策台账（第 6 节）、纪律（第 8 节）、五门含义（第 9 节） |
| 编排总览 | `docs\plan\lawbench-编排计划-第一版开发-20260928.html` | 给人看的总览、依赖图、候 owner 清单初版 |
| 终点 runbook | `docs\src\PRD.md` 第 8 章验收 27 项（1–26 + 16a）；执行在 T22 | "做完"的判据 |
| 候 owner 清单 | `D:\lawbench-coord\ORCH-候owner清单.md` | 只有用户能拍板的事；主编排维护（T0 建立，初版抄编排总览的候 owner 清单） |
| 值守计划 | `D:\lawbench-coord\ORCH-值守计划-<YYYYMMDD>.md` | 仅 keep-pushing 开窗时写 |
| lane 登记 | `D:\lawbench-coord\lawbench-lane-registry.json` | 现任主编排、各线工作目录 / 分支 / 当前工单；**现任主编排以此为唯一判据** |

compact、换代或新会话的第一动作：读五门台账，答出"在哪张卡、哪一门、缺什么"。

## 2. 角色

| token | 会话 | 模型 · 推理档 | 工作目录 / 分支 |
|---|---|---|---|
| `ORCH` | 主编排 | Fable · high | `D:\lawbench` / `main` |
| `A` | 线 A（客户端：DSH、组合包、界面、打包） | Opus 5.5 · high | `D:\lawbench-A` / `line-A` |
| `B` | 线 B（Python 工作台服务） | Opus 5.5 · high | `D:\lawbench-B` / `line-B` |
| `C` | 线 C（395 服务与周边、归档、所外访问） | Opus 5.5 · high | `D:\lawbench-C` / `line-C` |
| `D` | 线 D（macOS 版：平台隔离、云上打包与冒烟；T28 起，2026-10-06） | Opus 5.5 · high | `D:\lawbench-D` / `line-D` |
| `REVIEW` | 复核员（主编排派的子代理） | Opus 5.5 · high，`model` 显式写 | 只读检出待复核分支 |
| `SCAN` | 机械扫描、diff、只读取证、恢复演练（子代理） | Haiku · low 或 Sonnet · high，`model` 显式写 | 只读 |
| `OWNER` | 用户本人 | — | SSH 密码、395 上亲手操作、与律所沟通、拍板、真人门 |

- **施工线一律 Opus 5.5**，不按 5gate 用量纪律的"施工线 sonnet"。派子代理 `model` 必填，禁止继承主会话。
- 主编排不写产品代码。

## 3. 协调目录（文件信箱）

- 路径 `D:\lawbench-coord\`：**在仓库外**，四个会话共用一个，不进 git；历史件按月移到 `_archive\YYYYMM\`。T0 建立。
- 命名：
  - 定向件 `致<收件>-<发件>-<件型>-<主题>-<YYYYMMDD-HHMM>.md`，例 `致A-ORCH-执行令-T2-20260929-1730.md`、`致ORCH-B-交回-T3-20260930-1015.md`
  - 广播件 `ORCH-广播-<主题>-<YYYYMMDD-HHMM>.md`
  - 用户原话件 `OWNER-<主题>-<YYYYMMDD-HHMM>.md`：用户在某个会话里拍板后，该会话把原话逐字落成此件，其他会话以此为准
- 件型：执行令 / 回执 / 进度 / 交回 / 探活 / 注记 / SELFTEST / 心跳。时刻先取系统时间再写，禁手打。
- **交回件与交付说明的分工**：六节正文（目标与出处 / 改动清单与提交 SHA / 红绿验证 / 测试证据路径 / 契约或文档摘要 / 自检与遗留、模糊条款摘录）写在仓库里的 `docs\plan\evidence\T<n>\交付说明.md`，随分支提交；信箱里的交回件只写三行：工单号、分支最新提交 SHA、`交付说明.md` 路径。
- 收件 pattern（初稿，上线前按 moniter-on §2 用真实文件名回测）：
  - ORCH：`^致ORCH-|^OWNER-|^SELFTEST-ORCH`
  - A：`^致A-|^ORCH-广播-|^OWNER-|^SELFTEST-A`（B、C 换字母）
- 心跳：`D:\lawbench-coord\<角色>-心跳-监控存活.md`，只证进程活；会话活只认进度 / 回执 / 交回件的修改时间。停更超 40 分钟落探活件；探活 30 分钟无回执，主编排上候 owner 清单请用户看一眼那个窗口。
- **禁入信箱**：Key、密码、EasyTier 网络密钥、SSH 密码、真实案卷内容和材料名。需要时只写"见 `.env.local`"之类的位置。

## 4. worktree 与合并

1. 三条线用**分支**（`line-A` / `line-B` / `line-C`，T0 建立），不用 skill 里的 `--detach`。执行令写明当时 `main` 的 SHA；线开工先 `git rebase main`，再 `git rev-parse HEAD` 核对。
2. 合并权归主编排：线只在自己分支 commit，不 push；主编排复核后合并进 `main` 并 push `main`。
3. 工单集只由主编排改（各线改会在合并时冲突）。
4. **禁 `git stash`**（所有工作目录共用一个 stash 栈）。
5. 写前 `git status --short`；出现不是自己改的文件 = 停手，落注记件报 ORCH，不要 checkout 掉。
6. 端口预分配：测试里的服务一律监听端口 0（随机）；必须固定端口时 A 用 18801–18809，B 用 18811–18819，C 用 18821–18829；18765（本机转发默认端口）只在真机联调时用。
7. 全量测试在某个工作目录上跑的时候，不改那个目录；同一工作目录上复核与修改不并行。
8. 第一版收尾时统一 `git worktree remove`，中途不删。

## 5. 五门（以事实索引第 9 节为准）

| 门 | 本项目含义 | 与 5gate / verify-3way 原文的差别 |
|---|---|---|
| ①任务门 | 该卡"验收"全部满足；产品代码经复核（第 6 节）；证据在 `evidence\T<n>\` | 同 |
| ②合流门 | 合并进 `main` 后 pytest 全量、契约自检、`build_skills.py` 全绿；证据 `evidence\T<n>\merge.txt` | 不打候选 tag、不做"五处来源核对"；合流含 `contracts\_build\` 改动时先重跑生成脚本再跑全量 |
| ③盲测门 | 一个没看过开发过程的会话，只按验收步骤操作能复现 | 没有 staging；在开发机或 395 上用 `tests\fixtures\` 虚构材料；红绿灰判据照 verify-3way §2 |
| ④发车门 | 功能在 Windows 安装包里，干净机器上装好能跑 | 没有生产部署、回滚窗、规范镜像仓；"发车件"只在 T22 全量验收时出一份 |
| ⑤真人门 | 用户本人亲手验过（一句话 + 截图即可） | 同 |

verify-3way 里数据库事务、RLS、审批链、zod 三副本的条目与本项目无关，忽略。本项目的"契约多副本"= `gen_schemas.py` → 生成的 schema → 样例 → 服务端和插件里的校验代码。

## 6. 复核分级（覆盖 5gate 用量纪律第 2 条）

| 改动 | 谁复核 |
|---|---|
| 只改测试、文档或读侧一两行 | 主编排亲核 |
| 产品代码或库函数 | 一名复核员（REVIEW），事实索引 8.5 的八项清单，四小时封顶 |
| 高风险卡：T3（路径闸门、地址白名单、本机转发）、T17（DSH 数据落点与外连补丁）、T25（发票引擎白名单动作）、T26（委托材料窗口隔离） | `/senior-review` 双人复核（两名 Opus 5.5 · high，同一条消息里并发派出） |

复核结论只是证据；合并与否由主编排决定。

复核员起真服务做实验时（2026-09-30 加，起因：一名复核员往设置里写坏地址后服务退回默认地址，"测试连接"带着凭据管理器里的 Key 探了一次真实 6000D）：**先把 6000D、395 两组地址都设成 `127.0.0.1` 上没人监听的端口**，并把应用数据目录指到实验目录，再调"测试连接"或任何会外发的接口；实验里凡是"坏地址回退默认"的路径，只验证"服务起来了、用的是默认地址"，**不再调测试连接**；确需验证连接行为的，在实验副本里把默认地址常量改成本机死端口后再做。派发词里写明这一条。

## 7. 环境护栏

- 测试只用 `tests\fixtures\` 的虚构材料；仓库和信箱不放真实案卷。
- 测试 Key 只从各工作目录的 `.env.local` 读（`LAWFIRM_TEST_KEY_A` / `_B`），不打印、不写进证据；证据里出现 Key 就当场删掉重跑。
- 产品代码只允许访问 6000D、395 的所内地址（`192.168.8.77:8000`、`192.168.8.124:9000`）、所外地址（`10.126.126.1:8000`、`10.126.126.3:9000`）和 `127.0.0.1`。
- 6000D 目前不校验 Key（事实索引第 4 节），涉及 Key 的验收项标"候律所开启"，不判绿。
- 需要 SSH 进 6000D / 395 的步骤：写成命令交给用户执行，AI 不保存、不索要密码。
- `engines\` 原样使用；发票引擎只走白名单动作。
- Windows / PowerShell；中文路径加引号。

## 8. 无人值守授权范围（keep-pushing 用）

用户不在时**可以**：派单、复核、合并进 `main` 并 push `main`（仅在②合流门三项全绿后）、写信箱、回填台账、在开发机上跑测试和构建。

用户不在时**不做**，挂候 owner 清单：
- force-push、改写 `main` 历史、删除不是自己产出的文件；
- 需要 SSH 密码，或在 6000D / 395 / 阿里云中转上改配置；
- 改契约中影响接口语义的部分（纯补说明可由主编排同意后改，记 Spec 20.12）；
- 改 `engines\` 代码；
- 对律所或任何外部发送内容；
- 事实索引第 6 节"已定下的决定"的任何变动。

## 9. 交接与压缩

- 主编排换代交接：`D:\lawbench-coord\lawbench-ORCH-HANDOFF-<YYYYMMDD>-<NNN>.md`（首代 001），用 `/reboot`。
- compact 前 checkpoint：`D:\lawbench-coord\<角色>-COMPACT-CHECKPOINT-<YYYYMMDD-HHMM>.md`，用 `/compact-s`；主编排每个大节点（合流、派线、用户密集拍板后）刷一份。
- 交接件和 checkpoint 只记路径与状态，不抄 Key、不抄案卷内容。

## 10. 未安装的部分（skill 里提到、本仓库没有）

skill 包里提到的几个钩子脚本没有随包提供，本项目**暂不安装**；对应的事靠 skill 正文里的人工步骤做：
- `agent-model-gate.ps1`（拦截没写 `model` 的子代理派单）→ 靠 `CLAUDE.md` 和本文件第 2 节的规定；
- `compass-stop-guard.ps1`、`precompact-marker.ps1`、SessionStart 重架提醒 → 靠主编排自己在 compact / resume 后执行 `/moniter-on` 和 `/compass`；
- `autoCompactWindow` 未设置，用平台默认。

## 11. 启动口令（用户粘贴用）

| 会话 | 第一句话 |
|---|---|
| 主编排（`D:\lawbench`，Fable） | `读 CLAUDE.md、PROJECT-PROFILE.md 和 docs\plan 下的三件套，读 D:\lawbench-coord\lawbench-lane-registry.json，答出在哪张卡、哪一门、缺什么。` |
| 线 A / B / C（各自目录，Opus 5.5） | `读 CLAUDE.md 和 PROJECT-PROFILE.md。你是线 A（B / C 换字母）。执行 D:\lawbench-coord 里给你的最新执行令。` |
| 某条线交活了，对主编排说 | `线 B 交回 T5 了`（主编排去读它的交回件） |
| 主编排发了新执行令或返修令，对那条线说 | `有你的新执行令`（那条线去读 `D:\lawbench-coord` 里给它的最新一份） |
| 用户要离开较久时，对主编排说 | `/keep-pushing` |
| 回来后对主编排说 | `我回来了，/compass` |

## 12. 运行方式（2026-09-29 用户定，覆盖第 3 节的心跳和探活、skill 里"上线先挂监控"的要求）

- **用户在场时**：各会话不挂 Monitor、不跑巡检循环、不写心跳、不探活。传话由用户来：哪条线交活了，用户告诉主编排；主编排发了令，用户告诉那条线。
- **信箱件照常写**：执行令、回执、进度、交回、注记、原话件都照第 3 节落进 `D:\lawbench-coord\`。这是留证据，不能省。
- **只有用户说 `/keep-pushing`** 时才按 skill 架监控（moniter-on v4 的周期扫描）；用户回来后停掉。
- compact、resume、新会话之后不自动重架监控。
- 原话件：`D:\lawbench-coord\OWNER-简化运行方式-20260929-1936.md`。
