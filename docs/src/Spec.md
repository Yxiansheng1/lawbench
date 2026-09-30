# 律所本地 AI 平台 — Spec（第三版）

依据：
- PRD 第四版（本文引用的需求编号 `F-*`、`SEC-*`、`G-*` 和章节号都以第四版为准）、《服务器现状报告》；
- **DSH 官方仓库** `github.com/deepseek-ai/deepseek-harness`，按提交 `477b4f4`（2026-09-24）核对。开发时从官方仓库重新拉取并固定在这个提交（编排计划的事实索引中写完整 hash）；换提交前要重新核对第 3 节列出的配置行和文件位置；
- 案件 wiki 测试（`D:\pycharm\test\wiki`，含大卷宗流水线实测）；本地最小链路试验（只用来验证思路，不作为代码基础）；
- 《业务能力编排》（`docs/src/业务编排.md`）和仓库中的 `skills/`（第 10 节）；
- 律所周海沺律师提供的三个 Skill：发票整理（invoice-ledger-db 3.9.4）、委托材料（retainer-offline 3.4.1）、案卷归档（lawyer-archiving 1.0.0），见第 12.4、13.3、13.5 节；
- 甲方《EasyTier 律所工作台远程接入方案 V2》及部署参数台账（第 15 节）；
- 补充情况：395 是一台 Windows 11 电脑（第 6 节）；本次只交付 Windows 客户端。

**相对第二版的主要变化**（2026-09-28 甲方需求变更）：首页改为两级胶囊（D11、第 10.3 节）；聊天附件改为"拖入即导入"（D13、第 5.1 节）；新增诉讼文书、刑期计算、招投标、案卷归档四类 Skill，接入发票整理和委托材料两个现成工具（D12）；远程访问改为 EasyTier（服务器侧由我方配置，第 15 节）；契约升到 1.1。

**本文写"怎么做"**：技术选型、模块划分、接口、关键规则。读者是写代码的人（包括 Claude Code）。开发按编排计划的工单进行，工单引用本文的章节号和 `contracts/` 下的契约文件。
- **模块之间的接口和共用的数据格式都以第 20 节契约和 `contracts/` 目录为准**，写到字段级、可以用程序校验；正文中出现的接口和格式是说明，与契约不一致时以契约为准。
- 保密相关的实现写到机制级。
- 涉及 DSH 的地方写明官方仓库里的文件和配置行，方便直接定位。
- 模块内部写到"用什么、输入输出、关键规则"，内部结构由开发工单自行决定，但不得改动契约。
- 标 **〔待验证〕** 的是还没实测的点，给出主方案和备选。

---

## 0. 关键设计决定（先看这一节）

| # | 决定 | 依据 |
|---|---|---|
| D1 | **客户端用 DSH 官方桌面端**（`apps/desktop`，Electron）改造，不用社区版。本次只打 Windows 包。 | 官方仓库里已有桌面端，自带中文界面和打包脚本。 |
| D2 | **我方所有 DSH 扩展做成一个"组合包"（bundle）**：一个 npm 包，里面有配置补丁（preset、关掉的插件、模型路由等）和三个插件（Agent 侧、Host 侧、界面侧）。随安装包放进桌面端的运行时，不依赖用户目录下的任何配置文件。**不用 MCP。** | DSH 的扩展方式就是"组合包 + 插件"（官方文档 `docs/architecture.md`）。放在运行时里，律师改不了，升级也不会丢。 |
| D3 | **律师工作台是一个 preset**（DSH 里"一个会话的 AI 挂哪些插件"的配置），里面只有：系统提示、Skill 加载、`ask_user_question`、上下文压缩和我方 Agent 插件。不挂文件读写、命令、网页、AGENTS.md 加载。AI 只能用我方的 `case_*` 工具，而且看不到案件路径。 | 桌面端用的 `dsh-web-app` 组合包已经把文件、命令等工具从全局关掉、改由各 preset 自己挂；我们的 preset 不挂，AI 就没有这些工具。案件隔离不依赖 DSH 沙箱。 |
| D4 | **只保留律师工作台这一个 preset**：官方自带的 4 个 preset（`standard`、`ptc`、`minimal`、`cordis`，都能执行命令、读写文件）全部关掉，默认 preset 改成我们的。 | 否则律师切换 preset 就能拿到命令和文件工具。 |
| D5 | **业务逻辑都在 Python（工作台服务）**；DSH 插件只做转发和闸门。工作台服务是常驻的本机进程，由我方 Host 插件启动和看护。 | 解析、检索、流水线、识别队列用 Python 写最合适；识别队列需要常驻进程。 |
| D6 | **两种执行方式**：**流水线**——程序控制流程，模型只写每一步的内容，每步写完程序核对出处；**Agent**——由 DSH 的 Agent 循环调用 `case_*` 工具。每个 Skill 在头部用 `mode` 声明走哪种。本次**只有案件 wiki 走流水线**，其余 17 个业务 Skill 都是 Agent；流水线框架是通用的，以后阅卷类 Skill 实测预算不够时可改为流水线。 | wiki 测试证明流水线可行：大卷宗 21 份材料、74 页，36 次调用、290 秒，单次最大输入 15K token，无截断，核对修正后只剩 1 处页码疑点。wiki 若走 Agent，一份材料至少一次模型调用，会超出 8 次的预算。 |
| D7 | **发往服务器的操作不开放给 AI**。提交识别、9B 抽取、生成 wiki 只能由律师在界面上点击触发；AI 的工具里没有这些。 | SEC-02：每次外发都由律师的操作授权，AI 无法自行外发。 |
| D8 | **PDF 在本机拆页和渲染**，只把律师选定的页面图片发给 395。 | 发送量最小；395 只处理单页图片，接口简单。 |
| D9 | **律师 Key 存 Windows 凭据管理器**：写一个凭据插件替换 DSH 的 `credentials-local`，工作台服务用 Python `keyring` 读同一条目（第 8.1 节）。 | PRD F-ACC-01a；明文文件在硬盘被拆下时可读。 |
| D10 | **模块之间的接口和共用数据格式以契约为准**（第 20 节、`contracts/`）：JSON Schema 文件，Python 和 TypeScript 用同一份文件校验。 | 各模块由不同开发会话并行编写，只靠契约对齐。 |
| D11 | **首页是两级胶囊，由配置文件驱动**：一级分组（民事与商事、刑事案件、日常办公），二级胶囊打开一组 Skill 或一个内置工具。默认配置随安装包（`skills/capsules.default.json`），律师本机的配置在 `<应用数据>/capsules.json`，胶囊管理器只能排序、改名、隐藏、新增和恢复默认，不能删除，不设密码（第 10.3 节）。 | 甲方需求变更；每位律师用自己的电脑，改动只影响本机；"隐藏"代替"删除"，误操作可以恢复。 |
| D12 | **律所已有的成熟工具原样接入，不改写成 Agent**：发票整理引擎由工作台服务按白名单动作调用（第 13.3 节）；委托材料是离线网页，在独立窗口打开（第 13.5 节）。**案卷归档按我方格式重写**：判断和写作交给 AI，合并卷宗、页码、Word 由程序完成（第 12.4 节）。与我方规则冲突处以我方为准：发票引擎经作者同意去掉设备授权、不用邮箱联网收取；归档不执行命令。 | 前两个工具已经完整可用，改写只增加风险；归档原 Skill 依赖 AI 执行命令，与 D3 冲突，且需要案件上下文。 |
| D13 | **聊天附件改为"拖入即导入"**：拖到对话框或材料面板的文件、文件夹，都复制进当前案件文件夹再解析（`/api/materials/import`），不再进入 DSH 的附件目录；"+"附件按钮去掉，改为"导入"按钮（可选文件或文件夹）。 | 附件存在 `$DSH_HOME`，不在案件文件夹，不经过识别、检索和出处；导入后全部走统一流程（SEC-01）。 |

---

## 1. 总体架构

### 1.1 进程和连接

```
律师电脑
┌──────────────────────────────────────────────────────────────────┐
│ DSH 桌面端                                                         │
│  ├ Electron 壳（窗口、托盘、首次配置）                              │
│  ├ 界面（Web 客户端）＋ 我方界面插件（首页、案件面板、原文查看）     │
│  └ Desktop Host（Node 进程，只监听 127.0.0.1）                      │
│      ├ Agent 循环：只有"律师工作台"preset（D3、D4）                 │
│      │   └ 我方 Agent 插件：case_* 工具、上下文注入、预算           │
│      ├ LLM 适配器 dsh-llm-pi-ai → 律所网关                          │
│      └ 我方 Host 插件：启动并看护工作台服务；界面调用的转发接口      │
│             │ 本机 HTTP（启动令牌）                                  │
│             ▼                                                      │
│ 工作台服务（Python，常驻，127.0.0.1 随机端口）                       │
│   ├ 案件与路径闸门   ├ 材料解析    ├ 全文检索（SQLite FTS5）          │
│   ├ 任务单与上下文   ├ 识别队列    ├ 流水线      ├ 出处核对            │
│   ├ 导出 / 修订版    ├ 归档生成    ├ 刑期计算    ├ Word/PDF 转换       │
│   ├ 发票引擎（子进程，白名单动作）  ├ 证件识别驱动（127.0.0.1:17801）  │
│   └ 6000D、395 客户端（只允许所内外地址）                            │
│             │ 读写                                                   │
│             ▼                                                        │
│ 案件文件夹（律师指定位置；即 DSH 的"工作区"，会话的工作目录）          │
│ 日常办公文件夹（发票台账，不是案件）                                 │
│ 委托材料窗口（独立 Electron 窗口，加载本地网页）                     │
└──────────────────────────────────────────────────────────────────┘
        │ HTTP（局域网 / EasyTier 虚拟网）     │
        ▼                                     ▼
6000D 网关 :8000 → vLLM ×2（仅本机）     395 预处理服务 :9000（Windows）
                                           ├ OCR 后端（仅本机）
                                           └ 9B 模型（仅本机）
```

- Agent 调用 6000D：由 DSH 的 LLM 适配器发起（第 8.1 节）。
- 流水线调用 6000D、所有 395 调用：由工作台服务发起。
- 所有网络请求都只能去首次配置里填的两台服务器（第 14.3 节）。
- **案件 = DSH 的工作区**：DSH 里"打开文件夹"会把这个文件夹登记为一个工作区，之后在里面建的会话，工作目录（会话头的 `cwd`）就是这个文件夹（官方 `packages/api/session-controller/src/commands.ts`）。我方界面把"打开文件夹"改叫"打开案件"。

### 1.2 我方组合包（`lawbench-dsh`）

一个 npm 包，放在我方仓库 `dsh-ext/`，打包时装进桌面端运行时（第 14.1 节）。`package.json` 里用 `dsh.bundle.patch` 声明配置补丁，DSH 按"`dsh-base` → `dsh-web-app` → 我方组合包"的顺序叠加（第 3.1 节）。

| 部分 | 运行在 | 做什么 | 用到的 DSH 接口 |
|---|---|---|---|
| `cordis.patch.yml` | — | 关掉插件、关掉官方 preset、声明律师工作台 preset、模型路由、其他配置（第 3.1 节） | 配置补丁：按行 `id` 替换配置或 `disabled: true` |
| Agent 插件 `legal-agent` | Host（挂在 preset 里） | 注册 `case_*` 工具；注入上下文；预算；请求参数；结束时写结果 | `ctx.tools.register`、`agent/pre-step`、`agent/request`、`tools/pre-execute`、`session/event` |
| Host 插件 `legal-host` | Host（全局） | 启动并看护工作台服务；给界面提供转发接口；网络白名单 | `ctx.subprocess.spawn`、`TypertRemoteService`（`@Remote` 方法） |
| 凭据插件 `legal-credentials` | Host（全局，替换 `credentials-local`） | Key 读写 Windows 凭据管理器（D9、第 8.1 节） | DSH 凭据服务接口（与 `credentials-local` 相同） |
| 界面插件 `legal-ui` | 界面 | 首页、案件工作区面板、原文查看、设置页、识别进度 | `ctx.slots.register`（`main`、`sidebar.panellist`、`sidebar.right.pane.tab`、`settings.section` 等插槽）、`ctx.remote.<命名空间>` |

**Agent 插件的挂载点**（事件名和类型按官方 `packages/core/agent/src/runtime-types.ts`、`packages/core/tools/src/index.ts`、`packages/core/session/src/types.ts`）：

| 挂载点 | 做什么 |
|---|---|
| `ctx.tools.register` | 注册 `case_*` 工具（第 4.4 节）。`execute(args, exec)` 里，从 `exec.agent.session.header.cwd` 取案件目录，从 `exec.agent.id` 取会话 ID，转发给工作台服务；工具参数里没有路径，模型看不到案件目录 |
| `tools/pre-execute` | 白名单：只放行 `case_*`、`skill`、`ask_user_question`，其余返回 `{kind:'deny', reason}` 并记日志；统计工具调用次数，超出预算就拒绝（`case_save_draft` 除外，第 9.2 节） |
| `agent/pre-step` | 每轮第一步：向工作台服务申请本次任务的 `task_id`，取 L0 + L1 上下文，用 `{kind:'enter', messages:[...原消息, 上下文消息]}` 注入（第 9.2 节）；之后每步检查模型调用次数和时长预算，超限返回 `{kind:'reject'}`，最后一次前注入"立即收尾" |
| `agent/request` | 按任务单设置 `reasoningEffort` 和 `maxTokens`（`LlmCallConfig` 只允许改 `provider / model / reasoningEffort / temperature / maxTokens / stop`，不能改请求头） |
| `session/event` | `assistant/message`：把模型回复交给工作台服务保存进度（第 9.2 节）；`turn/end`：写结果清单（结束原因取 `reason.kind`：`completed / aborted / blocked / error / max-tokens / interrupted`） |

**调用工作台服务**：`POST http://127.0.0.1:<port>/core/<命令>`，共 5 个命令（开始任务、取上下文、执行工具、保存进度、结束任务），请求和返回见第 20.3 节；成功 `{ok:true, value}`，失败 `{ok:false, error:{code, message}}`（`message` 是给律师看的中文）。端口和令牌由 Host 插件在启动服务时生成，通过 Cordis 服务共享给 Agent 插件。工作台服务不可用时，工具返回"工作台服务未启动，请稍后重试"。

**界面调用工作台服务**：界面插件 → `ctx.remote.lawbench.<方法>()` → Host 插件（`TypertRemoteService`，命名空间 `lawbench`，每个 `@Remote` 方法对应第 4.3 节的一个接口）→ 工作台服务 `/api/*`。注意：新的远程命名空间要在官方 `packages/api/remotes/src/client/index.ts` 里加一行导入才能被界面使用，这是对 DSH 源码的一处必要修改（记入 `dsh/PATCHES.md`，见官方 `docs/cookbook/adding-a-remote-api.md`）。

### 1.3 工作台服务的启动和看护

- Host 插件启动时用 `ctx.subprocess.spawn` 拉起工作台服务，传入随机端口和 32 字节随机令牌（`LB_PORT`、`LB_TOKEN`）。DSH 会清掉子进程继承的环境变量，所以服务需要的变量（端口、令牌、应用数据目录、Key 文件位置）都要在 `env` 里显式传；另外把 Windows 的 `SYSTEMROOT`、`LOCALAPPDATA`、`APPDATA`、`USERPROFILE`、`TEMP`、`TMP` 原样传入（Python、Word / WPS 调用和发票引擎都需要，第 12.3、13.3 节）。

**2026-09-30 T7 合并时回写**：DSH 只清掉名字含 KEY / PASSWORD / SECRET / TOKEN 的变量和 `DSH_*`；Host 显式传 `LB_PORT`、`LB_TOKEN`、`LB_APPDATA`、`LB_FORWARD_PORT`、系统变量、全部 `OneDrive*` 和配置里给的其余变量；端口由 Host 挑（服务的 `--port 0` 不可用）；退出码 2 = 端口绑定失败，Host 换端口重启且不计次；退出码 3 = 被信号停止，Host 自己发起的停止不重启，不是 Host 发起的照常重启并计次；启动后比对 `contract_version`。转发端口被占时服务同样以退出码 2 退出，Host 换服务端口无济于事，处理办法随 T7 第二次交回定。
- DSH 没有现成的进程看护，由 Host 插件自己做：每 5 秒探测一次服务的 `/health`；进程退出或连续 3 次没有响应就重启，1 分钟内重启超过 3 次就停止重启，界面提示"工作台服务异常"。Host 退出时一起结束服务。
- 服务只监听 `127.0.0.1`；每个请求必须带 `Authorization: Bearer <LB_TOKEN>`，否则返回 401，防止本机其他程序调用。
- 关闭窗口时桌面端默认留在托盘，Host 和工作台服务继续运行，后台识别不中断（第 7.2 节）。
- Python 运行时：桌面端打包时已经内置了一个 Python 解释器（官方 `scripts/primary-runtime/lock.json`），优先复用它，把我方依赖一起装进去；不合适就单独内置 python-build-standalone。〔待验证〕

### 1.4 代码仓库结构

```
lawbench/                 我方仓库
├─ dsh/                   DSH 官方源码（git 子模块，固定提交 477b4f4），对它的改动都记在 dsh/PATCHES.md
├─ dsh-ext/               我方组合包 lawbench-dsh
│  ├─ package.json        dsh.bundle.patch 指向 cordis.patch.yml
│  ├─ cordis.patch.yml    第 3.1 节的全部配置
│  ├─ agent/              Agent 插件（TypeScript）
│  ├─ host/               Host 插件（TypeScript）
│  ├─ credentials/        凭据插件：Key 存 Windows 凭据管理器（第 8.1 节）
│  └─ ui/                 界面插件（TypeScript + React，按官方 client 插件规范构建）
├─ service/               工作台服务（Python 3.12）
│  └─ lawbench/
│     ├─ api/         core.py（插件调用的 /core/*）、ui.py（界面接口 /api/*）
│     ├─ case/        gate.py（路径闸门）、registry.py（案件注册表）、task.py（任务单、结果清单、读取记录）、context.py（L0/L1）
│     ├─ ingest/      detect.py、pdf.py、docx.py、xlsx.py、text.py、image.py、libreoffice.py
│     ├─ ocr/         queue.py、client395.py
│     ├─ search/      fts.py、normalize.py
│     ├─ llm/         client6000d.py、tokens.py
│     ├─ pipeline/    runner.py、prompts.py、steps/（本次只有 wiki）
│     ├─ checks/      citations.py、evidence.py（由 wiki 测试的两个检查脚本改成库）
│     ├─ export/      pandoc.py、redline.py
│     ├─ office/      convert.py（Word / WPS / LibreOffice 转 PDF，第 12.3 节）
│     ├─ archive/     match.py、build.py、templates/（第 12.4 节）
│     ├─ calc/        sentence.py（刑期计算规则表，第 13.4 节）
│     ├─ invoice/     runner.py（发票引擎白名单调用，第 13.3 节）
│     └─ retainer/    driver.py（证件识别驱动的启停，第 13.5 节）
├─ prep395/               395 预处理服务（Python，Windows）
├─ skills/                内置 Skill（平铺）、_shared/共用规则.md、capsules.default.json、_scripts/（第 10 节）
├─ engines/               律所提供的现成工具：invoice-ledger/（发票引擎）、retainer/（委托材料网页和证件识别驱动）
├─ docs/reference/        律所提供的原始 Skill（只作参考，不打包），如 client-skills/lawyer-archiving-1.0.0
├─ tools/                 splitter/（长截图切分）、convert/（格式互转）
├─ packaging/             安装包脚本、versions.lock、第三方许可证清单
├─ contracts/             契约：JSON Schema、case_db.sql、formats.md、样例和自检脚本（第 20 节）
├─ scripts/               build_docs.py（由 docs/src 生成 HTML）、check_6000d.py（网关和 Key 检查）
└─ docs/                  PRD.html、Spec.html（由 docs/src/*.md 生成，改文档改 md）、编排计划三件套

本机仓库 `D:\lawbench`，远程 `github.com/Yxiansheng1/lawbench`（私有）。测试 Key 等机密放在 `D:\lawbench\.env.local`，不提交；仓库中不放任何真实案卷。
```

---

## 2. 组件和许可证

版本号在对应验证通过后填入 `packaging/versions.lock`，之后锁定不跟随升级。

| 组件 | 用在哪 | 用途 | 许可证 | 备注 |
|---|---|---|---|---|
| DSH（含官方桌面端） | 客户端 | 界面、Agent 循环、LLM 适配 | MIT | 固定提交 `477b4f4`；开发者预览版，不跟随上游升级 |
| Electron | 客户端 | 桌面壳 | MIT | 版本随 DSH（当前 44） |
| Python 3.12 | 客户端、395 | 工作台服务、395 服务 | PSF | 内置 SQLite 须 ≥ 3.34（FTS5 trigram） |
| pypdfium2 | 客户端 | PDF 取文字、判断页面类型、渲染页面图片 | Apache-2.0 / BSD | |
| python-docx + lxml | 客户端 | docx 解析、修订版生成 | MIT / BSD | |
| openpyxl | 客户端 | xlsx 解析 | MIT | |
| charset-normalizer | 客户端 | txt / csv 编码识别 | MIT | |
| olefile | 客户端 | 识别加密的 Office 文件 | BSD | |
| Pillow、numpy | 客户端、395、小工具 | 图片处理、长截图切分 | HPND / BSD | |
| tokenizers + 模型的 tokenizer.json | 客户端 | 计算 token 数 | Apache-2.0 | tokenizer.json 从 6000D 模型目录拷贝，随包内置 |
| LibreOffice | 客户端、小工具 | 老格式转换、Word ↔ PDF | MPL-2.0 | 两者共用一份 |
| pandoc | 客户端、小工具 | Markdown ↔ Word | GPL-2.0+ | 独立程序分发，附许可证和源码获取方式 |
| FastAPI、uvicorn、httpx | 客户端、395 | 工作台服务、395 服务、HTTP 客户端 | MIT / BSD | |
| llama.cpp（`llama-server`，Vulkan） | 395 | OCR 视觉模型、9B 模型的推理 | MIT | 〔待 G-5、G-6〕 |
| WinSW | 395 | 把进程注册为 Windows 服务 | MIT | |
| OCR 模型、9B 模型 | 395 | 识别、抽取 | 选型后核对 | 〔待 G-5、G-6〕 |
| keyring | 客户端 | 读 Windows 凭据管理器中的 Key | MIT | |
| jsonschema（Python）、ajv（TypeScript） | 客户端、395 | 按契约校验请求、返回和落盘文件 | MIT | 第 20 节 |
| md2word 的脚本（律师提供的 Skill，MIT） | 客户端 | Word 导出的参考实现，可选 | MIT | 采用时列入许可证清单 |
| pypdf | 客户端 | 归档：合并卷宗 PDF、叠加页码 | BSD-3-Clause | 替代原归档 Skill 用的 PyMuPDF（AGPL） |
| reportlab | 客户端 | 归档：生成页码层（内置中文字体 STSong-Light） | BSD | |
| pywin32 | 客户端 | 调用本机 Word / WPS 转 PDF（第 12.3 节） | PSF | |
| 发票整理引擎（invoice-ledger-db 3.9.4.1） | 客户端 | 发票归档、查重、台账、报销批次（第 13.3 节） | 周海沺律师提供，律所内部使用，署名保留 | 自带 Python 3.12 嵌入式运行环境及 openpyxl、pdfplumber、pdfminer.six、pillow、pypdfium2、cryptography、charset-normalizer、winsdk，清单见其 `THIRD_PARTY.json` |
| 委托材料工具（retainer-offline 3.4.1） | 客户端 | 委托合同、授权委托书、所函生成（第 13.5 节） | 周海沺律师提供，律所内部使用，署名保留 | 网页部分用 JSZip（MIT） |
| RapidOCR + PP-OCRv6 模型、onnxruntime、opencv-python-headless | 客户端 | 委托材料的证件识别驱动（本机 CPU） | Apache-2.0 / MIT / Apache-2.0 | 驱动随委托材料工具提供，依赖装进客户端的 Python |

