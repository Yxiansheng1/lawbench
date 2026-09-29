# T4 复核记录（一名复核员，八项清单）与主编排裁决

- 复核员：主编排派出的子代理，Opus 5.5 · high，只读
- target：base `35a798a`，head `f610cda12f42b8d7bacfb6f841d3b75307bb9cb1`（line-A），一个提交，17 个文件；子模块指针仍为 `477b4f4`
- 复核位置：主编排临时目录里的克隆；DSH 源码只读取自 `D:\lawbench-A\dsh`（`git show` / `git grep` / `git apply --check`）
- 时间：2026-09-29 20:05–20:16
- 局限：复核员不能启动桌面端。凡标"静态推断"的结论来自读源码，没有在运行中的桌面端上验证
- 第一部分由主编排据复核员的最终报告整理，发现、证据和结论未作删改；第二部分是主编排的裁决

## 第一部分 复核员报告

### Verdict：AMEND

工单清单上要关的 21 行全部关了，没有漏、没有多、没有 id 写错。问题出在**清单以外**：反向检查发现桌面端还有几处会外连或能扩大 AI 工具的入口没关。

### Findings

| 编号 | 严重度 | 问题 | 证据 | 复核员建议的最小修复 |
|---|---|---|---|---|
| P1-1 | P1 | 桌面端仍启用侧栏浏览器 `ui-sidebar-browser`，可访问任意网址。模型回答里的链接也可能在侧栏打开；材料里的注入指令可以诱导模型生成带案卷内容的网址，律师一点就发到外网。它用独立分区的 `<webview>`，Spec 3.2 P-9 只拦默认会话，拦不到它。违反"产品不外连"、Spec 14.3 | DSH `packages/bundle/web-app/cordis.patch.yml:272-274`：`disabled: !!js "ctx.get('profileContext')?.name !== 'desktop'"`；`apps/desktop-host/src/index.ts:27`：`profile: 'desktop'`。证据 `plugin-tree.txt` 是按 web profile 导出的，这一行未求值；`check_plugin_tree.py` 只查清单里的行。（静态推断） | 补丁加一行关掉它，重新导出插件树核对 |
| P2-1 | P2 | 模型设置页 `ui-settings-models` 仍启用，律师可自建指向任意地址的模型路由；改动写进 profile 自己的补丁，叠加在我方补丁之后，会覆盖 `llm-pi-ai` 行。最终靠 P-7 地址白名单兜底，而 P-7 还没做 | 该插件 README；`packages/boot/config-editor/README.md`。（静态推断） | 关掉；不关就列为 T17 / P-7 的前置风险 |
| P2-2 | P2 | 账号设置页和账号服务（`ui-settings-account`、`account-controller`）仍启用，界面上有 DeepSeek 登录、充值、用量链接和一个飞书反馈表单地址 | `ui-settings-account/src/contact-config.ts:17` 等。（静态推断） | 两行都关 |
| P2-3 | P2 | 工具呈现模式没有锁死：`tools` 行的模式取环境变量 `DSH_TOOLS_MODE`，`ptc-runtime` 仍启用。环境变量或 `$DSH_HOME\.env` 里写了 `ptc` 或 `both`，模型就会拿到 `run_code`（在新的 Node 进程里执行模型写的代码）。违反 Spec 3.1 工具白名单 | `packages/core/tools/README.md`、`packages/ptc-runtime/ptc-runtime-node/README.md`、`packages/boot/app-boot/src/index.ts:192,234-255`。（静态推断） | 加 `tools` 行 `config: {mode: native}`；可顺手关 `ptc-runtime` |
| P2-4 | P2 | Skill 两个目录的先后与 Spec 10.1 相反：DSH 同一级内先到先得，现在内置目录排在前面，管理员下发的同名 Skill 覆盖不了。内置目录只来自开发期环境变量 `LAWBENCH_SKILLS_DIR`，打包后没人设它内置 Skill 就不加载，用户也能借它把 Skill 根目录指到任意位置 | `packages/skill/skill-filesystem/src/index.ts:245-258`；`packages/skill/skill/README.md:84,141`。（静态推断） | 数组顺序改成管理员目录在前；内置目录由什么决定交主编排定 |
| P2-5 | P2 | 证据导出的是 web profile 的插件树，不是 Spec 3.1 要求的 desktop；检查脚本只核对清单内 21 行，"配置已覆盖"只判断不为空、不比较取值 | `plugin-tree.txt`、`check_plugin_tree.py` | 按 desktop 语境列出带 `!!js` 的行逐条判定，或增加"允许启用的行"白名单、清单外的启用行一律报出；改配置的行比较取值 |
| P3-1 | P3 | `PATCHES.md` 说 `credentials-local` 行"不存在"不准确：凭据行存在，id 是 `credentials`。Spec 3.1 表里的 id 写错了 | `plugin-tree.txt` | `PATCHES.md` 改正；提请主编排修正 Spec 3.1 |
| P3-2 | P3 | `PATCHES.md` 里 P-10、P-03a 的"验证方法"在证据目录里没有对应的日志或 profile 摘录 | 证据目录 | 各补一段元数据摘录 |
| P3-3 | P3 | P-03a 吞掉账号服务的全部错误（方向安全：只会变成"未登录"）；账号服务不可用时主进程每秒重连一次本机 WebSocket，空转刷日志。（静态推断） | `welcome-backend.ts`、`main.ts:424`、`account-backend.ts` | 维持临时补丁定性，`PATCHES.md` 注明副作用 |

NOTE（复核员核实无问题或归后续的）：