**不用的组件**：
- 律师提供的 Skill 中 CC-BY-NC 许可的 4 个（contract-copilot、legal-proposal-generator、legal-text-format、legal-visualization）：授权明确前不吸收文本和脚本；legal-ocr 调用公网 OCR（MinerU、PaddleOCR 云端），违反 SEC-10，只可参考其 MIT 许可的后处理代码，不得打包其联网部分和 `config/.env`。
- MCP（Python SDK、DSH 的 `mcp-client`）：改用 DSH 插件注册工具（D2）。
- MarkItDown：转换时丢掉页码和段落位置，满足不了 F-MAT-04。
- pdf2docx、PyMuPDF：AGPL（或依赖 AGPL）。律所归档 Skill 原来用 PyMuPDF 合并卷宗，改用 pypdf + reportlab。
- 发票引擎的邮箱收取部分（IMAP、MCP 连接器、正文链接下载）：联网，违反 SEC-03；代码保留在引擎里，但工作台不提供调用入口（第 13.3 节）。
- DSH 的 `office-to-pdf`、文档预览侧栏：会在 DSH 目录缓存案卷转成的 PDF；原文查看由我方实现（第 9.3 节）。

---

## 3. DSH 定制

原则：**能用组合包的配置补丁解决的，不改 DSH 源码**；必须改源码的，逐条记在 `dsh/PATCHES.md`（改了哪个文件、为什么、怎么验证），换 DSH 提交时逐条重做。

### 3.1 组合包的配置补丁（`dsh-ext/cordis.patch.yml`）

**DSH 的配置怎么叠加**：桌面端的 profile（`$DSH_HOME/profiles/desktop`）由 `dsh-base`、`dsh-web-app` 两个官方组合包叠加而成（官方 `packages/boot/app-boot/src/profile.ts`）。每个组合包是一串"行"，每行是一个插件；后面的组合包可以按行 `id` 整行替换某个插件的配置，或者用 `disabled: true` 关掉它（官方 `vendor/include/src/index.ts`）。我们把自己的组合包加在最后（第 14.1 节），它的补丁最后生效。

**已知的现状**：`dsh-web-app` 已经把文件、命令、AGENTS.md 加载、子智能体等 Agent 工具从全局关掉，改由各 preset 自己挂载（官方 `packages/bundle/web-app/cordis.patch.yml` 中 "the agent plane moves behind agent presets" 一段）。所以：
- 我们的 preset 不挂这些插件，律师工作台的会话里就没有这些工具；
- 危险在于官方自带的 4 个 preset 都挂了这些工具，必须关掉（下面第 2 项）。

**补丁内容**：

**1. 关掉的行**（`disabled: true`）：

| 类别 | 行 id | 原因 |
|---|---|---|
| 官方 preset | `preset-standard`、`preset-ptc`、`preset-minimal`、`preset-cordis` | 都带命令、文件工具（D4） |
| 联网 | `web`、`web-search-deepseek`、`web-fetch-http`、`mcp-resources` | 联网能力，全局挂载 |
| 插件管理 | `plugin-manager`、`ui-plugin-manager`、`plugin-package-inventory-deepseek` | 会用 pnpm 在线安装插件 |
| DeepSeek 账号和官方模型 | `deepseek-account`、`llm-deepseek`、`llm-deepseek-account` | 连 DeepSeek 服务器 |
| 遥测和反馈 | `session-telemetry-otel`、`message-feedback`、`ui-message-feedback` | 律师点"反馈"后会把整段会话记录上传到 `harness-telemetry.deepseeksvc.com`（官方 `packages/session/session-telemetry-otel/README.md`）；另在环境变量中设 `DSH_TELEMETRY_DISABLED=1` |
| 标题生成 | `session-title-llm` | 用首条消息生成标题，标题会存到 `$DSH_HOME`；改由我方插件按"<胶囊名> · <时间>"设标题 |
| 文档预览 | `ui-sidebar-documentpreview`、`office-to-pdf` | 会在 DSH 目录缓存 PDF |
| 官方品牌 | `ui-brand-official` | 换成我方品牌（第 3.4 节） |
| 侧栏浏览器 | `ui-sidebar-browser` | 桌面端默认开启（web profile 下关），可访问任意网址，用独立分区的 webview，P-9 拦不到（2026-09-29 T4 复核发现） |
| 模型设置页 | `ui-settings-models` | 可自建指向任意地址的模型路由并覆盖我方的 `llm-pi-ai` 行；服务器地址只在我方设置页改 |
| 账号设置页和账号服务 | `ui-settings-account`、`account-controller` | 带 DeepSeek 登录、充值、用量链接和外部反馈表单地址 |
| 代码执行运行时 | `ptc-runtime`；休眠的 `session-log-deepseek` 一并关掉 | 配合下面 `tools` 行锁定模式，杜绝模型拿到 `run_code` |

**反向检查**（2026-09-29 T4 复核后加）：上表是"要关的"，不保证列全。验收以"允许启用的行"白名单为准：导出的插件树里，凡不在白名单里的启用行一律报出；带 `!!js` 表达式的行按 desktop 语境（`profileContext.name == 'desktop'`）求值后再判。白名单和每行的理由放 `docs/plan/evidence/T4/`，换 DSH 提交要重做。

关掉某行导致其他插件加载失败的，按报错处理，结果记入 `dsh-patches/PATCHES.md`。最后在开发机上导出实际的插件树（`dsh --profile desktop --dump-config`；桌面 profile 由 Electron 独占、命令行导不出时，导出 web profile 并按上面的方法对带 `!!js` 的行逐条判定），存档核对。行 id 以固定提交为准，换提交要重新核对。

**2. 改配置的行**（注意：替换的是整行 `config`，没写的字段会丢，要把需要保留的字段一起写上）：

| 行 id | 配置 |
|---|---|
| `agent-preset-registry` | `default: lawbench`（不改的话，默认 preset 仍指向已关掉的 `standard`，新建会话会报 `agent-preset/not-found`） |
| `llm-pi-ai` | 律所模型路由（第 8.1 节） |
| `spill-policy` | `maxInlineTokens: 1000000`（大于模型窗口），工具结果永远不溢出到文件（第 3.3 节） |
| `spill-local` | `cleanupPeriodDays: 1`；按上一行配置不会产生文件，验收时检查其目录为空 |
| 重试 | `llm-retry` 行没有配置项（2026-09-29 T4 核实）；重试策略写在 `llm-pi-ai` 路由的 `retryPolicy`：`mode: normal, maxRetries: 1`。默认可重试的错误不含鉴权失败，401 / 403 不重试（第 8.3 节） |
| `tools` | `mode: native`。原配置取环境变量 `DSH_TOOLS_MODE`，设成 `ptc` 或 `both` 模型就会拿到 `run_code`，必须锁死 |
| `agent-default-model` | 新会话默认用律所路由（官方默认模型所在的路由已关掉） |
| `ui-settings` | `enabled: false`，保持开发者模式关闭；开着时新会话页会显示 preset 选择入口 |
| `locale` | `preference: zh`，界面固定中文（官方 `packages/client/locale`） |
| 工作区 | `documentsDirectory` 指向应用数据目录下的空目录，避免在"文档"里自动建 `deepseek-harness/default-workspace`；首页不提供"默认工作区"入口，必须先打开案件 |
| `credentials`（插件名 `@deepseek-ai/dsh-credentials-local`；本文其他地方说的 `credentials-local` 指这一行） | 整行替换为我方凭据插件 `lawbench-dsh/credentials`（第 8.1 节） |
| `session-persistence-jsonl` | 整行替换为我方会话记录插件，按案件存储（第 3.3 节，P-8） |

**2026-09-30 T7 合并时回写**：实际做法是原行 `disabled: true`，另插一行 `legal-credentials` 提供同名服务（不整行替换；DSH 连接插件启动时要写浏览器会话密钥，见第 8.1 节）。

**G-2 补充核对**：除 AGENTS.md 和 `.dsh/skills` 外，逐一列出 DSH 在打开工作区时会从 `cwd` 读取的所有内容（项目级配置、插件、忽略文件等），写进 `dsh/PATCHES.md`，确认律师工作台 preset 下都不生效。

**3. 律师工作台 preset**（新增行 `preset-lawbench`，插件 `@deepseek-ai/dsh-agent-preset`，写法参照官方 `packages/bundle/web-app/presets/standard.patch.yml`）：

```yaml
- insert:
    - id: preset-lawbench
      name: '@deepseek-ai/dsh-agent-preset'
      config:
        id: lawbench
        name: 律师工作台
        order: 1
        plugins:
          - id: persona
            name: '@deepseek-ai/dsh-persona'
            config: {complete: true, includeRuntimeContext: false, prefix: <通用规则，第 9.2 节>}
          - id: skill-filesystem
            name: '@deepseek-ai/dsh-skill-filesystem'
            config: {providerName: lawbench-skills, includeDefaultRoots: false, watch: false,
                     customSkillDirs: [<管理员下发目录>, <内置目录>]}      # 第 10.1 节；DSH 同名先到先得，管理员目录排前面
          - id: tool-skill
            name: '@deepseek-ai/dsh-tool-skill'
          - id: tool-ask-user
            name: '@deepseek-ai/dsh-tool-ask-user'
          - id: compaction            # 照抄 standard preset 的 compaction 组，保留长对话压缩
            name: cordis:group
            group: true
            isolate: {compaction: true, toolResultPruner: true}
            config:
              - id: compaction-basic
                name: '@deepseek-ai/dsh-compaction-basic'
              - id: tool-result-pruner
                name: '@deepseek-ai/dsh-compaction-tool-result-pruner'
                config: {thresholdChars: 8192, headChars: 4096, tailChars: 1024}
          - id: legal-agent
            name: 'lawbench-dsh/agent'
```

- preset 里不写 `agent-instructions`、`tool-bash`、`tool-pwsh`、`tool-fs`、`tool-fs-search`、`tool-jobs`、`tool-web`、`tool-subagent*`、`tool-workflow`、`tool-goal`、`tool-todo`、`plan-mode`。
- preset 里如果有插件对外提供服务，必须放在带 `isolate` 的组里，否则 DSH 拒绝挂载（官方 `packages/preset/agent-preset-registry/src/mount.ts`）。
- 界面上选择 preset 的入口只在开发者模式下出现；我们保持开发者模式关闭。

**验证**：
- 抓一次发给模型的请求，工具定义里只有 `skill`、`ask_user_question` 和 `case_*`；
- Agent 插件日志中没有"拒绝不在白名单内的工具"（出现就说明有工具漏进来）；
- 案件内放 `AGENTS.md`、`.dsh/skills/<恶意 Skill>`、含越权指令的材料，都不起作用；
- 界面上看不到其他 preset。

### 3.2 必须改 DSH 源码的地方

| # | 功能 | 位置（官方仓库） | 改法 |
|---|---|---|---|
| P-1 | 自动更新 | `apps/desktop/src/update-coordinator.ts`、`update-schedule.ts`、`main.ts`（`DesktopUpdateCoordinator`、`automaticCheck`、"检查更新"菜单）；设置页版本行 `packages/client/ui-settings-general/src/client/index.ts` | 删除更新检查和菜单。打包时不写更新源（`electron-builder-config.mjs` 的 `publish: null`，不生成 `app-update.yml`） |
| P-2 | 强制更新策略查询 | `apps/desktop/src/mandatory-update-policy.ts`；打包 `apps/desktop/scripts/electron-builder-config.mjs`（`resolveDesktopPolicyEnvironment` 调用、`extraMetadata.dshMandatoryUpdatePolicy`） | 删掉这两处；安装包里没有这个字段，运行时就不查询 |
| P-3 | 欢迎窗口 | `apps/desktop/src/welcome-window.ts`、`src/client/WelcomePage.tsx`、`welcome-backend.ts`、`main.ts` 中 `needsWelcome` 判断 | 换成我方"首次配置"页：填 6000D 和 395 的所内、所外地址（带默认值，第 15 节）、个人 Key、测试连接（PRD 7.9）；判断条件改为"没有配置过律所服务器" |
| P-4 | 品牌 | `apps/desktop/scripts/electron-builder-config.mjs`（`productName`、`appId` 来自 `DSH_DESKTOP_APP_ID`、`protocols`、图标）、`apps/desktop/resources/icon*`、`tray-windows.ico`、`src/locale.ts`（产品名文案）、`main.ts` 关于面板、`apps/desktop/installer/`（安装界面文案和图片） | 换成律所名称和 logo，"技术支持"放我方 |
| P-5 | 聊天附件改为导入 | `packages/client/ui-conversation/src/client/apply.ts` 中 `addFiles`（2026-09-30 更正位置）；输入区的"+"按钮 | `addFiles` 改为调用我方的导入处理：取出文件的本机路径（Electron `webUtils.getPathForFile`），调 `/api/materials/import`，不写附件；粘贴的截图（没有本机路径）先存为 `工作区/临时/` 下的图片再导入到 `02案件材料/粘贴图片/`。"+"按钮去掉，由我方"导入"按钮代替（D13） |
| P-6 | 远程命名空间 | `packages/api/remotes/src/client/index.ts` | 加一行导入我方 `lawbench` 命名空间（第 1.2 节） |
| P-7 | 网络白名单 | `packages/util/http-proxy/src/install.ts`（全局 undici dispatcher） | 加地址白名单（第 14.3 节） |
| P-8 | 会话记录存到案件目录 | `packages/session/session-persistence-jsonl` | 复制为我方插件，改目录规则（第 3.3 节）；如果做成独立插件、通过补丁替换 `session-persistence-jsonl` 行，就不算改源码 |
| P-9 | Electron 后台请求 | `apps/desktop/src/main.ts` | 主窗口关闭拼写检查（`session.setSpellCheckerEnabled(false)`）；`session.defaultSession.webRequest.onBeforeRequest` 拦截白名单以外的请求 | 2026-09-30 T17 落地：`P-9-default-session-request-whitelist.patch`（`onBeforeRequest` 白名单，放行本应用资源与 Host 自己的 http/ws；侧栏浏览器、用量页、策略测试鉴权用各自分区会话不走它，入口已由配置关掉；拼写检查与 `webviewTag`/`browserAcquire` 在返修中补） |
| P-11 | 委托材料窗口 | `apps/desktop/src/main.ts` | 增加一个 IPC 通道 `lawbench:open-retainer`：新建 `BrowserWindow` 加载 `<安装目录>/engines/retainer/启动.html`，`partition: 'persist:retainer'`（与主窗口的存储隔开），`nodeIntegration: false`、`contextIsolation: true`、禁止 `window.open` 和跳转到其他地址。**这个分区是独立的 session，P-9 不会自动作用到它**：对 `session.fromPartition('persist:retainer')` 同样设置 `webRequest` 白名单（只放行 `file://` 和 `127.0.0.1:17801`）并关闭拼写检查。预加载脚本在网页脚本运行前删除 `window.showDirectoryPicker`，让网页改用下载保存；`will-download` 把下载一律存到当前案件的 `工作区/临时/委托材料/<时间>/`（第 13.5 节）。关闭窗口时通知工作台服务停止证件识别驱动 |
| P-10 | 组合包进入桌面端 | `packages/boot/app-boot/src/profile.ts`（`PROFILE_TEMPLATES.web`）；`@deepseek-ai/dsh` 的依赖列表 | 加上 `lawbench-dsh`（第 14.1 节） |
| P-12 | 桌面端自带的 Office 组合 | `apps/desktop-host/src/index.ts` | 去掉 `desktop-office` 的挂载（Office Skill 和 `load_workspace_dependencies` 工具）。桌面端 Host 在补丁行之外直接挂载它，配置补丁关不掉；不去掉模型会多出白名单外的工具（2026-09-29 T4 抓包发现） |
| P-13 | 设置页的"打开配置文件"按钮 | `packages/client/ui-settings-general/src/client/index.ts` | 桌面端不注册 `open-document` 动作。这个按钮会用系统文本编辑器打开 profile 自己的 `cordis.patch.yml`，它叠在我方补丁之后、改了即时生效，律师可以借它改模型地址、重新打开已关掉的插件（2026-09-29 T4 第二轮复核发现）。设置接口的远程写入由 P-7 地址白名单兜底 |
| P-03a | 欢迎窗口读账号状态（临时） | `apps/desktop/src/welcome-backend.ts` | 账号服务调用失败按"未登录"处理，否则关掉账号相关行后进不了工作区。P-3 落地时整体替换、删掉本条 |
| P-14 | 组合包缺失即不启动 | `apps/desktop-host/src/index.ts`、新文件 `lawbench-bundle-guard.ts` | 桌面端 Host 读完 profile 后，有组合包被跳过或组合包层里没有 `lawbench-dsh`，就抛中文错误、不启动（用户 2026-09-30 放行 N40 ①）。原来加载失败只记一行、照常以原版 DSH 启动 |
| P-15 | `/api/file` 限定范围 | `packages/api/session-controller/src/media-references.ts` | 先 `realpath`（解析 `..`、链接、联接、长路径前缀），再要求落在已登记案件文件夹或本机附件库之内；否则 403，回应与日志不带路径（用户 2026-09-30 放行 N40 ②）。原来本机任何可读文件都能读到 |
| P-16 | 出处做成正式按钮 | `packages/client/ui-primitives/src/markdown/render.tsx`、`MarkdownText.tsx`；`packages/client/ui-chat`（新服务 `chatInlineMarks`） | Markdown 定稿渲染时按插件登记的正则把出处片段画成 `<button>`（Tab 可到、Enter 打开原文、读屏可读）；流式帧与链接文字里不生效；不登记时渲染与原版逐字一致（用户 2026-09-30 放行 N36）。已知限制：出处被加粗切成两半、紧跟裸网址时不成按钮 |
| P-17 | 回答里的链接不打开 | `apps/desktop/src/main.ts`；`ui-primitives` 的 Markdown 渲染 | 主窗口开新窗口一律拒绝、外部跳转只阻止、不交给系统浏览器或邮件程序；Markdown 里 `http(s)`、`mailto` 链接展开成纯文字（文字不是网址时用全角括号补上网址，便于复制）（用户 2026-09-30 放行 N15 ①）。与 P-9 互补：P-9 管渲染进程发出的请求，P-17 管交给系统程序的动作 |
| P-18 | `@` 占位文字与开发者开关 | `packages/client/ui-conversation/src/client/locales.ts`；`packages/client/ui-settings-general/src/client/index.ts` | 输入框占位文字去掉"@ 文件或对话"；通用设置不再挂"代码工作工具"（开发者模式）开关（用户 2026-09-30 放行）。快捷键说明里的"@ 打开引用菜单"随返修去掉 |

**2026-09-30 T7 合并时回写**：P-3 已落地（`dsh-patches\P-3-first-run-page.patch`，删去临时的 P-03a）；"测试连接"先保存再测、失败恢复，见第 8.1 节；"是否配置过"由 Host 自己看 `<应用数据>\settings.json` 是否存在并问凭据插件有没有 Key，不经服务。P-6 不需要改 DSH 源码：界面插件启动时自己 `` 一份手写的远程描述（T13），`PATCHES.md` 已写明。

完成后用抓包核对（第 14.3 节）。

### 3.3 数据落点（SEC-01、SEC-11；G-4）

DSH 默认把以下数据写在 `$DSH_HOME` 或系统临时目录，其中几项含案卷内容：

| 数据 | 默认位置 | 含正文 | 处理 |
|---|---|---|---|
| 会话记录（JSONL） | `$DSH_HOME/sessions`（`session-persistence-jsonl`，`root: dshHomePath('sessions')`） | 是 | **按案件存储**：复制 `session-persistence-jsonl` 为我方插件，在组合包补丁里替换该行。官方实现中会话目录由 `sessionDir(root, header.cwd, id)` 决定，创建时就能拿到会话头的 `cwd`；改为 `<cwd>/工作区/会话/<会话ID>/`。`list` / `stat` 原本扫描 `root` 下的项目目录，改为遍历案件注册表中的案件。`cwd` 不是已登记案件的会话，拒绝创建 |
| 会话列表缓存 | `$DSH_HOME/storages`（`session-projection-cache`） | 可能含标题 | 标题改为程序生成（第 3.1 节）后，抽查确认不含正文 |
| 工作区列表 | `$DSH_HOME/storages` | 否（只有文件夹路径） | 保持 |
| 会话全文检索索引 | `session-query-sqlite` | — | 官方默认已是 `:memory:` 且不开启，保持不变 |
| 大段工具输出的溢出文件 | `spill-local`，系统临时目录 | 是 | 默认超过 12500 token 的工具结果会写成溢出文件。**把 `spill-policy` 的阈值调到大于模型窗口**（第 3.1 节），任何工具结果都不会溢出。另外 `tool-fs-search` 也会写溢出文件，律师工作台 preset 不挂它。验收时检查溢出目录为空 |
| 聊天中粘贴的图片、拖入的文件 | `attachment-local`，`$DSH_HOME` | 是 | 改为导入到案件文件夹，不经过附件存储（第 3.2 节 P-5）；验收时确认附件目录为空 |
| 委托材料窗口的浏览器存储 | Electron `userData/Partitions/retainer` | 含委托人姓名、证件信息，不含案卷 | 默认只在内存中处理，律师在该工具里主动开启"在这台电脑记住工作内容"才写入；工具自带"清除本机记忆"。操作说明中写明 |
| 发票引擎运行环境 | `%LOCALAPPDATA%\invoice-ledger-db\runtimes` | 否（只有 Python 运行环境） | 保持；发票和台账本身在律师指定的日常办公文件夹（第 13.3 节） |
| Word / WPS 的"最近使用的文档" | Office 注册表和最近文件列表 | 文件名 | 转换时以 `AddToRecentFiles=False` 打开、不显示窗口（第 12.3 节）；LibreOffice 的配置目录放在案件临时目录（第 5.2 节） |
| 凭据（Key） | `$DSH_HOME/.credentials.yaml` | Key | 替换为我方凭据插件，存 Windows 凭据管理器；验收时确认该文件不存在或不含 Key（第 8.1 节） |
| 桌面端日志 | Electron `userData/logs`、Host 日志 | 抽查 | 确认不含正文；含正文的日志项关闭 |
| Electron 用户数据（缓存、localStorage） | `userData` | 抽查 | 关闭 HTTP 缓存；抽查确认 |

验收方法：用测试案卷完整跑一遍后，在案件目录以外全盘搜索案卷中的特征字符串（第 16 节 SEC-01）。

### 3.4 界面

界面扩展都做在我方界面插件 `legal-ui` 里，用官方提供的插槽，不改官方界面代码（除第 3.2 节列出的几处）。

| # | 要求 | 做法 |
|---|---|---|
| U-1 | 中文界面 | 桌面端和界面都已支持中文；补丁里设 `locale.preference: zh`（第 3.1 节）；我方文字按官方方式注册中文词条（`ctx.locale.register`）；律师可见的文字不出现 token、context 等词 |
| U-2 | 双品牌 | 桌面壳部分见第 3.2 节 P-4；界面侧栏的品牌位（`sidebar.brand.mark`、`sidebar.brand.name` 插槽）由我方插件占用，律所为主，我方为"技术支持" |
| U-3 | 去掉无关入口 | 插件管理、反馈、preset 选择已在第 3.1 节关掉，附件改为导入（P-5）；其余入口（如终端、工作区依赖安装）按界面实际情况在补丁中关闭对应行 |
| U-4 | 首页 | 用"整页"插槽：`sidebar.panellist`（侧栏图标）+ `main`（页面），写法参照官方 `packages/client/ui-plugin-manager`。内容自上而下：分流提示语（`capsules.json` 的 `hint`）；一级胶囊（分组）一行，点选后下面一行显示该组的二级胶囊；最近案件、新建 / 打开案件。点 Skill 胶囊：没有打开的案件时先让律师选案件（新建时可选"民商事 / 刑事"标准目录），然后进入案件工作区并写任务单；点工具胶囊：打开对应工具（U-13、U-14） |
| U-5 | 案件工作区 | 左栏（材料、识别进度、wiki）和右栏（草稿、成果、自检结果）做成右侧栏标签页（`ctx.sidebarRightTabs.register` + `sidebar.right.pane.tab` 插槽，参照 `packages/client/ui-sidebar-documentpreview`）；中间的对话区沿用官方会话界面；Skill 选择、参数放在会话输入区上方 |
| U-6 | 原文查看 | 右侧栏标签页，按出处定位（第 9.3 节） |
| U-7 | 通知 | 识别完成、流水线完成时发系统通知，只写"识别任务已完成"或"整理任务已完成"，**不带案件名和材料名** |
| U-8 | 设置 | `settings.section` 插槽：服务器（所内、所外地址）和 Key、个人参数预设、Word 模板、本机律师姓名、日常办公文件夹、发票购买方名称、Word 转 PDF 用哪个程序、胶囊管理（U-11）、关于（双 logo） |
| U-9 | 取消 | 沿用官方的停止按钮（断开流式请求）；同时通知工作台服务停止正在运行的流水线（第 8.4 节） |
| U-10 | 关闭窗口 | 官方行为是隐藏到托盘、Host 继续运行，正好满足后台识别；首次关闭时的提示改为说明"识别会在后台继续" |
| U-11 | 胶囊管理 | 首页右上角"管理胶囊"进入编辑状态：拖动胶囊排序（同组内、跨组都可以），点名字改名，点眼睛图标隐藏或显示，"新增胶囊"选择一组 Skill 或一个内置工具并起名，"恢复默认"用默认配置覆盖（先确认）。没有删除按钮，没有密码。保存时调 `PUT /api/capsules`，服务端校验 Skill 和工具存在 |
| U-12 | 拖入导入 | 对话框（P-5）、材料面板、首页的案件卡片都接受拖入文件和文件夹；材料面板的"导入"按钮可以选文件或文件夹。弹出确认框：复制到哪个子文件夹（默认 `02案件材料`，可改）、共几个文件；确认后调 `/api/materials/import`，结果列出复制了哪些、跳过了哪些及原因 |
| U-13 | 发票整理面板 | `main` 插槽的一个页面（第 13.3 节）：报销年月、导入发票文件夹、分析、入账、生成贴票包、确认已报销等按钮，引擎输出原样显示在页面下方；首次使用时要求先在设置中指定日常办公文件夹和购买方名称 |
| U-14 | 委托材料窗口 | 点"文件生成"胶囊，经 P-11 打开独立窗口并启动证件识别驱动；窗口标题显示当前案件名；生成的文书下载到案件临时目录，窗口关闭后案件工作区提示"导入新生成的文件到 01委托手续"（第 13.5 节） |
| U-15 | 归档面板 | 案卷归档任务保存归档方案后，右侧栏出现"归档"标签：显示方案表格（可改材料顺序、名称、办案结果等字段），办案结果必须由律师点选，未选时"生成归档文件"按钮不可用；生成后列出文件和"立卷申请书需打印手签后扫描"等提示 |

界面布局是否能完全按 PRD 7.9 的三栏实现，要在第一阶段做出来后跟律师确认；官方界面的插槽决定了"对话区在中间、面板在右侧栏"这种布局最省事。

---

## 4. 工作台服务

### 4.1 案件目录（完整结构和各文件格式见第 20.8 节、`contracts/formats.md`）

```
<案件文件夹>/                律师指定；即 DSH 的工作区、会话的工作目录
├─ <律师的原有文件和子文件夹>  = 原件区，只读，程序不改动
├─ 工作区/
│  ├─ 材料/                 index.json（原件索引：路径、大小、修改时间、sha256）、_处理状态.md
│  │  ├─ 文本/              每份材料一个 md，带位置标记（第 5.3 节）
│  │  └─ 识别页/            395 返回的逐页结果
│  ├─ wiki/                 case.json（案件卡片）、案件/*.md、材料/*.md、index.md、log.md、待确认.json
│  ├─ 任务/<任务ID>/        task.json（任务单）、reads.json（读取记录）、草稿/、result.json（结果清单）、归档方案.json（归档任务）
│  ├─ 会话/                 DSH 会话记录（第 3.3 节）
│  ├─ 临时/                 转换、渲染的中间文件，用完即删
│  └─ case.db               SQLite：案件编号、识别任务、检索索引（contracts/case_db.sql）
└─ 成果/                    律师确认后的成果，索引.json；归档/（归档总文件夹，第 12.4 节）
```

- **标准案件目录**（可选）：新建案件时律师可选"民商事"或"刑事"，程序按 `contracts/formats.md` 第 1.1 节补建子文件夹（`01委托手续`、`02案件材料`、`03一审/我方证据` 等），与委托材料工具和归档目录一致；只补缺，不改已有文件夹。不选则不建。

- **材料编号**（`material_id`）：`M` + 4 位序号，首次导入时按顺序分配，写入 `材料/index.json`，同一案件内不复用；原件改名或移动视为删除后新增。识别页、检索索引、出处记录都用它关联材料。（2026-09-30 契约 1.2，N26：编号同时在 `case.db` 的 `material_ids` 表留底，`index.json` 丢失后重建时同一份原件拿回原来的编号、新编号不占用旧的）
- **材料名**：给 AI 和律师看的名字，在案件内唯一，规则见第 20.2 节。

- **原件区** = 案件根目录下除 `工作区/`、`成果/` 和以 `.` 开头的项以外的所有文件。已在案件文件夹里的原件不复制、不改动；律师从案件外拖入或选择的文件，由导入操作复制进案件文件夹（第 5.1 节），之后同样只读。
- **原件哈希**：记在 `材料/index.json`，按大小和修改时间做缓存，变了才重算。验收时比对哈希（SEC-08）。
- **案件编号**：首次打开时生成 UUID，写进 `case.db`。整个文件夹复制到别处后，在新位置"打开案件"一次即可继续使用（F-CASE-04）；会话记录在案件目录内，跟着一起走。
- **案件注册表**：工作台服务在应用数据目录维护 `cases.json`（`case_id → 案件目录`，只有路径，没有内容），"最近案件"也从这里读。
- `case.db` 带 `schema_version`，升级前自动备份为 `case.db.bak-<版本>`。第一版只有版本 `1`，不做升级：遇到版本不符的 `case.db` 拒绝打开（`INVALID_ARGUMENT`），文件不做任何改动（2026-09-29 T3 返修）；以后真要改表结构时，再连同测试一起加升级和备份。
- **会话和任务分开编号**：会话是 DSH 的一段对话（`<会话ID>`），任务是一次执行。律师在一个会话里每发起一次请求就是一个新任务，`任务ID` 形如 `T-<时间>-<4位随机>`；流水线任务形如 `P-<时间>-<4位随机>`。任务单记录所属会话。这样同一会话的多次执行不会互相覆盖任务单、读取记录和结果清单。

### 4.2 路径闸门（`case/gate.py`）

所有读写案件文件的代码都必须经过闸门，没有其他写文件的途径。