- P-12 只去掉了 Office 挂载这一处，没有多删，没有残留引用。P-10 的锁文件只加了 3 行，没有夹带别的依赖。三个补丁单独和合在一起都能干净应用。
- "只配一个 128K 窗口条目"的理由属实：DSH 把模型条目的 id 原样作为请求的模型名，同一路由内做不到三个条目发同一个模型名。可选方案：配三条路由，每条一个 id 为 `qwen38-27b`、窗口不同的条目。
- 重试配置改用路由的 `retryPolicy` 有源码依据；Spec 3.1、8.3 的写法要跟着改。
- `agent-ping` 只注册 `case_ping`，无日志、无网络；T7 要删的东西代码注释里写明了。
- 从案件文件夹加载指令或 Skill 的插件（`agent-instructions`、默认 Skill 根目录）都已关或已排除。遥测、更新、市场、联网搜索、MCP 相关的行都已关。
- 仍启用、归后续工单加固的界面能力（不是 AI 工具，也不外连）：侧栏终端、`@` 文件引用、跨会话引用（会把别的案件的会话快照注入本会话）、`workspace-files`（可读工作区外路径）、`open-in-app`、在界面里运行动态 Cordis 包。
- `session-log-deepseek` 目前不起作用，建议顺手关掉。
- `ui-settings.enabled`、`locale.preference` 是用户可改的字段，本卡只设了默认值。

### 八项清单

| # | 项 | 结论 |
|---|---|---|
| 1 | 契约与 Spec 一致 | 清单内 21 行通过；反向检查不通过（P1-1、P2-1、P2-2、P2-3）；P2-4 |
| 2 | 边界输入 | `agent-ping` 参数处理无问题；环境变量缺失时的行为见 P2-4；`!!js` 出错时的行为未实测 |
| 3 | 错误路径 | P3-3；P-12 无残留引用 |
| 4 | 日志不含正文 | 通过。抓包代理只记模型名、工具名、思考档参数等；`request-tools.json` 里没有消息内容、Key、Authorization |
| 5 | 路径闸门 | preset 里没有文件和命令工具；用户侧能读到案件外文件的入口归后续（T17） |
| 6 | 无外连 | 配置里的网址只有 `http://127.0.0.1:18765/v1`；三个补丁没有引入新的网络访问；反向检查有外连入口（P1-1、P2-1、P2-2） |
| 7 | 证据充分性 | 工具集合、思考档参数、`case_ping`、preset 入口不可见都有证据支撑；插件树证据见 P2-5 |
| 8 | 无机密入库 | 通过。`plugin-tree.txt` 里只有变量名，没有 Key 值；三张截图没有文字元数据 |

## 第二部分 主编排裁决（2026-09-29 20:17）

主编排在 DSH 源码里核了 P1-1（`web-app/cordis.patch.yml:272-274`、`desktop-host/src/index.ts:27`），并确认我方补丁里没有出现 `ui-sidebar-browser`、`ui-settings-models`、`ui-settings-account`、`account-controller`、`tools`、`ptc-runtime` 这几行。复核员的描述与源码一致。

**T4 不合并，返修。**

说明：漏掉的这几行不在 Spec 3.1 的清单里，线 A 是照清单做的，清单本身不全。所以这次返修同时要改 Spec。

### 必修

| 编号 | 裁决 |
|---|---|
| P1-1 | 关掉 `ui-sidebar-browser` |
| P2-1 | 关掉 `ui-settings-models`。服务器地址只在我方设置页改（T13） |
| P2-2 | 关掉 `ui-settings-account`、`account-controller`；关掉后实测欢迎页和进入工作区正常，P-03a 是否还需要如实写明 |
| P2-3 | `tools` 行锁成 `mode: native`，关掉 `ptc-runtime`；实测设了环境变量 `DSH_TOOLS_MODE=both` 后抓到的工具集合仍恰为三个 |
| P2-4 | Skill 目录数组改成管理员目录在前。内置目录：开发期继续用环境变量，打包后由 Host 固定为安装目录（T20 落实），在 `PATCHES.md` 记一条待办 |
| P2-5 | 反向检查做成脚本：增加"允许启用的行"白名单，清单外的启用行一律报出；带 `!!js` 的行按 desktop 语境逐条判定并写进证据；改配置的行比较取值 |
| P3-1、P3-2、P3-3 | `PATCHES.md` 改正并补摘录、注明副作用 |
| 另 | 顺手关掉 `session-log-deepseek` |

### 交付说明第 6 节 5 项和其他说明

| # | 事项 | 裁决 |
|---|---|---|
| 1 | "高"档发 `xhigh` | 同意。主编排已独立实测并改了 Spec 8.1、8.2（`main` 提交 `5b8c35b`） |
| 2 | P-12 不在 Spec 3.2 清单里 | 同意，主编排补进 Spec 3.2 |
| 3 | P-03a 临时补丁 | 同意，P-3 落地时删掉 |
| 4 | 应用数据目录 | 暂用 `%LOCALAPPDATA%\lawbench\`，正式位置随软件名称定（候 owner 清单第 8 项） |
| 5 | 产品名暂用 `lawbench` | 同上 |
| — | 只配一个 128K 条目 | 同意（Spec 8.2 允许的备选）。三条路由的方案不采用：律师选的窗口只控制输入长度和最大生成量，由我方插件控制，够用 |
| — | 新增 `agent-default-model`、`ui-settings` 两行 | 同意 |
| — | 重试改用路由的 `retryPolicy` | 同意，主编排改 Spec 3.1、8.3 |
| — | G-2（打开工作区时从 `cwd` 读取的内容） | 归 T17 |

### 记账，归后续工单

侧栏终端、`@` 文件引用、跨会话引用、`workspace-files`、`open-in-app`、动态 Cordis 包、"默认工作区"入口、溢出目录为空的检查：归 T17 / T13 加固。主编排在派 T17 的执行令时逐项列入。

返修后由一名**新的**复核员对 T4 的完整范围重新复核。