1. **案件根目录**：只从案件注册表取（Agent 路径先用会话头的 `cwd` 查注册表），取 `realpath` 保存为 `ROOT`。根目录本身是链接或 junction 的，拒绝登记，提示"请直接选择实际文件夹"。
   **云同步目录**（SEC-14）：打开案件时，`ROOT` 位于以下位置之一即拒绝（错误码 `CASE_IN_SYNC_FOLDER`）：环境变量 `OneDrive`、`OneDriveCommercial`、`OneDriveConsumer` 指向的目录及其子目录；注册表 `HKCU\Software\Microsoft\OneDrive\Accounts\*\UserFolder`；路径中任一级目录名包含 `OneDrive`、`坚果云`、`Nutstore`、`BaiduNetdisk`、`百度网盘`、`Dropbox`、`Google Drive`、`iCloudDrive`、`WPS云盘`。列表写在配置里，可以补充。按子串匹配，宁可误拒不可漏放：案件文件夹名里带这些字样（如"Dropbox公司诉某某案"）也会被拒，律师改个文件夹名即可（2026-09-29 用户定）。
   **不能当案件根目录的位置**（2026-09-29 用户定）：盘符根目录（如 `D:\`）；包含本软件应用数据目录的文件夹（如整个用户目录）。选到时返回 `INVALID_ARGUMENT`。`\\?\` 前缀先去掉、统一 `realpath` 后再登记。
2. **AI 传入的参数**：
   - 材料用 `case_list_materials` 返回的名称或相对路径；
   - 不能是绝对路径或带盘符，不能含 `..`，不能以 `.`、`工作区`、`成果` 开头（按第一级目录名整级判断：`成果/x` 拒绝，原件 `成果汇总.pdf` 放行）；
   - 任何一级不能是 Windows 设备名（`CON`、`PRN`、`AUX`、`NUL`、`COM0`–`COM9`、`LPT0`–`LPT9`、`CONIN$`、`CONOUT$`，不分大小写，带扩展名的如 `NUL.txt` 同样拒绝）。
3. **不跟随链接**：对拼接后的路径及其每一级父目录执行 `lstat`；只要有一级是符号链接或 reparse point（Windows 下判断 `st_file_attributes & FILE_ATTRIBUTE_REPARSE_POINT`，junction 在此范围内），就拒绝。
4. **最终校验**：`realpath` 必须以 `ROOT + 分隔符` 开头；Windows 下比较前统一大小写。
5. **写权限**：只允许写 `工作区/` 和 `成果/`。原件区只有两种写入，都由律师在界面上操作触发、AI 的工具里没有：`/api/materials/import` 复制新文件（目标已存在同名文件时改名为"原名(2)"，从不覆盖）；`/api/case/open` 按标准目录新建空文件夹。已有原件在任何情况下都不改动、不删除。写文件时先写临时文件再原子替换（`os.replace`）。
6. **拒绝时**：返回中文错误"超出当前案件范围"，本机日志记一条（只记工具名和原因，不记参数内容）。

### 4.3 给界面的接口（`/api/*`，仅限界面调用）

以下操作**只在这里提供**，AI 的工具里没有（D7）。凡是会发数据到服务器的操作，界面在调用前必须先弹确认框，写明发给哪台服务器、多少页或多少字。

**案件和任务的绑定**：
- `POST /api/case/open` 返回 `case_id`（案件的 UUID）。服务端维护 `case_id → 案件目录` 的注册表；除 `case/open` 和 `case/recent` 外，**所有接口都必须带 `case_id`**，服务端只按注册表找目录，不接受界面传来的路径。
- 服务端**没有"当前案件"这种全局状态**。界面切换案件只是换了请求里的 `case_id`。
- 每次执行（识别、流水线、抽取、Agent 任务）创建时分配 `task_id`（识别为 `job_id`），同时固定所属案件、输入材料的版本和律师确认过的发送范围；之后的进度查询、取消都按 `task_id`，与界面当前显示哪个案件无关。
- 插件调用 `/core/*` 时，由会话头的 `cwd` 查出 `case_id`；`cwd` 不在注册表中的会话，工具一律拒绝。

共 25 个接口，请求和返回的字段见第 20.5 节和 `contracts/api/`，下表只说作用。

| 接口 | 作用 | 发往服务器 |
|---|---|---|
| `POST /api/case/open` | 打开案件（新建时初始化 `工作区/`，可按标准目录补建子文件夹），登记到注册表；拒绝链接根目录和云同步目录 | 否 |
| `GET /api/case/recent` | 最近案件 | 否 |
| `POST /api/materials/scan` | 扫描原件区，在本机解析新增或变化的材料 | 否 |
| `POST /api/materials/import` | 拖入或选择的文件、文件夹复制进案件文件夹，然后同 scan（第 5.1 节） | 否 |
| `GET /api/materials` | 材料列表、状态、失败原因、需识别的页 | 否 |
| `POST /api/ocr/jobs` | 提交识别 | 395 |
| `GET /api/ocr/jobs`；`POST /api/ocr/jobs/{job_id}/cancel` | 识别进度；取消 | — |
| `POST /api/task` | 写任务单：律师点的胶囊、Skill、选用的前序成果和参数；Agent 插件在该会话下一次请求时使用 | 否 |
| `POST /api/pipeline/run`；`GET /api/pipeline/{task_id}`；`POST /api/pipeline/{task_id}/cancel` | 运行、查看、取消流水线（本次只有案件 wiki）；律师勾选"使用 395 抽取"时，字段抽取和分类走 395 | 6000D（勾选时另有 395） |
| `GET /api/tasks` | 本案任务、草稿列表（成果区） | 否 |
| `GET /api/task/current` | 读该会话当前的选择（1.2 起；界面每次显示前读） | 否 |
| `GET /api/outputs` | 本案已确认的成果列表（成果区；1.2 起） | 否 |
| `POST /api/redline` | 生成修订版 Word（第 12.2 节） | 否，本机生成 |
| `GET /api/wiki/suggestions`；`POST /api/wiki/suggestions/{id}` | 列出、处理 AI 提出的 wiki 修改建议 | 否 |
| `POST /api/outputs/confirm` | 草稿确认进成果目录并导出 | 否 |
| `GET /api/source` | 原文查看：按出处返回定位单元的文本；PDF 另返回该页的页面图片（定位到页，不做文字高亮） | 否 |
| `GET /api/search` | 律师检索 | 否 |
| `GET/PUT /api/settings`；`POST /api/connection/test` | 设置；测试两台服务器连接 | 测试时只发探测请求 |
| `GET/PUT /api/capsules`；`POST /api/capsules/reset` | 读写本机胶囊配置；恢复默认（第 10.3 节） | 否 |
| `POST /api/archive/build` | 按律师确认的归档方案生成归档总文件夹（第 12.4 节） | 否，本机生成 |
| `POST /api/invoice/run` | 发票整理的一个白名单动作（第 13.3 节） | 否 |
| `POST /api/retainer/driver` | 启停委托材料的证件识别驱动（第 13.5 节） | 否 |

第一版中的独立接口 `POST /api/extract` 取消：9B 抽取只作为 wiki 流水线的一个选项使用（PRD 路由表）。

### 4.4 给 AI 的工具（`case_*`，由 Agent 插件注册）

共 11 个工具。所有工具只作用于当前会话所在的案件；单次返回不超过 8000 字（DSH 的工具结果裁剪阈值是 8192 字符），超出的截断并提示分段读取。每个工具的定义按官方 `ToolDefinition`：`name`、`description`、`parameters`（JSON Schema，`additionalProperties: false`）、`output`（`schema` + `render`）、`execute`。

参数和返回的字段以第 20.4 节和 `contracts/tools/` 为准，下表是摘要。工具的 `parameters` 直接取契约文件中的 `$defs/args`。

| 工具 | 参数 | 返回 | 说明 |
|---|---|---|---|
| `case_list_materials` | — | 材料清单：材料名、编号、类型、状态、位置单位和数量、是否识别所得、失败原因 | 材料名在案件内唯一（第 20.2 节），AI 引用时照抄 |
| `case_read_material` | `name, start?, max_chars?` | 带位置标记的原文、`start`、`end`、`has_more`、`next_start` | 读 `工作区/材料/文本/` 下的解析结果；`start` 是页号、段号或行号；每次读取记入 `reads.json`，用于计算覆盖清单 |
| `case_search` | `query, max_hits?` | 命中列表：材料名、出处文本、片段、是否识别所得 | 第 11 节的全文检索 |
| `case_read_input` | `index, start?, max_chars?` | 任务单里选用的第 `index` 个前序成果（按行分段） | L1 放不下的输入用它读 |
| `case_read_wiki` | `section, name?` | wiki 分节全文、是否过期 | 分节：卡片、概览、当事人、时间线、材料清单、争议焦点、材料摘要（需给材料名） |
| `case_save_draft` | `title, content` | 保存路径和版本、`citation_check`（含 `problems`）、`coverage`、`not_fully_read` | 写入 `工作区/任务/<任务ID>/草稿/<标题>-v<N>.md`；同标题再存生成新版本，旧版本保留 |
| `case_suggest_wiki` | `field, value, source, reason?` | 建议编号 | 写入 `wiki/待确认.json`，律师在界面上确认后才改 wiki |
| `case_save_edit_list` | `name, edits[]` | 保存路径、接受条数、范围外条目 | 保存合同修改清单（第 12.2 节），律师点"生成修订版"时使用 |
| `case_calc_sentence` | `penalty, years?, months?, execution_start?, custody[]` | 刑期起止日、折抵天数、节点、计算依据、需律师判断的情形 | 纯程序计算，不读写文件（第 13.4 节） |
| `case_archive_match` | `catalog` | 归档目录逐项匹配结果、未匹配和忽略的材料 | 只读（第 12.4 节） |
| `case_save_archive_plan` | 归档方案（卷类、当事人、日期、办案结果、结案报告内容、各项材料） | 保存路径、缺失的必交项、提示 | 写 `工作区/任务/<任务ID>/归档方案.json`；归档文件由律师在面板点击后生成 |

测试链路中的 `case_wiki_plan`、`case_wiki_put_facts` 不再提供：案件 wiki 改为流水线（D6）。

另外可用：DSH 的 `skill`（加载 Skill 正文）、`ask_user_question`（必问问题，第 10.2 节）。

**不提供**：写原件、删除文件、任意路径、执行命令、联网、提交识别或抽取、导出到成果目录、生成归档文件、调用发票引擎。

### 4.5 本机日志

- 工作台服务的日志在 `<应用数据>/logs/`，按天滚动，保留 14 天。
- 只记：时间、模块、操作名、案件编号、耗时、状态、错误类型。**不记**：材料名、检索词、模型输入输出、异常的完整信息（只记异常类名）。调试模式也不放开。
- DSH 插件的日志用 `[lawbench]` 前缀，遵守同样的规则；只记数量（如"注入上下文：L0 N 字"），不记内容。

## 5. 材料处理

### 5.1 导入流程

材料进入案件有两种方式，结果相同：
- 律师自己把文件放进案件文件夹（资源管理器里复制），再点"导入"；
- 把文件或文件夹**拖到**对话框、材料面板或首页的案件卡片上，或点"导入"按钮选择文件、文件夹（D13、U-12）。

拖入或选择的路径在案件文件夹**外**时，`/api/materials/import` 先复制（不移动，原文件不动）：
- 目标子文件夹：律师在确认框中选择；默认有 `02案件材料` 就放进去，没有就放案件根目录。文件夹整体复制，保留内部结构。
- 跳过：位于云同步目录的源文件（与 SEC-14 同一套检测）、快捷方式和链接、无法读取的文件、单个超过 300MB 的文件；目标已有同名且内容相同（sha256 一致）的文件。
- 同名但内容不同：改名为"原名(2)"，不覆盖。
- 路径已在案件文件夹内的，不复制，直接解析；**例外**：位于案件 `工作区/` 下的临时文件（粘贴的截图、委托材料窗口的下载）照样复制到目标子文件夹，复制后删除临时文件。
- `unzip` 为 true 时（委托材料窗口的 ZIP 下载），先把 ZIP 解压到 `工作区/临时/`（拒绝路径越界、链接和超过 500 个文件的 ZIP）再复制；ZIP 顶层含标准目录文件夹（如 `01委托手续`）时按其结构放到案件根目录，否则放到 `target`。

复制完成后（或律师直接点"导入"时）：

1. 扫描原件区，对比 `材料/index.json`，找出新增、变化、删除的文件。
2. 新增或变化的文件，按扩展名和文件头判断格式，交给第 5.2 节对应的解析器。
3. 每份材料单独处理，互不影响；失败的写入失败原因（F-MAT-05、F-MAT-06）。
4. 输出 `工作区/材料/文本/<原件相对路径>.md`，更新检索索引，更新 `材料/_处理状态.md`。
5. 原件内容变了（路径相同、哈希不同）：重新解析，已有的识别结果标为"过期"，提示"wiki 和已有成果需要复核"（F-MAT-07）。原件被删除：材料标为"原件已删除"，保留文本，提示律师。

### 5.2 各格式怎么解析

| 格式 | 解析 | 位置单位 | 特殊处理 |
|---|---|---|---|
| PDF | pypdfium2 逐页取文字；按第 5.4 节判断每页是否需要识别 | 页 | 需要识别的页先占位 `（本页需识别）`，识别完成后替换 |
| docx | python-docx 加 lxml 直接读 `document.xml` | 段（正文中非空段落的顺序号，从 1 开始）；表格整体算一段，内部转成 md 表格 | 有修订痕迹时：保留 `w:ins` 的内容、去掉 `w:del` 的内容，材料头部标"含修订，已按修订后文本"（F-MAT-04a）；页眉页脚、脚注附在文末，另标一段 |
| doc / wps | LibreOffice 转成 docx 后按 docx 处理 | 段 | 转换所得的 docx 放在 `工作区/临时/`，用完删除；材料头部标"由 doc 转换" |
| xlsx | openpyxl 读两遍：`data_only=True` 取显示值，`data_only=False` 取公式 | 单元格：`工作表名!A1` | 每个工作表转成带行号、列字母的 md 表格；显示值为空而公式不为空（文件没存计算结果）时，先用 LibreOffice 重算后再读；公式单独存一份，律师需要时查看 |
| xls | LibreOffice 转 xlsx 后按 xlsx 处理 | 单元格 | |
| csv | 编码识别（先试 utf-8-sig，再试 gb18030），按行处理 | 行 | |
| md / txt | 编码识别 | 行 | |
| 图片（jpg / png / tif / bmp） | 整份材料需要识别；一张图算一页 | 页 | |

**2026-09-30 用户定（候 owner 清单 N27）**："显示值"指律师在 Excel 里看到的样子，不是单元格存的原始值：数字按单元格的数字格式套出来写（百分比 `12.5%`、千分位 `1,234.50`、固定小数位、日期和时间按格式、会计格式的负号和货币符号）；套不出来的冷门格式写原始值并在交付说明列出哪些；公式仍单独存一份。改了取法后已导入的表格要重扫一次（原件没变也要重解析，按材料文本格式版本号触发）。

LibreOffice 调用方式：`soffice --headless --norestore -env:UserInstallation=file:///<案件>/工作区/临时/lo_profile --convert-to <格式> --outdir <临时目录> <文件>`。用户配置目录放在案件临时目录，转换后删除，避免在系统里留下"最近打开的文件"记录（SEC-11）。超时 120 秒。

**配置目录的位置改为短路径**（2026-09-29，T19、T3 复核实测）：LibreOffice 会在配置目录下再建很深的子路径，配置目录自身的路径长到约 146 个字符时 `soffice` 直接崩溃（退出码 `0xC0000409`，没有任何输出），115 个字符时正常。案件文件夹的路径常常很长，所以配置目录不放在案件里，改放 `<应用数据>\临时\lo\<8 位随机>\`，每次转换新建、用完删除（删除用长路径前缀并重试，失败要报出来，不能静默）；启动时清理这个目录下的残留。被转换的文件副本和转换结果仍放 `<案件>\工作区\临时\`。调用前检查配置目录路径长度，超过 100 个字符时不调用、报"软件的数据目录路径太长"；`soffice` 以 `0xC0000409` 退出时报"转换程序异常退出"，不要报成"文件可能已损坏或加密"。

**无法处理的文件**（写入失败清单，并附原因）：
- 加密：PDF 打开时报密码错误；Office 文件是 OLE 容器并且包含 `EncryptionInfo` 流。提示"文件已加密，请提供未加密版本"。
- 损坏：解析器报错。提示"文件无法打开，可能已损坏"。
- 超大：单个文件超过 300MB，或超过 2000 页。提示"文件过大，请拆分后导入"。

### 5.3 材料文本格式

沿用 wiki 测试已验证的格式，完整规定见 `contracts/formats.md` 第 2 节：

```
# <材料名>

> Source: <原件相对路径>（<文字版 / 识别所得 / 部分识别 / 待识别>，<N>页）
> Collected: <导入日期>

【第1页】
<原文>

【第2页】
> 识别所得
<识别文本；看不清的字用 ■，整行看不清用 [看不清]>
```

- 位置标记：PDF 和图片用 `【第N页】`，Word 用 `【第N段】`，Excel 用 `【表:工作表名】` 加带行列号的表格，txt / md / csv 用 `【第N行】`（每 50 行标一次，引用时写具体行号）。
- 同一份 PDF 里既有本机解析的页又有识别的页时，识别页在标记下一行写 `> 识别所得`。
- `【】` 位置标记只出现在材料文本里；草稿和成果中的出处一律用 `〔〕`（第 9.3 节）。

### 5.4 PDF 页面类型判断

对每一页：
- 可提取文字 < 30 个字 → **需识别**。
- 可提取文字 ≥ 30 字，并且图片面积 > 页面面积的 30% → **图文混排**：先用提取到的文字，材料列表里提示"本页含图片，可提交识别"。
- 其余 → **文字页**。

阈值写在配置里，用 G-8 的样本校准。

---

## 6. 395 预处理服务（`prep395/`）

395 是一台 **Windows 11** 电脑（AMD Ryzen AI Max+ 395，核显），直接在 Windows 上运行，不用 WSL2。

### 6.1 部署

- **进程**：
  - `prep395`：Python 3.12 + FastAPI + uvicorn，监听 `<395 局域网 IP>:9000`；
  - OCR 后端、9B 模型：各自一个推理进程，只监听 `127.0.0.1`（端口 9101、9102）。
- **推理后端**：首选 llama.cpp 的 `llama-server`（Vulkan 后端，Windows 上对这块 AMD 核显支持最稳），OCR 用它能加载的视觉模型，9B 用 GGUF 量化模型；关闭请求日志（不开 `--verbose`，不开 `--log-file`，关闭 `--slots` 等调试接口）。〔待 G-5、G-6：在这台 Windows 上实测速度和准确率；Vulkan 不行时再试 AMD 的 ROCm for Windows（HIP SDK）〕
- **以 Windows 服务运行**：三个进程都用 WinSW（MIT）包装成 Windows 服务，开机自启、崩溃自动重启；运行账号是专用的本地低权限账号 `prep395svc`，不是管理员。
- **目录**：程序在 `C:\prep395\`（该账号只读）；日志在 `C:\prep395\logs\`（该账号可写）；不设其他可写目录。
- **防火墙**：Windows Defender 防火墙入站规则只放行 9000 端口，来源限定律所局域网网段和 EasyTier 虚拟网段（第 15 节）；9101、9102 不放行。关闭远程桌面以外的共享（文件和打印机共享关闭）。
- **系统盘开 BitLocker**：Windows 的页面文件、休眠文件无法可靠关闭，内存中的内容可能被写到磁盘；开 BitLocker 后，即使写入也是加密的。同时关闭休眠（`powercfg /h off`）。页面文件的残余风险写进部署说明，告知甲方。
- **不装与服务无关的软件**；Windows 更新由甲方按内网策略管理。
- **现状与差距**（2026-09-28 盘点，详见 `docs/src/环境事实.md`）：地址 `192.168.8.124`，Vulkan 可用，可访问 hf-mirror / ModelScope 下载模型；BitLocker 未开、休眠未关、Python 装在用户目录（服务账号无法使用，部署时改为在 `C:\prep395\` 内置 Python 或为所有用户安装）。
- **远程控制软件**：395 上装有向日葵。它经由厂商的公网服务器中转远程控制，处理案卷的节点上不应常驻这类软件（SEC-13 的精神：服务器不经公网可达）。部署完成后卸载或至少禁止开机自启，改用局域网内的远程桌面和 SSH；是否保留由甲方决定，写入部署说明。
- **显存**：Windows 只看到 31.6 GB 内存，其余大概率在 BIOS / Adrenalin 中划给了核显。部署前在任务管理器"GPU → 专用 GPU 内存"核对，OCR 模型和 9B 模型同时加载需要的显存在 G-5、G-6 中实测。

### 6.2 内存中处理，不落盘（SEC-12）

PRD SEC-12 要求临时文件只放内存盘、不写硬盘。Windows 没有 tmpfs，改为**全程不产生临时文件**：
- 上传的图片**不用 multipart**：请求体就是图片的原始字节（`Content-Type: image/png` 或 `image/jpeg`），服务端用 `await request.body()` 读成 `bytes`，先按 `Content-Length` 拒绝超过 10MB 的请求。原因：FastAPI 底层的 Starlette 解析 multipart 时，会把超过约 1MB 的部分写进磁盘临时文件。
- 图片预处理（旋转、增强、去水印）用 Pillow / numpy 在内存中完成。
- 调用推理后端时，图片以 base64 放在请求体里通过本机 HTTP 发送，后端不写文件。
- 结果在内存中返回，处理完即释放。
- **启动清理**：服务启动时检查系统临时目录和 `C:\prep395\` 下是否出现本服务产生的文件，有就删除并记日志（只记数量）。用来兜底进程被强制结束的情况。
- **验收**：连续发送测试图片后，全盘搜索测试图片中的特征文字（针对 `C:\prep395\`、系统临时目录、推理后端的目录），不得命中。

### 6.3 鉴权

- 每个请求带 `Authorization: Bearer <律师 Key>`，与 6000D 用的是同一个 Key。
- **395 不另存 Key**：收到请求后，用这个 Key 向 6000D 网关发一个最小的对话请求（`POST /v1/chat/completions`，`max_tokens: 1`，关闭思考）做校验；返回 200 视为有效，401 / 403 视为无效。有效结果在内存中缓存 30 秒，无效结果不缓存。
  - 效果：管理员在 `/admin` 停用 Key 后，395 最迟 30 秒内拒绝（PRD F-ACC-02）。
  - 实测（2026-09-28，`scripts/check_6000d.py`）：网关目前**没有开启 Key 校验**，不带 Key、带错误 Key 都返回 200；`GET /v1/models` 也不校验 Key，所以不能用它校验。甲方打开 `require_key` 之前，这个校验形同虚设，验收第 6 条（无 Key / 停用 Key 不能用）要等甲方改完再测；开发期间照常实现，用 `check_6000d.py` 复测。
  - 6000D 不可用时无法校验，395 返回 503"无法验证 Key"。这是有意的：不能绕开 Key。
- 日志中的 Key 只记 SHA-256 的前 8 位。

### 6.4 接口

所有接口都在同一个请求内处理完并返回，服务不保存任何跨请求的数据。字段以第 20.6 节和 `contracts/prep395/` 为准。

**`GET /health`**（不需要 Key，不含任何内容）
```json
{"status": "ok", "ocr": "ok", "llm9b": "ok", "queue": 3, "version": "1.0.0", "contract_version": "1.1"}
```

**`POST /v1/ocr/page?dewatermark=false&deskew=true&return_image=false`**：单页识别
- 请求体：单页 PNG 或 JPEG 的原始字节，长边不超过 2480 像素，大小不超过 10MB（第 6.2 节）
- 返回 200：
  ```json
  {"markdown": "…", "unclear": 2, "elapsed_ms": 5400, "backend": "<后端名>", "image_png_base64": null}
  ```
  `image_png_base64` 只在 `return_image=true` 时有值，是预处理后送去识别的那张工作副本，**只用于验收**；客户端正常运行时不请求、不保存。第一版去水印未启用（第 6.7 节），所以它是纠偏后的图；没有纠偏时就是原图。
- 识别不清的标注规则：后端能给出置信度的，低于阈值的字替换为 `■`、整行低于阈值的替换为 `[看不清]`；视觉大模型一类不给置信度的，在提示词中要求这样标注〔待 G-5，用样本校准〕。
- 错误：`400` 图片格式或尺寸不对；`401` Key 无效；`413` 文件过大；`503` 排队已满（响应头带 `Retry-After`）或无法验证 Key；`504` 识别超时（单页 120 秒）。错误体为 `{"error": {"code", "message"}}`（第 20.6 节）。

**`POST /v1/extract`**：9B 抽取，两种任务
- 字段抽取：`{"task": "fields", "text": "<带位置标记的材料文本>", "fields": ["当事人","日期","金额","案号"]}` → `{"task": "fields", "result": [{"field": "金额", "value": "60,000.00", "loc": "第6页"}], "elapsed_ms": 3200}`
- 材料分类：`{"task": "classify", "text": "…", "categories": ["起诉意见书","讯问笔录","询问笔录","书证","鉴定意见","合同","其他"]}` → `{"task": "classify", "result": {"category": "讯问笔录"}, "elapsed_ms": 900}`
- 第一版中的"按卷提取目录"（`volume_toc`）取消：卷宗整理不再是单独的 Skill。
- 单次文本不超过 16K 字；客户端负责按页切分。
- 客户端拿到结果后按原文核对（值必须能在所标位置原样找到），核对不上的丢弃并记数。核对不过的比例高于 20% 时，这次改由 27B 完成（F-ENT-04）。

**`GET /admin`**（HTTP Basic，管理员账号在部署时设置）：只读页面，显示队列长度、处理中的请求数、按 Key 前缀统计的今日页数和耗时。**不改动甲方的网关**（PRD F-ACC-02）。

### 6.5 并发、排队和取消

- 识别同时处理 N 页（默认 2，按 G-5 实测调整），其余在内存队列中排队；排队超过 20 个时返回 503。9B 抽取同时处理 1 个。
- **取消**（客户端断开连接）分两种情况，分别验证：
  - 请求还在排队：检测到连接断开后直接出队，不做处理。
  - 请求已在推理：取消本服务对推理后端的请求（`llama-server` 在连接断开时停止生成）；单页识别最长 120 秒，最坏情况是这一页算完后结果被丢弃。
- 验证方法：提交 20 页后立即取消，确认 `/admin` 中排队数在 5 秒内归零、推理进程在一页的时间内空闲。

### 6.6 395 日志

JSON Lines 格式，写到 `C:\prep395\logs\access.log`，按天滚动，保留 30 天：
```json
{"ts": "...", "key": "a1b2c3d4", "api": "ocr/page", "pages": 1, "bytes": 812345, "elapsed_ms": 5400, "status": 200, "err": null}
```
`err` 只写异常类名。关闭 uvicorn 自带的访问日志；推理后端的日志只保留启动和错误信息，不含请求内容（部署后抽查）。

### 6.7 去水印

- 只处理这次请求中的图片副本；律师电脑上的原件不变，引用仍指向原件页码。
- 规则保守：只去除浅灰色、低饱和度、大面积重复的斜向文字或图案。**红色和蓝色像素（印章、签名、批注笔迹）一律不动。**
- 用带印章、签名、手写批注的样本验收（PRD 验收第 16a 项）；效果不稳定时，默认关闭去水印，由律师按需勾选。
- **第一版去水印未启用**（2026-09-29，T6 三轮复核后按止损线定；候 owner 清单 N14）：
  - 原因：页上既有水印又有浅灰手写批注时，按"浅灰、低饱和"的像素统计分不开两者，批注会被一起抹掉，识别结果里悄悄少字。扫描页正文的抗锯齿边缘本身就是浅灰像素，量级与几行手写相当。测量数据在 `docs/plan/evidence/T6/p2a-measure.txt`。
  - 395 服务：`dewatermark=true` 照常接受（契约不变），图片原样送识别；算法代码保留但不被调用，由写死的开关常量控制，没有环境变量或配置项能打开。
  - 客户端（T12、T13）：识别任务的"去水印"选项不显示；`ocr_jobs` 表里"是否去水印"一律记否；提交识别时不带 `dewatermark` 参数。
  - 验收第 16a 项：按"去水印未启用，原件、印章、签名、批注不变"验。
  - 以后要做，方向是认出水印的文字内容或版式再去除，不是再调像素阈值。

---

## 7. 识别任务（客户端，`ocr/queue.py`）

### 7.1 状态

每个识别任务记在所属案件的 `case.db` 里，表结构见 `contracts/case_db.sql`：

- 任务表 `ocr_jobs`：编号、材料编号、材料版本（sha256）、是否去水印、状态（排队中 / 识别中 / 已暂停 / 已完成 / 已取消 / 部分失败）、暂停原因、总页数、已完成、失败数、时间。
- 页面表 `ocr_pages`：任务编号 + 页号（联合主键，写入幂等）、状态（待发送 / 发送中 / 已完成 / 失败 / 已取消）、尝试次数、失败原因、结果路径。

任务创建时就固定了所属案件和材料版本，之后切换界面上的案件不影响它（第 4.3 节）。状态都在案件文件夹内，所以切换案件、关闭或重启软件后都能接着做（F-NODE-04）。

### 7.2 执行

1. 律师在材料区选定页面（默认选中"需识别"的页），点"提交识别"。确认框写明"将把 N 页图片发送到 395 识别；识别在本机后台逐页进行，期间请保持电脑开机、联网，不要退出软件"。
2. 工作台服务启动时，扫描"最近案件"注册表中所有案件的未完成任务，加入全局队列。每位律师同时发送 2 页。
3. 每一页的处理：用 pypdfium2 以 200 DPI 渲染为 PNG（长边不超过 2480 像素），**在内存中**直接发送到 `/v1/ocr/page`，不写临时文件；结果写入 `工作区/材料/识别页/<材料编号>/<页号>.md`，标记该页已完成。
4. 整份材料的页全部完成（或失败）后，重新生成材料文本（第 5.3 节），更新检索索引，发系统通知（第 3.4 节 U-7）。

**不同情况下的行为**（写进操作说明）：

| 律师的操作 | 识别 |
|---|---|
| 关闭窗口（软件留在托盘） | 继续进行 |
| 切换到其他案件 | 继续进行（任务绑定原案件） |
| 从托盘完全退出软件、关机、合盖睡眠、断网 | 暂停，不再发送后续页；正在发送的那一页作废 |
| 重新打开软件、恢复网络 | 自动继续，从第一个未完成的页开始；"发送中"的页重新发送 |
| 395 停机 | 暂停，显示"等待 395 恢复"，每 30 秒探测一次，恢复后自动继续 |

395 不保存任何结果，所以识别只在律师电脑开着软件时进行；这与 PRD F-NODE-03～07 一致，不承诺"关机后服务端继续处理"。

### 7.3 出错和中断

| 情况 | 处理 |
|---|---|
| 连接失败或超时 | 任务转为"已暂停"；每 30 秒探测一次 `/health`，恢复后自动继续（F-NODE-05、F-NODE-07） |
| 503 | 按 `Retry-After` 等待后重试，不计入失败次数 |
| 504 或 5xx | 该页重试，最多 3 次；3 次都失败则标为失败，继续处理下一页 |
| 401 | 整个任务暂停，提示"Key 无效或已停用，请联系管理员" |
| 400 或 413 | 该页标为失败，附原因 |
| 取消 | 未发送的页标为已取消，正在发送的请求立即断开（395 端的处理见第 6.5 节），已完成的页保留（F-NODE-06） |

- 每页有唯一编号（`job_id + page_no`），结果写入是幂等的，重发不会重复写入。
- 原件哈希变了、而识别结果还是基于旧版本时，材料列表中标"过期"。

### 7.4 6000D 临时接管识别（可选）

管理员在设置中开启后，395 不可用时改为发到 6000D：模型支持图片输入，请求格式为 OpenAI 的 `image_url`（base64），提示词与 395 的视觉模型一致。默认关闭。〔待 G-5 之后决定是否做〕

---

## 8. 6000D 接入

### 8.1 请求约定

两条调用路径用同一套约定：

- **Agent**：DSH 的 `dsh-llm-pi-ai` 适配器，按 OpenAI 兼容接口配置一条路由（写在组合包补丁的 `llm-pi-ai` 行）：
  ```yaml
  providers:
    lawfirm:
      displayName: 律所模型
      api: openai-completions
      baseURL: http://127.0.0.1:<转发端口>/v1   # 工作台服务的本机转发，由它选所内或所外地址（第 15 节）
      apiKeyEnv: LAWFIRM_KEY            # 通过 ctx.credentials 解析
      timeoutMs: 1200000
      models:                           # 三个条目只差 contextWindow，对应律师选的窗口（第 8.2 节）
        - id: lawfirm-32k               # DSH 内部标识；发给网关的模型名必须是 qwen38-27b（见第 8.2 节〔待验证〕）
          name: 律所模型（32K）
          contextWindow: 32768
          input: [text]                 # 图片走 395，不给 Agent 发图
          reasoningEfforts: {off: null, low: low, medium: medium, high: xhigh}   # 6000D 不接受 high，见第 8.2 节
        # - 64K、128K 两个条目写法相同，contextWindow 分别为 65536、131072
      compat:
        supportsStore: false
        supportsDeveloperRole: false
        maxTokensField: max_tokens
        thinkingFormat: qwen-chat-template   # pi-ai 支持的取值之一：按思考档位发送 chat_template_kwargs.enable_thinking
  ```
  配好后抓一次请求核对：关闭档是否发出 `enable_thinking: false`，低 / 中 / 高是否带上 `reasoning_effort`；带不上的，用 `chatTemplateKwargs` 补〔待验证〕。
- **流水线**：工作台服务直接调用 `<当前选用的 6000D 地址>/chat/completions`（地址选择见第 15 节），流式输出，请求体沿用 wiki 测试的 `run_pipeline_v2.py`。
- 请求头：`Authorization: Bearer <律师 Key>`。流水线另加 `X-Session-Id: <案件编号前 8 位>-<任务编号>`，让同一任务的请求落到同一张卡，命中前缀缓存；Agent 路由在 profile 里配置的请求头是固定的；DSH 会把会话 ID 作为 `sessionId` 交给 pi-ai，它是否会变成请求头，抓请求核对〔待验证〕，不会就不带，由网关按默认规则分卡。
- 温度：流水线用 0.2；Agent 用 Skill 推荐值，默认 0.3。

**律师 Key 的存放**（D9，PRD F-ACC-01a）：DSH 从 `ctx.credentials` 取 Key，默认实现 `credentials-local` 把 Key 明文存在 `$DSH_HOME/.credentials.yaml`，本项目不用它。

**2026-09-30 T7 合并时回写**：我方凭据插件只认 `LAWFIRM_KEY`，不读环境变量；DSH 自己要写的授权记录（目前只有连接插件的 `client-connection/browser-session` 一种）只放进程内存、不落盘、不进凭据管理器，其他记录名一律拒绝并在插件日志记记录名；崩溃转储可能带出这条内存记录，归 T17 数据落点核对。首次配置页的"测试连接"：服务只能按已保存的设置测，所以先保存再测，没通过就恢复成测试前的地址和 Key（之前没有的就删掉），恢复失败明确提示"未能恢复原配置"；测试进行中程序被结束会留下未验证的配置，第一版用应用数据目录里的"测试进行中"标记兜住（候 owner 清单 N34 ②，随 T7 第二次交回）。
- **我方凭据插件** `lawbench-dsh/credentials`：实现与 `credentials-local` 相同的服务接口，通过组合包补丁替换 `credentials-local` 行（第 3.1 节）。Key 存在 Windows 凭据管理器的"普通凭据"中，目标名固定为 `lawbench/LAWFIRM_KEY`，用户名字段写 `lawbench`。Node 侧用 Windows 的 `CredWriteW` / `CredReadW`（经 N-API 原生模块或 PowerShell 调用均可，由开发工单选定并在安装包中内置，不在运行时下载）。
- **首次配置页**写入 Key；设置页可以更换 Key。
- **工作台服务**用 Python `keyring`（Windows 后端）读同一条目：`keyring.get_password("lawbench/LAWFIRM_KEY", "lawbench")`〔待验证：keyring 的 Windows 后端与 `CredWriteW` 写入的目标名、用户名能否对上；对不上时两边统一改用 keyring 约定的格式〕。只读，不缓存到文件。
- **验收**：`$DSH_HOME/.credentials.yaml` 不存在或不含 Key；在"凭据管理器 → Windows 凭据"中能看到该条目；换一个 Windows 账号登录读不到。

### 8.2 参数映射

| 界面 | Agent（DSH） | 流水线（请求体） |
|---|---|---|
| 思考：关闭 | `reasoningEffort: off` | `chat_template_kwargs: {"enable_thinking": false}` |
| 思考：低 / 中 / 高 | `reasoningEffort: low / medium / high`（Agent 插件在 `agent/request` 中按任务单设置）；路由配置把 `high` 映射为发给网关的 `xhigh` | `chat_template_kwargs: {"enable_thinking": true, "reasoning_effort": "low" / "medium" / "xhigh"}` |
| 窗口 32K / 64K / 128K | 插件在 `agent/request` 中按任务单选择对应窗口的模型条目（`LlmCallConfig.model`）；控制 L1 长度；DSH 按该条目的 `contextWindow` 压缩历史（见下） | 客户端按窗口控制"输入 token + max_tokens" |
| 最大生成量 | `maxTokens`（插件设置） | `max_tokens` |

**2026-09-30 T7 合并时回写**：`agent/request` 不切换 `model`，"窗口"只控制输入长度和 `maxTokens`。

**"高"档发 `xhigh`**（2026-09-29 实测，T4 发现、主编排复测）：6000D 对 `reasoning_effort: "high"` 返回 400（`Unexpected reasoning effort high. Supported types are xhigh (default), medium, and low.`），放在请求体顶层或 `chat_template_kwargs` 里都一样；`xhigh`、`medium`、`low` 和关闭思考都返回 200。界面、任务单、契约里仍叫"高"（`high`），只在发给 6000D 的那一步换成 `xhigh`：Agent 由路由配置的 `reasoningEfforts` 映射，流水线（T16）和 395 的 Key 校验、抽取（T6）在拼请求体时映射。网关把 `xhigh` 标为默认值，不带 `reasoning_effort` 时可能等同最高档，G-7 比较三档差异时要每档都显式带上。

思考三档是否有实际差异〔待 G-7〕；没有差异就合并为"开"。服务器上限是 262144。

- **流水线**：token 数用内置的 tokenizer.json 计算（`llm/tokens.py`），按整条请求计：系统提示 + 本步输入 + `max_tokens`，超过窗口就先切小再发。
- **Agent**：整条请求由 DSH 组装（系统提示、工具定义、历史消息、已加载的 Skill、工具返回），插件拿不到完整请求，所以分两层控制：
  - 插件控制自己加进去的内容：L0 不超过 6000 字；L1 不超过窗口的 40%（按 token 计），即 32K 窗口约 13000 token、64K 约 26000 token、128K 约 52000 token（按 tokenizer.json 计，不按字数），超出的输入只列目录；
  - 整体交给 DSH：律师选的窗口对应路由中的一个模型条目（三个条目只差 `contextWindow`），插件在 `agent/request` 中设置 `model` 为该条目；DSH 的用量统计（`token-meter`）和上下文压缩（preset 里的 compaction 组）按它工作；仍然超限时，网关返回超出上下文的错误，按第 8.3 节提示律师。
  - 〔待验证〕pi-ai 能否让三个条目发给网关的模型名都是 `qwen38-27b`（条目 id 不同、请求中的 model 相同）。不能时的备选：只配一个 128K 条目，律师选的窗口只控制 L1 长度和最大生成量，历史压缩统一按 128K。
- 超出窗口时，发送前就在界面提示"材料超出当前窗口，请缩小范围或调大窗口"（F-PARAM-04），不截断。
- 参数取值的优先级按 PRD F-PARAM-03 实现；个人预设存在 `<应用数据>/settings.json`。

### 8.3 超时和错误提示

| 情况 | 判断方式 | 提示（中文） | 重试 |
|---|---|---|---|
| 连不上 | 连接被拒绝或超时（10 秒） | 无法连接服务器，请检查网络 | 1 次 |
| Key 无效或已停用 | 401 / 403 | Key 无效或已停用，请联系管理员 | 否 |
| 繁忙 | 503 | 服务器繁忙，排队已超过 5 分钟，请稍后再试 | 否 |
| 超出上下文 | 400，且错误信息包含 context length | 内容超出模型上限 | 否 |
| 输出被截断 | `finish_reason == "length"` | 输出达到上限，已保存为草稿，可调大"最大生成量"后继续 | 否 |
| 单次请求过长 | 客户端计时超过 1200 秒 | 本次生成时间过长，已停止并保存草稿 | 否 |

排队时长取响应头 `X-Queue-Wait-Ms`，显示在运行状态中（F-RUN-01）。

上表是流水线（工作台服务）的处理。Agent 路径的错误由 DSH 的 LLM 适配器报出：插件在 `session/event` 中把结束原因写进结果清单；DSH 界面上的错误文字按上表改为中文〔核对 DSH 现有文案，缺的补〕。DSH 默认会重试，改为最多 1 次（写在 `llm-pi-ai` 路由的 `retryPolicy`，见第 3.1 节），不对 401 / 403 重试。

### 8.4 取消

- 客户端断开连接后，网关记录状态 499，vLLM 随之中止生成（服务器报告 4.1 节）。
- 流水线取消：设置取消标志，中止所有正在进行的请求，已完成的步骤保存为草稿。
- **确认服务端真的停了（F-RUN-02）**：取消后 10 秒内，客户端调用网关的 `/status`，确认本 Key 没有在途请求（〔待验证 `/status` 是否按 Key 返回；如果不能，就只在验收时用 `/admin` 和 vLLM 的 `num_requests_running` 指标人工确认〕）。

### 8.5 并发

每位律师在客户端同时最多 2 个 6000D 请求（与计划中网关"每人 2 路"一致）；流水线的并行度也是 2。

### 8.6 需要甲方在 6000D 上改的配置

1. 网关 `require_key=true`，为每位律师发 Key，删除默认 Key `bld`。
2. 两个 vLLM 实例改为 `--host 127.0.0.1`。
3. `keys.json` 改为 `chmod 600`。

建议但本次不强制：每 Key 并发限制、上游超时（`sock_read=1200`）、ufw 防火墙。

---

## 9. 上下文编排和出处

### 9.1 流水线（D6）

参照 wiki 测试的 `run_pipeline_v2.py`，把它改成 `pipeline/runner.py` 通用框架：

- **每个步骤** = 取输入 → 拼提示词 → 调用模型 → 清理输出 → 核对出处 → 不通过时只把有问题的部分交回模型修改（最多 2 轮；改完内容没变化就停止）→ 写入草稿。
- **提示词**：放在 Skill 目录的 `流水线提示词.md` 里，按 `## 标题` 分段；系统提示 = "通用规则"段 + 本步骤段。修改规则只改这个文件，不改程序。
- **长材料**：按页切段，每段约 8000 字，一段一次调用。
- **表格类材料**（银行流水、通话详单）的摘要页：**只用于 wiki 摘要这一步**，目的是让摘要篇幅可控。由程序按筛选条件列出部分行（wiki 测试用的是：对方为个人、金额 ≥ 10,000、取现、含 ■ 的行），其余只计数；筛选条件写在 Skill 的配置里，可按案件调整。规则：
  - 摘要页开头写明筛选条件和"已列出 X 行 / 共 Y 行"，材料清单中该材料标"摘要为筛选结果，非全量"；
  - 原文不删，全部行都在检索索引里，AI 和律师都能查到；
  - 阅卷笔录、证据矛盾等其他 Skill **默认不筛选**，需要筛选时由该 Skill 定义并在成果中注明范围；筛选过的材料不计为"已读完"。
  判断是否为表格类材料：以 `|` 开头的行占全部行数的 60% 以上。
- **材料清单、目录、日志**由程序生成，不经过模型，覆盖情况一定准确（F-CITE-03）。
- **进度**：界面显示"第 k 步 / 共 n 步，当前处理：<材料名>"。
- **任务记录**：流水线也是一个任务，编号形如 `P-<时间>`，与 Agent 任务一样使用 `工作区/任务/<任务编号>/`（task.json、草稿/、result.json），成果确认流程相同。

案件 wiki 的步骤：逐份材料写摘要 → 程序生成材料清单 → 当事人、时间线、争议焦点、概览（每篇一次调用）→ 生成案件卡片 `case.json`（一次调用，从四篇文章中摘取当事人、争议焦点、关键事实，每条带出处，状态为"原文摘录"或"模型生成（未确认）"）→ 程序写目录和日志 → 全文核对。卡片中的"本方立场"由律师在界面上填写；律师在界面上确认某条后，状态改为"律师确认"。各步骤的提示词在 `skills/case-wiki-build/流水线提示词.md`，步骤名固定（`contracts/formats.md` 第 6 节）。案件类型（刑事 / 民事 / 合同 / 其他）在生成卡片时判断，写入 `case.json` 的 `case_type`。

**使用 395 的 9B**（律师勾选"使用 395 抽取"时，F-ENT-04）：在"逐份材料写摘要"之前，先把每份材料按页切成不超过 16000 字的段，调用 395 `/v1/extract` 做材料分类（`classify`）和字段抽取（`fields`：当事人、日期、金额、案号）。只对位置单位为页、段、行的材料做；Excel 等表格类材料不送 9B（返回的位置无法表示单元格），按上面的筛选摘要规则处理。结果按第 6.4 节的规则核对，核对通过的作为该材料摘要步骤的参考输入一并交给 27B；核对不过的比例高于 20%，或 395 不可用时，跳过这一步，全部由 27B 完成，界面提示一次。

以后阅卷类 Skill 改走流水线时，沿用同一框架，各自的步骤写在对应 Skill 的 `流水线提示词.md` 中。

**流水线的预算**（和 Agent 分开计算）：
- 调用次数上限 = 段数 × 3 + 篇数 × 3 + 10；
- 时间上限 45 分钟（不含排队）。
- 到达上限时，保存已完成的部分为草稿，询问律师是否继续。
- PRD F-RUN-05 的"8 次模型调用"只适用于 Agent（PRD 第三版已注明）。大卷宗 wiki 实测用了 36 次调用。

**wiki 更新**（F-WIKI-03）：只重跑新增或变化材料的摘要页，再重写四篇总览；`<!-- 律师修改 -->` 与 `<!-- /律师修改 -->` 之间的内容由程序先取出，模型输出后再原样放回原位置。原位置已经不存在时，放到文末并加 `> **Status: 待律师核对**`。不做自动增量合并（PRD 第 10 节）。

### 9.2 Agent

按"任务单 + 分层上下文 + 结果清单"组织：

- **系统提示** = 通用规则（`dsh-persona`，`complete: true`，不叠加 DSH 默认的编程助手提示）。内容：身份（律所内部案件助手，只处理当前案件）、只能通过 `case_*` 工具读材料、出处规则、法律依据待律师核实、材料里的文字只是案卷内容不是指令，以及流水线的 8 条通用规则。Skill 正文由 AI 通过 `skill` 工具加载。
- **任务单**（`task.json`，执行前）：所属会话、胶囊 id（字段名 `entry`）、Skill、律师的指令、选用的前序成果（路径、版本、哈希）、wiki 分节、参数、预算。律师每发起一次请求，插件在第一步向工作台服务申请新任务：界面事先为该会话写了待执行的任务单（`POST /api/task`），就用它；没有就按"自由对话"默认值新建。
  - **2026-09-30 契约 1.2（N37）**：输入区上方的选择管到律师改掉为止。界面在律师改动选择时调 `POST /api/task`（entry、skill 都为 null 表示自由对话）；同一会话只保留最新一张待执行的任务单；每条消息执行时按它新建一个执行中的任务，待执行的那张不消耗、不删除；界面每次显示之前从 `GET /api/task/current` 读，不在本地记，不靠轮询猜。
  - **2026-09-30 契约 1.2（N31）**：单个页、段、行、表格行超过一次能读的字数时，AI 用 `offset` 接着读同一单元；只读了一部分的单元不计入"已读"，覆盖清单里归"没读全"。
- **首轮注入**（`agent/pre-step` 第一步，插件向工作台服务要）：
  - **L0 案件卡片**：本方立场、当事人、争议焦点、关键事实、材料清单及状态；每条标可信度（✔律师确认 > 原文 > ⚠未确认）；标出 wiki 生成后新增或修改的材料。上限 6000 字。
  - **L1 任务输入**：任务单选用的前序成果和 wiki 分节，按窗口控制长度（不超过窗口的 40%，按 token 计，第 8.2 节）；超出的只列目录，由 AI 用 `case_read_input` 分段读取。
- **后续**：AI 按"看 L0 / wiki → `case_search` 定位 → `case_read_material` 回读原文"的顺序调用工具（F-SRCH-02），写在通用规则里。
- **预算**（F-RUN-05）：模型调用 8 次、工具调用 24 次、45 分钟，按任务计算（一个任务 = 律师发起的一次请求）。由 Agent 插件实现：`agent/pre-step` 超限时拒绝，最后一次调用前注入"立即收尾"；`tools/pre-execute` 超限时拒绝工具调用，**但 `case_save_draft` 不计入、也不受工具预算限制**，保证模型总有机会保存。

**2026-09-30 T7 合并时回写**：工具预算只数 `case_*`（`case_save_draft` 除外），被拒绝的不计；碰到过上限的任务结束原因报 `budget`。进度保存传的是本任务到目前为止全部回复的拼接，空文本不传。`task/begin` 或 `context` 失败时插件拒绝整轮（DSH 的拒绝不能附带消息，界面提示归 T13）；工具在没有任务时返回"工作台服务未启动"。
- **结果清单**（`result.json`，执行后）：状态（完成 / 取消 / 预算停止 / 输出上限 / 失败）、实际用量、草稿、出处核对结果、覆盖清单。覆盖清单按 `reads.json` 的实际读取记录计算，不采信模型自报。
- 正常完成前应调用 `case_save_draft`；返回有 A–E、G 类问题或有未读完的材料时，修正后用同一标题再保存（最多 2 轮）。
- **中断时由程序保存**（F-RUN-04）：不依赖模型调用工具。
  - 执行中：插件监听 `session/event` 中的 `assistant/message` 事件（模型每完成一次回复就有一条），把回复文本交给工作台服务，覆盖写入 `草稿/进行中.md`，并更新结果清单中的进度（已用调用次数、已读材料）。
  - 结束时（`turn/end`，含取消、预算停止、输出上限、出错）：由程序写结果清单的最终状态；本任务没有保存过正式草稿的，把 `进行中.md` 改名为 `未完成-<时间>.md`。
  - 硬退出（进程被结束、断电）：下次打开案件时，发现状态仍为"执行中"的任务，标为"异常中断"，保留已有的 `进行中.md`。
  - 模型主动调用 `case_save_draft` 用于保存结构化的正式草稿，不是异常情况下唯一的保存途径。

### 9.3 出处格式

- 正文中的写法：`〔材料名 第N页〕`、`〔材料名 第N段〕`、`〔材料名 工作表!B12〕`、`〔材料名 第N行〕`；范围写 `第N-M页`；同一括号内多处用顿号分隔，每处都写材料名。严格写法（正则）见第 20.2 节，Skill 的共用规则与之一致。
- **材料名唯一**：规则见第 20.2 节（先用文件名，重名时依次改用相对路径、带扩展名的相对路径），由 `case_list_materials` 给出，AI 照抄。底层每条出处都解析为 `材料编号 + 版本（原件哈希）+ 位置`，记录在任务的结果清单里；原件之后变了（哈希不同），点这条出处时提示"原件已更新，出处可能对不上，请重新核对"；不保留旧版本的材料文本。
- **出处用六角括号 `〔〕`**，与材料文本里的位置标记 `【第N页】` 区分开（wiki 测试已验证这种写法）。
- 找不到依据写 `〔未找到依据〕`，推断写 `〔推断〕`。
- 法律内容没有律师提供的依据的，加"（法律依据待律师核实）"（F-CITE-04）。
- 在界面上，出处渲染为可点击链接，点击后打开原文查看并定位：PDF 显示对应页的页面图片，其他格式滚动到对应段、行或单元格（F-CITE-01）。不做文字高亮（PRD 第 10 节）。
- 导出为 Word 时，出处保留为纯文本。

### 9.4 出处核对（`checks/`）

把 wiki 测试中的 `check_evidence.py` 和 `check_citations.py` 改成库函数（输入一篇文本和材料集合，输出问题列表），流水线和 `case_save_draft` 共用：

| 类 | 含义 | 处理 |
|---|---|---|
| A | 疑似补全：原文是"8■,000.00"，文中写成完整值 | 必须修改 |
| B | 页码不对：值存在，但不在所标的那一页 | 必须修改 |
| C | 所引材料中找不到这个值 | 必须修改 |
| D | 头部 Raw 字段漏了正文引用的材料（仅 wiki） | 必须修改 |
| E | 出处格式错误 | 必须修改 |
| F | 含金额或日期但没有出处 | 提示 |
| G | 评价性用语（可信度、佐证、预谋、构成犯罪…），引号内的原文不算 | 按成果类型，见下 |

**按成果类型区分**：在 Skill 头部用 `kind` 声明成果类型。
- `excerpt`（摘录类：wiki、阅卷笔录、时间线）：要求忠实原文。A–E、G 类都必须修改。
- `analysis`（分析类：证据矛盾分析、合同审查意见）和 `draft`（文书类：辩护意见、律师函、合同）：允许有依据的判断。A–E 类必须修改；G 类只提示，但判断性的句子要标明是"分析意见"并带出处。

**核对能证明什么**：这套核对只能证明"这个数字、日期、引语在所标的材料位置原样存在"，不能证明那一页支持整句话的结论。所以界面上叫"数值与出处位置核对"，不叫"事实已核验"；结论是否成立由律师判断。

需要扩展的地方：支持单元格和行号出处；中文数字金额（如"十八万元"）的比对〔先列为提示，不做自动比对〕。

核对结果随成果一起显示在"自检结果"中（F-SKILL-03）。

---

## 10. Skill 和胶囊

### 10.1 加载位置

只从以下两处加载，按顺序，同名时后者覆盖前者（F-SKILL-06）：
1. `<安装目录>/skills/`：随安装包内置，只读。
2. `%ProgramData%\<产品名>\skills\`：管理员下发。普通用户账号不可写（由安装程序设置权限）。

实现：`dsh-skill-filesystem` 设 `includeDefaultRoots: false`，`customSkillDirs` 只列这两个目录（第 3.1 节）。注意 DSH 对同名 Skill 是先到先得，所以数组里**管理员下发目录写在前面**，才能实现"管理员下发的覆盖内置的"（2026-09-29 T4 复核核实）。这样**不会**扫描 `<案件>/.dsh/skills`、`<案件>/.agents/skills` 和用户目录（验收时在案件里放一个恶意 Skill 目录验证）。

Skill 中的 `scripts/` 只由工作台服务从以上位置导入执行，AI 不能执行。

**DSH 对 Skill 的要求**：`SKILL.md` 头部必须有 DSH 识别的 `name`（英文短名，即目录名）和 `description`（触发说明）；下面的扩展字段 DSH 不读，由工作台服务读取。

### 10.2 目录结构

```
skills/
├─ _shared/共用规则.md   所有业务 Skill 共用的规则，由 build_skills.py 同步进每个 SKILL.md，不在单个 Skill 里改
├─ _scripts/            build_skills.py（同步共用规则并校验）、install.py（复制到安装目录）、skill_manifest.py（校验规则）
├─ capsules.default.json  默认胶囊配置（第 10.3 节）
└─ <skill-id>/          每个 Skill 一个文件夹，平铺
   ├─ SKILL.md          头部信息 + 六部分正文
   ├─ 流水线提示词.md    流水线类 Skill 才有（本次只有 case-wiki-build），分段约定见 contracts/formats.md 第 6 节
   ├─ references/       输出模板、文书模板
   ├─ scripts/          专用核对脚本（可选）
   └─ tests/
      ├─ 样本01/ …      至少 4 个样本（虚构或脱敏材料）
      └─ 要点.md        每个样本必须找出的要点和扣分项（格式参照大卷宗的"标准答案.md"）
```

`SKILL.md` 头部信息（契约 `contracts/skill/frontmatter.schema.json`）：

```yaml
---
name: criminal-reading-notes   # DSH 用；与目录名一致
title: 刑事阅卷笔录             # 界面显示
description: 刑事阅卷笔录。律师要求对刑事案件卷宗阅卷、制作阅卷笔录……时使用。
mode: agent               # pipeline 或 agent
kind: excerpt             # 成果类型：excerpt 摘录 / analysis 分析 / draft 文书（决定 G 类核对规则，第 9.4 节）
params: {thinking: 低, window: 64K, max_tokens: 16384}
owner: 待定               # 责任律师；发版校验（build_skills.py --strict）时不能是"待定"
inputs: [materials, wiki] # 需要哪些输入：materials 材料 / wiki / prior 前序成果
---
```

正文必须包含六个二级标题：`## 适用场景`、`## 输入`、`## 必问问题`、`## 处理步骤`、`## 输出模板`、`## 自检清单`（F-SKILL-01）。加载时检查，缺少任何一个就不加载，并在设置页提示管理员。

- **必问问题**：每条写成 `- key：问题（可从材料中获取：是/否）`。Agent 在开始时调用 DSH 的 `ask_user_question`，把能从材料里找到的值预先填好，请律师确认（F-SKILL-02）。
- **自检清单**：每条是一句可以检查的规则。AI 在输出前逐项自查并写出结果；另外，`case_save_draft` 的核对结果一并显示。

哪个 Skill 出现在哪个胶囊，由胶囊配置决定（第 10.3 节），Skill 头部不再写入口和顺序（契约 1.1 删除了 `entry`、`order` 字段）。

**本次的 Skill**：18 个，唯一存放位置是仓库的 `skills/`（`D:\lawbench\skills`），全部按本节格式，`build_skills.py` 和契约自检（`contracts/check_examples.py --skills`）都已通过：
- 第一版的 13 个：case-wiki-build、case-reading-notes、criminal-reading-notes、criminal-evidence-review、defense-opinion、cross-exam-opinion、criminal-applications（增加"不予批准逮捕的法律意见书"）、contract-review、contract-draft、general-drafting、pre-issue-check、doc-revise、legal-workflow（改为按胶囊导航）；
- 本版新增 5 个：litigation-docs（诉讼文书起草）、sentence-calc（刑期计算）、tender-review（招标文件审查）、bid-drafting（投标文件起草）、case-archiving（案卷归档，由律所归档 Skill 改写，附 `catalogs/` 四类归档目录）。

律所提供的发票整理、委托材料两个工具不是 Skill，放在 `engines/`（第 13.3、13.5 节）；原归档 Skill 只作参考，放在 `docs/reference/client-skills/`。律师此前提供的 11 个参考 Skill 仍不放进仓库、不被加载（第 2 节"不用的组件"）。

**Skill 的工作流程**：改了 Skill 或胶囊配置后，运行 `python skills/_scripts/build_skills.py`（同步共用规则并校验，发版时加 `--strict`），再由打包脚本运行 `install.py --out <安装目录>/skills`。

### 10.3 胶囊配置

`skills/capsules.default.json`（契约 `contracts/skill/capsules.schema.json`）是首页的默认配置，随安装包复制到 `<安装目录>/skills/`。律师本机的配置在 `<应用数据>/capsules.json`，首次启动时从默认配置复制；胶囊管理（U-11）改的是本机配置，"恢复默认"再从默认配置复制一次。升级安装包不覆盖本机配置；默认配置新增的胶囊，在本机配置里以隐藏状态补进去，并在首页提示"有新功能，可在管理胶囊中显示"。（2026-09-30 契约 1.2，N35：补进去的胶囊标 `new: true`，界面据此提示；律师显示或隐藏它一次后清掉）

| 分组 | 胶囊 | 类型 | Skill（按推荐顺序）或工具 |
|---|---|---|---|
| 民事与商事 | 合同审查 | skill | contract-review → pre-issue-check → doc-revise |
| 民事与商事 | 合同起草 | skill | contract-draft → contract-review → pre-issue-check → doc-revise |
| 民事与商事 | 诉讼文书起草 | skill | litigation-docs → pre-issue-check → doc-revise |
| 刑事案件 | 案卷分析 | skill | criminal-reading-notes → criminal-evidence-review → pre-issue-check → doc-revise |
| 刑事案件 | 刑期计算 | skill | sentence-calc |
| 刑事案件 | 取保候审/不予逮捕申请 | skill | criminal-applications → pre-issue-check → doc-revise |
| 刑事案件 | 辩护词起草 | skill | defense-opinion → pre-issue-check → doc-revise |
| 刑事案件 | 质证意见起草 | skill | cross-exam-opinion → pre-issue-check → doc-revise |
| 日常办公 | 发票整理 | tool | invoice（第 13.3 节） |
| 日常办公 | 律师函起草 | skill | general-drafting → pre-issue-check → doc-revise |
| 日常办公 | 招投标材料处理 | skill | tender-review → bid-drafting → pre-issue-check → doc-revise |
| 日常办公 | 文件生成 | tool | retainer（委托材料，第 13.5 节） |
| 日常办公 | 案卷归档 | skill | case-archiving |
| 日常办公 | 通用文书 | skill | general-drafting → case-reading-notes → pre-issue-check → doc-revise |

`shared`（每个 Skill 胶囊里都可用）：case-wiki-build、legal-workflow。

- `case-wiki-build` 是流水线 Skill：在每个 Skill 胶囊的工作区显示为"生成 / 更新案件 wiki"按钮，调用 `POST /api/pipeline/run`，不进入对话。其余 Skill 都在对话中运行（写任务单后由 Agent 执行）。
- 胶囊内按顺序列出 Skill，第一个默认选中；律师可以跳过或单独运行任何一个，也可以自由对话。
- 胶囊名最长 12 个字，分组名最长 8 个字。律师新增的胶囊 `custom: true`，只能从已安装的 Skill 和两个内置工具中选。
- 服务端校验（`PUT /api/capsules`）：分组和胶囊的 id 全局唯一；Skill 都存在；工具只能是 `invoice`、`retainer`；**默认配置里的每个分组和胶囊 id 都必须还在**（只能隐藏，不能删除）；`shared` 和 `hint` 必须与默认配置相同（律师不能改）。不合格返回 `INVALID_ARGUMENT`，不保存。
- 任务单的 `entry` 存胶囊 id（不是名称），律师改名不影响已有任务。
- **选用前序成果**（F-ENT-02、F-ENT-03）：运行时，律师可以勾选本案的任意草稿或成果（包括其他胶囊产生的）作为输入。任务单的 `inputs` 记录每个输入的路径、版本号和 sha256；执行时核对哈希，选用后被改过的，提示律师复核。上游修改后生成新版本，不覆盖下游。

---

## 11. 全文检索（`search/`）

- 每个案件一个 FTS5 表，放在 `case.db` 中，使用 `tokenize='trigram'`。
- **索引单位**：一页、一段、一个工作表的每 20 行，或文本文件的每 50 行；每条记录包含 `material_id, loc, text, text_norm`。
- **归一化**（`text_norm`，查询词也做同样处理）：全角转半角；去掉数字中的千分位逗号；统一空白字符。（2026-09-30 T9 复核后补：**两个汉字（CJK 统一表意文字及中文标点）之间的空白一并去掉**——PDF 材料文本常在句中硬换行，否则跨行的词搜不到；拉丁字母、数字之间的空白保留；位置映射照样保留，出处仍指向原文位置。）
- **短词**：trigram 要求至少 3 个字。查询词 1–2 个字时，改为在 `text_norm` 上用 `instr` 逐条扫描。单个案件的数据量在几十 MB 以内，速度可以接受。**保证不会静默搜不到**（F-SRCH-03）。
- **查询扩展**：
  - 日期"2025年3月10日" ↔ "2025-03-10" ↔ "2025.3.10"；
  - 金额"8万" ↔ "80000" ↔ "80,000"；
  - 以上各写法同时查询，结果合并。
- **返回**：命中文字前后各 40 字作为片段，附出处；排序为：完全匹配 > 扩展匹配，再按材料顺序。
- **验证集**：用 G-9 的检索验证集（两字姓名、简称、日期、金额、案号）做自动测试，全部命中才算通过。

---

## 12. 导出和修订版

### 12.1 导出（`export/pandoc.py`）

- **Word**：`pandoc <草稿>.md -o <成果>.docx --reference-doc=<律所模板>.docx`。模板分为文书模板和合同模板，在设置中选择。出处保留为纯文本；可选择在文末附"出处索引"表。
- **Markdown**：去掉指向工作区的链接，出处保留为纯文本。
- **确认流程**（F-OUT-03）：草稿只存在 `工作区/任务/<任务编号>/草稿/`；律师点"确认保存"后，才导出到 `成果/<标题>-v<N>.<md|docx>`，版本号自动递增，并写入 `成果/索引.json`（来源任务、选用的输入、出处核对结果）。

### 12.2 修订版 Word（`export/redline.py`）

**修改清单格式**（`contract-review` Skill 在保存审查意见后调用 `case_save_edit_list` 保存到 `工作区/任务/<任务ID>/修改清单/<合同材料名>.json`；契约 `contracts/tools/case_save_edit_list.schema.json`）。生成的修订版存为该任务的草稿 `草稿/<合同材料名>-修订版-v<N>.docx`，律师确认后与其他成果一样进入 `成果/`：

```json
[{"id": 1, "para": 37, "action": "replace", "find": "乙方应于收到货物后九十日内付款",
  "text": "乙方应于收到货物后三十日内付款", "comment": "付款期限过长，建议缩短（理由……）"}]
```

`action` 取值：`replace`（替换）、`insert_after`（在 `find` 之后插入）、`delete`（删除）。`para` 与第 5.2 节 docx 的段号一致。

**生成方法**（lxml 直接操作 OOXML）：
1. 定位第 `para` 段，要求 `find` 在该段中**恰好出现一次**。
2. 按字符位置拆分 run，保留原来的格式属性（`w:rPr`）。
3. 被删除的部分包在 `<w:del w:id w:author="AI审查（待律师确认）" w:date>` 中，并把 `w:t` 改为 `w:delText`；新文字包在 `<w:ins>` 中。
4. 批注：没有 `comments.xml` 时新建（同时补上关系文件和内容类型登记）；在修改处加 `commentRangeStart` / `commentRangeEnd` 和批注引用。

**范围外的情况**（PRD 4.7）：以下情况不修改该条，放入"需人工修改"清单，只在审查意见表中给出建议：
- 目标段落在表格、文本框、页眉页脚中；
- `find` 跨越域代码或超链接；
- `find` 找不到或出现多次。

原文**已有修订痕迹**的文件：整份不生成修订版，提示"原文件含未处理的修订，请先接受或拒绝后再生成"。

**在本机生成**（工作台服务）。甲方提纲原本放在 395，改动原因：修订版生成不需要模型，是纯程序处理；在本机做，合同不必发往服务器，也少一个依赖 395 的环节。`redline.py` 是独立的库，将来需要放到 395（例如客户门户）时，包一层接口即可。

**验收**：G-10 的样本在 Word 和 WPS 中都能显示修订，并能逐条接受或拒绝。

### 12.3 Word 转 PDF（`office/convert.py`）

**2026-09-30 用户定（候 owner 清单 N24）**：第一版的格式互转小工具**不转换旧版 `.doc` / `.wps`**（按文件头判断），提示律师用 Word 或 WPS 另存为 docx 再来；原因是对旧版二进制文档的外链检查无法独立验证（见 14.3 ②a 和 T19 复核记录）。工作台服务导入旧版文档的做法不变（14.3 ②a：查到外链就拒绝，N17）。

归档需要把 docx、doc、wps 转成 PDF，而且结案报告要求一页排版准确。律所电脑装有 Word 或 WPS，优先调用它们；按设置 `converter` 选择，默认 `auto` 依次尝试：

| 顺序 | 程序 | 调用方式 |
|---|---|---|
| 1 | Microsoft Word | pywin32：`Dispatch("Word.Application")`，`Visible=False`、`DisplayAlerts=0`；`Documents.Open(path, ReadOnly=True, AddToRecentFiles=False)`；`ExportAsFixedFormat(out, 17)`；关闭文档，不保存 |
| 2 | WPS 文字 | pywin32：`Dispatch("KWPS.Application")`（没有再试 `WPS.Application`），接口与 Word 相同 |
| 3 | 内置 LibreOffice | 第 5.2 节的命令行方式 |

- 每次转换在单独的子进程里做，超时 120 秒即结束该进程，换下一个程序；COM 对象用完即 `Quit()`。
- 转换源文件先复制到 `工作区/临时/`，转换程序只打开副本，原件不被 Word 锁定或写入。
- 三种都失败：返回 `CONVERTER_UNAVAILABLE`，提示律师手动另存为 PDF 后放进案件文件夹。
- 返回里写明实际用了哪个程序，界面提示"结案报告请在 Word / WPS 中核对是否为一页"。
- **不依赖打印机**（2026-09-29 用户提出，开发机实测）：系统默认打印机是连不上的网络打印机时，Word / WPS 被自动化调用会弹"等待打印机连接"之类的窗口，LibreOffice 启动也可能因此变慢。转换代码不得调用任何打印接口（`PrintOut`、虚拟打印机），只用导出接口；不得修改系统默认打印机；弹窗或卡住一律由子进程超时兜底：到 120 秒结束该子进程**及其启动的 Word / WPS / soffice 进程**（只结束本次转换启动的那个进程，不动律师自己开着的 Word / WPS），再换下一个程序，不留隐藏窗口和残留进程。本节和第 5.2 节的 LibreOffice 调用同样适用。验收时要在默认打印机为连不上的网络打印机的机器上实测一次（第 16 节）。
- **留痕**：Word / WPS 作为独立进程运行，可能在 `%TEMP%`、自动恢复目录里留下临时文件，不受我方控制。验收（第 16 节 SEC-01 / SEC-11）的全盘搜索要覆盖归档转换之后的状态；如果在案件目录外搜到正文，把 `converter` 的默认值改为 `libreoffice`，Word / WPS 只作为律师在设置里自选的选项。

### 12.4 案卷归档（`archive/`）

由律所周海沺律师的归档 Skill（`docs/reference/client-skills/lawyer-archiving-1.0.0`）改写。原 Skill 让 AI 执行 `find`、`soffice`、Python 脚本，并假定 Mac 环境和固定承办律师；本版分成 AI 部分（`case-archiving` Skill）和程序部分（本节），承办律师取设置中的本机律师姓名，可在方案中改。

**归档目录**：`skills/case-archiving/catalogs/<卷类>.json`（契约 `skill/archive_catalog.schema.json`），四类：民事行政卷（附件3）、刑事卷（附件2）、常法卷（附件4）、其他非诉卷（附件5）。每项有编号、名称、是否必交、文件名关键词、对应的标准目录文件夹。"结案报告"一项标 `generated: true`：由程序生成，不参与匹配，不算缺失，AI 也不把它放进归档方案。

**匹配**（`case_archive_match`，`archive/match.py`）：
1. 跳过 `generated` 项。取材料清单，忽略：`~$` 开头的临时文件、`._` 开头的文件、名字形如"微信图片_数字""IMG_数字"的文件、加密或无法读取的材料。
2. 文件名命中某项关键词就归入该项；命中多项时，优先该项 `folders` 包含材料所在文件夹的，再取命中关键词最长的。
3. 没有命中关键词、但所在文件夹只对应一项的（如 `03一审/我方证据` 只对应"证据材料"），按文件夹归入。
4. 其余列为未匹配。

**生成**（`/api/archive/build`，`archive/build.py`），律师在归档面板确认办案结果后点击：
1. 用界面提交的 `confirmed` 方案（`result` 不能为 null）。
2. 每项材料按方案顺序取原件：PDF 直接用；docx / doc / wps 按第 12.3 节转 PDF；图片用 Pillow 转 PDF；xlsx、xls 用 LibreOffice 转 PDF。中间文件放 `工作区/临时/`，用完删除。
3. 结案报告（`generated` 项，自动加入卷宗对应编号的位置）：`skills/case-archiving/templates/结案报告模板.docx` 存在时，用 python-docx 按顺序替换其中的 `【…】` 占位符（占位符可能被拆成多个 run，先合并同一段内的 run 再替换）；不存在时用内置的临时版式生成（仿宋 12 号，一页），并在提示中写"结案报告为临时模板，待律所模板到位后替换"。转 PDF 后放在卷宗的"结案报告"一项。
4. 卷宗：用 pypdf 按编号顺序合并，缺项跳过、不插空白页，记下每项的起止页；用 reportlab 生成页码层（每页底部先画一条白色矩形遮住原有页码，再居中写"第x页 共x页"，字体 STSong-Light 10 号），逐页叠加。
5. 立卷申请书：`templates/立卷申请书模板<_卷类>.docx` 存在时按原 Skill 的规则填写（案件编号段、删除缺项行、民事行政卷保留原编号、常法卷重新连续编号、每项名称后加页码范围如 `p12-15`、表格内容仿宋 12 号不加粗）；不存在时用临时版式生成同样内容的表格。只生成 docx，提示"打印 → 手签 → 扫描为 PDF 后上传，不得代签或电子签"。
6. 发票.pdf：编号为"收费发票凭证"一项的材料单独合并一份。
7. 有必交项缺失时（`generated` 项不算），按 `references/特殊情况说明模板.md` 的模板一生成《材料缺失情况说明及承诺》docx，缺失材料逐项列出，原因处留【待填写】；`fee_settled` 为 false 时生成模板二《律师费未结清情况说明及承诺》。
8. 输出到 `成果/归档/<委托人>与<对方当事人>案件归档/`（无对方当事人时为 `<委托人>案件归档`），同名已存在时加 `-v2`；另写 `归档目录.md`（逐项材料、页码、缺失项）。登记到 `成果/索引.json`。

**模板**：律所的结案报告、立卷申请书（附件2–5）Word 原件待律所提供（编排计划的负责人待办），放入 `skills/case-archiving/templates/` 后自动使用，不改程序。

---

## 13. 小工具和内置工具

13.1、13.2 是独立的小工具（`tools/`），13.3–13.5 是在工作台里使用的内置工具。

两个小工具都是独立程序：Python 加 tkinter 界面，用 PyInstaller 打包；不连网，不调用模型。LibreOffice 和 pandoc 与客户端共用同一份安装。

### 13.1 长截图切分（F-TOOL-01）

1. 转为灰度图。对每一行计算该行像素与该行众数颜色的差值；差值 < 8 的像素占 98% 以上的行，记为"空白行"。这样可以兼容聊天界面的彩色背景。
2. 设目标段高 H（默认 2000 像素，可以调整）。在 [0.6H, H] 的范围内找连续空白行（至少 6 行），选其中最长的一段，在中间切开。最长的空白段通常就是两条消息之间的间隔。
3. 范围内找不到空白段时，在 H 处切开，下一段向上重叠 120 像素，并在结果列表中标注"此处可能切到文字"。
4. 输出按 `原名_01.png` … 命名，放在原图旁的"切分结果"文件夹；可以选择合并为 PDF（用 Pillow）；支持批量处理；原图不动。

### 13.2 格式互转（F-TOOL-02）

| 转换 | 实现 |
|---|---|
| doc / wps → docx，xls → xlsx，Word → PDF | LibreOffice headless |
| PDF → Word | 仅限文字版 PDF：pypdfium2 取文字 → 按段落组织 → pandoc 输出 docx。**只保留文字和段落，不保留版式**，界面中写明 |
| Markdown ↔ Word | pandoc |
| 图片 → PDF | Pillow |

扫描件转 Word 不在本次范围内。

### 13.3 发票整理（`engines/invoice-ledger/`、`invoice/runner.py`）

律所周海沺律师的发票 Skill（invoice-ledger-db 3.9.4）功能完整：PDF / ZIP / 图片归档、Windows 本地识别、查重、台账、报销批次和贴票包。本版**原样作为引擎**，只做以下改动，记在引擎的 `CHANGELOG.md`（版本 `3.9.4.1`）：
- 经作者同意去掉设备授权：删除 `license_gate.py`、`license_cli.py`、`license-public.json`，运行环境入口不再校验；署名保留。
- 其余代码不改。

**调用方式**：工作台服务用客户端自带的 Python 作为宿主，运行 `python engines/invoice-ledger/scripts/invoke.py <脚本> <参数>`；引擎首次运行时把自带的 `vendor/env-win_amd64.zip` 展开到 `%LOCALAPPDATA%\invoice-ledger-db\runtimes` 并复用。环境变量只传：`INVOICE_BUYER`（设置中的购买方名称）、`PYTHONUTF8=1`，以及引擎和 Python 运行必需的 `SYSTEMROOT`、`LOCALAPPDATA`、`USERPROFILE`、`TEMP`、`TMP`（第 1.3 节）；不传代理等其他变量。

**白名单动作**（契约 `api/invoice_run.schema.json`），台账目录固定为 `<日常办公文件夹>/发票台账`，任务目录固定为 `发票台账/_任务/<报销年月>`：

| 动作 | 引擎命令 | 界面按钮 |
|---|---|---|
| `env_check` | `env_check.py --deep --ocr` | 环境检查 |
| `history` | `workflow.py history --ledger … --out _任务/<period>/历史未报清单-<时间>.json` | 查看历史未报（先选报销年月） |
| `plan` | `workflow.py plan --job … --period … --channel local\|eml --history exclude\|selected [--history-numbers <文件>]` | 开始本期（先回答报销年月、历史票是否纳入） |
| `run` | `workflow.py run --job … --batch … --ledger … --src <文件夹>`（channel 为 eml 时用 `--eml`） | 导入并生成贴票包 |
| `analyze`、`import` | `workflow.py analyze\|import --job … --ledger …` | 分析对账、入账 |
| `prepare` | `workflow.py prepare --job … --ledger … --batch … [--replace]` | 生成贴票包 |
| `reprint` | `workflow.py reprint --ledger … --batch …` | 重印 |
| `cancel`、`reimburse` | `workflow.py cancel\|reimburse --ledger … --batch … [--apply]` | 取消批次、确认已报销（`--apply` 前先预览） |
| `review` | `workflow.py review --ledger … --sha256 … --reviewer … [--confirm]` | 人工核验识别结果 |
| `exclude`（2026-09-30 契约 1.3 加，T25 调研 P4） | `workflow.py exclude --job … --item <记录ID> --reason … --reviewer … --confirm` | 人工排除一项（待核、冲突、正文链接项；逐项确认，写明"排除后本期不再计入该票"；只改任务目录内的 `collection.json` 与对账表，不碰台账、不联网、不可逆） |
| `report`、`check_schema` | `invoice_db.py report\|check-schema --ledger …` | 报表、台账体检 |

- **不提供**：`--imap-host`、`--download-links`、`attach`、`channel=mcp/imap`（都需要联网）。邮箱里的发票由律师自己下载，或在邮件客户端导出为 EML 后导入。
- 引擎退出码 0 为成功，2 为"有重复、冲突、待核或部分失败"（界面标黄，提示看明细），其他为失败（`ENGINE_FAILED`）。引擎输出原样显示在面板上，不写日志；日志只记动作名、退出码、耗时。
- 同一时间只运行一个动作（引擎自己也有台账文件锁）；单个动作超时 30 分钟。
- 日常办公文件夹未设置时返回 `OFFICE_DIR_NOT_SET`；设置时按 SEC-14 的规则拒绝云同步目录。
- 发票不是案卷：台账和原票在日常办公文件夹，不进案件检索，不进 AI 上下文。

**2026-09-30 T25 调研后回写（主编排定）**：①引擎缓存路径超过 259 字符会失败（`LongPathsEnabled=0` 时 `%LOCALAPPDATA%` 长过约 59 字符即触发）：服务另传 `INVOICE_RUNTIME_CACHE=<应用数据>\ivc`（加入上面"只传"名单），T20 安装时检查该路径长度并提示；②引擎所有异常都退出 2 且输出以 `[BLOCKED]` 开头——服务见 `[BLOCKED]` 判 `ENGINE_FAILED`，不当"待核"；③`cancel` 引擎不支持预览：界面先用 `report`/`reprint` 展示批次内容再确认，服务对 `cancel` 一律带 `--apply`；④本地渠道不处理图片发票（引擎记"未选取"）：第一版界面写明"图片发票请先转成 PDF（可用小工具）"，`import --img` 不进白名单；⑤`invoke.py` 接受任意脚本路径、`run` 自带 `--download-links`、`collect` 可直接调用、子进程继承全部环境变量：服务把脚本名和参数写死、启动引擎时清空环境只传名单内变量，并断言测试；⑥缓存日常启动只核大小不核 sha256：本机信任边界内的已知风险；⑦`check_schema`、`import` 会往台账目录 `_日志\`、`运行日志\` 和 `%TEMP%\invoice-ocr-*` 写文件：列入第 14 节数据落点表；⑧引擎贴票清单写死了律所名（`reimbursement.py:86`）：用户定 N50 ③——服务在引擎生成清单后**另存一份** `贴票清单（<购买方>）.html`（把这一个固定字符串换成设置里的"发票购买方名称"；为空则不生成），原文件不动——引擎的 `check_artifacts` 会核对打印包内每个文件的哈希，原地替换会让重印与确认报销失败；界面只给新文件的打开/打印入口。这是对引擎输出的唯一一处后处理；引擎不改。契约 1.3 相应改动见 20.12。

### 13.4 刑期计算（`calc/sentence.py`，工具 `case_calc_sentence`）

纯日期计算，不调用模型。规则表写在代码里，每条带一句依据文字（返回的 `basis`），文字由责任律师核对后定稿，未核对前每条后面加"（待律师核实）"。

| 规则 | 实现 |
|---|---|
| 折抵比例 | 管制：羁押 1 日折抵 2 日；拘役、有期徒刑：1 日折抵 1 日；指定居所监视居住：管制 1 日折抵 1 日，拘役、有期徒刑 2 日折抵 1 日（不足 1 日的部分不计，写入 notes） |
| 羁押天数 | 每段按起止日含两端计算；各段重叠的部分只算一次 |
| 刑期起止 | 给了判决执行之日：起 = 执行之日，止 = 起 + 刑期 − 1 日 − 折抵天数。没给执行之日、且各段羁押首尾相接（后一段的 `from` 是前一段 `to` 的次日，如拘留转逮捕）视为连续：起 = 羁押首日，止 = 起 + 刑期 − 1 日（管制、指定居所监视居住按比例调整）；最后一段的 `to` 由律师填到计算当天。羁押有间断而没给执行之日：不算起止，notes 写"羁押期间不连续，请提供判决执行之日" |
| 刑期加法 | 按日历月加：先加年、再加月，月末日期对齐到当月最后一天（如 1 月 31 日加 1 个月为 2 月 28 日或 29 日） |
| 节点 | 管制、拘役、有期徒刑：执行满二分之一的日期（减刑后实际执行的下限、有期徒刑假释的执行期限）。折半方法：刑期为偶数个整月时按月折半（如 3 年 6 个月折半为 1 年 9 个月）；否则按天折半（起止之间的总天数除以 2，向上取整），并在 notes 注明"按天折半"；无期徒刑：不算起止，notes 写"无期徒刑的减刑、假释节点按实际执行年限计算，请律师判断" |
| 不处理 | 数罪并罚、缓刑考验期、减刑后的新刑期：写入 notes，由律师判断 |

单元测试覆盖：跨闰年、月末、多段重叠、管制和指定居所监视居住的比例、不连续羁押。

### 13.5 委托材料（`engines/retainer/`，"文件生成"胶囊）

律所周海沺律师的委托材料工具（retainer-offline 3.4.1）是一个离线网页：13 份 Word 模板（个人委托、公司委托、刑事三组，含委托合同、授权委托书、所函；风险告知已在合同内），合同第六条按固定、半风险、全风险收费自动生成；支持 Excel 逐案导入、证件识别预填、生成案件目录。**原样使用，不改网页代码。**

- **打开**：点"文件生成"胶囊 → Host 插件经 P-11 在独立窗口打开 `engines/retainer/启动.html`，同时调 `/api/retainer/driver` 的 `start`。
- **证件识别驱动**：`engines/retainer/tools/ocr-driver/driver.py --port 17801 --host 127.0.0.1`，由工作台服务用客户端的 Python 启动（依赖 RapidOCR 及其 onnxruntime、opencv，装进客户端 Python；驱动目录里自带的 `vendor/` 优先），只监听 `127.0.0.1`；窗口关闭时 `stop`。识别在本机 CPU 完成，不发往 395。原来的 `启动委托工作台.bat` 不使用。已知情况：驱动的跨域设置为允许任何来源（`Access-Control-Allow-Origin: *`），本机其他网页理论上也能调用它；因为只监听本机、只在委托材料窗口打开期间运行、只返回调用者自己上传的证件的识别结果，本版不改律所的代码，记为残余风险。
- **网络**：网页自带的内容安全策略只允许连 `127.0.0.1:17801`；窗口的独立 session 由 P-11 另设白名单、关闭拼写检查。
- **保存位置**：为了守住"原件区只能由导入新增、不覆盖"（第 4.2 节第 5 条、SEC-08），网页**不直接写案件文件夹**：P-11 的预加载脚本删除 `showDirectoryPicker`，网页按其自身逻辑改为下载单份 Word 或当前案件 ZIP（开发时实测确认这一回退；不回退时改为拦截该调用）；主进程把下载存到当前案件的 `工作区/临时/委托材料/<时间>/`。窗口关闭后，案件工作区提示"导入新生成的文件到 01委托手续"，律师确认后调 `/api/materials/import`（`target` 为 `01委托手续`，ZIP 时 `unzip: true`），同名文件改名、不覆盖。窗口标题显示当前案件名；没有打开的案件时，下载存到 `<应用数据>/临时/委托材料/`，关闭时提示先打开案件再导入。
- **默认信息**：网页的律所、律师、电话、银行账户默认值来自 `data/config.json`（现为律所某团队的信息），各律师在网页的"高级配置"里改成自己的，保存在该窗口的浏览器存储中（第 3.3 节）。
- **程序性文书模板**：`engines/retainer/procedural-templates/` 的 25 份民事程序性文书（财产保全、调查令、延期开庭等），律师可在网页的"模板管理"中作为附加文书导入使用；诉讼文书起草 Skill 不重写这些文书。

---

## 14. 打包、安装、升级

### 14.1 安装包

- 本次只出 **Windows**（Win10 / 11 x64）安装包；macOS 预留（PRD 9.4），我方插件和工作台服务按跨平台写法开发，但不做 macOS 的打包和测试。
- 用 DSH 桌面端自带的打包流程（electron-builder，Windows 为 NSIS），命令如 `pnpm run package:desktop:win:x64:unsigned`。打包前设置我方的应用 ID、产品名、图标；更新地址留空（第 3.2 节）。
- **我方组合包怎么进安装包**：桌面端的运行时是一棵打包好的依赖树（`app.asar/dsh`），启动时不运行 pnpm。做法是：
  1. 把 `lawbench-dsh` 加为 `@deepseek-ai/dsh` 的运行时依赖，使它被打进运行时（官方可选组合包就是这样打进去的）；
  2. 把它加到桌面端 profile 模板的组合包列表末尾（官方 `packages/boot/app-boot/src/profile.ts` 中 `PROFILE_TEMPLATES.web`，桌面端 `apps/desktop/src/project-manager.ts` 用它初始化 profile），记为 DSH 源码修改 P-10。
  注意：已经存在的 profile 不会被重写，所以测试机要删掉旧的 `$DSH_HOME/profiles/desktop` 再装。
- 包内包含：DSH 定制版（含我方组合包）、Python 运行时及全部依赖（构建时离线安装好，含 pywin32、pypdf、reportlab、RapidOCR 及其依赖）、LibreOffice、pandoc、tokenizer.json、内置 Skill 和 `capsules.default.json`、`engines/`（发票引擎含其运行环境压缩包约 45MB，委托材料网页和证件识别驱动）、Word 模板、第三方许可证清单。**运行时不下载任何东西**，也不执行任何包安装。
- 桌面端安装器只面向当前用户安装；管理员下发 Skill 的公共目录由我方安装步骤单独创建并设权限。
- 小工具单独打包，检测到已安装客户端时复用客户端的 LibreOffice 和 pandoc；没有安装客户端时自带一份。
- 没有代码签名证书时（PRD 待确认 #5），在操作说明中写明 Windows SmartScreen 的放行步骤。

### 14.2 升级和回退

- 程序文件在安装目录，设置在 `<应用数据>`，案件数据在案件文件夹，三者分开存放；升级只替换安装目录。
- `case.db` 的结构升级见第 4.1 节（升级前自动备份）；回退到旧版本时，使用备份的 `case.db.bak-<版本>`。
- 每个版本的安装包都保留，用于回退。

### 14.3 只连两台服务器（SEC-03）

**2026-09-30 用户定（候 owner 清单 N19）**：工作台服务导入旧版 `.doc` / `.wps` 维持 ②a"查到外链就拒绝"；对二进制文档做模式匹配可能漏判的两种写法（碎片表拆分、图形属性引用外链）记为**已知残留风险**，不在第一版补；上线前由用户决定要不要在律师电脑的系统防火墙里禁止转换程序（LibreOffice、pandoc）联网（T22）。

所有发出网络请求的地方都要做地址白名单检查（只允许设置中 6000D、395 的所内和所外地址，以及 `127.0.0.1`，第 15 节），并且**不自动跟随重定向**（收到 3xx 视为错误），防止跳转到白名单外的地址：

| 请求来源 | 怎么限制 |
|---|---|
| 工作台服务（Python） | 统一的 httpx 客户端，发送前检查目标主机；`follow_redirects=False` |
| DSH Desktop Host（Node 进程，含 pi-ai 模型适配器） | DSH 已有一个全局的 undici dispatcher（官方 `packages/util/http-proxy/src/install.ts`，Host 启动时安装，所有 `fetch` 都经过它），在其中加地址白名单：目标不在白名单就直接拒绝连接，重定向同样检查（第 3.2 节 P-7）。另外包装 `http` / `https` 的 `request`，覆盖不走 `fetch` 的代码。`webRequest` 管不到这个进程，不能依赖它 |
| Electron 渲染进程（界面） | `session.webRequest` 拦截白名单以外的请求；界面只加载本地资源 |
| 其他子进程（LibreOffice、pandoc、Word / WPS 转换） | **会按文档里的链接去取图，必须关掉**（2026-09-29 T19 复核实测）：pandoc 处理 Markdown 里的远程图片、LibreOffice 处理 docx 里以外部链接引用的图片时，会向链接指向的地址发请求；对方提交的文档里埋一个链接，律师一转换或一导入就把本机地址和打开时间发了出去。做法：①pandoc 每次调用都带 `--sandbox`（同时也不读 `file://` 和相对路径的本机图片）；②LibreOffice 每次用的独立用户配置目录里，启动前写入 `user\registrymodifications.xcu`，把 `/org.openoffice.Office.Common/Security/Scripting` 下的 `BlockUntrustedRefererLinks` 设为 `true`；②a 旧版二进制格式（`.doc`、`.wps`）里的外链图片，上面的设置拦不住（2026-09-29 T19 返修实测：链接不更新、代理指向连不上的地址都无效），所以交给 LibreOffice 之前先检查文件里有没有指向 `http://`、`https://`、`\\` 开头地址的图片链接，有就**拒绝转换**并提示"文档里有指向外部地址的图片，为避免联网没有转换；请在 Word 或 WPS 里断开链接（或另存为 docx）后再试"。检查方法（2026-09-29 T19 第二轮复核后）：只在域指令范围内（域开始符 0x13 到分隔符 0x14 或结束符 0x15 之间）找链接类域名（`INCLUDEPICTURE`、`INCLUDETEXT`、`LINK`、`IMPORT`、`DDE`、`DDEAUTO`），域名之后、同一段域指令之内**任意位置**出现外部地址前缀就算，不管开关写在地址前面还是后面；UTF-16LE 和单字节两种解码都查；另查 Data 流里单字节存放的地址前缀。正文里的普通网址文字和超链接不触发。**已知残留风险**：这是对二进制格式做模式匹配，域代码被拆开存放、用图形属性引用外链图片等写法可能漏判（未造出样本，未证实能联网）；记在候 owner 清单；②b `xlsx`、`xlsm`、`fods` 交给 LibreOffice 之前（材料解析里公式没有缓存值要重算时），先查压缩包里的关系文件（`xl/**/_rels/*.rels`）有没有 `TargetMode="External"` 的图片或对象关系，有就不交给 LibreOffice，该材料按"公式没有缓存值"处理：没有缓存值的单元格在材料文本里写公式本身（契约 1.1 的 `note` 枚举里没有对应取值，`note` 留空；要不要加取值见候 owner 清单 N21）——实测 Calc 导入时会去取这类外链图片，上面的设置拦不住；③Word / WPS 自动化打开文档时不更新链接（`Documents.Open` 的 `UpdateLinks` 相关设置关掉，T23 实测确认）。适用于所有调用这三类程序的地方：材料导入（第 5.2 节）、导出（第 12.1 节）、Word 转 PDF（第 12.3 节）、小工具（第 13.2 节）。每处都要有测试：文档里放一个指向 `127.0.0.1` 本机监听的图片链接，转换后监听收到 0 个请求 |
| 发票引擎子进程 | 引擎里有联网代码（IMAP、正文链接下载），工作台只开放第 13.3 节的白名单动作，参数由服务端拼装、不接受界面传入的任意参数；验收时抓包覆盖全部发票动作 |
| 证件识别驱动 | 只监听 `127.0.0.1:17801`，模型随包，不联网 |
| 委托材料窗口 | 网页自带内容安全策略只允许 `127.0.0.1:17801`（T0 在 Windows 上核对 `启动.html`）；窗口的独立 session 另设白名单并关闭拼写检查（P-11） |

另外可选：安装时加一条 Windows 防火墙出站规则，只允许本程序连接两台服务器的所内、所外地址（作为第二道保险，不替代上面的检查）。

- DSH 的其他外连来源按第 3.2 节处理。
- 验收（G-11）：在断网的机器上安装和运行；抓包 30 分钟，覆盖导入、识别、生成 wiki、对话、导出等全部流程，只能看到两台服务器的地址。

---

## 15. 网络

- 两台服务器都在律所局域网内，所内直接访问。
- **所外访问**：按甲方《EasyTier 律所工作台远程接入方案 V2》（自建共享节点、`--secure-mode`、私有模式、按律师分发凭据、ACL 默认拒绝）。原方案中的 WireGuard 不再采用。**分工**（2026-09-28 定）：共享节点用的云服务器由律所提供；两台服务器侧的配置由我方完成（编排计划工单 T27）。
- 我方要做的：
  1. 首次配置和设置中的 6000D、395 地址可以填 EasyTier 虚拟网地址，地址白名单按设置中的实际地址生效（第 14.3 节）；"测试连接"对虚拟网地址同样适用。
  2. 在 6000D（Linux）和 395（Windows）上按方案 V2 安装 EasyTier 并加入律所虚拟网，经虚拟网只放行 **6000D 的 8000 端口和 395 的 9000 端口**（`--tcp-whitelist`；方案原文只放行了模型端口，这里补上 9000）。**不使用子网代理（`-n`）**：2026-09-29 实测经子网代理进来的访问不受白名单限制，与方案 V2 一致已去掉。所外因此访问虚拟 IP，所内访问局域网地址，客户端自动切换（下面"地址选择"）。
  3. 两台服务器的防火墙：6000D 入站只放行虚拟网段和局域网到 8000；395 的 Windows 防火墙入站规则加上虚拟网段（第 6.1 节）。
  4. 写一个检查脚本，在律所外的网络上用一台律师电脑实测：8000、9000 可达，其他端口不可达，客户端"测试连接"通过。
  5. 各项参数填进甲方方案的部署参数台账（密钥和凭据只写存放位置，不写明文）。
- 局域网和虚拟网内都使用 HTTP（与 6000D 网关现状一致）；所外流量由 EasyTier 加密。
- **现状**（2026-09-29 实测，详见 `deploy/easytier/README.md`）：6000D 虚拟 IP `10.126.126.1`，395 虚拟 IP `10.126.126.3`，阿里云中转节点由律所提供；所外检查全部通过（`docs/plan/evidence/T27/remote-check.txt`）。上线前还要换正式密钥并按方案加固中转节点。

**地址选择（所内 / 所外自动切换）**：设置中每台服务器有两个地址：所内地址（`llm_base_url`、`prep_base_url`，局域网）和所外地址（`llm_alt_base_url`、`prep_alt_base_url`，虚拟 IP），首次配置页两个都填，默认值分别为 `http://192.168.8.77:8000/v1`、`http://192.168.8.124:9000`、`http://10.126.126.1:8000/v1`、`http://10.126.126.3:9000`。
- 工作台服务的统一 HTTP 客户端（`net.py`）在启动时、网络变化时（Windows 网络状态变化通知）、以及请求出现连接错误时探测：先试所内地址（6000D 请求 `/v1/models`，395 请求 `/health`，各 1.5 秒超时），不通再试所外地址；选中的结果缓存 60 秒。两者都不通时报 `SERVER_UNREACHABLE`。
- 识别（395）和流水线（6000D）请求直接用选中的地址。
- **Agent 的模型请求**由 DSH 的适配器发出，而 DSH 的地址写在组合包配置里、运行时改不了，所以改为指向工作台服务的**本机转发**：工作台服务另开一个只监听 `127.0.0.1` 的固定端口（默认 18765；第一版由 Host 插件启动服务时用 `--forward-port` 或 `LB_FORWARD_PORT` 指定，设置页不提供修改，2026-09-29 用户定；端口绑定失败时服务进程以非零码退出，由 Host 按第 1.3 节处理），把 `/v1/*` 原样转发到当前选中的 6000D 地址（流式透传，请求头里的律师 Key 原样带过去，转发本身不记录请求和回答内容，只记元数据）。这个端口不需要启动令牌（DSH 的适配器加不了动态请求头），但只接受 `/v1/chat/completions` 和 `/v1/models` 两个路径，其余返回 404；没有律师 Key 的请求 6000D 会拒绝。转发端口只接受 `Host` 为 `127.0.0.1:<端口>` 或 `localhost:<端口>` 的请求，带 `Origin` 请求头的请求（来自网页）一律 404、不发往上游。
- "测试连接"返回实际连通的是所内还是所外地址（契约 `api/connection_test` 的 `route`），界面显示"已连接（所内）/（所外）"。
- 地址白名单（第 14.3 节）同时包含两组地址。

---

## 16. 保密要求的实现对照

| 编号 | 实现位置 | 验证方法 |
|---|---|---|
| SEC-01 | 第 4.1 节目录；第 3.3 节 DSH 数据落点；第 4.5 节日志不含正文；拖入的文件复制进案件文件夹、不进附件目录（P-5） | 用测试案卷完整走一遍（含拖入导入、归档），在案件目录以外全盘搜索案卷中的特征字符串；发票台账在日常办公文件夹，不属于案卷 |
| SEC-02 | D7：外发操作只在界面接口中提供，调用前弹确认框 | 检查 AI 工具列表；抓包比对发出的请求与确认框中显示的内容 |
| SEC-03 | 第 14.3 节；第 3.2 节 | G-11 抓包 |
| SEC-04 | 没有向量检索组件；服务器不建立任何索引 | 代码审查；检查服务器的磁盘 |
| SEC-05 | D3、D4；第 4.2 节路径闸门 | 自动测试：`../`、绝对路径、符号链接、junction、大小写变体、超长名字 |
| SEC-06 | 第 6.3 节；第 8.1 节 Key 存 Windows 凭据管理器 | 用无 Key、停用的 Key 分别调用两台服务器；换 Windows 账号读不到 Key |
| SEC-07 | 第 3.1 节（律师工作台 preset 不挂 agent-instructions，官方 preset 全部关掉，Skill 不扫默认目录）；第 10.1 节 | 测试案件内放 AGENTS.md、`.dsh/skills/<恶意 Skill>`、含越权指令的材料，确认都不起作用 |
| SEC-08 | 已有原件没有改写接口；原件区只有律师触发的导入（只新增、不覆盖）和标准目录建文件夹（第 4.2 节）；`材料/index.json` 记录哈希；归档、Word 转换只读原件副本 | 验收前后比对原件哈希（含导入同名文件、归档之后） |
| SEC-09 | 甲方网关现状（不记正文）；第 8.6 节 | 检查网关的 `usage.db` 和日志 |
| SEC-10 | 第 14.3 节地址白名单；代码中不存在其他模型地址 | 代码审查 + 抓包 |
| SEC-11 | 第 4.5 节日志；LibreOffice 配置目录放在案件临时目录；临时文件都在 `工作区/临时/` | 同 SEC-01 的全盘搜索 |
| SEC-12 | 第 6.2 节全程在内存中处理、启动清理；第 6.1 节 BitLocker、关闭休眠；第 6.6 节日志 | 第 6.2 节的全盘搜索；检查日志中是否有测试文本 |
| SEC-13 | 第 6.1 节 Windows 防火墙；第 8.6 节 vLLM 只监听本机；第 15 节（所外经 EasyTier，服务器侧由我方配置） | 从外网和律所局域网分别扫描端口 |
| SEC-14 | 第 4.2 节云同步目录检测 | 在 OneDrive 同步目录、名字含"坚果云"的目录下各建一个案件，打开时都被拒绝 |

---

## 17. 待验证项对设计的影响

| # | 主方案 | 测不通时 |
|---|---|---|
| G-1 DSH 桌面版 | **已基本确定**：用官方桌面端（D1）。剩余：第 3.2 节的对外连接全部去掉后能正常运行 | 保留 DSH 的 Web 版（`dsh web`，本机浏览器打开），外面包一个最小的 Electron 壳 |
| G-2 案件隔离 | 律师工作台 preset 不挂文件、命令、指令文件插件，官方 preset 全部关掉，加上白名单和路径闸门（D3、D4），不依赖 DSH 沙箱 | 抓包发现有其他工具出现在请求里时，找到挂载它的配置行关掉；关不掉的，由 `tools/pre-execute` 拦截执行 |
| G-3 工具接入 | 我方 Agent 插件注册 `case_*`，经 HTTP 调用常驻的工作台服务（第 1.2 节）；本地试验已验证 DSH 插件注册工具可行 | 插件每次调用时启动一个 Python 子进程（不常驻，慢但简单） |
| G-4 数据落点 | 第 3.3 节逐项处理；会话记录按案件存储（源码已确认可行） | 关闭 DSH 的会话持久化，由工作台服务把对话记录另存到案件目录 |
| G-5 395 OCR | 在 Windows 上用 llama.cpp（Vulkan）跑通视觉模型，定下模型、并发数 N 和"看不清"的标注方式 | 试 ROCm for Windows；仍不行则 6000D 接管识别（第 7.4 节） |
| G-6 395 小模型 | Windows 上用 llama.cpp（Vulkan）跑 9B，客户端逐条核对 | 由 27B 完成 |
| G-7 模型能力 | 思考分四档 | 只保留开和关两档 |
| G-8 原文引用 | 第 5.2、5.3 节的位置规则 | 调整页面类型判断的阈值；Word 表格改为按行编段 |
| G-9 中文检索 | trigram + 短词逐条扫描 + 查询扩展 | 增加 bigram 辅助索引 |
| G-10 修订版 | 第 12.2 节 | 缩小范围到只做"替换" |
| G-11 离线安装 | 第 14 节 | 逐个找出并去掉联网的来源 |

---

## 18. 与 PRD 的对应

第一版 Spec 列出的 14 条 PRD 变更已全部写入 PRD 第三版（DSH 官方桌面端、插件不用 MCP、原件不复制、修订版本机生成、PDF 本机拆页、预算区分 Agent 和流水线、组件表、395 的 Key 和 `/admin`、PDF 转 Word 只保留文字、395 为 Windows、识别的各种情况、通知不带案件名、界面布局）。另外本版按以下决定同步修改：

1. 本次只交付 Windows 客户端，macOS 预留（PRD 1.1、9.4）。
2. Key 存 Windows 凭据管理器（PRD F-ACC-01a，本文 D9、第 8.1 节）。
3. 案件文件夹不得位于云同步目录（PRD SEC-14，本文第 4.2 节）。
4. 五个入口和 Skill 按《五个业务能力编排》（当时 PRD 第三版 6.3；第三版起改为胶囊，见第 8 条）。
5. 案件 wiki 走流水线，其余 Skill 走 Agent（本文 D6）。
6. 出处统一为 `〔材料名 位置〕`（本文第 9.3、20.2 节；Skill 的共用规则已同步）。
7. 395 的 9B 只用于 wiki 生成中的字段抽取和分类，取消"按卷提取目录"（PRD F-ENT-04，本文第 6.4、9.1 节）。

第三版按 2026-09-28 甲方需求变更同步修改（对应 PRD 第四版）：

8. 首页两级胶囊替代五个入口（PRD 6.3，本文 D11、第 10.3 节、U-4、U-11）。
9. 聊天附件改为拖入即导入，"+"按钮去掉（PRD F-MAT-02a、7.9，本文 D13、P-5、第 5.1 节、U-12）。
10. 新增诉讼文书起草、刑期计算、招投标、案卷归档（PRD 6.3、F-ARC-*，本文第 10.2、12.4、13.4 节）。
11. 接入发票整理、委托材料两个现成工具（PRD F-TOOL-03、F-TOOL-04，本文 D12、第 13.3、13.5 节）。
12. Word 转 PDF 优先用本机 Word / WPS（本文第 12.3 节）。
13. 所外访问改为 EasyTier：云服务器由律所提供，两台服务器侧由我方配置，不再做 WireGuard（PRD 4.7、8、SEC-13，本文第 15 节）。

---

## 19. 实施顺序

先打通一条最细的完整链路，再逐块做全。本节是方向；具体工单、执行者、依赖和验收标准由编排计划（`/orch-plan` 产出的三件套）给出，工单按本节顺序拆，并以第 20 节契约为输入。

**第一阶段：细链路**。目标是"一个案件、两份材料（一份文字版 PDF、一份扫描页）、一次识别、一次分析、一次导出"从头到尾跑通，每个环节只做最简单的版本：

| 步 | 内容 | 验证 |
|---|---|---|
| 0 | 契约落地：`contracts/` 放进仓库，`check_examples.py` 通过；Python 和 TypeScript 两边的校验工具接好（第 20 节） | 自检脚本退出码 0 |
| 1 | 从官方仓库拉取 DSH（固定提交），桌面端能在开发机跑起来；写组合包的配置补丁：关掉官方 preset 和联网、遥测等插件，新增律师工作台 preset，律所模型路由（第 3.1、8.1 节） | 第 3.1 节的验证项；抓请求核对思考档位 |
| 2 | 我方组合包骨架（Agent、Host、凭据、界面四个插件的空壳）；工作台服务骨架（Host 插件启动看护、`/core/*`、`case_id` / `task_id` 绑定、路径闸门）（第 1.2、1.3、4.2、4.3 节） | `case_list_materials`、`case_read_material` 在会话里能用；闸门自动测试；越权植入测试；`/core/*` 的请求和返回通过契约校验 |
| 3 | 只做 PDF 的解析（文字页 + 需识别页判断）和最简检索 | 两份材料能导入、能搜到 |
| 4 | 395 最小服务（`/health`、`/v1/ocr/page`，Windows 服务）和客户端识别队列 | 扫描页识别完成，结果合并进材料文本；中途退出再打开能接着做 |
| 5 | 一个 Agent 任务：用已写好的 `criminal-reading-notes` Skill；上下文注入、预算、程序保存进度和结果清单 | 草稿里的出处能点回原文；取消后有草稿；`case_save_draft` 返回通过契约校验 |
| 6 | 确认保存并导出 Word（pandoc + 模板） | 成果目录里有 docx，索引有记录 |

**第二阶段：逐块做全**：

| 步 | 内容 | 验证 |
|---|---|---|
| 7 | 会话记录按案件存储；第 3.3 节其余数据落点；第 14.3 节网络白名单 | 全盘搜索测试案卷特征字符串；抓包 |
| 8 | 全部格式的解析、完整检索（第 5、11 节） | G-8、G-9 验证集 |
| 9 | 出处核对库、流水线框架、案件 wiki 流水线（第 9 节） | 大卷宗对照标准答案打分，A–E 类问题为 0 |
| 10 | 395 完整功能：9B 抽取、去水印、取消、`/admin`（第 6 节） | G-5、G-6；取消测试 |
| 11 | 界面：首次配置、首页、案件工作区面板、原文查看；去掉对外连接和无关入口（第 3.2、3.4 节） | G-11 抓包 |
| 12 | 修订版（第 12.2 节）；首页胶囊和胶囊管理（第 10.3 节、U-4、U-11）；拖入导入（第 5.1 节、P-5、U-12）；14 个胶囊的 18 个 Skill 逐个在链路中跑通 | G-10；各 Skill 测试集（律所样本到位前用虚构样本） |
| 12a | Word / PDF 转换（第 12.3 节）、案卷归档（第 12.4 节）、刑期计算（第 13.4 节） | 归档：虚构案件生成三个文件，页码和立卷申请书页码范围一致；刑期计算单元测试 |
| 12b | 发票整理面板和引擎调用（第 13.3 节）、委托材料窗口和证件识别驱动（第 13.5 节） | 虚构发票走完一期；委托材料生成到案件的 `01委托手续`；两项都抓包 |
| 13 | 小工具（第 13.1、13.2 节）；打包（第 14 节） | 断网安装；Windows 10、Windows 11 各装一遍 |

**贯穿两个阶段的测试样本**：律所材料暂时拿不到，由一张单独的工单造虚构测试案卷，放在仓库 `tests/fixtures/`：刑事卷宗（文字版 PDF + 扫描页 + 图片）、民事借贷案（docx 含修订痕迹、银行流水 xlsx、csv）、一份合同 docx（含表格、页眉页脚，用于修订版的范围外测试）、G-9 检索验证集、越权植入材料（AGENTS.md、`.dsh/skills/`、"忽略以上要求"文字）。各步骤的验收都用这套样本；wiki 测试的大卷宗（`D:\pycharm\test\wiki`）作为流水线的对照样本。

---

## 20. 契约

本节规定模块之间约定好、谁都不能单方面改的接口和数据格式。**正文只写规则，字段以 `contracts/` 目录下的文件为准**；正文其他章节中出现的接口和格式与这里不一致时，以这里和 `contracts/` 为准。

### 20.1 通用约定

- **写法**：JSON Schema Draft 2020-12。每个文件的 `$id` 以 `lawbench://contracts/` 开头，引用一律写完整 `$id`。接口类契约在同一个文件的 `$defs` 下分 `request` / `response`（或 `args` / `result`）；落盘文件的契约就是整个文件本身。
- **版本**：整套契约一个版本号，写在 `contracts/VERSION`（当前 `1.1`）。工作台服务的 `/health` 和 395 的 `/health` 都返回 `contract_version`；Host 插件启动工作台服务后先比对版本，不一致就提示"组件版本不一致，请重新安装"，不继续。落盘的 JSON 文件带 `"v": 1`，读到不认识的 `v` 时只读、不写。
- **改契约的规矩**：先改 `contracts/`（`*.schema.json` 由 `contracts/_build/gen_schemas.py` 生成，改契约就改这个脚本再运行，不手改生成的文件；样例由 `_build/gen_examples.py` 生成），再升 `VERSION`，再在本节末尾"变更记录"加一行，最后才改代码。开发工单不得在代码里私自增减字段。
- **本机接口的返回体**（`/core/*`、`/api/*`）：成功 `{"ok": true, "value": …}`；失败 `{"ok": false, "error": {"code": …, "message": …}}`。业务错误一律 HTTP 200；缺少或错误的启动令牌返回 HTTP 401（无返回体）；服务内部异常返回 HTTP 500，返回体仍按失败格式，`code` 为 `INTERNAL`。
- **错误码**（`common.schema.json#/$defs/error_code`）和给律师看的提示：

| code | 什么时候 | message（中文，不含材料名、检索词、正文） |
|---|---|---|
| `INVALID_ARGUMENT` | 参数不符合契约 | 请求参数有误 |
| `OUT_OF_CASE` | 路径闸门拒绝 | 超出当前案件范围 |
| `CASE_NOT_FOUND` | case_id 不在注册表，或会话 cwd 不是已登记案件 | 找不到该案件，请重新打开 |
| `CASE_ROOT_IS_LINK` | 案件根目录是链接或 junction | 请直接选择实际文件夹 |
| `CASE_IN_SYNC_FOLDER` | 案件在云同步目录（SEC-14） | 该文件夹在云同步目录中，请移到本机普通文件夹后再打开 |
| `MATERIAL_NOT_FOUND` | 材料名不存在 | 没有这份材料，请先查看材料清单 |
| `MATERIAL_NOT_READY` | 材料未解析完、待识别或失败 | 这份材料还不能读取（待识别或处理失败） |
| `TASK_NOT_FOUND` | task_id / job_id 不存在 | 找不到该任务 |
| `INPUT_CHANGED` | 选用的输入在选用后被修改（sha256 不一致） | 选用的材料已被修改，请复核后重新选择 |
| `BUDGET_EXCEEDED` | 超出任务预算 | 已达到本次任务的上限，已保存草稿 |
| `SERVER_UNREACHABLE` | 连不上 6000D 或 395 | 无法连接服务器，请检查网络 |
| `KEY_INVALID` | 401 / 403 | Key 无效或已停用，请联系管理员 |
| `SERVER_BUSY` | 6000D 排队超时（503） | 服务器繁忙，排队已超过 5 分钟，请稍后再试 |
| `CONTEXT_TOO_LONG` | 超出上下文 | 内容超出模型上限，请缩小范围或调大窗口 |
| `OUTPUT_TRUNCATED` | `finish_reason == "length"` | 输出达到上限，已保存为草稿，可调大"最大生成量"后继续 |
| `TIMEOUT` | 单次请求超过 1200 秒 | 本次生成时间过长，已停止并保存草稿 |
| `HOST_NOT_ALLOWED` | 目标地址不在白名单 | 不允许连接该地址 |
| `PREP_UNAVAILABLE` | 395 不可用 | 395 暂时不可用，恢复后会自动继续 |
| `CANCELLED` | 已取消 | 已取消 |
| `SERVICE_UNAVAILABLE` | 工作台服务未启动（由插件返回） | 工作台服务未启动，请稍后重试 |
| `INTERNAL` | 其他 | 内部错误，请重试；多次出现请联系技术支持 |
| `OFFICE_DIR_NOT_SET` | 没有设置日常办公文件夹就用发票整理 | 请先在设置中指定日常办公文件夹 |
| `CONVERTER_UNAVAILABLE` | Word、WPS、LibreOffice 都转换失败 | 无法把文件转成 PDF，请在 Word 或 WPS 中另存为 PDF 后放入案件文件夹 |
| `TEMPLATE_MISSING` | 需要的模板文件缺失且没有临时版式 | 缺少模板文件，请联系管理员 |
| `ENGINE_FAILED` | 发票引擎退出码不是 0 或 2，或超时 | 发票整理未完成，请查看下方的输出信息 |
| `PLAN_NOT_CONFIRMED` | 归档方案的办案结果为空 | 请先确认办案结果 |

- **编号**（`common.schema.json`）：`case_id` 为 UUID v4；`material_id` 为 `M` + 4 位序号；`task_id` 为 `T-`（Agent）或 `P-`（流水线）+ `YYYYMMDDHHMMSS` + `-` + 4 位小写十六进制；`job_id` 为 `J-` + 同样格式；wiki 事实 `F` + 4 位、wiki 建议 `S` + 4 位。
- **时间**：ISO 8601 带时区（如 `2026-09-28T09:30:00+08:00`）。
- **路径**：契约中的路径一律是相对案件根目录的路径，分隔符用 `/`，不以 `/` 开头、不含 `..`；绝对路径（`common.schema.json#/$defs/abs_path`）只出现在界面与工作台服务之间：`cases.json` 的 `root`、`/api/case/open` 的 `path`、`/api/materials/import` 的源路径、发票整理的源文件夹和输出文件，AI 工具里没有绝对路径。

### 20.2 出处和材料名

- **出处文本**（AI 和律师看到的写法）：`〔材料名 位置〕`，严格写法为 `common.schema.json#/$defs/citation_text` 的正则。位置：`第N页`、`第N-M页`、`第N段`、`第N-M段`、`第N行`、`第N-M行`、`工作表名!B12`、`工作表名!B12:D12`。同一括号内多处用顿号分隔，每处都写材料名。固定写法 `〔未找到依据〕`、`〔推断〕`。
- **结构化出处**（程序记录用，`$defs/citation`）：材料编号 + 原件 sha256 + 位置对象（`$defs/loc`）。核对程序把出处文本解析成结构化出处，写入 `result.json` 的 `citations`。
- **括号的分工**：`〔〕` 只用于出处；`【第N页】` 等位置标记只出现在材料文本里；草稿中的 `【】` 只用于占位和标签（如 `【待补充：…】`、`【待确认我方立场】`、`【律师提供】`），形如 `【材料名 第N页】` 的写法按 E 类出处格式错误处理。
- **材料名唯一规则**：① 原件文件名去掉扩展名；② 案件内重复时，改用去掉扩展名的相对路径（如 `证据/借条`）；③ 仍重复时用带扩展名的相对路径（如 `证据/借条.pdf`）。材料名中的空格和顿号替换为下划线。材料名在导入时确定，写入 `index.json`；新材料导致重名时，已有材料的名字也按规则改长，并提示"材料名有变化"。
- 详细格式见 `contracts/formats.md` 第 2、3 节。Skill 的共用规则（`skills/_shared/共用规则.md`）与本节一致。

### 20.3 Agent 插件 → 工作台服务（`contracts/core/`）

请求头 `Authorization: Bearer <LB_TOKEN>`；只监听 `127.0.0.1`。

| 命令 | 契约文件 | 调用时机 | 要点 |
|---|---|---|---|
| `POST /core/task/begin` | `task_begin.schema.json` | `agent/pre-step` 每轮第一步 | 由 `cwd` 查注册表得到案件；取该会话待执行的任务单，没有则按"自由对话"默认值新建；返回参数和预算 |
| `POST /core/context` | `context.schema.json` | 紧接上一步 | 返回 L0、L1 文本，以及没放进 L1 的输入目录 |
| `POST /core/tool` | `tool.schema.json` | 每次 `case_*` 工具执行 | `args` 和 `value` 的结构见 20.4；服务端按工具契约校验 `args`，不合格返回 `INVALID_ARGUMENT` |
| `POST /core/progress` | `progress.schema.json` | `session/event` 收到 `assistant/message` | 覆盖写 `进行中.md`，更新用量 |
| `POST /core/task/end` | `task_end.schema.json` | `turn/end` | 写 `result.json` 最终状态；返回写入的状态 |
| `GET /health` | — | Host 插件每 5 秒 | `{"status":"ok","contract_version":"1.1"}`，不需要令牌 |

### 20.4 AI 工具（`contracts/tools/`）

**2026-09-30 T7 合并时回写**：DSH 工具定义的 `output.schema` 用宽松写法 `{type: object}`，结果由我方插件按契约 `/result` 校验，失败抛错并把中文 `message` 给模型；参数展开 `` 后逐字来自契约 `/args`；`render` 输出 JSON 文本。

11 个工具，每个文件的 `$defs/args` 直接用作 DSH `ToolDefinition.parameters`，`$defs/result` 是 `/core/tool` 成功时 `value` 的结构。Skill 正文里引用的返回字段（`has_more`、`next_start`、`citation_check.problems`、`not_fully_read` 等）必须和这里一致，`build_skills.py` 校验工具名，契约自检校验 Skill 头部。

| 工具 | 契约文件 | 关键字段 |
|---|---|---|
| `case_list_materials` | `case_list_materials.schema.json` | `materials[]`（材料名、编号、类型、状态、位置单位和数量、是否识别所得、失败原因） |
| `case_read_material` | `case_read_material.schema.json` | 参数 `name`、`start`、`max_chars`；返回 `start`、`end`、`text`、`has_more`、`next_start` |
| `case_search` | `case_search.schema.json` | `hits[]`，每条带现成的出处文本 `citation` |
| `case_read_input` | `case_read_input.schema.json` | 按行分段读前序成果 |
| `case_read_wiki` | `case_read_wiki.schema.json` | 分节枚举；`材料摘要` 需给材料名；`stale` |
| `case_save_draft` | `case_save_draft.schema.json` | `path`、`version`、`citation_check{passed, problems[], stats}`、`coverage`、`not_fully_read` |
| `case_suggest_wiki` | `case_suggest_wiki.schema.json` | 字段枚举；`source` 必须是合格的出处文本 |
| `case_save_edit_list` | `case_save_edit_list.schema.json` | 修改条目 `edit_item`；返回 `out_of_scope` |
| `case_calc_sentence` | `case_calc_sentence.schema.json` | 刑种枚举、羁押期间数组；返回 `start`、`end`、`milestones`、`basis`、`notes` |
| `case_archive_match` | `case_archive_match.schema.json` | 卷类枚举；返回逐项 `matched`、`unmatched`、`ignored` |
| `case_save_archive_plan` | `case_save_archive_plan.schema.json` | 参数即归档方案（`$defs/plan`，`/api/archive/build` 复用）；`result` 未经律师确认时为 null |

### 20.5 界面 → 工作台服务（`contracts/api/`）

界面插件 → `ctx.remote.lawbench.<方法>()` → Host 插件 → 工作台服务 `/api/*`。每个接口一个文件，`$defs/request` 对 GET 接口表示查询参数。25 个接口见第 4.3 节表格，文件名与接口一一对应：`case_open`、`case_recent`、`materials_scan`、`materials_import`、`materials_list`、`ocr_submit`、`ocr_list`、`ocr_cancel`、`task_create`、`pipeline_run`、`pipeline_status`、`pipeline_cancel`、`tasks_list`、`redline`、`wiki_suggestions`、`outputs_confirm`、`source`、`search`、`settings`、`connection_test`、`capsules`、`capsules_reset`、`archive_build`、`invoice_run`、`retainer_driver`。Host 插件的 `@Remote` 方法名与文件名相同（改成驼峰）。

### 20.6 工作台服务 → 395（`contracts/prep395/`）

| 接口 | 契约文件 | 要点 |
|---|---|---|
| `GET /health` | `health.schema.json` | 不需要 Key |
| `POST /v1/ocr/page` | `ocr_page.schema.json` | 请求体是图片原始字节，选项在查询参数（`$defs/query`）；返回 `$defs/response` |
| `POST /v1/extract` | `extract.schema.json` | `fields` 和 `classify` 两种任务 |

错误体 `$defs/error`：`{"error": {"code", "message"}}`。HTTP 状态与 code 对应：400 `BAD_IMAGE` / `BAD_REQUEST`，401 `KEY_INVALID`，413 `TOO_LARGE`，503 `QUEUE_FULL`（带 `Retry-After`）/ `KEY_CHECK_UNAVAILABLE`，504 `TIMEOUT`，500 `INTERNAL`。客户端按第 7.3 节处理。

### 20.7 工作台服务、DSH → 6000D

6000D 网关是甲方已有的 OpenAI 兼容接口，不由我方定义，不写 JSON Schema。我方依赖的部分如下，换网关或升级时逐项核对：

- 请求：`POST /v1/chat/completions`，字段 `model`（固定 `qwen38-27b`）、`messages`、`stream: true`、`max_tokens`、`temperature`、`chat_template_kwargs.enable_thinking`、`chat_template_kwargs.reasoning_effort`；请求头 `Authorization: Bearer <律师 Key>`、`X-Session-Id`（流水线）。
- 响应：流式 `choices[0].delta`、`finish_reason`；响应头 `X-Queue-Wait-Ms`。
- 错误到错误码的映射：第 8.3 节的表格，对应 20.1 的 `SERVER_UNREACHABLE`、`KEY_INVALID`、`SERVER_BUSY`、`CONTEXT_TOO_LONG`、`OUTPUT_TRUNCATED`、`TIMEOUT`。
- Key 校验（395 使用）：`POST /v1/chat/completions`，`max_tokens: 1`，返回 200 视为有效（第 6.3 节；`/v1/models` 不校验 Key，已实测）。

### 20.8 落盘文件（`contracts/files/`、`contracts/case_db.sql`、`contracts/formats.md`）

| 文件 | 契约 | 谁写 | 谁读 |
|---|---|---|---|
| `工作区/材料/index.json` | `files/material_index.schema.json` | 导入 | 工具、检索、识别队列、界面 |
| `工作区/材料/文本/*.md` | `formats.md` 第 2 节 | 导入、识别合并 | `case_read_material`、检索、流水线 |
| `工作区/case.db` | `case_db.sql` | 案件、识别队列、检索 | 同左 |
| `工作区/任务/<ID>/task.json` | `files/task.schema.json` | `/api/task`、`/core/task/begin`、流水线 | 插件（经 `/core`）、上下文 |
| `工作区/任务/<ID>/reads.json` | `files/reads.schema.json` | `case_read_material` | 覆盖清单计算 |
| `工作区/任务/<ID>/result.json` | `files/result.schema.json` | `/core/progress`、`/core/task/end`、`case_save_draft`、流水线 | 界面成果区 |
| `工作区/任务/<ID>/草稿/*.md` | `formats.md` 第 5 节 | `case_save_draft`、`/core/progress`、流水线 | 界面、`/api/outputs/confirm` |
| `工作区/任务/<ID>/修改清单/*.json` | `tools/case_save_edit_list.schema.json#/$defs/args` | `case_save_edit_list` | `/api/redline` |
| `工作区/任务/<ID>/归档方案.json` | `tools/case_save_archive_plan.schema.json#/$defs/plan` | `case_save_archive_plan` | 归档面板、`/api/archive/build` |
| `成果/归档/<…>案件归档/` | `formats.md` 第 1 节 | `/api/archive/build` | 律师上传金助理 |
| `工作区/wiki/case.json` | `files/case_card.schema.json` | wiki 流水线、界面（本方立场、律师确认） | L0 注入、`case_read_wiki` |
| `工作区/wiki/案件/*.md`、`材料/*.md` | `formats.md` 第 4 节 | wiki 流水线 | `case_read_wiki`、界面 |
| `工作区/wiki/待确认.json` | `files/wiki_pending.schema.json` | `case_suggest_wiki` | `/api/wiki/suggestions` |
| `成果/索引.json` | `files/outputs_index.schema.json` | `/api/outputs/confirm` | 界面、选用前序成果 |
| `<应用数据>/cases.json` | `files/cases.schema.json` | `/api/case/open` | 注册表、最近案件 |
| `<应用数据>/settings.json` | `files/settings.schema.json` | `/api/settings` | 工作台服务、界面 |
| `<应用数据>/capsules.json` | `skill/capsules.schema.json` | `/api/capsules`、首次启动复制 | 首页、胶囊管理 |
| `<日常办公文件夹>/发票台账/` | 发票引擎自有格式（`formats.md` 第 1.2 节） | 发票引擎 | 发票整理面板 |

`<应用数据>` 为 `%APPDATA%\<产品名>\`。所有 JSON 文件写入时先写临时文件再原子替换（第 4.2 节）；写入前按契约校验，不合格不写并记日志（只记契约名和字段路径）。

### 20.9 文本格式

目录树、材料文本、出处、wiki 分节、草稿、流水线提示词的分段约定见 `contracts/formats.md`。

### 20.10 Skill、胶囊和归档目录（`contracts/skill/`）

`SKILL.md` 头部按 `skill/frontmatter.schema.json`（1.1 起不再有 `entry`、`order`）；胶囊配置按 `skill/capsules.schema.json`（替代 1.0 的 `skill/entry.schema.json`）；归档目录按 `skill/archive_catalog.schema.json`。正文六部分、必问问题的写法、允许的工具名由 `skills/_scripts/skill_manifest.py` 规定，与本契约一起维护。

### 20.11 怎么校验

- **自检**：`python contracts/check_examples.py --skills skills`。它把 `contracts/` 下所有 schema 注册进去，校验 `examples/` 中的正例和反例（`manifest.json` 写明每个样例应当通过还是失败），再校验胶囊配置、胶囊用到的全部 Skill 头部和四个归档目录。退出码 0 才算通过。当前：51 个样例全部符合预期，胶囊配置、18 个 Skill 和 4 个归档目录全部通过。
- **Python**：`jsonschema` 的 `Draft202012Validator` + `referencing.Registry`（写法照 `check_examples.py` 的 `validator()`）。工作台服务在 `/core/tool` 收到参数时、写落盘文件前校验；开发和测试环境下对所有返回也校验，生产环境关闭返回校验以省时间。
- **TypeScript**：`ajv/dist/2020`，启动时 `addSchema` 整个 `contracts/` 目录。Agent 插件用 `tools/*` 的 `$defs/args` 注册工具；界面插件的类型由 schema 生成（如 `json-schema-to-typescript`），不手写。
- **契约测试**：每张开发工单的验收里，凡涉及接口或落盘文件的，都包含"实际请求 / 返回 / 文件通过对应契约校验"。

### 20.12 变更记录

| 版本 | 日期 | 内容 |
|---|---|---|
| 1.0 | 2026-09-28 | 首版 |
| 1.1 | 2026-09-28 | 甲方需求变更：新增工具 `case_calc_sentence`、`case_archive_match`、`case_save_archive_plan`；新增接口 `materials_import`、`capsules`、`capsules_reset`、`archive_build`、`invoice_run`、`retainer_driver`；`case_open` 增加 `template`；`settings` 增加 `profile`、`office`、`converter`；新增 `skill/capsules`、`skill/archive_catalog`，删除 `skill/entry`；frontmatter 删除 `entry`、`order`；错误码增加 5 个；`formats.md` 增加标准案件目录、日常办公文件夹、归档文件夹；`settings.servers` 增加所外地址 `llm_alt_base_url`、`prep_alt_base_url`，`connection_test` 返回增加 `route`（2026-09-29） |
| 1.2 | 2026-09-30 | 用户当日拍板的一批（候 owner 清单 N37、N21、N26、N28、N31、N32、N35）：①任务单改为"管到律师改掉为止"——`POST /api/task` 改为设置该会话当前的选择，同一会话只保留最新一张，执行时不消耗；新增 `GET /api/task/current?session_id=`；`/core/task/begin` 按当前选择新建执行中的任务；②`case_read_material` 加可选参数 `offset`、返回加 `next_offset`，单元超过 `max_chars` 时能接着读同一单元；`start`/`end` 的 Excel 编号改为整份材料连续（`formats.md` 第 2 节）；③`tasks_list` 任务项加 `coverage`、`citation_check`，并写明不列待执行的任务单；④新增 `GET /api/outputs?case_id=` 成果列表；⑤胶囊项加可缺省字段 `new`（升级新补进来的胶囊，首页据此提示"有新功能"）；⑥材料索引 `note` 枚举加"有外部链接，未重算公式"；⑦材料文本 Source 行加取值"待识别"；⑧`unit_count` 写明 cell 时为工作表个数；⑨`case_db.sql` 新增 `material_ids` 表（材料编号留底，schema_version 仍为 1）。`contract_version` 升 1.2 |
| 1.3 | 2026-09-30 | T25 调研（线 C）发现契约与发票引擎不一致，随 T25 开工前一并改：①`invoice_run` plan 的 `history_numbers` 票号改 18–20 位（引擎 `[0-9]{18,20}`）；②`batch` 加正则 `^[A-Za-z0-9_\u4e00-\u9fff-]{1,40}$`（引擎 `[\w-]{1,80}`）；③plan 加可缺省的 `start`/`end`（YYYY-MM-DD），`channel=eml` 时必填（引擎 `period_plan` 要求邮件来源必须给起止日期）；④`cancel` 的 `apply=false` 说明：引擎不支持取消预览，服务忽略、界面先展示批次再确认。⑤`exclude` 动作加入白名单（线 C 17:34 给出引擎参数）：`{action, period, item ^[0-9a-f]{64}$, reason 1–200, reviewer 1–40, confirm: true}`，服务一律带 `--confirm`。**未纳入**：N45（出处正则允许材料名含 `〔〕`）——材料名内含括号会让出处解析二义，要先定解析规则，留待 1.4。`contract_version` 升 1.3；395 与工作台服务的 `/health` 读 `contracts\VERSION` |
